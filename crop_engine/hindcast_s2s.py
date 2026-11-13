#!/usr/bin/env python3
"""
Sub-seasonal crop hindcast: does the ECMWF extended range's 46-day rain (and temperature) improve the crop outlook
over the observations alone? From ECMWF's extended-range reforecasts (data/ecmwf_s2s_reforecast/refc_tp_<date>_kenya.nc:
the current model started on the same day and month of 2006–2025, 10 perturbed members, 46 days, 1.5°;
scripts/fetch_ecmwf_reforecast.py), for start dates INITS of each hindcast year y.

Weather of member k of the forecast started on day I of year y, at a site:
  1 Aug – I−1       observed CHIRPS v2, ERA5-Land temperature and ET0
  I – I+45          reforecast member k's rain at the site's nearest 1.5° cell, quantile-mapped to the site's CHIRPS
                    (empirical, per lead day ± LEAD_WINDOW, the other hindcast years' members against CHIRPS on the
                    same valid days: year y never trains its own mapping)
  I+46 – 31 Mar     observed CHIRPS of another year (member k: pool year k + y, never y): climatology
  temperature and ET0 from I: the 1993–2016 day-of-year climatology (the forecast's rain is the only signal)
With the reforecast temperature on disk (refc_t2m_<date>_kenya.nc, `scripts/fetch_ecmwf_reforecast.py --kind
temperature`), a third forecast ("forecast_t") also takes member k's daily maximum and minimum temperature for its
46 days, delta-corrected to the site's ERA5-Land by lead day (the other hindcast years' member mean minus ERA5-Land on
the same valid days, ±3-day smoothed: year y never trains its own correction), with ET0 there the climatology × the
member's Hargreaves ratio (as the live sub-seasonal runs without radiation).
The reference ("observations only"): the same members with climatology from I, no forecast rain. Both are sown by
Agri rule 1 in each member's rain (the same rule as the observed-weather benchmark's rule 1), re-sown after a false
start, and grown by AquaCrop; the truth is the crop grown in the observed weather (climatology.json, rule 1).

Scores per site, crop and start (hindcast.scores, over the years): the rank correlation of the members' median yield
with the observed-weather yield, the failure Brier skill score and ROC area, and the tercile RPSS, for the forecast
and the reference, and their difference; also over the years whose observed rule-1 sowing falls on or after I (the
season still open: the forecast can matter). Radiation, humidity and wind forecasts (not in the reforecasts on
disk) are left out.

DSSAT (--engine dssat): the same forecasts grown by DSSAT, against DSSAT's own crop in the observed weather
(climatology_dssat.json); its radiation, humidity and wind as its temperature: ERA5-Land to the start, the 1993–2016
day-of-year climatology from it (the forecast's rain is again the signal). Output hindcast_s2s_dssat.json.

Outputs (not committed): outputs/crop_engine/verification/hindcast_s2s.json and a table in the log.
Usage: python -m crop_engine.hindcast_s2s --workers 3 [--inits 10-01 10-17 11-01] [--varieties maize_early sorghum]
       python -m crop_engine.hindcast_s2s --engine dssat --workers 3
"""
import argparse
import datetime as dt
import json
import sys
import time

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C
from crop_engine import hindcast as hc
from crop_engine import run_outlook as ro
from crop_engine.data import era5land
from crop_engine.data import soil as soil_mod
from crop_engine.data import seas5 as s5
from crop_engine.data import weather as W
from crop_engine.scenarios import planting as pl

import onset_rules as orl  # noqa: E402
import process_ecmwf_september as pes  # noqa: E402

REFC = C.BASE / "data" / "ecmwf_s2s_reforecast"
INITS = ["10-01", "10-17", "11-01"]
LEAD_WINDOW = 3
RULE = "rule1"
OUT = C.OUT / "verification"


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] s2s hindcast: {m}", flush=True)


def reforecast_temperature(init_md, sites):
    """(hyears, tmax, tmin (hyear, member, lead, site)) of the model-version date, or None when not on disk."""
    f = REFC / f"refc_t2m_2026{init_md.replace('-', '')}_kenya.nc"
    if not f.exists():
        return None
    with xr.open_dataset(f) as ds:
        sel = dict(lat=xr.DataArray([s.lat for s in sites], dims="site"),
                   lon=xr.DataArray([s.lon for s in sites], dims="site"))
        return (ds.hyear.values.astype(int), ds["tmax"].sel(**sel, method="nearest").values.astype(np.float32),
                ds["tmin"].sel(**sel, method="nearest").values.astype(np.float32))


def corrected_temperature(reft, inp, init_md, y, k, smooth=3):
    """Site k's reforecast tmax, tmin of year y (member, lead), delta-corrected without year y (module doc)."""
    from crop_engine.data.s2s_temperature import _smooth
    hyears, tx, tn = reft
    others = [i for i, h in enumerate(hyears) if h != y]
    iy = hyears.tolist().index(y)
    t = inp.temps[inp.sites[k].id]
    out = []
    for key, a in (("tmax", tx), ("tmin", tn)):
        n_lead = a.shape[2]
        obs = np.stack([t[key].reindex(pd.date_range(pd.Timestamp(f"{hyears[i]}-{init_md}"), periods=n_lead)).values
                        for i in others])                                       # (year, lead)
        with np.errstate(invalid="ignore"):
            bias = _smooth(np.nanmean(a[others][:, :, :, k].mean(axis=1) - obs, axis=0)[:, None], smooth)[:, 0]
        out.append(a[iy, :, :, k] - bias[None])
    return out[0], np.minimum(out[1], out[0])


def reforecast(init_md, sites):
    """(hyears, (hyear, member, lead, site) rain at the sites' nearest cells) of the model-version date init_md."""
    f = REFC / f"refc_tp_2026{init_md.replace('-', '')}_kenya.nc"
    with xr.open_dataset(f) as ds:
        p = ds["precip"].sel(lat=xr.DataArray([s.lat for s in sites], dims="site"),
                             lon=xr.DataArray([s.lon for s in sites], dims="site"), method="nearest")
        return ds.hyear.values.astype(int), np.clip(p.values.astype(np.float32), 0, None)


def mapped(hyears, ref, inp, init_md, y, k):
    """Site k's reforecast of year y (member, lead), quantile-mapped to CHIRPS without year y (module doc)."""
    out = np.empty(ref.shape[1:3], np.float32)
    others = [i for i, h in enumerate(hyears) if h != y]
    n_lead = ref.shape[2]
    sid = inp.sites[k].id
    for L in range(n_lead):
        lo, hi = max(0, L - LEAD_WINDOW), min(n_lead, L + LEAD_WINDOW + 1)
        s_pool = ref[others][:, :, lo:hi, k].ravel()
        c_pool = np.concatenate([inp.hist[sid].reindex(pd.date_range(pd.Timestamp(f"{hyears[i]}-{init_md}") + pd.Timedelta(days=lo),
                                                                     periods=hi - lo)).values for i in others])
        f = pes._build_qm_transfer(c_pool[np.isfinite(c_pool)], s_pool[np.isfinite(s_pool)])
        out[:, L] = f(ref[hyears.tolist().index(y), :, L, k])
    return out


def climatology_rain(inp, dates, y, n_mem):
    """(member, site, T): member k's rain on each date is CHIRPS of pool year (k + y) on the same day and month."""
    pool = [c for c in range(C.HIST_YEARS[0], C.HIST_YEARS[1]) if c != y]
    out = np.empty((n_mem, len(inp.sites), len(dates)), np.float32)
    for m in range(n_mem):
        c = pool[(m + y) % len(pool)]
        md = pd.DatetimeIndex([pd.Timestamp(c + (d.year - y), d.month, min(d.day, 28 if d.month == 2 else d.day))
                               for d in dates])
        out[m] = inp.observed_rain(md)
    return out


def met_series(inp, dates, start):
    """DSSAT's radiation, vapour pressure and wind (site, T): ERA5-Land to `start`, the day-of-year climatology from it."""
    r = inp.radiation(dates)
    if r is None:
        raise RuntimeError("no ERA5-Land radiation, humidity or wind at the sites (DSSAT needs them)")
    vals, _, elev = r
    after = dates >= start
    doy = era5land.doy_noleap(dates[after]) - 1
    out = {}
    for col in vals:
        v = vals[col].copy()
        for k, st in enumerate(inp.sites):
            v[k, after] = inp.met2_clim[st.id][col][doy]
        out[col] = v.astype(np.float32)
    return out, elev


def simulate(inp, years, inits, rep_cells, varieties, soils, workers, engine="aquacrop"):
    pet = orl.load_pet(inp.lat, inp.lon, orl.EXT_DAYS)
    refs = {md: reforecast(md, inp.sites) for md in inits}
    reft = {md: reforecast_temperature(md, inp.sites) for md in inits}
    log("reforecast temperature: " + ", ".join(f"{md} {'on disk' if reft[md] else 'missing'}" for md in inits))
    ids = [x.id for x in inp.sites]
    tasks, keys = [], []
    for y in years:
        dates = inp.dates(y)
        obs = inp.observed_rain(dates)
        tmax, tmin, et0, _, _ = inp.met(y, dates)
        frac = inp.initial_water(y)
        for md in inits:
            hyears, ref = refs[md]
            if y not in hyears:
                continue
            I = pd.Timestamp(f"{y}-{md}")
            n_mem = ref.shape[1]
            clim = climatology_rain(inp, dates, y, n_mem)
            fc_days = (dates >= I) & (dates < I + pd.Timedelta(days=ref.shape[2]))
            after = dates >= I
            doy = era5land.doy_noleap(dates[after]) - 1
            tx, tn, e0 = tmax.copy(), tmin.copy(), et0.copy()
            for k, s in enumerate(inp.sites):
                cx, cn = inp.tclim[s.id]
                tx[k, after], tn[k, after] = cx[doy], np.minimum(cn[doy], cx[doy])
            e0[:, after] = inp.et0_clim.T[:, after]
            met = met_series(inp, dates, I) if engine == "dssat" else None
            for s, _ in rep_cells:
                k = ids.index(s.id)
                base = np.where(after[None], clim[:, k], obs[k][None])               # observations only
                fcr = base.copy()
                fcr[:, fc_days] = mapped(hyears, ref, inp, md, y, k)[:, :fc_days.sum()]
                TX, TN, E0 = (np.repeat(a[k][None], n_mem, 0) for a in (tx, tn, e0))
                runs = [("forecast", fcr, TX, TN, E0), ("reference", base, TX, TN, E0)]
                if reft[md] is not None and y in reft[md][0]:
                    gx, gn = corrected_temperature(reft[md], inp, md, y, k)
                    n = int(fc_days.sum())
                    tx_f, tn_f, e_f = TX.copy(), TN.copy(), E0.copy()
                    ratio = s5.hargreaves_ratio(gx[:, :n], gn[:, :n], TX[:, fc_days], TN[:, fc_days])
                    tx_f[:, fc_days], tn_f[:, fc_days] = gx[:, :n], gn[:, :n]
                    e_f[:, fc_days] = E0[:, fc_days] * ratio
                    runs.append(("forecast_t", fcr, tx_f, tn_f, e_f))
                for kind, rain, rx, rn, re in runs:
                    plant = [pl.observed_rule_date(rain[m], dates, pet[:, s.i, s.j], RULE) for m in range(n_mem)]
                    resow = pl.sowing_opportunities(rain, dates)
                    for vk, v in varieties.items():
                        t = dict(dates=dates.values, rain=rain, tmax=rx.astype(np.float32),
                                 tmin=rn.astype(np.float32), et0=re.astype(np.float32),
                                 source=np.zeros(len(dates), np.int8), planting=plant, resow=resow, variety=v,
                                 kw=v["kw"], layers=soils[s.id], initial_frac=float(frac[k]))
                        if met is not None:
                            vals, elev = met
                            t.update(rad=vals["rad_mj_m2"][k], vap=vals["vap_hpa"][k], wind2=vals["wind2_ms"][k],
                                     lat=s.lat, lon=s.lon, elev=float(elev[k]), potential=False)
                        tasks.append(t)
                        keys.append((s.id, vk, md, kind, y))
    log(f"{len(tasks)} forecasts to simulate ({sum(len(t['planting']) for t in tasks)} member seasons)")
    t0 = time.time()
    res = ro.run_tasks(tasks, workers, engine=engine)
    log(f"simulated in {time.time() - t0:.0f} s")
    out = {}
    for (sid, vk, md, kind, y), members in zip(keys, res):
        out.setdefault(sid, {}).setdefault(vk, {}).setdefault(md, {}).setdefault(kind, {})[str(y)] = [
            ro.effective_yield(m) for m in members if m["status"] != "error"]
    return out


def score(members, bench, varieties, years):
    out = {}
    for sid, vs in members.items():
        for vk, inits in vs.items():
            thr = varieties[vk]["failure_t_ha"]
            b = bench[sid][vk][RULE]["years"]
            for md, kinds in inits.items():
                yy = [y for y in years if str(y) in kinds["forecast"] and str(y) in b]
                obs = np.array([ro.effective_yield(b[str(y)]) for y in yy])
                first = [b[str(y)].get("first_planting") or b[str(y)].get("planting") for y in yy]
                open_ = np.array([f is None or f >= f"{y}-{md}" for f, y in zip(first, yy)])
                cell = {"years": yy, "observed_t_ha": obs.round(3).tolist(), "open_years": int(open_.sum())}
                for kind in [x for x in ("forecast", "forecast_t", "reference") if x in kinds]:
                    rows = [kinds[kind][str(y)] for y in yy]
                    n = min(map(len, rows))
                    fc = np.array([r[:n] for r in rows])
                    cell[kind] = hc.scores(fc, obs, thr)
                    cell[f"{kind}_open"] = hc.scores(fc[open_], obs[open_], thr) if open_.sum() >= 8 else None
                    cell[f"{kind}_median_t_ha"] = np.median(fc, axis=1).round(3).tolist()
                out.setdefault(sid, {}).setdefault(vk, {})[md] = cell
    return out


def table(sc):
    f = lambda x: "  —  " if x is None else f"{x:+.2f}"  # noqa: E731
    log(f"{'site':16s} {'crop':12s} {'start':5s} | r fc / obs-only (open years) | failure AUC fc / obs-only | n open")
    for sid, vs in sc.items():
        for vk, inits in vs.items():
            for md, c in inits.items():
                o, ro_ = c["forecast_open"] or {}, c["reference_open"] or {}
                log(f"{sid[:16]:16s} {vk:12s} {md:5s} | {f(c['forecast']['spearman'])} / {f(c['reference']['spearman'])} "
                    f"({f(o.get('spearman'))} / {f(ro_.get('spearman'))}) | "
                    f"{f(c['forecast']['failure_auc'])} / {f(c['reference']['failure_auc'])} | {c['open_years']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inits", nargs="+", default=INITS)
    ap.add_argument("--varieties", nargs="+", default=["maize_early", "sorghum"])
    ap.add_argument("--sites", nargs="+")
    ap.add_argument("--years", nargs=2, type=int, default=[2006, 2025])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--engine", choices=["aquacrop", "dssat"], default="aquacrop",
                    help="dssat: DSSAT's varieties against DSSAT's own benchmark (climatology_dssat.json)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    years = list(range(a.years[0], a.years[1] + 1))
    _, varieties = ro.load_varieties(a.varieties)
    inp = W.Inputs(refresh=False)
    bench = json.loads((C.OUT / "climatology.json").read_text(encoding="utf-8"))
    if a.engine == "dssat":
        varieties = {vk: varieties[vk] for vk in ro.dssat_varieties(varieties)}
        bp = C.OUT / "climatology_dssat.json"
        if not bp.exists():
            log("no DSSAT benchmark (climatology_dssat.json): run the outlook once with DSSAT")
            return 1
        bench = json.loads(bp.read_text(encoding="utf-8"))
    rep_cells = [(s, g) for s, g in ro.cells(inp.sites) if not a.sites or s.id in a.sites]
    soils = {s.id: soil_mod.profile(s) for s, _ in rep_cells}
    members = simulate(inp, years, a.inits, rep_cells, varieties, soils, a.workers, a.engine)
    sc = score(members, bench["sites"], varieties, years)
    table(sc)
    OUT.mkdir(parents=True, exist_ok=True)
    name = "hindcast_s2s.json" if a.engine == "aquacrop" else f"hindcast_s2s_{a.engine}.json"
    (OUT / name).write_text(json.dumps({
        "years": years, "inits": a.inits, "rule": RULE, "config_hash": bench.get("config_hash"), "engine": a.engine,
        "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "reference": "the crop grown in the observed weather ("
                     + ("climatology.json" if a.engine == "aquacrop" else f"climatology_{a.engine}.json") + "), Agri rule 1",
        "sites": sc,
        "members": members}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
