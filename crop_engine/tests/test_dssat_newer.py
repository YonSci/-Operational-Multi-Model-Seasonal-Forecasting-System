"""A newer DSSAT (CROP_ENGINE.md "A newer DSSAT, built from source"): the water table, observed pest damage and
potassium on the build CROP_ENGINE_DSSAT_HOME selects. Skipped when it is not set (the default, installed 4.8.0.28
build has none of these). CROP_ENGINE_DSSAT_HOME=C:/Users/.../dssat_build/home python -m pytest crop_engine/tests"""
import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crop_engine.adapters import dssat_adapter as ds
from crop_engine.calibration.dssat import LOAM

pytestmark = pytest.mark.skipif(not os.environ.get("CROP_ENGINE_DSSAT_HOME") or not ds.installed(),
                                reason="CROP_ENGINE_DSSAT_HOME (a newer DSSAT build) is not set or not installed")

DATES = pd.date_range("2026-08-01", "2027-03-31")
T = len(DATES)


def _rain(kind):
    r = np.zeros(T)
    if kind == "wet":                                                      # 4 mm a day from late October
        r[85:] = 4.0
    else:                                                                  # a sowing rain, then 5 mm every 10 days
        r[85:90] = 15.0
        r[90:160:10] = 5.0
    return r


def _task(kind, **extra):
    from crop_engine import run_outlook as ro
    _, vs = ro.load_varieties(["maize_early"])
    t = {"dates": DATES.values, "rain": _rain(kind)[None, :], "tmax": np.full(T, 29.0), "tmin": np.full(T, 17.0),
         "et0": np.full(T, 5.0), "rad": np.full(T, 21.0), "vap": np.full(T, 16.0), "wind2": np.full(T, 2.0),
         "source": np.zeros(T), "planting": [dt.date(2026, 10, 28)], "resow": [[]],
         "variety": ds.attach(vs)["maize_early"], "layers": LOAM, "initial_frac": 0.3, "lat": -2.21, "lon": 37.72,
         "elev": 975, "potential": False}
    return dict(t, **extra)


def _nitrogen(rate, **extra):
    return {"rate_kg_ha": rate, "split": [(0, 0.4), (30, 0.6)], **ds.soil_nitrogen(None), **extra}


def test_the_selected_build_is_used():
    assert ds.HOME == Path(os.environ["CROP_ENGINE_DSSAT_HOME"]) and ds.EXE.is_relative_to(ds.HOME)
    assert ds.supports_water_table()                                       # WaterTable.f90 (ADJWTD) is in it
    prof = ds.run_profile(ds.RUNS, "MZ", "MZCER048")
    assert all(len(ln.split()[1]) <= ds.MAX_PATH for ln in prof.splitlines())


def test_a_water_table_waters_a_dry_season():
    (none,) = ds.simulate(_task("dry"))
    (wt,) = ds.simulate(_task("dry", groundwater={"depth_m": 1.5}))        # inside the 2 m profile, roots reach it
    assert none["status"] == wt["status"] == "ok"
    assert wt["yield_t_ha"] > 2 * none["yield_t_ha"]                       # 5.32 against 1.11 t/ha (4.8.6.4)


def test_observed_leaf_damage_lowers_maize_yield():
    (clean,) = ds.simulate(_task("wet", nitrogen=_nitrogen(50)))
    (eaten,) = ds.simulate(_task("wet", nitrogen=_nitrogen(50, pest={"total_pct": 50, "days": 21, "from_das": 40})))
    assert clean["status"] == eaten["status"] == "ok"
    assert eaten["yield_t_ha"] < 0.9 * clean["yield_t_ha"]                 # 3.59 against 4.40 t/ha (4.8.6.4)
    assert eaten["max_lai"] < clean["max_lai"]


def test_potassium_when_the_build_runs_it():
    (high,) = ds.simulate(_task("wet", nitrogen=_nitrogen(50, soil_k_cmol_kg=1.0)))
    if "Potassium model not enabled" in (high.get("error") or ""):
        pytest.skip("this build stops potassium for every crop (DSSAT's IPSIM error 7)")
    (low,) = ds.simulate(_task("wet", nitrogen=_nitrogen(50, soil_k_cmol_kg=0.03)))
    assert high["status"] == "ok" and low["yield_t_ha"] < high["yield_t_ha"]
