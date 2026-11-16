#!/usr/bin/env python3
"""
DSSAT's dry bean (dssat_cultivars.yaml `bean`: BNGRO048 IB0014 Canadian Wonder, its phases fitted to the class's 75
days at 21 °C, its yield level DSSAT's own) against the Kenyan bean trials of the yields database
(crop_engine/yields observations: N2Africa's agronomy trials, IITA, and the Kenya soil health compilation).

The trials. Bush-bean plots with a sowing date to the day, coordinates and a season within the platform's weather
(HIST_YEARS), grouped into trial-seasons (study, place to 0.01°, sowing date). Climbing beans are left out (DSSAT's
Canadian Wonder is a bush bean): N2Africa labels its experiments BB / CB; the soil-health plots are classed by their
cultivar (HABIT; Kenya Umoja AFR 708 bush, Kenya Tamu MAC 34 and Kenya Mavuno MAC 64 climbing, as N2Africa's own
experiments class them); a plot with no cultivar or an unknown one is left out. The plots are farmers' fields and
on-farm trials in western Kenya (Busia, Siaya, Kakamega, Bungoma, Migori, Kisumu), 2010–2012: not at the monitored
sites, and limited by phosphorus, diseases and pests as well as water.

The runs. Each trial-season is grown by DSSAT as the outlook grows the bean: sown on the trial's date, in that
season's weather at the trial (CHIRPS v2 rain of its 0.25° cell; ERA5-Land temperature, solar radiation, vapour
pressure and wind at the point), on the SoilGrids profile of its 0.25° cell, from SPINUP_DAYS before sowing with
INITIAL_FRAC of the soil's available water (INITIAL_SENSITIVITY: the same with a drier and a wetter start). Three
yields per trial-season: water-limited (the outlook's production level: no nitrogen limit), its yield without water
stress (potential_t_ha), and nitrogen-limited (DSSAT's nitrogen balance on, the bean fixing its own nitrogen, no
fertiliser, the soil's regional organic-nitrogen factor: run_nitrogen's n0).

The test, set before the runs. These plots can only bound the model from below: a model without phosphorus, disease
or pest limits should yield at least what the best-managed plots of a trial-season yielded (their 90th percentile),
as the maize yield level was checked against trials (calibration/wofost.py CHECKS, upper bounds). The yield level is
kept if the water-limited yield is at least that in UPPER_BOUND_SHARE of the trial-seasons; otherwise it is too low.
A yield far above the plots is not evidence against it (the plots' limits are not modelled). The phenology: DSSAT's
days to flowering and to maturity against N2Africa's dates (50 % flowering, full maturity) of the same trials.

Writes outputs/crop_engine/calibration/dssat/bean.json and bean_trials.csv. Usage:
python -m crop_engine.calibration.bean [--workers 2]
"""
import argparse
import datetime as dt
import json
import sys

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import dssat_adapter as ds
from crop_engine.data import era5land
from crop_engine.data import soil as soil_mod
from crop_engine.data.sites import Site

OUT = C.OUT / "calibration" / "dssat"
CHIRPS_HIST = C.BASE / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
CACHE_DIR = C.CACHE / "bean_trials"           # the trial points' ERA5-Land over the trials' window (point_weather)
SPINUP_DAYS = 60
SEASON_DAYS = 200                 # weather after sowing (the bean matures in about 75-95 days)
INITIAL_FRAC = 0.5
INITIAL_SENSITIVITY = (0.25, 0.75)
UPPER_BOUND_SHARE = 0.75
MIN_PLOTS = 3
# growth habit of the soil-health plots' cultivars (upper case, spaces removed); N2Africa's own BB / CB label first
CLIMBING = ("KENYATAMU", "KENYAMAVUNO", "KENYASAFI", "UMUBANO", "GASIRIDA", "GASILIDA", "MAMESA", "MAC", "RWV")
BUSH = ("KENYAUMOJA", "KATB", "KATX", "NEWROSCOCO", "ROSECOCO", "KK", "OKWODHO", "LOCALCHECK(TSIMBINDI)", "TSIMBINDI")


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] bean check: {m}", flush=True)


def habit(maturity_class, cultivar):
    """'bush', 'climbing' or None: N2Africa's experiment label, else the cultivar's (HABIT in the module doc)."""
    if isinstance(maturity_class, str) and maturity_class in ("bush bean", "climbing bean"):
        return maturity_class.split()[0]
    if not isinstance(cultivar, str):
        return None
    c = cultivar.upper().replace(" ", "")
    if c.startswith(CLIMBING):
        return "climbing"
    if c.startswith(BUSH):
        return "bush"
    return None


def trial_seasons(obs, years=C.HIST_YEARS):
    """The bean plots grouped into trial-seasons (module doc) → DataFrame, one row each, with the plots' yields
    (dry, t/ha) and N2Africa's phenology."""
    b = obs[(obs.crop == "bean") & (obs.date_quality == "day") & obs.latitude.notna() & obs.longitude.notna()].copy()
    b["habit"] = [habit(m, c) for m, c in zip(b.maturity_class, b.cultivar)]
    b["sown"] = pd.to_datetime(b.planting_date)
    b = b[b.sown.dt.year.between(years[0], years[1])]
    b["lat"], b["lon"] = b.latitude.round(2), b.longitude.round(2)
    y = b.grain_yield_dry_kg_ha / 1000.0
    b["y"] = y
    g = b.groupby(["habit", "study", "lat", "lon", "planting_date"], dropna=False)
    t = g.agg(location=("location", "first"), season=("season", "first"), plots=("y", "size"),
              cultivars=("cultivar", lambda s: ", ".join(sorted(s.dropna().astype(str).str.strip().unique())[:4])),
              obs_median=("y", "median"), obs_p90=("y", lambda s: s.quantile(0.9)), obs_max=("y", "max"),
              obs_flowering_days=("days_to_flowering", "median"), obs_maturity_days=("days_to_maturity", "median"),
              harvest=("harvest_date", lambda s: s.dropna().min() if s.notna().any() else None)).reset_index()
    t = t[t.plots >= MIN_PLOTS].reset_index(drop=True)
    t["habit"] = t.habit.fillna("unknown")
    t["point"] = [f"bean_{la:+.2f}_{lo:.2f}" for la, lo in zip(t.lat, t.lon)]
    return t


def _sites(trials):
    """One Site per trial point, its 0.25° cell the CHIRPS / SoilGrids cell it falls in."""
    with xr.open_dataset(CHIRPS_HIST) as d:
        glat, glon = d.lat.values, d.lon.values
    out = {}
    for p, la, lo in trials[["point", "lat", "lon"]].drop_duplicates("point").itertuples(index=False):
        out[p] = Site(p, p, float(la), float(lo), "kenya", cell_lat=float(glat[np.abs(glat - la).argmin()]),
                      cell_lon=float(glon[np.abs(glon - lo).argmin()]))
    return out


def _rain(sites):
    with xr.open_dataset(CHIRPS_HIST) as d:
        p = d["precip"].sel(lat=xr.DataArray([s.cell_lat for s in sites.values()], dims="site"),
                            lon=xr.DataArray([s.cell_lon for s in sites.values()], dims="site"), method="nearest")
        return pd.DataFrame(p.values.astype(np.float32), index=pd.DatetimeIndex(d.time.values), columns=list(sites))


def window(trials):
    """The weather the trial-seasons need: SPINUP_DAYS before the first sowing to SEASON_DAYS after the last."""
    sown = pd.to_datetime(trials.planting_date)
    return ((sown.min() - pd.Timedelta(days=SPINUP_DAYS)).date(), (sown.max() + pd.Timedelta(days=SEASON_DAYS)).date())


def point_weather(sites, start, end):
    """ERA5-Land at the trial points for start..end only, cached in CACHE_DIR: tmax, tmin (Open-Meteo's archive, as
    era5land.site_temperature) and solar radiation, vapour pressure, 2 m wind and surface pressure (Earth Engine, as
    era5land.site_met). Not era5land's own site caches: those fetch 1993 to today, thousands of Open-Meteo calls for
    points needed over two or three years. → {point: DataFrame by date}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out, missing = {}, []
    for p, s in sites.items():
        f = CACHE_DIR / f"{p}_{start}_{end}.csv"
        if f.exists() and f.stat().st_size:
            out[p] = pd.read_csv(f, parse_dates=["date"]).set_index("date")
        else:
            missing.append(s)
    if missing:
        log(f"ERA5-Land for {len(missing)} trial points, {start} to {end}")
        raw = era5land._ee_fetch(missing, start, end)
        for s in missing:
            t = era5land._fetch(s.lat, s.lon, start, end).set_index("date")
            m = era5land.derive(raw[s.id])
            df = t.join(m, how="inner")
            df.index.name = "date"
            df.to_csv(CACHE_DIR / f"{s.id}_{start}_{end}.csv", float_format="%.3f")
            out[s.id] = df
    return out


def build_tasks(trials, variety, sites, initial_frac=INITIAL_FRAC):
    """The DSSAT tasks of the trial-seasons (module doc): water-limited (with its potential) and nitrogen-limited."""
    import fao_water_balance as fw  # noqa: E402  (scripts/, on sys.path via config)
    rain = _rain(sites)
    wx = point_weather(sites, *window(trials))
    temps = met = wx
    soils = {p: soil_mod.profile(s) for p, s in sites.items()}
    soil_n = ds.soil_nitrogen()                      # the regional soil nitrogen: these fields are not the sites'
    tasks, nitro = [], []
    for r in trials.itertuples():
        s, sown = sites[r.point], dt.date.fromisoformat(r.planting_date)
        d = pd.date_range(sown - dt.timedelta(days=SPINUP_DAYS), periods=SPINUP_DAYS + SEASON_DAYS)
        t, m = temps[r.point].reindex(d), met[r.point].reindex(d)
        w = pd.DataFrame({"rain": rain[r.point].reindex(d), "tmax": t.tmax, "tmin": t.tmin, "rad": m.rad_mj_m2,
                          "vap": m.vap_hpa, "wind2": m.wind2_ms})
        if w.isna().any().any():
            raise ValueError(f"{r.point}: weather missing between {d[0].date()} and {d[-1].date()}")
        elev = float(fw.elevation_from_pressure(float(met[r.point].sp_kpa.mean())))
        task = dict(dates=d.values, rain=w.rain.values, tmax=w.tmax.values, tmin=w.tmin.values, rad=w.rad.values,
                    vap=w.vap.values, wind2=w.wind2.values, et0=np.zeros(len(d)), source=np.zeros(len(d), int),
                    planting=[sown], resow=None, variety=variety, kw=variety["kw"], layers=soils[r.point],
                    initial_frac=initial_frac, lat=s.lat, lon=s.lon, elev=elev)
        tasks.append(task)
        nitro.append(dict(task, potential=False,
                          nitrogen={"rate_kg_ha": 0, "split": [[0, 1.0]], **soil_n}))
    return tasks, nitro


def _days(m, key):
    if m.get(key) and m.get("planting"):
        return (dt.date.fromisoformat(m[key]) - dt.date.fromisoformat(m["planting"])).days
    return None


def simulate(trials, variety, sites, workers, initial_frac=INITIAL_FRAC, nitrogen=True):
    tasks, nitro = build_tasks(trials, variety, sites, initial_frac)
    res = ro.run_tasks(tasks + (nitro if nitrogen else []), workers, engine="dssat")
    out = trials.copy()
    wl = [r[0] for r in res[:len(tasks)]]
    out["status"] = [m["status"] for m in wl]
    out["sim_t_ha"] = [round(float(m["yield_t_ha"] or 0.0), 3) for m in wl]
    out["sim_potential_t_ha"] = [m.get("potential_t_ha") for m in wl]
    out["sim_flowering_days"] = [_days(m, "anthesis") for m in wl]
    out["sim_maturity_days"] = [_days(m, "harvest") if m["status"] == "ok" else None for m in wl]
    out["sim_stress_days"] = [m.get("stress_days") for m in wl]
    out["sim_rain_mm"] = [m.get("rain_mm") for m in wl]
    if nitrogen:
        out["sim_n0_t_ha"] = [round(float(r[0]["yield_t_ha"] or 0.0), 3) for r in res[len(tasks):]]
    return out


def summarize(t):
    """The test of the module doc on the bush-bean trial-seasons (and the same figures for the others, as context)."""
    from scipy.stats import spearmanr
    out = {}
    for h, g in t.groupby("habit"):
        ok = g[g.status.isin(["ok", "died", "too_late", "failed_establishment"])]
        above = (ok.sim_t_ha >= ok.obs_p90)
        rho = (spearmanr(ok.sim_t_ha, ok.obs_median)[0] if len(ok) >= 5 and ok.sim_t_ha.nunique() > 1 else None)
        fl = (g.sim_flowering_days - g.obs_flowering_days).dropna()
        mt = (g.sim_maturity_days - g.obs_maturity_days).dropna()
        s = {"trial_seasons": int(len(g)), "plots": int(g.plots.sum()), "simulated": int(len(ok)),
             "statuses": g.status.value_counts().to_dict(),
             "obs_median_t_ha": round(float(g.obs_median.median()), 2), "obs_p90_t_ha": round(float(g.obs_p90.median()), 2),
             "obs_max_t_ha": round(float(g.obs_max.max()), 2),
             "sim_median_t_ha": round(float(ok.sim_t_ha.median()), 2) if len(ok) else None,
             "sim_potential_median_t_ha": (round(float(pd.to_numeric(ok.sim_potential_t_ha).median()), 2)
                                           if len(ok) else None),
             "sim_at_or_above_p90": int(above.sum()), "share_at_or_above_p90": round(float(above.mean()), 2) if len(ok) else None,
             "spearman_sim_vs_obs_median": None if rho is None or np.isnan(rho) else round(float(rho), 2),
             "flowering_bias_days": {"n": int(len(fl)), "mean": round(float(fl.mean()), 1) if len(fl) else None},
             "maturity_bias_days": {"n": int(len(mt)), "mean": round(float(mt.mean()), 1) if len(mt) else None}}
        if "sim_n0_t_ha" in g:
            s["sim_n0_median_t_ha"] = round(float(ok.sim_n0_t_ha.median()), 2) if len(ok) else None
        out[h] = s
    b = out.get("bush")
    verdict = None
    if b and b["simulated"]:
        verdict = ("kept: at or above the best plots in {:.0%} of the bush-bean trial-seasons (rule: {:.0%})"
                   if b["share_at_or_above_p90"] >= UPPER_BOUND_SHARE else
                   "too low: at or above the best plots in only {:.0%} of the bush-bean trial-seasons (rule: {:.0%})"
                   ).format(b["share_at_or_above_p90"], UPPER_BOUND_SHARE)
    return out, verdict


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ds.installed():
        log(f"DSSAT is not installed ({ds.EXE}): python -m crop_engine.adapters.dssat_adapter --install")
        return 1
    from crop_engine.yields import observations
    obs = observations.load_all(log=log)
    trials = trial_seasons(obs)
    log(f"{len(trials)} trial-seasons ({trials.groupby('habit').size().to_dict()}), "
        f"{trials.point.nunique()} points, {int(trials.plots.sum())} plots")
    _, vs = ro.load_varieties(["bean"])
    ds.attach(vs)
    bean = vs["bean"]
    sites = _sites(trials)
    t = simulate(trials, bean, sites, a.workers)
    summary, verdict = summarize(t)
    sens = {}
    for f in INITIAL_SENSITIVITY:
        s = simulate(trials, bean, sites, a.workers, initial_frac=f, nitrogen=False)
        sens[str(f)] = {"sim_median_t_ha_bush": round(float(s[s.habit == "bush"].sim_t_ha.median()), 2),
                        "max_change_t_ha": round(float((s.sim_t_ha - t.sim_t_ha).abs().max()), 2)}
        log(f"initial water {f}: bush median {sens[str(f)]['sim_median_t_ha_bush']} t/ha, "
            f"largest change {sens[str(f)]['max_change_t_ha']} t/ha")
    for h, s in summary.items():
        log(f"{h}: {s}")
    log(f"yield level {verdict}")
    res = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
           "variety": {"cultivar": bean["dssat"]}, "initial_frac": INITIAL_FRAC, "spinup_days": SPINUP_DAYS,
           "rule": {"upper_bound": "the trial-season's 90th-percentile plot yield", "share": UPPER_BOUND_SHARE},
           "summary": summary, "verdict": verdict, "initial_water_sensitivity": sens}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bean.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    t.to_csv(OUT / "bean_trials.csv", index=False)
    log(f"written to {OUT / 'bean.json'} and bean_trials.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
