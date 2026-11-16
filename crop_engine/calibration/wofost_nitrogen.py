#!/usr/bin/env python3
"""
WOFOST 8.1's soil nitrogen fitted to the Kenyan maize nitrogen trials, as DSSAT's was (calibration/dssat.py
--nitrogen): early maize grown in the observed Short Rains of the calibration years at KALRO Kiboko and Kapiti, sown on
the FAO agricultural onset, without fertiliser and with 60 kg N/ha (urea, 40 % at sowing and 60 % at 30 days,
recovery N_RECOVERY); the soil's base nitrogen supply NSOILBASE is chosen so the unfertilised yield over the fertilised
one, summed over the seasons, is TARGET_RATIO (the trials of the yields database: 0.62, the median of 24 Kenyan
trial-seasons 0.63, the eastern ones 0.64).

Caveat: PCSE's tropical maize set lets the crop's nitrogen concentrations fall far below measured maize (6 t/ha of
grain from 20 kg of nitrogen in a synthetic season), so the fitted supply reproduces the trials' response, not the
nitrogen a field holds: read NSOILBASE as a calibration parameter, not as a soil measurement.

Writes crop_engine/wofost_nitrogen.yaml (adopted values) and outputs/crop_engine/calibration/wofost/nitrogen.json.
  python -m crop_engine.calibration.wofost_nitrogen [--workers 3]
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import yaml

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import wofost_adapter as wf

SITES = ("kalro_kiboko", "kapiti")
TARGET_RATIO = 0.62
GRID = (2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 70.0, 100.0)
FIXED = {"NSOILBASE_FR": 0.025, "NAVAILI": 5.0, "BG_N_SUPPLY": 0.02}
SPLIT = [[0, 0.4], [30, 0.6]]
SETTINGS = Path(__file__).resolve().parent.parent / "wofost_nitrogen.yaml"
OUT = C.OUT / "calibration" / "wofost"


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] wofost nitrogen: {m}", flush=True)


def soil(nsoilbase):
    return {"NSOILBASE": float(nsoilbase), **FIXED}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from crop_engine import compare_engines as ce
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.weather import Inputs
    inp = Inputs(refresh=False)
    rep = [(s, [s.id]) for s in inp.sites if any(s.id.startswith(x) for x in SITES)]
    if not rep:
        log("no calibration sites")
        return 1
    _, vs = ro.load_varieties(["maize_early"])
    years = list(range(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1))
    soils = {s.id: soil_mod.profile(s) for s, _ in rep}
    tasks, keys = ce.tasks_for(inp, years, rep, vs, ["fao-agricultural"], soils)
    runs, idx = [], []
    for nb in GRID:
        for rate in (0, 60):
            for i, t in enumerate(tasks):
                runs.append(dict(t, nitrogen={"rate_kg_ha": rate, "split": SPLIT, **soil(nb)}))
                idx.append((nb, rate, i))
    log(f"{len(tasks)} observed seasons at {', '.join(s.id for s, _ in rep)} x {len(GRID)} supplies x 2 rates")
    res = ro.run_tasks(runs, a.workers, engine="wofost")
    y = {}
    for (nb, rate, i), r in zip(idx, res):
        m = r[0]
        y.setdefault(nb, {}).setdefault(rate, []).append(float(m["yield_t_ha"] or 0.0) if m["status"] != "error" else np.nan)
    table = []
    for nb in GRID:
        y0, y60 = np.array(y[nb][0]), np.array(y[nb][60])
        ok = np.isfinite(y0) & np.isfinite(y60)
        ratio = float(y0[ok].sum() / y60[ok].sum()) if y60[ok].sum() > 0 else None
        table.append({"NSOILBASE": nb, "ratio": None if ratio is None else round(ratio, 3),
                      "median_0N_t_ha": round(float(np.median(y0[ok])), 2), "median_60N_t_ha": round(float(np.median(y60[ok])), 2)})
        log(f"NSOILBASE {nb:5.1f}: ratio {table[-1]['ratio']}, median 0 N {table[-1]['median_0N_t_ha']} t/ha, "
            f"60 N {table[-1]['median_60N_t_ha']} t/ha")
    # the supply whose ratio is nearest the target, interpolated between the grid's neighbours
    xs = np.array([r["NSOILBASE"] for r in table if r["ratio"] is not None])
    rs_ = np.array([r["ratio"] for r in table if r["ratio"] is not None])
    order = np.argsort(rs_)
    fit = float(np.interp(TARGET_RATIO, rs_[order], xs[order]))
    log(f"fitted NSOILBASE {fit:.1f} kg N/ha (ratio {TARGET_RATIO})")
    adopted = {"note": "WOFOST 8.1's soil nitrogen (wofost_adapter module doc), fitted by calibration/wofost_nitrogen.py "
                       f"to the Kenyan maize trials' unfertilised / 60 kg N ratio {TARGET_RATIO} over the observed Short "
                       f"Rains {years[0]}-{years[-1]} at {', '.join(SITES)}; a calibration parameter, not a soil measurement",
               "fitted": dt.date.today().isoformat(), "soil": {**soil(round(fit, 1))}, "recovery": wf.N_RECOVERY}
    SETTINGS.write_text(yaml.safe_dump(adopted, sort_keys=False, allow_unicode=True), encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nitrogen.json").write_text(json.dumps({"target_ratio": TARGET_RATIO, "years": years, "sites": list(SITES),
                                                   "fixed": FIXED, "table": table, "fitted_NSOILBASE": fit}, indent=1),
                                       encoding="utf-8")
    log(f"written {SETTINGS.name} and {OUT / 'nitrogen.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
