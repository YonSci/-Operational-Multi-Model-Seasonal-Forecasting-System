#!/usr/bin/env python3
"""
Hindcast verification of the crop outlook: the crop grown in each past seasonal forecast (ECMWF SEAS5, 1 Oct runs,
25 members, 1993–2016), scored against the same crop grown in that season's observed weather (the benchmark,
climatology.json). It asks whether the crop forecasts tell good seasons from bad ones, and whether they say more
than the forecasts the platform already gives (season length, rain, onset).

Weather of a past forecast, member k (as a forecast issued on 1 Oct of year y would have had it):
  1 Aug – 30 Sep   observed CHIRPS v2 (and the observed ERA5-Land temperature and ET0)
  1 Oct – 31 Dec   SEAS5 member k, bias-corrected to CHIRPS (outputs/ecmwf_oct/ECMWF_bc_daily_all_years.nc)
  1 Jan – 28 Feb   SEAS5 member k, as the outlook (onset_rules.EXT_CACHE)
  1–31 Mar         climatological: the observed March of another calibration year (never year y)
  temperature and ET0 from 1 Oct: the 1993–2016 day-of-year climatology (as the outlook without SEAS5 temperature)
With --temperature seas5 (as the outlook now runs), from 1 Oct: SEAS5 member k's temperature, bias-corrected to
ERA5-Land with year y left out of the correction, the ET0 climatology scaled by it (Hargreaves ratio, or the
Penman-Monteith ratio with SEAS5 radiation, humidity and wind when their files are on disk) and SEAS5
member k's March rain quantile-mapped to CHIRPS (crop_engine.data.seas5); only the years whose 182-day file is on
disk. Its outputs carry the suffix _seas5t, and the run also scores the climatological-temperature members of the
same years, so the two are compared on equal terms.
Sowing: each member's onset of that forecast, by the platform's own hindcast onsets:
  rule1             Agri rule 1 (outputs/ecmwf_oct/icpac_rule1/ECMWF_onset_all_years.nc)
  fao-agricultural  the FAO water balance's agricultural onset of the 1 Oct runs (observed CHIRPS v3 and ERA5-Land
                    to 30 Sep, then each SEAS5 member: scripts/fao_water_balance.py forecast, run once into
                    outputs/crop_engine/verification/fao_oct by `python -m crop_engine.hindcast --fao-onsets`)

Scores per site, crop and rule, over the years (crop_engine.hindcast.scores):
  spearman        rank correlation of the members' median yield with the observed-weather yield
  rpss            ranked probability skill score of the yield terciles (leave-one-out terciles of the
                  observed-weather yields), against 1/3 each; None where a third or more of the seasons failed
  failure_bss     Brier skill score of the chance of crop failure (yield below the variety's threshold), against
                  the leave-one-out failure rate; failure_auc its ROC area (None when no or every season failed)
and the same correlation and ROC area for the platform's other forecasts of the season, read as yield predictors
(baselines): the members' median season length (by the sowing rule's own method: the Agri rules' LGP for rule 1,
the FAO water balance's for the FAO onset), Oct–Dec rain and the onset itself (later = worse).

Outputs (not committed): outputs/crop_engine/verification/hindcast_members.json (every member's outcome) and
hindcast_scores.json; a table in the log.

Usage:
  python -m crop_engine.hindcast --workers 3                       # simulate and score (about 14,000 seasons)
  python -m crop_engine.hindcast --score-only                      # score the saved members again
  python -m crop_engine.hindcast --fao-onsets                      # the FAO onsets of the 1 Oct runs (once)
  python -m crop_engine.hindcast --temperature seas5 --workers 3   # SEAS5 temperature, compared with climatology
  python -m crop_engine.hindcast --sites kalro_kiboko_makueni_farm --varieties maize_early --years 2005 2010
"""
import argparse
import datetime as dt
import json
import sys
import time

import numpy as np
import pandas as pd
import xarray as xr
from scipy.stats import spearmanr

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.data import seas5 as s5
from crop_engine.data import soil as soil_mod
from crop_engine.data import weather as W
from crop_engine.scenarios import planting as pl

import onset_rules as orl  # noqa: E402

FC_DIR = C.BASE / "outputs" / "ecmwf_oct"
RAIN_OCT_DEC = FC_DIR / "ECMWF_bc_daily_all_years.nc"            # (member, year, day 0–91 = 1 Oct – 31 Dec, lat, lon)
OUT = C.OUT / "verification"
FAO_RUN = OUT / "fao_oct"                                         # the FAO water balance of the 1 Oct runs
ONSETS = {"rule1": FC_DIR / "icpac_rule1" / "ECMWF_onset_all_years.nc",
          "fao-agricultural": FAO_RUN / "fao_wb_agricultural" / "ECMWF_onset_all_years.nc"}
LGP = {"rule1": FC_DIR / "ECMWF_lgp_days_all_years.nc",
       "fao-agricultural": FAO_RUN / "fao_wb_agricultural" / "ECMWF_lgp_all_years.nc"}
TEMPERATURE = ("climatology", "seas5")


def suffix(temperature):
    return "" if temperature == "climatology" else "_seas5t"


def fao_onsets():
    """The FAO water balance of the 1 Oct runs, all years, into FAO_RUN (its own folder: the platform's run folders
    are not touched). run_forecast reads only the years of the folder's ECMWF_bc_daily_all_years.nc."""
    import fao_water_balance as fw  # noqa: E402
    FAO_RUN.mkdir(parents=True, exist_ok=True)
    with xr.open_dataarray(RAIN_OCT_DEC) as da:
        years = da.year.values
    xr.DataArray(np.zeros(len(years), np.int8), dims="year", coords={"year": years},
                 name="years").to_netcdf(FAO_RUN / "ECMWF_bc_daily_all_years.nc")
    fw.run_forecast(fw.load_config(), FAO_RUN)


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] hindcast: {m}", flush=True)


def _grid(path, y, ii, jj):
    """(member, ..., site) values of year y at the sites' cells."""
    with xr.open_dataarray(path) as da:
        a = da.sel(year=y).values
    return a[..., ii, jj]


def assemble_rain(obs, oct_dec, janfeb, march, dates, y):
    """Members' rain (member, site, T) of the year-y forecast: obs (site, T) observed, oct_dec (member, 92, site),
    janfeb (member, 59, site), march (member, site, days of March in `dates`)."""
    M = oct_dec.shape[0]
    rain = np.repeat(obs[None].astype(np.float32), M, axis=0)
    od = (dates >= pd.Timestamp(y, 10, 1)) & (dates <= pd.Timestamp(y, 12, 31))
    rain[:, :, od] = np.moveaxis(oct_dec[:, (dates[od] - pd.Timestamp(y, 10, 1)).days], 1, 2)
    jf = (dates >= pd.Timestamp(y + 1, 1, 1)) & (dates < pd.Timestamp(y + 1, 3, 1))
    rain[:, :, jf] = np.moveaxis(janfeb[:, W.jan_feb_index(dates[jf], y)], 1, 2)
    mar = dates >= pd.Timestamp(y + 1, 3, 1)
    rain[:, :, mar] = march
    return rain


def season(inp, y, temperature="climatology"):
    """The year-y forecast's weather at the sites: rain, tmax, tmin, et0 (member, site, T) and dates. temperature
    "seas5": SEAS5 member k from 1 Oct (bias-corrected without year y) and its March rain (module doc)."""
    dates = inp.dates(y)
    obs = inp.observed_rain(dates)
    oct_dec = _grid(RAIN_OCT_DEC, y, inp.ii, inp.jj).astype(np.float32)         # (member, 92, site)
    with xr.open_dataarray(orl.EXT_CACHE) as da:
        janfeb = da.sel(year=y).values[:, :, inp.ii, inp.jj].astype(np.float32)
    mar = dates >= pd.Timestamp(y + 1, 3, 1)
    pool = [c for c in range(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1) if c != y]
    march = np.stack([inp.observed_rain(pd.DatetimeIndex([pd.Timestamp(pool[m % len(pool)] + 1, d.month, min(d.day, 31))
                                                            for d in dates[mar]])) for m in range(oct_dec.shape[0])])
    rain = assemble_rain(obs, oct_dec, janfeb, march, dates, y)
    tmax, tmin, et0, _, _ = inp.met(y, dates)
    fc = dates >= pd.Timestamp(y, 10, 1)                                 # no observed weather after the issue date
    doy = W.era5land.doy_noleap(dates[fc]) - 1
    for k, s in enumerate(inp.sites):
        cx, cn = inp.tclim[s.id]
        tmax[k, fc], tmin[k, fc] = cx[doy], np.minimum(cn[doy], cx[doy])
    et0[:, fc] = inp.et0_clim.T[:, fc]
    M = rain.shape[0]
    tmax, tmin, et0 = (np.repeat(a[None], M, axis=0) for a in (tmax, tmin, et0))
    if temperature == "seas5":
        S = s5.Seas5(y, [x.id for x in inp.sites], inp.lat[inp.ii], inp.lon[inp.jj], inp.temps, inp.hist, exclude=y,
                     met=inp.met2)
        mk = np.arange(M) % S.n_members
        p = S.on(dates)
        use = fc & (p >= 0)
        fx = np.moveaxis(S.tmax[mk][:, p[use]], 1, 2)                   # (member, site, days)
        fn = np.minimum(np.moveaxis(S.tmin[mk][:, p[use]], 1, 2), fx)
        if S.met is not None:                                            # Penman-Monteith, as the outlook
            w = {key: np.moveaxis(S.met[key][mk][:, p[use]], 1, 2) for key in s5.MET}
            ref = {key: a[:, use] for key, a in inp.clim_weather(dates).items()}
            ratio = inp.et0_pm_ratio({"tmax": fx, "tmin": fn, **w}, ref, dates[use], inp.radiation(dates)[2])
        else:
            ratio = s5.hargreaves_ratio(fx, fn, tmax[:, :, use], tmin[:, :, use])
        et0[:, :, use] *= ratio
        tmax[:, :, use], tmin[:, :, use] = fx, fn
        pos = S.march_dates.get_indexer(dates[mar])
        if (pos >= 0).all():
            rain[:, :, mar] = np.moveaxis(S.march[mk][:, pos], 1, 2)
    return rain, tmax.astype(np.float32), tmin.astype(np.float32), et0.astype(np.float32), dates


def seas5_years(years):
    """The years a SEAS5-temperature hindcast can run: the 182-day file on disk and enough other calibration years."""
    cal = s5.calibration_years()
    return [y for y in years if s5.path(y).exists() and len([c for c in cal if c != y]) >= s5.MIN_CAL_YEARS]


def simulate(inp, years, rep_cells, varieties, rules, soils, workers, temperature="climatology"):
    """Every member of every past forecast → {site: {variety: {rule: {year: [outcome, ...]}}}}."""
    tasks, keys = [], []
    for y in years:
        rain, tmax, tmin, et0, dates = season(inp, y, temperature)
        frac = inp.initial_water(y)
        src = np.full(len(dates), C.PRECIP_SOURCES.index("seasonal"), np.int8)
        for s, _ in rep_cells:
            k = [x.id for x in inp.sites].index(s.id)
            resow = pl.sowing_opportunities(rain[:, k], dates)
            for rk in rules:
                on = _grid(ONSETS[rk], y, np.array([s.i]), np.array([s.j]))[:, 0]
                plant = [pl.doy_to_date(v, y) for v in on]
                for vk, v in varieties.items():
                    tasks.append(dict(dates=dates.values, rain=rain[:, k], tmax=tmax[:, k], tmin=tmin[:, k], et0=et0[:, k],
                                      source=src, planting=plant, resow=resow, variety=v, kw=v["kw"],
                                      layers=soils[s.id], initial_frac=float(frac[k])))
                    keys.append((s.id, vk, rk, y))
    log(f"{len(tasks)} forecasts to simulate ({len(tasks) * 25} member seasons)")
    t0 = time.time()
    res = ro.run_tasks(tasks, workers)
    log(f"simulated in {time.time() - t0:.0f} s")
    out = {}
    for (sid, vk, rk, y), members in zip(keys, res):
        out.setdefault(sid, {}).setdefault(vk, {}).setdefault(rk, {})[str(y)] = [
            {k: m.get(k) for k in ("status", "planting", "harvest", "yield_t_ha", "sowings")} for m in members]
    return out


# ── scores ──────────────────────────────────────────────────────────────────
def _auc(score, event):
    """ROC area of `score` (higher = event more likely) for the boolean `event`; None without both classes."""
    score, event = np.asarray(score, float), np.asarray(event, bool)
    pos, neg = score[event], score[~event]
    if not len(pos) or not len(neg):
        return None
    greater = (pos[:, None] > neg[None]).sum() + 0.5 * (pos[:, None] == neg[None]).sum()
    return round(float(greater / (len(pos) * len(neg))), 3)


def _r(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 5 or np.ptp(a[ok]) == 0 or np.ptp(b[ok]) == 0:
        return None
    return round(float(spearmanr(a[ok], b[ok])[0]), 3)


def scores(fc, obs, thr):
    """fc (year, member) effective yields of the forecasts, obs (year,) the observed-weather yields, thr the failure
    threshold → the scores (module doc)."""
    fc, obs = np.asarray(fc, float), np.asarray(obs, float)
    Y = len(obs)
    out = {"n_years": Y, "n_success": int((obs >= thr).sum()), "spearman": _r(np.median(fc, axis=1), obs)}
    # terciles, leave-one-out; only where they separate yields (as the outlook: not when a third or more failed)
    t33, t67 = np.quantile(obs, [1 / 3, 2 / 3])
    if t33 >= thr and t67 > t33:
        rps, rps_c = [], []
        for i in range(Y):
            o = np.delete(obs, i)
            a, b = np.quantile(o, [1 / 3, 2 / 3])
            p = np.array([(fc[i] < a).mean(), (fc[i] <= b).mean()])           # cumulative: below, below or normal
            c = np.array([obs[i] < a, obs[i] <= b], float)
            rps.append(((p - c) ** 2).sum())
            rps_c.append(((np.array([1 / 3, 2 / 3]) - c) ** 2).sum())
        out["rpss"] = round(1 - float(np.mean(rps)) / float(np.mean(rps_c)), 3) if np.mean(rps_c) > 0 else None
    else:
        out["rpss"] = None
    fail = obs < thr
    p = (fc < thr).mean(axis=1)
    base = np.array([np.delete(fail, i).mean() for i in range(Y)])
    bs, bs_c = float(((p - fail) ** 2).mean()), float(((base - fail) ** 2).mean())
    out.update(failure_rate=round(float(fail.mean()), 3), failure_bss=round(1 - bs / bs_c, 3) if bs_c > 0 else None,
               failure_auc=_auc(p, fail))
    return out


def baseline_scores(pred, sign, obs, thr):
    """A platform forecast read as a yield predictor: pred (year,) its members' median, sign +1 if more is better."""
    pred = np.asarray(pred, float)
    return {"spearman": _r(sign * pred, obs), "failure_auc": _auc(-sign * np.nan_to_num(pred, nan=-sign * 1e9),
                                                                  np.asarray(obs) < thr)}


def score_all(members, bench, inp, varieties, years):
    """Scores of every site, crop and rule, with the baselines → {site: {variety: {rule: {...}}}}."""
    cells = {s.id: s for s in inp.sites}
    rules = sorted({rk for vs in members.values() for rs in vs.values() for rk in rs})
    base = {}                                                            # {(site, rule): {name: (values, sign)}}

    def med(path, s, onset=False):
        v = []
        for y in years:
            a = _grid(path, y, np.array([s.i]), np.array([s.j]))[:, 0].astype(float)
            if onset:
                a = np.where(np.isfinite(a), a, orl.LATE)
            v.append(float(np.nanmedian(a)) if np.isfinite(a).any() else np.nan)
        return v
    for sid, s in cells.items():
        r = [float(np.median(_grid(RAIN_OCT_DEC, y, np.array([s.i]), np.array([s.j]))[:, :, 0].sum(axis=1)))
             for y in years]
        for rk in rules:
            base[sid, rk] = {"lgp_days": (med(LGP[rk], s), 1), "rain_oct_dec_mm": (r, 1),
                             "onset_doy": (med(ONSETS[rk], s, onset=True), -1)}
    out = {}
    for sid, vs in members.items():
        for vk, rs in vs.items():
            thr = varieties[vk]["failure_t_ha"]
            for rk, ys in rs.items():
                yy = [y for y in years if str(y) in ys and str(y) in bench[sid][vk][rk]["years"]]
                rows = [[ro.effective_yield(m) for m in ys[str(y)] if m["status"] != "error"] for y in yy]
                n = min(map(len, rows))                                  # model errors left out (rare)
                fc = np.array([r[:n] for r in rows])
                obs = np.array([ro.effective_yield(bench[sid][vk][rk]["years"][str(y)]) for y in yy])
                idx = [years.index(y) for y in yy]
                # seasons sown (in the observed weather) before the forecast's 1 Oct start are known, not forecast:
                # the scores are also given without them, for the forecast's own skill
                first = [(bench[sid][vk][rk]["years"][str(y)].get("first_planting")
                          or bench[sid][vk][rk]["years"][str(y)].get("planting")) for y in yy]
                open_ = np.array([f is None or f >= f"{y}-10-01" for f, y in zip(first, yy)])
                out.setdefault(sid, {}).setdefault(vk, {})[rk] = {
                    "years": yy, "observed_t_ha": obs.round(3).tolist(), "forecast_median_t_ha": np.median(fc, axis=1).round(3).tolist(),
                    "forecast_p_failure": (fc < thr).mean(axis=1).round(3).tolist(), "crop": scores(fc, obs, thr),
                    "sown_before_oct": int((~open_).sum()), "sown_before_oct_success": int(((~open_) & (obs >= thr)).sum()),
                    "crop_from_oct": scores(fc[open_], obs[open_], thr) if open_.sum() >= 8 else None,
                    "baselines_from_oct": {name: baseline_scores(np.array(v)[idx][open_], sign, obs[open_], thr)
                                           for name, (v, sign) in base[sid, rk].items()} if open_.sum() >= 8 else None,
                    "baselines": {name: baseline_scores(np.array(v)[idx], sign, obs, thr) for name, (v, sign) in base[sid, rk].items()}}
    return out


def table(sc, log=log):
    log(f"{'site':14s} {'crop':13s} {'rule':6s} ok/pre  r_crop  rpss   bss   auc | r_lgp  r_rain r_onset | auc_lgp || Oct+: r_crop r_lgp  auc auc_lgp")
    for sid, vs in sc.items():
        for vk, rs in vs.items():
            for rk, d in rs.items():
                c, b, o = d["crop"], d["baselines"], d.get("crop_from_oct") or {}
                ob = (d.get("baselines_from_oct") or {}).get("lgp_days", {})
                f = lambda x: "  —  " if x is None else f"{x:+.2f}"
                log(f"{sid[:14]:14s} {vk:13s} {rk[:6]:6s} {c['n_success']:2d}/{d.get('sown_before_oct_success', 0):<2d}  "
                    f"{f(c['spearman'])}  {f(c['rpss'])} {f(c['failure_bss'])} {f(c['failure_auc'])} | "
                    f"{f(b['lgp_days']['spearman'])}  {f(b['rain_oct_dec_mm']['spearman'])}  {f(b['onset_doy']['spearman'])} | "
                    f"{f(b['lgp_days']['failure_auc'])}  ||       {f(o.get('spearman'))}  {f(ob.get('spearman'))} "
                    f"{f(o.get('failure_auc'))} {f(ob.get('failure_auc'))}")


def compare(clim, seas, log=log):
    """Scores of the same years with climatological and SEAS5 temperature, side by side → summary dict."""
    log(f"{'site':14s} {'crop':13s} {'rule':6s} | r_crop clim → seas5 | auc clim → seas5 | Oct+ r clim → seas5")
    f = lambda x: "  —  " if x is None else f"{x:+.2f}"
    diffs = {"spearman": [], "failure_auc": [], "oct_spearman": []}
    for sid, vs in seas.items():
        for vk, rs in vs.items():
            for rk, d in rs.items():
                c = clim.get(sid, {}).get(vk, {}).get(rk)
                if c is None:
                    continue
                pairs = [(c["crop"]["spearman"], d["crop"]["spearman"], "spearman"),
                         (c["crop"]["failure_auc"], d["crop"]["failure_auc"], "failure_auc"),
                         ((c.get("crop_from_oct") or {}).get("spearman"), (d.get("crop_from_oct") or {}).get("spearman"),
                          "oct_spearman")]
                for a, b, k in pairs:
                    if a is not None and b is not None:
                        diffs[k].append(b - a)
                log(f"{sid[:14]:14s} {vk:13s} {rk[:6]:6s} |   {f(pairs[0][0])} → {f(pairs[0][1])}    |  "
                    f"{f(pairs[1][0])} → {f(pairs[1][1])}  |  {f(pairs[2][0])} → {f(pairs[2][1])}")
    summ = {k: {"n": len(v), "mean_change": round(float(np.mean(v)), 3) if v else None,
                "n_better": int(sum(x > 0 for x in v)), "n_worse": int(sum(x < 0 for x in v))} for k, v in diffs.items()}
    for k, v in summ.items():
        log(f"{k}: SEAS5 temperature changes it by {v['mean_change']} on average ({v['n_better']} better, "
            f"{v['n_worse']} worse of {v['n']})")
    return summ


def _merge(old, new):
    """Members of new rules (or sites, crops) added to those saved."""
    for sid, vs in new.items():
        for vk, rs in vs.items():
            old.setdefault(sid, {}).setdefault(vk, {}).update(rs)
    return old


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs=2, type=int, default=list(C.CAL_YEARS))
    ap.add_argument("--sites", nargs="+")
    ap.add_argument("--varieties", nargs="+")
    ap.add_argument("--rules", nargs="+", choices=list(ONSETS),
                    help="sowing rules to simulate (default: those whose hindcast onsets are on disk)")
    ap.add_argument("--temperature", choices=TEMPERATURE, default="climatology")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--score-only", action="store_true", help="score the saved members, without simulating")
    ap.add_argument("--fao-onsets", action="store_true", help="compute the FAO onsets of the 1 Oct runs, then stop")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.fao_onsets:
        fao_onsets()
        return 0
    rules = a.rules or [rk for rk, f in ONSETS.items() if f.exists()]
    years = list(range(a.years[0], a.years[1] + 1))
    if a.temperature == "seas5":
        years = seas5_years(years)
        log(f"SEAS5 temperature: {len(years)} years with the 182-day files ({', '.join(map(str, years))})")
        if len(years) < 8:
            log("too few years to score")
            return 1
    _, varieties = ro.load_varieties(a.varieties)
    inp = W.Inputs(refresh=False)
    bench = json.loads((C.OUT / "climatology.json").read_text(encoding="utf-8"))
    rep_cells = [(s, g) for s, g in ro.cells(inp.sites) if not a.sites or s.id in a.sites]
    OUT.mkdir(parents=True, exist_ok=True)
    sfx = suffix(a.temperature)
    mpath = OUT / f"hindcast_members{sfx}.json"
    saved = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else None
    if a.score_only:
        members, years = saved["sites"], saved["years"]
    else:
        soils = {s.id: soil_mod.profile(s) for s, _ in rep_cells}
        members = simulate(inp, years, rep_cells, varieties, rules, soils, a.workers, a.temperature)
        if saved and saved["years"] == years and saved.get("config_hash") == bench.get("config_hash"):
            members = _merge(saved["sites"], members)                    # keep the other rules' members
        mpath.write_text(json.dumps({"years": years, "config_hash": bench.get("config_hash"),
                                     "temperature": a.temperature, "sites": members}), encoding="utf-8")
    sc = score_all(members, bench["sites"], inp, varieties, years)
    out = {"years": years, "config_hash": bench.get("config_hash"), "temperature": a.temperature,
           "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
           "reference": "the same crop grown in each season's observed weather (climatology.json)", "sites": sc}
    table(sc)
    cpath = OUT / "hindcast_members.json"
    if a.temperature == "seas5" and cpath.exists():                     # the same years, climatological temperature
        clim_members = json.loads(cpath.read_text(encoding="utf-8"))["sites"]
        log(f"the same {len(years)} years with climatological temperature:")
        out["climatology_same_years"] = score_all(clim_members, bench["sites"], inp, varieties, years)
        out["comparison"] = compare(out["climatology_same_years"], sc)
    (OUT / f"hindcast_scores{sfx}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
