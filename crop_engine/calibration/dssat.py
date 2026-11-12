#!/usr/bin/env python3
"""
DSSAT's varieties (adapters/dssat_adapter.py), calibrated to the same targets as AquaCrop's and WOFOST's:

Phenology. Each variety's DSSAT cultivar has its phase durations scaled by one factor (their ratios kept) so that,
sown at the site with a constant daily mean of the varieties' reference temperature (21 °C, varieties.yaml) and no
water stress, it reaches physiological maturity in the variety's `maturity_days` after sowing: the target AquaCrop's
and WOFOST's phenology are scaled to (wofost_adapter.phenology). The phases: maize P1 (emergence to the end of the
juvenile phase, °C d above 8 °C; P5, silking to maturity, stays the cultivar's: the early and late Kenyan cultivars
of DSSAT's file differ mostly in P1); sorghum P1 and P5 (PANTH, P3 and P4 are fixed in DSSAT's file: their minimum
and maximum are the same); dry bean EM-FL, FL-SH, FL-SD, SD-PM and FL-LF (photothermal days). Every coefficient is
kept within the minimum and maximum of DSSAT's cultivar file (its MINIMA and MAXIMA lines); a target out of reach
there is reported, not forced. Photoperiod: the site's (Kiboko, 2.2° S: about 12 h, below the 12.5 h at which
maize and sorghum slow).

Yield level, as WOFOST's (calibration/wofost.py, calibration/sorghum.py). Maize: medium maize with no water stress
at KARI Kiboko in the 2012 dry season, sown every 14 days from 1 Jun to 31 Jul, should yield what Duma 43 yielded
well watered there (7.76 t/ha, Ngugi, Collins & Muchira 2013, Table 5); the fitted parameter is one factor on the
cultivar's G2 (potential kernels per plant) and G3 (kernel filling rate) together, the sink (G2 alone reaches only
6.9 t/ha at its maximum, 990), and early maize takes the same factor on its own G2 and G3. Sorghum: its
no-water-stress yield over the Short Rains 2012 sowings at Kiboko (20 Oct, 3 and 17 Nov) is matched to AquaCrop's
(4.97 t/ha, calibration/sorghum result), through a factor on G2 (partitioning to the panicle). The dry bean has no
trial: its yield level stays DSSAT's. Weather: the site's ERA5-Land temperature, radiation, vapour pressure and wind.

Writes outputs/crop_engine/calibration/dssat/result.json and prints the coefficients for crop_engine/dssat_cultivars.yaml
(edited by hand, citing it). Usage: python -m crop_engine.calibration.dssat [--varieties ...]
"""
import argparse
import datetime as dt
import json
import sys

import numpy as np
import pandas as pd

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import dssat_adapter as ds
from crop_engine.calibration import wofost as cw
from crop_engine.data import era5land
from crop_engine.data.sites import registered_sites
from crop_engine.data.soil import Layer

SITE = "kalro_kiboko_makueni_farm"
PHASES = {"MaizeGDD": ("P1",), "SorghumGDD": ("P1", "P5"), "DryBeanGDD": ("EM-FL", "FL-SH", "FL-SD", "SD-PM", "FL-LF")}
YIELD_COEF = {"MaizeGDD": ("G2", "G3"), "SorghumGDD": ("G2",)}
LIMITS = ("999991", "999992")     # DSSAT's MINIMA and MAXIMA lines of each cultivar file
MAIZE_TRAIN = {"variety": "maize_medium", "observed_t_ha": 7.76, "year": 2012,
               "source": "Duma 43, well watered, KARI Kiboko 2012 (Ngugi et al. 2013, Table 5)"}
MAIZE_CHECKS = cw.CHECKS
SORGHUM_TRAIN = {"variety": "sorghum", "sowings": ["2012-10-20", "2012-11-03", "2012-11-17"],
                 "source": "AquaCrop's no-water-stress yield at Kiboko, SR 2012 sowings (calibration/sorghum result.json)"}
DAYS = 300
SCALE_RANGE = (0.3, 2.5)
OUT = C.OUT / "calibration" / "dssat"
# a generic loam (calibration/wofost.py's), in DSSAT layers: no water limitation in these runs anyway
LOAM = [Layer(top, bottom, 40, 20, 1.5, 0, 0.30, 0.14) for top, bottom in ((0, 15), (15, 30), (30, 60), (60, 100), (100, 200))]


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] dssat calibration: {m}", flush=True)


def _with(variety, coef):
    """The variety on its DSSAT cultivar with only `coef` overridden (not the calibrated values on file)."""
    return dict(variety, dssat=dict(cultivar=variety["dssat"]["cultivar"], **coef))


def limits(key):
    lo, hi = (ds.cultivar_coefficients(key, c) for c in LIMITS)
    return lo, hi


def scaled(variety, phen=1.0, yld=1.0):
    """The variety's DSSAT coefficients with its phases × phen and its yield coefficients × yld (module doc), each
    within DSSAT's minimum and maximum."""
    key = variety["aquacrop_crop"]
    base = ds.cultivar_coefficients(key, variety["dssat"]["cultivar"])
    lo, hi = limits(key)
    over = {k: base[k] * phen for k in PHASES[key]}
    over.update({k: base[k] * yld for k in YIELD_COEF.get(key, ()) if yld != 1.0})
    return {k: float(np.clip(v, lo.get(k, -np.inf), hi.get(k, np.inf))) for k, v in over.items()}


def at_limits(variety, over):
    lo, hi = limits(variety["aquacrop_crop"])
    return sorted(k for k, v in over.items() if np.isclose(v, lo.get(k, np.nan)) or np.isclose(v, hi.get(k, np.nan)))


def run(variety, plantings, weather, site, elev):
    """DSSAT with no water stress for sowings `plantings` in `weather` (DataFrame: tmax, tmin, rad_mj_m2,
    vap_hpa, wind2_ms, from the first sowing for DAYS days) → [outcome dict per sowing]."""
    dates = weather.index
    M, T = len(plantings), len(dates)
    task = {"dates": dates.values, "variety": variety, "layers": LOAM, "initial_frac": 1.0, "water": False,
            "lat": site.lat, "lon": site.lon, "elev": elev, "source": np.zeros(T),
            "rain": np.full((M, T), 3.0), "tmax": np.tile(weather.tmax.values, (M, 1)),
            "tmin": np.tile(weather.tmin.values, (M, 1)), "rad": np.tile(weather.rad_mj_m2.values, (M, 1)),
            "vap": np.tile(weather.vap_hpa.values, (M, 1)), "wind2": np.tile(weather.wind2_ms.values, (M, 1))}
    got = ds.run_members(task, list(range(M)), plantings)
    return [ds._member(task, m, p, *got[m], pd.DatetimeIndex(dates)) for m, p in enumerate(plantings)]


def constant_weather(start, tmean, days=DAYS):
    d = pd.date_range(start, periods=days)
    return pd.DataFrame({"tmax": tmean + 1.0, "tmin": tmean - 1.0, "rad_mj_m2": 20.0, "vap_hpa": 15.0, "wind2_ms": 2.0},
                        index=d)


def days_to_maturity(variety, phen, site, elev, tmean):
    plant = dt.date(2012, 3, 1)
    w = constant_weather(dt.date(2012, 2, 25), tmean)
    r = run(_with(variety, scaled(variety, phen)), [plant], w, site, elev)[0]
    if r["status"] != "ok":
        return None
    return (dt.date.fromisoformat(r["harvest"]) - plant).days


def _fit(f, target, grid, done):
    """The factor of `grid`'s range whose f(factor) is target: bracketed on the grid, then bisected (done(value):
    close enough); when no two neighbours bracket it (the coefficients' limits), the grid factor closest to it, with
    reached False."""
    vals = [(g, f(g)) for g in grid]
    for (g0, v0), (g1, v1) in zip(vals, vals[1:]):
        if v0 is not None and v1 is not None and min(v0, v1) <= target <= max(v0, v1):
            lo, hi, up = g0, g1, v1 >= v0
            mid, v = g0, v0
            for _ in range(30):
                mid = (lo + hi) / 2
                v = f(mid)
                if v is None or done(v) or hi - lo < 1e-4:
                    break
                lo, hi = (mid, hi) if (v < target) == up else (lo, mid)
            return round(mid, 4), v, True
    ok = [(g, v) for g, v in vals if v is not None]
    if not ok:
        raise ValueError("no valid run over the factor range")
    g, v = min(ok, key=lambda x: abs(x[1] - target))
    return round(g, 4), v, False


def fit_phenology(variety, site, elev, tmean):
    """The phase factor whose days to maturity at tmean are the variety's maturity_days → (factor, days, reached)."""
    target = variety["maturity_days"]
    return _fit(lambda s: days_to_maturity(variety, s, site, elev, tmean), target, np.geomspace(*SCALE_RANGE, 10),
                lambda d: d == target)


def site_weather(site, start, days=DAYS):
    temps = era5land.site_temperature(site, refresh=False)
    met = era5land.site_met([site], refresh=False)[site.id]
    d = pd.date_range(start, periods=days)
    t, m = temps.reindex(d), met.reindex(d)
    w = pd.DataFrame({"tmax": t.tmax, "tmin": t.tmin, "rad_mj_m2": m.rad_mj_m2, "vap_hpa": m.vap_hpa,
                      "wind2_ms": m.wind2_ms}, index=d)
    if w.isna().any().any():
        raise ValueError(f"ERA5-Land weather missing at {site.id} from {start}")
    return w


def mean_yield(variety, phen, yld, site, elev, plantings):
    w = site_weather(site, plantings[0] - dt.timedelta(days=5))
    rs = run(_with(variety, scaled(variety, phen, yld)), plantings, w, site, elev)
    ys = [r["yield_t_ha"] for r in rs if r["status"] == "ok"]
    return float(np.mean(ys)) if ys else None, rs


def fit_yield(variety, phen, target, site, elev, plantings, tol=0.02):
    """The yield-coefficient factor whose mean no-water-stress yield over the sowings is target → (factor, yield,
    reached)."""
    return _fit(lambda s: mean_yield(variety, phen, s, site, elev, plantings)[0], target, np.geomspace(*SCALE_RANGE, 8),
                lambda y: abs(y - target) < tol)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--varieties", nargs="+", default=["maize_early", "maize_medium", "sorghum", "bean"])
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ds.installed():
        log(f"DSSAT is not installed ({ds.EXE}): python -m crop_engine.adapters.dssat_adapter --install")
        return 1
    tref, varieties = ro.load_varieties(a.varieties)
    ds.attach(varieties)
    site = next(s for s in registered_sites() if s.id == SITE)
    met = era5land.site_met([site], refresh=False)[site.id]
    import fao_water_balance as fw  # noqa: E402
    cal = met[(met.index.year >= C.CAL_YEARS[0]) & (met.index.year <= C.CAL_YEARS[1])]
    elev = float(fw.elevation_from_pressure(float(cal.sp_kpa.mean())))
    res = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "site": SITE,
           "reference_tmean_c": tref, "varieties": {}}
    for vk, v in varieties.items():
        if not (v.get("dssat") or {}).get("cultivar"):
            log(f"{vk}: no DSSAT cultivar in dssat_cultivars.yaml, left out")
            continue
        before = days_to_maturity(v, 1.0, site, elev, tref)
        phen, d, reached = fit_phenology(v, site, elev, tref)
        lim = at_limits(v, scaled(v, phen))
        note = ("" if reached else ", not reached") + (f"; at DSSAT's limits: {', '.join(lim)}" if lim else "")
        log(f"{vk} ({v['dssat']['cultivar']}): maturity at {tref} °C {before} → {d} days (target {v['maturity_days']}), "
            f"phase factor {phen}{note}")
        res["varieties"][vk] = {"cultivar": v["dssat"]["cultivar"], "phase_factor": phen, "at_limits": lim,
                                "days_to_maturity": {"before": before, "after": d, "target": v["maturity_days"],
                                                     "reached": reached}}
    yld = {}
    if "maize_medium" in res["varieties"]:
        v = varieties["maize_medium"]
        plants = cw.sowings(MAIZE_TRAIN["year"])
        phen = res["varieties"]["maize_medium"]["phase_factor"]
        own = mean_yield(v, phen, 1.0, site, elev, plants)[0]
        f, y, reached = fit_yield(v, phen, MAIZE_TRAIN["observed_t_ha"], site, elev, plants)
        log(f"maize_medium no water stress, Kiboko {MAIZE_TRAIN['year']}: {own:.2f} → {y:.2f} t/ha with G2, G3 × {f} "
            f"(target {MAIZE_TRAIN['observed_t_ha']}{'' if reached else ', not reached'}; {MAIZE_TRAIN['source']})")
        yld["maize"] = {"train": MAIZE_TRAIN, "own_t_ha": round(own, 2), "factor": f, "fitted_t_ha": round(y, 2),
                        "reached": reached, "checks": []}
        for c in MAIZE_CHECKS:
            if c["variety"] not in res["varieties"]:
                continue
            vv = varieties[c["variety"]]
            ph_ = res["varieties"][c["variety"]]["phase_factor"]
            o = mean_yield(vv, ph_, 1.0, site, elev, cw.sowings(c["year"]))[0]
            k = mean_yield(vv, ph_, f, site, elev, cw.sowings(c["year"]))[0]
            log(f"  check {c['variety']} {c['year']}: {o:.2f} → {k:.2f} t/ha against {c['observed_t_ha']} ({c['source']}; upper bound)")
            yld["maize"]["checks"].append({**c, "own_t_ha": round(o, 2), "calibrated_t_ha": round(k, 2)})
    if "sorghum" in res["varieties"]:
        v = varieties["sorghum"]
        sres = json.loads((C.OUT / "calibration" / "sorghum" / "result.json").read_text(encoding="utf-8"))
        target = float(sres["yield"]["aquacrop_potential_t_ha"][0])
        plants = [dt.date.fromisoformat(d) for d in SORGHUM_TRAIN["sowings"]]
        phen = res["varieties"]["sorghum"]["phase_factor"]
        own = mean_yield(v, phen, 1.0, site, elev, plants)[0]
        f, y, reached = fit_yield(v, phen, target, site, elev, plants)
        log(f"sorghum no water stress, Kiboko SR 2012: {own:.2f} → {y:.2f} t/ha with G2 × {f} (AquaCrop's {target}"
            f"{'' if reached else ', not reached'})")
        yld["sorghum"] = {"train": dict(SORGHUM_TRAIN, target_t_ha=target), "own_t_ha": round(own, 2), "factor": f,
                          "fitted_t_ha": round(y, 2), "reached": reached}
    res["yield"] = yld
    for vk, r in res["varieties"].items():
        v = varieties[vk]
        f = yld.get("maize" if vk.startswith("maize") else vk, {}).get("factor", 1.0)
        r["coefficients"] = {k: round(x, 3) for k, x in scaled(v, r["phase_factor"], f).items()}
        log(f"dssat_cultivars.yaml {vk}: {{cultivar: {r['cultivar']}, " + ", ".join(f"{k}: {x}" for k, x in r["coefficients"].items()) + "}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
