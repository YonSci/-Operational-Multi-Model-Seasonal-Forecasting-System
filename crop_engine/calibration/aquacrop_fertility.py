#!/usr/bin/env python3
"""
AquaCrop's soil fertility stress (adapters/aquacrop_stress.py, FAO AquaCrop 7's semi-quantitative method) calibrated
to the Kenyan maize nitrogen trials of the yields database, as DSSAT's soil nitrogen is (calibration/dssat.py).

AquaCrop's stress has a level (%) and four response shapes (canopy growth, maximum canopy, water productivity,
canopy decline). The shapes need canopy measurements under stress, which these trials do not have: they stay
AquaCrop's generic crop's. The level is what the trials fix, as AquaCrop's own calibration does it (the level whose
relative biomass is the field's):

  regional       the level at which early maize, over the observed Short Rains 1993-2016 at Kiboko and Kapiti (FAO
                 onset, the outlook's sowing), yields the trials' 0.62 of its unstressed yield: the median of the
                 seasons whose unstressed crop yields at least 0.5 t/ha. The target of DSSAT's regional fit
                 (dssat.N_TARGET: the yield without nitrogen over the yield with 45-75 kg N/ha, 24 trial-seasons).
  Kiboko's field the KALRO Kiboko 2013 irrigated trial (dssat.SITE_TRIALS): medium maize, irrigated, sown every 14
                 days in Jun-Jul 2013 (the date is not reported), in the site's ERA5-Land weather (FAO-56 ET0): the
                 levels at which it yields the trial's 0.22, 0.51 and 0.80 of its 160 kg N/ha yield at 0, 40 and 80
                 kg N/ha.

Writes outputs/crop_engine/calibration/aquacrop/fertility.json and prints the rows of crop_engine/
aquacrop_fertility.yaml (edited by hand, citing it). Usage: python -m crop_engine.calibration.aquacrop_fertility
"""
import argparse
import datetime as dt
import json
import sys

import numpy as np
import pandas as pd

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.calibration import dssat as cd
from crop_engine.calibration import wofost as cw

OUT = C.OUT / "calibration" / "aquacrop"
LEVELS = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90)
REGIONAL_SITES = cd.N_SITES
REGIONAL_YEARS = cd.N_YEARS
MIN_UNSTRESSED_T_HA = 0.5
IRRIGATED = {"irrigation_method": 1, "SMT": [70, 70, 70, 70], "MaxIrr": 50}


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] aquacrop fertility: {m}", flush=True)


def fit_level(levels, ratios, target):
    """The level (%) whose relative yield is target, linearly between the scanned levels (ratios fall with the
    level); None outside the scan."""
    for (l0, r0), (l1, r1) in zip(zip(levels, ratios), list(zip(levels, ratios))[1:]):
        if r0 is None or r1 is None:
            continue
        if min(r0, r1) <= target <= max(r0, r1) and r0 != r1:
            return round(l0 + (target - r0) * (l1 - l0) / (r1 - r0), 1)
    return None


def regional(workers):
    from crop_engine import compare_engines as ce
    from crop_engine.data import soil as soil_mod
    from crop_engine.data import weather as W
    _, vs = ro.load_varieties(["maize_early"])
    inp = W.Inputs(refresh=False, with_met=True)
    rep = [(s, g) for s, g in ro.cells(inp.sites) if s.id in REGIONAL_SITES]
    soils = {s.id: soil_mod.profile(s) for s, _ in rep}
    tasks, _ = ce.tasks_for(inp, list(range(REGIONAL_YEARS[0], REGIONAL_YEARS[1] + 1)), rep, vs, ["fao-agricultural"], soils)
    tasks = [t for t in tasks if t["planting"][0] is not None]
    log(f"regional: {len(tasks)} observed seasons at {', '.join(REGIONAL_SITES)}, early maize")
    base = [r[0]["yield_t_ha"] for r in ro.run_tasks(tasks, workers)]
    keep = [k for k, y in enumerate(base) if y >= MIN_UNSTRESSED_T_HA]
    ratios = []
    for lv in LEVELS:
        if lv == 0:
            ratios.append(1.0)
            continue
        ys = [r[0]["yield_t_ha"] for r in ro.run_tasks([dict(tasks[k], fertility={"stress_pct": lv}) for k in keep], workers)]
        ratios.append(round(float(np.median([y / base[k] for y, k in zip(ys, keep)])), 3))
        log(f"  stress {lv} %: median relative yield {ratios[-1]} ({len(keep)} seasons)")
    target = cd.N_TARGET["ratio_0_60"]
    return {"target": target, "source": cd.N_TARGET["source"], "seasons": len(keep), "levels": list(LEVELS),
            "relative_yield": ratios, "stress_pct": fit_level(LEVELS, ratios, target)}


def kiboko_trial(workers):
    from crop_engine.data import era5land, met_check
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.sites import Site, registered_sites
    from crop_engine.yields import observations
    trial = cd.SITE_TRIALS["kalro_kiboko_makueni_farm"]
    target, _ = cd.observed_response(observations.load_all(log=lambda m: None), trial)
    site = next(s for s in registered_sites() if s.id == "kalro_kiboko_makueni_farm")
    _, vs = ro.load_varieties([trial["variety"]])
    v = vs[trial["variety"]]
    plants = cw.sowings(trial["year"])
    d = pd.date_range(plants[0] - dt.timedelta(days=5), periods=cd.DAYS)
    t = era5land.site_temperature(site, refresh=False).reindex(d)
    met = era5land.site_met([site], refresh=False)[site.id]
    et0 = met_check.site_et0(t, met, site.lat).reindex(d)
    if t.isna().any().any() or et0.isna().any():
        raise ValueError("ERA5-Land weather missing at Kiboko for the trial's season")
    layers = soil_mod.profile(Site(site.id, site.name, site.lat, site.lon, site.country, cell_lat=site.lat, cell_lon=site.lon))
    M = len(plants)
    base = dict(dates=d.values, rain=np.zeros((M, len(d))), tmax=t.tmax.values, tmin=t.tmin.values, et0=et0.values,
                source=np.zeros(len(d), int), planting=plants, variety=v, kw=v["kw"], layers=layers, initial_frac=0.7,
                irrigation=IRRIGATED)
    runs = [base] + [dict(base, fertility={"stress_pct": lv}) for lv in LEVELS[1:]]
    res = ro.run_tasks(runs, workers)
    y = [float(np.mean([m["yield_t_ha"] for m in r])) for r in res]
    ratios = [round(v_ / y[0], 3) if y[0] > 0 else None for v_ in y]
    log(f"Kiboko 2013 trial: unstressed {y[0]:.2f} t/ha; relative yields by level {dict(zip(LEVELS, ratios))}")
    fits = {f"n{int(r)}": fit_level(LEVELS, ratios, target[r]) for r in trial["rates"] if r != max(trial["rates"])}
    return {"trial": trial["source"], "sowings": [p.isoformat() for p in plants], "observed_relative": target,
            "unstressed_t_ha": round(y[0], 2), "levels": list(LEVELS), "relative_yield": ratios, "stress_pct": fits}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
           "regional": regional(a.workers), "kalro_kiboko_makueni_farm": kiboko_trial(a.workers)}
    log(f"regional: stress {out['regional']['stress_pct']} % gives {out['regional']['target']} "
        f"(relative yields {dict(zip(LEVELS, out['regional']['relative_yield']))})")
    log(f"Kiboko's field: {out['kalro_kiboko_makueni_farm']['stress_pct']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fertility.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
