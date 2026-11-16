#!/usr/bin/env python3
"""
GLUE (Generalized Likelihood Uncertainty Estimation, Beven & Binley 1992) for a variety's DSSAT cultivar: a check of
the uncertainty of the coefficients calibration/dssat.py adopted, not a new calibration (dssat_cultivars.yaml is not
changed from it). DSSAT's own GLUE (its R scripts) is not installed; this is the same idea in Python.

Prior. N parameter sets drawn uniformly within DSSAT's cultivar file's MINIMA and MAXIMA (calibration/dssat.py
limits) for the coefficients the calibration fits (PARAMS: maize P1, P5, G2, G3, P5 included because the
calibration kept it at the cultivar's value; sorghum P1, P5, G2), stratified (a Latin hypercube: each coefficient's
range cut into N equal strata, one draw in each) and seeded. Every other coefficient is the adopted one.

Targets: the calibration's own experiments (calibration/dssat.py, its functions reused):
  maturity  days from sowing to physiological maturity at a constant daily mean of the varieties' reference
            temperature (21 °C), no water stress, against the variety's maturity_days; error scale SIGMA_DAYS
  yield     mean no-water-stress yield over the calibration's sowings at KARI Kiboko, error scale SIGMA_REL of the
            target: medium maize, the 2012 dry-season sowings against Duma 43's 7.76 t/ha; sorghum, the Short Rains
            2012 sowings against AquaCrop's 4.97 t/ha; early maize has no trial of its own (it takes the medium
            maize's G2/G3 factor), so its target is the yield the adopted coefficients give there (calibration/dssat
            result.json check, 4.96 t/ha) and the posterior shows how tightly the two targets hold its coefficients;
            the Local Katumani composite's observed 3.02 t/ha (an upper bound in the calibration) is reported as an
            alternative posterior on the same runs
Likelihood of a set: exp(-1/2 (z_days² + z_yield²)), 0 for a set DSSAT could not grow to maturity; the weights are
the likelihoods normalised. Reported: each coefficient's likelihood-weighted mean, sd and 5 / 50 / 95 % quantiles,
the best set, the adopted value and its quantile in the posterior, the effective sample size (Σw)² / Σw², the number of
behavioural sets (both targets within BEHAVIOURAL z), the weighted correlations between coefficients (trade-offs:
equifinality), and the simulated maturity and yield of the adopted set.

Writes outputs/crop_engine/calibration/dssat/glue_<variety>.json.
Usage: python -m crop_engine.calibration.dssat_glue --variety maize_early --n 300 --workers 2
"""
import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import dssat_adapter as ds
from crop_engine.calibration import dssat as cd
from crop_engine.calibration import wofost as cw
from crop_engine.data import era5land
from crop_engine.data.sites import registered_sites

PARAMS = {"MaizeGDD": ("P1", "P5", "G2", "G3"), "SorghumGDD": ("P1", "P5", "G2")}
SIGMA_DAYS = 3.0
SIGMA_REL = 0.10
BEHAVIOURAL = 2.0                  # |z| on both targets within this: a behavioural set (reported, not a cut-off)
QUANTILES = (0.05, 0.5, 0.95)
PLANT = dt.date(2012, 3, 1)        # calibration/dssat.days_to_maturity's sowing and constant weather
WEATHER_FROM = dt.date(2012, 2, 25)
RETRIES = 2
OUT = cd.OUT


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] dssat glue: {m}", flush=True)


# ── sampling, likelihood and posterior (no DSSAT) ──────────────────────────────────────────────────────────────────
def sample(bounds, n, seed=0, lhs=True):
    """n parameter sets uniform within bounds {name: (lo, hi)} → array (n, len(bounds)) in the bounds' order. lhs:
    stratified (Latin hypercube: one draw in each of n equal strata per coefficient, the strata shuffled
    independently), else plain uniform draws."""
    rng = np.random.default_rng(seed)
    k = len(bounds)
    if lhs:
        u = (np.stack([rng.permutation(n) for _ in range(k)], axis=1) + rng.random((n, k))) / n
    else:
        u = rng.random((n, k))
    lo = np.array([b[0] for b in bounds.values()], float)
    hi = np.array([b[1] for b in bounds.values()], float)
    return lo + u * (hi - lo)


def likelihood(days, yld, target_days, target_yield, sigma_days=SIGMA_DAYS, sigma_rel=SIGMA_REL):
    """Gaussian likelihood of each set's simulated days to maturity and yield (arrays; None / NaN: not grown → 0)."""
    d = np.array([np.nan if x is None else x for x in np.atleast_1d(days)], float)
    y = np.array([np.nan if x is None else x for x in np.atleast_1d(yld)], float)
    zd, zy = (d - target_days) / sigma_days, (y - target_yield) / (sigma_rel * target_yield)
    L = np.exp(-0.5 * (zd ** 2 + zy ** 2))
    return np.where(np.isfinite(L), L, 0.0)


def weighted_quantile(x, w, q):
    """Quantile(s) q of x weighted by w (the weighted empirical CDF, interpolated at the midpoints of the weights)."""
    x, w = np.asarray(x, float), np.asarray(w, float)
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return np.interp(q, c, x)


def weighted_cdf(x, w, v):
    """The posterior's share of weight at or below v."""
    x, w = np.asarray(x, float), np.asarray(w, float)
    return float(w[x <= v].sum() / w.sum())


def ess(w):
    w = np.asarray(w, float)
    return float(w.sum() ** 2 / (w ** 2).sum()) if (w ** 2).sum() > 0 else 0.0


def posterior(theta, names, L, adopted=None, bounds=None):
    """The posterior of the sets theta (n, k) with likelihoods L: per coefficient its weighted mean, sd, QUANTILES,
    the best set's value, the adopted value with its quantile in the posterior; the effective sample size and the
    weighted correlations. None when no set has any likelihood."""
    L = np.asarray(L, float)
    if not np.isfinite(L).all() or L.sum() <= 0:
        return None
    w = L / L.sum()
    best = int(np.argmax(L))
    mean = w @ theta
    sd = np.sqrt(w @ (theta - mean) ** 2)
    cov = (theta - mean).T @ ((theta - mean) * w[:, None])
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = cov / np.outer(sd, sd)
    out = {"ess": round(ess(w), 1), "best_index": best, "coefficients": {}, "correlation": {}}
    for j, n in enumerate(names):
        q = weighted_quantile(theta[:, j], w, QUANTILES)
        row = {"mean": float(mean[j]), "sd": float(sd[j]), **{f"q{int(p * 100):02d}": float(v) for p, v in zip(QUANTILES, q)},
               "best": float(theta[best, j])}
        if bounds:
            row["prior"] = [float(bounds[n][0]), float(bounds[n][1])]
        if adopted and n in adopted:
            a = float(adopted[n])
            row["adopted"] = a
            row["adopted_quantile"] = round(weighted_cdf(theta[:, j], w, a), 3)
            row["adopted_in_90"] = bool(q[0] <= a <= q[-1])
        out["coefficients"][n] = row
        for i, m in enumerate(names[j + 1:], start=j + 1):
            out["correlation"][f"{n}~{m}"] = round(float(corr[j, i]), 3) if np.isfinite(corr[j, i]) else None
    return out


def summarise(values, L):
    """Likelihood-weighted mean and 5–95 % of a simulated output (None where not grown)."""
    v = np.array([np.nan if x is None else x for x in values], float)
    ok = np.isfinite(v) & (np.asarray(L) > 0)
    if not ok.any():
        return None
    q = weighted_quantile(v[ok], np.asarray(L)[ok], (0.05, 0.95))
    return {"mean": float(np.average(v[ok], weights=np.asarray(L)[ok])), "q05": float(q[0]), "q95": float(q[1])}


# ── the experiments (calibration/dssat.py's) ───────────────────────────────────────────────────────────────────────
def _variety_with(variety, coef):
    """The variety with its adopted DSSAT overrides and `coef` on top."""
    return dict(variety, dssat=dict(variety["dssat"], **{k: float(v) for k, v in coef.items()}))


def _run(variety, plantings, weather, site, elev):
    """calibration/dssat.run, retried where DSSAT stopped (its crashes come under load)."""
    for k in range(RETRIES + 1):
        rs = cd.run(variety, plantings, weather, site, elev)
        if all(r["status"] != "error" for r in rs) or k == RETRIES:
            return rs
        time.sleep(0.5 * (k + 1))


def experiments(variety_key, variety):
    """The variety's targets and sowings (module doc) → dict."""
    if variety_key == "maize_medium":
        return {"target_t_ha": cd.MAIZE_TRAIN["observed_t_ha"], "sowings": cw.sowings(cd.MAIZE_TRAIN["year"]),
                "source": cd.MAIZE_TRAIN["source"], "alternatives": {}}
    if variety_key == "maize_early":
        res = json.loads((OUT / "result.json").read_text(encoding="utf-8"))
        chk = next(c for c in res["yield"]["maize"]["checks"] if c["variety"] == "maize_early"
                   and c["year"] == cd.MAIZE_TRAIN["year"])
        return {"target_t_ha": float(chk["calibrated_t_ha"]), "sowings": cw.sowings(chk["year"]),
                "source": f"the adopted coefficients' yield with the medium maize's G2/G3 factor (calibration/dssat "
                          f"result.json, {res['created'][:10]}): early maize has no trial of its own",
                "alternatives": {"observed_katumani_composite": {"target_t_ha": float(chk["observed_t_ha"]),
                                                                 "source": chk["source"] + " (an upper bound in the "
                                                                                           "calibration)"}}}
    if variety_key == "sorghum":
        sres = json.loads((C.OUT / "calibration" / "sorghum" / "result.json").read_text(encoding="utf-8"))
        return {"target_t_ha": float(sres["yield"]["aquacrop_potential_t_ha"][0]),
                "sowings": [dt.date.fromisoformat(d) for d in cd.SORGHUM_TRAIN["sowings"]],
                "source": cd.SORGHUM_TRAIN["source"], "alternatives": {}}
    raise ValueError(f"{variety_key}: no calibration target (maize_early, maize_medium, sorghum)")


class Experiment:
    """One parameter set → (days to maturity at tref, anthesis days, mean no-water-stress yield at the sowings)."""

    def __init__(self, variety, tref, sowings, site, elev):
        self.variety, self.site, self.elev, self.sowings = variety, site, elev, sowings
        self.const = cd.constant_weather(WEATHER_FROM, tref)
        self.met = cd.site_weather(site, sowings[0] - dt.timedelta(days=5))

    def __call__(self, coef):
        v = _variety_with(self.variety, coef)
        r = _run(v, [PLANT], self.const, self.site, self.elev)[0]
        days = (dt.date.fromisoformat(r["harvest"]) - PLANT).days if r["status"] == "ok" else None
        anth = (dt.date.fromisoformat(r["anthesis"]) - PLANT).days if r["status"] == "ok" and r.get("anthesis") else None
        ys = [x["yield_t_ha"] for x in _run(v, self.sowings, self.met, self.site, self.elev) if x["status"] == "ok"]
        yld = float(np.mean(ys)) if len(ys) == len(self.sowings) else None    # every sowing grown, else not behavioural
        return {"days": days, "anthesis_days": anth, "yield_t_ha": yld}


def site_and_elev():
    import fao_water_balance as fw  # noqa: E402
    site = next(s for s in registered_sites() if s.id == cd.SITE)
    met = era5land.site_met([site], refresh=False)[site.id]
    cal = met[(met.index.year >= C.CAL_YEARS[0]) & (met.index.year <= C.CAL_YEARS[1])]
    return site, float(fw.elevation_from_pressure(float(cal.sp_kpa.mean())))


def adopted_coefficients(variety):
    """The cultivar's coefficients with the adopted overrides (dssat_cultivars.yaml)."""
    base = ds.cultivar_coefficients(variety["aquacrop_crop"], variety["dssat"]["cultivar"])
    return {**base, **{k: float(v) for k, v in variety["dssat"].items() if k != "cultivar"}}


def glue(variety_key, n=300, workers=2, seed=2026, params=None, sigma_days=SIGMA_DAYS, sigma_rel=SIGMA_REL):
    tref, vs = ro.load_varieties([variety_key])
    ds.attach(vs)
    v = vs[variety_key]
    key = v["aquacrop_crop"]
    names = tuple(params or PARAMS[key])
    lo, hi = cd.limits(key)
    bounds = {p: (lo[p], hi[p]) for p in names}
    fixed = [p for p, (a, b) in bounds.items() if not b > a]
    if fixed:
        raise ValueError(f"{', '.join(fixed)}: fixed in DSSAT's file (MINIMA = MAXIMA), nothing to sample")
    exp = experiments(variety_key, v)
    site, elev = site_and_elev()
    run = Experiment(v, tref, exp["sowings"], site, elev)
    adopted = adopted_coefficients(v)
    log(f"{variety_key} ({v['dssat']['cultivar']}): {n} sets of {', '.join(names)} within DSSAT's limits "
        f"{bounds}; targets {v['maturity_days']} days at {tref} °C (σ {sigma_days}) and {exp['target_t_ha']} t/ha "
        f"(σ {sigma_rel:.0%}) over {len(exp['sowings'])} sowings")
    at_adopted = run({p: adopted[p] for p in names})
    log(f"adopted {({p: adopted[p] for p in names})}: {at_adopted}")
    theta = sample(bounds, n, seed)
    sets = [dict(zip(names, map(float, row))) for row in theta]
    t0, sims = time.time(), []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for k, s in enumerate(pool.map(run, sets)):
            sims.append(s)
            if (k + 1) % max(1, n // 10) == 0:
                log(f"  {k + 1}/{n} sets ({time.time() - t0:.0f} s)")
    days = [s["days"] for s in sims]
    ylds = [s["yield_t_ha"] for s in sims]
    L = likelihood(days, ylds, v["maturity_days"], exp["target_t_ha"], sigma_days, sigma_rel)
    zd = (np.array([np.nan if d is None else d for d in days], float) - v["maturity_days"]) / sigma_days
    zy = (np.array([np.nan if y is None else y for y in ylds], float) - exp["target_t_ha"]) / (sigma_rel * exp["target_t_ha"])
    behavioural = int(np.sum((np.abs(zd) <= BEHAVIOURAL) & (np.abs(zy) <= BEHAVIOURAL)))
    post = posterior(theta, names, L, adopted, bounds)
    out = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "variety": variety_key,
           "cultivar": v["dssat"]["cultivar"], "site": cd.SITE, "reference_tmean_c": tref,
           "method": {"n": n, "seed": seed, "sampling": "uniform within DSSAT's MINIMA/MAXIMA, Latin hypercube",
                      "likelihood": "exp(-(z_days^2 + z_yield^2) / 2)", "sigma_days": sigma_days,
                      "sigma_yield_rel": sigma_rel, "behavioural_z": BEHAVIOURAL, "workers": workers,
                      "seconds": round(time.time() - t0)},
           "targets": {"maturity_days": v["maturity_days"], "yield_t_ha": exp["target_t_ha"],
                       "yield_source": exp["source"], "sowings": [d.isoformat() for d in exp["sowings"]]},
           "params": list(names), "prior": {p: list(map(float, b)) for p, b in bounds.items()},
           "adopted": {p: adopted[p] for p in names}, "adopted_simulated": at_adopted,
           "grown": int(sum(d is not None and y is not None for d, y in zip(days, ylds))),
           "behavioural": behavioural, "posterior": post,
           "simulated": {"days": summarise(days, L), "yield_t_ha": summarise(ylds, L),
                         "anthesis_days": summarise([s["anthesis_days"] for s in sims], L)},
           "best": None, "alternatives": {}, "sets": []}
    if post:
        b = post["best_index"]
        out["best"] = {"coefficients": sets[b], "likelihood": float(L[b]), **sims[b]}
        log(f"posterior: ESS {post['ess']}, {behavioural} behavioural of {n}; best {sets[b]} → {sims[b]}")
        for p, r in post["coefficients"].items():
            log(f"  {p}: mean {r['mean']:.3f} (5–95 % {r['q05']:.3f}–{r['q95']:.3f}), best {r['best']:.3f}, adopted "
                f"{r['adopted']:.3f} at quantile {r['adopted_quantile']}")
    else:
        log("posterior: no set has any likelihood (the targets are out of reach of the prior)")
    for name, alt in exp["alternatives"].items():
        La = likelihood(days, ylds, v["maturity_days"], alt["target_t_ha"], sigma_days, sigma_rel)
        pa = posterior(theta, names, La, adopted, bounds)
        out["alternatives"][name] = dict(alt, posterior=pa,
                                         simulated={"yield_t_ha": summarise(ylds, La), "days": summarise(days, La)},
                                         best=None if pa is None else {"coefficients": sets[pa["best_index"]],
                                                                       **sims[pa["best_index"]]})
        if pa:
            log(f"alternative {name} ({alt['target_t_ha']} t/ha): ESS {pa['ess']}; "
                + ", ".join(f"{p} {r['q05']:.1f}–{r['q95']:.1f}" for p, r in pa["coefficients"].items()))
    out["sets"] = [{**s, **m, "likelihood": float(l)} for s, m, l in zip(sets, sims, L)]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"glue_{variety_key}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    log(f"→ {path}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variety", default="maize_early", choices=["maize_early", "maize_medium", "sorghum"])
    ap.add_argument("--n", type=int, default=300, help="parameter sets drawn")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--params", nargs="+", help="coefficients sampled (default: PARAMS of the crop)")
    ap.add_argument("--sigma-days", type=float, default=SIGMA_DAYS)
    ap.add_argument("--sigma-yield", type=float, default=SIGMA_REL, help="relative error scale of the yield target")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ds.installed():
        log(f"DSSAT is not installed ({ds.EXE}): python -m crop_engine.adapters.dssat_adapter --install")
        return 1
    glue(a.variety, a.n, a.workers, a.seed, a.params, a.sigma_days, a.sigma_yield)
    return 0


if __name__ == "__main__":
    sys.exit(main())
