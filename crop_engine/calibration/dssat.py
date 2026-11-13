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

Soil nitrogen (--nitrogen). With DSSAT's nitrogen balance on, the SoilGrids organic carbon (with a C : N of 10)
mineralises so much nitrogen that maize without fertiliser yields as much as with it, which cropped dryland fields
do not: a cropped field's organic nitrogen is depleted. One factor on the soil's organic nitrogen (organic_n_factor,
dssat_cultivars.yaml "soil") is fitted so that early maize without fertiliser yields N_TARGET of its yield with 60
kg N/ha, at the median of the observed Short Rains seasons N_YEARS at N_SITES (FAO agricultural onset, the
outlook's urea split): the ratio Kenyan maize nitrogen trials give (crop_engine/yields observations: the median of
24 trial-seasons 0.63, 8 in the east 0.64, the dryland Short Rains seasons of Machang'a 2005 and 2006 and Machakos
2015 0.57–0.59). A first, regional calibration: the sites' own fields are not measured.

Writes outputs/crop_engine/calibration/dssat/result.json (nitrogen: nitrogen.json) and prints the coefficients for crop_engine/dssat_cultivars.yaml
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
N_TARGET = {"ratio_0_60": 0.62, "source": "Kenyan maize nitrogen trials (crop_engine/yields observations): median "
                                            "yield without N over the yield with 45-75 kg N/ha, 24 trial-seasons 0.63, "
                                            "8 eastern 0.64, dryland Short Rains 0.57-0.59"}
N_SITES = ("kalro_kiboko_makueni_farm", "kapiti_research_station_farm")
N_YEARS = (1993, 2016)
N_SPLIT = [(0, 0.4), (30, 0.6)]
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


def nitrogen_ratio(tasks, factor, workers, initial=None):
    """Median, over the seasons whose crop matures with 60 kg N/ha, of the yield without N over the yield with it.
    initial: {initial_no3_ppm, initial_nh4_ppm} (default: the adapter's)."""
    from crop_engine import run_outlook as ro_
    runs = []
    for t in tasks:
        for rate in (0, 60):
            runs.append(dict(t, nitrogen={"rate_kg_ha": rate, "split": N_SPLIT, "organic_n_factor": factor,
                                          **(initial or {})}))
    res = ro_.run_tasks(runs, workers, engine="dssat")
    ratios = []
    for k in range(0, len(res), 2):
        y0, y60 = res[k][0], res[k + 1][0]
        if y60["status"] == "ok" and y60["yield_t_ha"] >= 0.5:
            ratios.append((y0["yield_t_ha"] if y0["status"] in ("ok", "died") else 0.0) / y60["yield_t_ha"])
    return (float(np.median(ratios)) if ratios else None), len(ratios)


def calibrate_nitrogen(workers, initial_scale=None, factors=(1.0, 0.5, 0.25, 0.12, 0.06)):
    """The regional organic-nitrogen factor (module doc), with the starting mineral nitrogen × initial_scale of the
    adapter's INIT_NO3 / INIT_NH4 (default: the regional value of dssat_cultivars.yaml soil)."""
    from crop_engine import compare_engines as ce
    from crop_engine.data import soil as soil_mod
    from crop_engine.data import weather as W
    _, vs = ro.load_varieties(["maize_early"])
    ds.attach(vs)
    inp = W.Inputs(refresh=False)
    rep = [(s, g) for s, g in ro.cells(inp.sites) if s.id in N_SITES]
    soils = {s.id: soil_mod.profile(s) for s, _ in rep}
    tasks, _ = ce.tasks_for(inp, list(range(N_YEARS[0], N_YEARS[1] + 1)), rep, vs, ["fao-agricultural"], soils)
    tasks = [t for t in tasks if t["planting"][0] is not None]
    log(f"nitrogen: {len(tasks)} observed seasons at {', '.join(N_SITES)}, early maize, 0 and 60 kg N/ha")
    reg = ds.soil_nitrogen()
    initial = ({"initial_no3_ppm": reg["initial_no3_ppm"], "initial_nh4_ppm": reg["initial_nh4_ppm"]}
               if initial_scale is None else
               {"initial_no3_ppm": ds.INIT_NO3 * initial_scale, "initial_nh4_ppm": ds.INIT_NH4 * initial_scale})
    log(f"nitrogen: starting mineral N {initial}")
    target = N_TARGET["ratio_0_60"]
    scan = {}
    ratio = lambda f: scan.setdefault(f, nitrogen_ratio(tasks, f, workers, initial))[0]        # noqa: E731
    for f in factors:
        log(f"  organic N × {f}: ratio {ratio(f)} ({scan[f][1]} seasons)")
    f, r, reached = _fit(ratio, target, sorted(scan), lambda v: abs(v - target) < 0.01)
    log(f"nitrogen: organic_n_factor {f} → ratio {r:.3f} (target {target}{'' if reached else ', not reached'})")
    out = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "target": N_TARGET,
           "sites": list(N_SITES), "years": list(N_YEARS), "split": N_SPLIT, "c_to_n": ds.C_TO_N,
           "initial_ppm": {"NO3": initial["initial_no3_ppm"], "NH4": initial["initial_nh4_ppm"]},
           "scan": {str(k): {"ratio": v[0], "seasons": v[1]} for k, v in sorted(scan.items())},
           "organic_n_factor": f, "ratio": r, "reached": reached}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nitrogen.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    log(f"dssat_cultivars.yaml soil: {{organic_n_factor: {f}}}")
    return 0


# ── the sites' own fields (--nitrogen-sites) ───────────────────────────────────────────────────────────────────────
# Nitrogen trials on or beside a monitored site's own fields (crop_engine/yields observations). Each is grown in its
# own season and the site's soil nitrogen (dssat_cultivars.yaml soil.sites) fitted to its measured response: the yield
# at each rate over the yield at the trial's top rate (reference "top"), or, where the response is flat above the
# lowest rate (reference "fertilised"), the unfertilised yield over the mean of the fertilised rates; so the trial's
# own yield level (variety, phosphorus, pests) does not enter.
SITE_TRIALS = {
    "kalro_kiboko_makueni_farm": dict(
        studies=("doi_10.7910_DVN_SOAWL6", "doi_10.5061_dryad.j3tx95xhc"), location="Kiboko", year=2013,
        rates=(0, 40, 80, 160), variety="maize_medium", irrigated=True, sowings="dry season, Jun-Jul (not reported)",
        fit=("organic_n_factor", "initial"),
        source="KALRO Kiboko 2013, irrigated, 0/40/80/160 kg N/ha with 20 kg P/ha (Kenya soil health compilation: "
               "doi 10.7910/DVN/SOAWL6 and its Dryad copy 10.5061/dryad.j3tx95xhc)"),
    "kapiti_research_station_farm": dict(
        studies=("doi_10.5061_dryad.fg15tg2",), location="Machakos", year=2015, rates=(0, 30, 60, 90, 120),
        variety="maize_early", irrigated=False, sowings="2015-04-08", fit=("organic_n_factor",),
        reference="fertilised",       # a poor season: the yield peaks at 30 kg N/ha and is flat above
        source="Machakos 2015 Long Rains, rainfed, 0-120 kg N/ha x 0-22 kg P/ha, sown 8 Apr 2015, about 15 km from "
               "Kapiti (Kenya soil health compilation: doi 10.5061/dryad.fg15tg2)"),
}
SITE_FACTORS = (0.01, 0.02, 0.04, 0.06, 0.1, 0.2, 0.3, 0.5)
SITE_INITIAL = (0.0, 0.25, 0.5, 1.0)          # × INIT_NO3 / INIT_NH4, the starting mineral nitrogen
IRRIGATED = {"irrigation_method": 1, "SMT": [70, 70, 70, 70]}
RAINFED_START_DAYS, RAINFED_INITIAL_FRAC = 60, 0.25


def observed_response(obs, trial):
    """The trial's yield at each rate over its yield at the top rate: the mean of its studies' (copies') ratios of
    their mean yields per rate → ({rate: relative yield}, {rate: mean t/ha per study})."""
    o = obs[obs.study.isin(trial["studies"]) & (obs.crop == "maize")
            & obs.location.astype(str).str.contains(trial["location"]) & obs.n_kg_ha.isin(trial["rates"])]
    if trial.get("year"):
        o = o[(o.year == trial["year"]) | o.year.isna()]
    per = o.groupby(["study", "n_kg_ha"]).grain_yield_dry_kg_ha.mean().unstack() / 1000.0
    per = per.dropna(subset=[max(trial["rates"])])
    if per.empty:
        raise ValueError(f"no yields at {trial['location']} for {trial['studies']}")
    rel = per.div(_reference(per, trial), axis=0).mean()
    return ({int(k): round(float(v), 3) for k, v in rel.items()},
            {s: {int(k): round(float(v), 2) for k, v in r.dropna().items()} for s, r in per.iterrows()})


def _reference(y, trial):
    """The yield the response is relative to: the top rate's, or the mean of the fertilised rates' (SITE_TRIALS)."""
    if trial.get("reference", "top") == "fertilised":
        return y[[r for r in trial["rates"] if r > 0]].mean(axis=1) if isinstance(y, pd.DataFrame) else             float(np.mean([y[r] for r in trial["rates"] if r > 0]))
    return y[max(trial["rates"])]


def _fitted_rates(trial):
    return [0] if trial.get("reference", "top") == "fertilised" else [r for r in trial["rates"] if r != max(trial["rates"])]


def _trial_tasks(trial, site, variety, elev):
    """One DSSAT task per rate (members: the trial's sowings), without the nitrogen settings being fitted."""
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.sites import Site
    layers = soil_mod.profile(Site(site.id, site.name, site.lat, site.lon, site.country, cell_lat=site.lat,
                                   cell_lon=site.lon))
    if trial["irrigated"]:
        plants = cw.sowings(trial["year"])
        w = site_weather(site, plants[0] - dt.timedelta(days=5))
        rain, frac, extra = np.zeros(len(w)), 0.7, {"irrigation": IRRIGATED}
    else:
        plants = [dt.date.fromisoformat(trial["sowings"])]
        w = site_weather(site, plants[0] - dt.timedelta(days=RAINFED_START_DAYS))
        from crop_engine.calibration import bean as cb
        r = cb._rain({site.id: Site(site.id, site.name, site.lat, site.lon, site.country, cell_lat=site.lat,
                                    cell_lon=site.lon)})
        rain = r[site.id].reindex(w.index).values
        if np.isnan(rain).any():
            raise ValueError(f"CHIRPS missing at {site.id} from {w.index[0].date()}")
        frac, extra = RAINFED_INITIAL_FRAC, {}
    M = len(plants)
    base = dict(dates=w.index.values, rain=np.tile(rain, (M, 1)), tmax=w.tmax.values, tmin=w.tmin.values,
                rad=w.rad_mj_m2.values, vap=w.vap_hpa.values, wind2=w.wind2_ms.values, et0=np.zeros(len(w)),
                source=np.zeros(len(w), int), planting=plants, resow=None, variety=variety, kw=variety["kw"],
                layers=layers, initial_frac=frac, lat=site.lat, lon=site.lon, elev=elev, potential=False, **extra)
    return base, plants


def site_response(base, trial, factor, initial, workers):
    """Simulated yield at each rate relative to the trial's reference (_reference; means over the sowings)."""
    rates = trial["rates"]
    runs = [dict(base, nitrogen={"rate_kg_ha": r, "split": N_SPLIT, "organic_n_factor": factor,
                                 "initial_no3_ppm": ds.INIT_NO3 * initial, "initial_nh4_ppm": ds.INIT_NH4 * initial})
            for r in rates]
    res = ro.run_tasks(runs, workers, engine="dssat")
    y = {r: float(np.mean([m["yield_t_ha"] if m["status"] in ("ok", "died") else 0.0 for m in out]))
         for r, out in zip(rates, res)}
    top = _reference(y, trial)
    return ({r: (round(v / top, 3) if top > 0 else None) for r, v in y.items()}, {r: round(v, 2) for r, v in y.items()})


def calibrate_site_nitrogen(workers, only=None):
    """Each SITE_TRIALS site's soil nitrogen fitted to its trial (the comment above SITE_TRIALS): a grid over the
    organic factor (and, where the trial is irrigated, the starting mineral nitrogen), the least squares of the
    relative yields below the top rate. Writes calibration/dssat/nitrogen_sites.json and prints the soil.sites rows."""
    from crop_engine.yields import observations
    obs = observations.load_all(log=lambda m: None)
    import fao_water_balance as fw  # noqa: E402
    out = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "split": N_SPLIT,
           "c_to_n": ds.C_TO_N, "default_initial_ppm": {"NO3": ds.INIT_NO3, "NH4": ds.INIT_NH4}, "sites": {}}
    regional = ds.soil_nitrogen()
    for sid, trial in SITE_TRIALS.items():
        if only and sid not in only:
            continue
        site = next(s for s in registered_sites() if s.id == sid)
        _, vs = ro.load_varieties([trial["variety"]])
        ds.attach(vs)
        met = era5land.site_met([site], refresh=False)[site.id]
        elev = float(fw.elevation_from_pressure(float(met.sp_kpa.mean())))
        target, per_study = observed_response(obs, trial)
        base, plants = _trial_tasks(trial, site, vs[trial["variety"]], elev)
        below = _fitted_rates(trial)
        inits = SITE_INITIAL if "initial" in trial["fit"] else (regional["initial_no3_ppm"] / ds.INIT_NO3,)
        scan = []
        for f in SITE_FACTORS:
            for i in inits:
                rel, y = site_response(base, trial, f, i, workers)
                sse = (sum((rel[r] - target[r]) ** 2 for r in below) if all(rel[r] is not None for r in below)
                       else None)
                scan.append({"organic_n_factor": f, "initial_scale": i, "relative": rel, "yield_t_ha": y, "sse": sse})
                log(f"{sid}: organic N × {f}, starting mineral N × {i}: relative {rel} (observed {target}), "
                    f"yields {y}")
        ok = [s for s in scan if s["sse"] is not None]
        best = min(ok, key=lambda s: s["sse"])
        edge = [k for k, v, grid in (("organic_n_factor", best["organic_n_factor"], SITE_FACTORS),
                                     ("initial_scale", best["initial_scale"], inits))
                if len(grid) > 1 and v in (min(grid), max(grid))]
        # the organic factor and the starting mineral nitrogen trade off along a ridge (one trial fixes the field's
        # supply, not its split): the row adopted is the best organic factor at the regional starting nitrogen
        reg_scale = regional["initial_no3_ppm"] / ds.INIT_NO3
        at_reg = [s for s in ok if np.isclose(s["initial_scale"], reg_scale)]
        chosen = min(at_reg, key=lambda s: s["sse"]) if at_reg else best
        row = {"organic_n_factor": chosen["organic_n_factor"],
               "initial_no3_ppm": round(ds.INIT_NO3 * chosen["initial_scale"], 3),
               "initial_nh4_ppm": round(ds.INIT_NH4 * chosen["initial_scale"], 3), "source": trial["source"]}
        out["sites"][sid] = {"trial": {k: v for k, v in trial.items() if k != "studies"} | {"studies": list(trial["studies"])},
                             "sowings": [p.isoformat() for p in plants], "observed_relative": target,
                             "observed_t_ha": per_study, "best": best, "at_grid_edge": edge,
                             "at_regional_initial": chosen, "regional": regional, "scan": scan,
                             "dssat_cultivars_row": row}
        log(f"{sid}: best organic N × {best['organic_n_factor']}, starting mineral N × {best['initial_scale']} "
            f"(sse {best['sse']:.4f}): {best['relative']} against {target}" + (f"; at the grid's edge: {edge}" if edge else ""))
        log(f"{sid}: at the regional starting mineral N (× {reg_scale:g}): organic N × {chosen['organic_n_factor']} "
            f"(sse {chosen['sse']:.4f}), against the regional factor {regional['organic_n_factor']}")
        log(f"dssat_cultivars.yaml soil.sites.{sid}: {row}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nitrogen_sites.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--varieties", nargs="+", default=["maize_early", "maize_medium", "sorghum", "bean"])
    ap.add_argument("--nitrogen", action="store_true", help="fit the soil's organic nitrogen factor instead")
    ap.add_argument("--nitrogen-sites", nargs="*", metavar="SITE",
                    help="fit the sites' own soil nitrogen to the trials on their fields (SITE_TRIALS; all if none named)")
    ap.add_argument("--initial-scale", type=float,
                    help="--nitrogen: the starting mineral nitrogen × this (default: dssat_cultivars.yaml soil's)")
    ap.add_argument("--factors", type=float, nargs="+", default=[1.0, 0.5, 0.25, 0.12, 0.06],
                    help="--nitrogen: the organic-nitrogen factors scanned before the fit")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ds.installed():
        log(f"DSSAT is not installed ({ds.EXE}): python -m crop_engine.adapters.dssat_adapter --install")
        return 1
    if a.nitrogen_sites is not None:
        return calibrate_site_nitrogen(a.workers, only=a.nitrogen_sites or None)
    if a.nitrogen:
        return calibrate_nitrogen(a.workers, a.initial_scale, tuple(a.factors))
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
