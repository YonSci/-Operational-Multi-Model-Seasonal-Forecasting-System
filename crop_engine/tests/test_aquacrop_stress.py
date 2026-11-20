"""AquaCrop 7's soil fertility, weeds and salinity in AquaCrop-OSPy (adapters/aquacrop_stress.py): the ported formulas
against AquaCrop's own values, and whole seasons on synthetic weather. python -m pytest crop_engine/tests"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from crop_engine import run_outlook as ro
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.adapters import aquacrop_stress as st
from crop_engine.calibration.dssat import LOAM


def test_fertility_parameters_as_aquacrop():
    # the generic crop's response at 50 % (CropStressParametersSoilFertility evaluated)
    p = st.fert_params(50)
    assert (p["RedCGC"], p["RedCCX"], p["RedWP"]) == (25, 40, 30) and p["CDecline"] == pytest.approx(0.3026, abs=1e-4)
    p = st.fert_params(20)
    assert (p["RedCGC"], p["RedCCX"], p["RedWP"]) == (7, 14, 9) and p["CDecline"] == pytest.approx(0.0920, abs=1e-4)
    assert st.fert_params(0)["RedCCX"] == 0 and st.fert_params(100)["RedCCX"] == 100


def test_ks_any_and_canopy_helpers():
    assert st.ks_any(0.0, 0.0, 1.0, 2.0) == 1.0 and st.ks_any(1.0, 0.0, 1.0, 2.0) == 0.0
    assert st.ks_any(0.5, 0.0, 1.0, 0.0) == pytest.approx(0.5, abs=0.01)           # shape 0: (nearly) a line
    assert st.cc_at_time(0, 0.05, 0.01, 0.8) == pytest.approx(0.05)
    t = st.time_to_reach(0.98 * 0.8, 0.05, 0.8, 0.01, 50)
    assert st.cc_at_time(t - 50, 0.05, 0.01, 0.8) == pytest.approx(0.98 * 0.8, abs=0.01)


def test_salt_mobility_as_aquacrop():
    # SaltDiff 20 %, a compartment whose field capacity sits at the 8th of 11 cells: Mobil[1..7] as AquaCrop's
    scp1, ul, dx, mob = st.salt_cells(0.45, 0.30, 100.0)
    assert scp1 == 11 and ul == pytest.approx(0.375)
    assert np.round(mob[1:8], 4).tolist() == pytest.approx([0.0017, 0.0062, 0.0183, 0.0508, 0.1381, 0.3721, 1.0], abs=2e-4)
    assert st.active_cell(0.10, scp1, ul, dx) == 3 and st.active_cell(0.40, scp1, ul, dx) == 11


def test_salinity_helpers():
    assert st.ks_salinity(1.0, 1.7, 10.0) == 1.0 and st.ks_salinity(10.0, 1.7, 10.0) == 0.0
    assert st.ks_salinity(5.85, 1.7, 10.0) == pytest.approx(0.5)
    assert st.adjusted_ks_sto(1.7, 10.0, 4.0, 4.0, 4.0, 0.0, (0, 1, 0), ks_in=0.8) == 0.8          # Wrel 0: as given
    assert st.adjusted_ks_sto(1.7, 10.0, 8.0, 14.0, 12.0, 0.3, (0, 1, 0), ks_in=1.0) == 0.0         # beyond ECemax
    assert st.cc_multiplier_weed(0, 0.8) == 1.0 and st.cc_multiplier_weed(100, 0.8) == pytest.approx(1.25)
    assert 1.0 < st.cc_multiplier_weed(50, 0.8) < 1.25


def _task(**extra):
    _, vs = ro.load_varieties(["maize_early"])
    v = vs["maize_early"]
    d = pd.date_range("2025-08-01", "2026-03-31")
    t = dict(dates=d.values, rain=np.zeros((1, len(d))), tmax=np.full(len(d), 28.0), tmin=np.full(len(d), 16.0),
             et0=np.full(len(d), 4.5), source=np.zeros(len(d), int), planting=[dt.date(2025, 10, 25)], variety=v,
             kw=v["kw"], layers=LOAM, initial_frac=0.8,
             irrigation=dict(irrigation_method=1, SMT=[70, 70, 70, 70], MaxIrr=50))     # water not limiting
    t.update(extra)
    return aq.simulate(t)[0]


def test_seasons_under_the_three_stresses():
    base = _task()
    assert base["status"] == "ok" and base["yield_t_ha"] > 5
    # fertility: the season's biomass lands on AquaCrop's own target for the level (stress-biomass relationship)
    seen = {}
    orig = st._after_day
    try:
        st._after_day = lambda x, c, b: (orig(x, c, b), seen.update(frac=x.frac))
        r = _task(fertility={"stress_pct": 25})
    finally:
        st._after_day = orig
    assert r["biomass_t_ha"] / base["biomass_t_ha"] == pytest.approx(seen["frac"], abs=0.03)
    # weeds: a larger total canopy, less crop
    w = _task(weeds={"rc_pct": 50})
    assert w["max_canopy"] > base["max_canopy"] and w["yield_t_ha"] < 0.75 * base["yield_t_ha"]
    # salinity: FAO 29's maize tolerance (threshold 1.7 dS/m, 12 % per dS/m) within 6 points at ECe 4 and 6
    for ece, fao in ((4.0, 0.72), (6.0, 0.48)):
        s = _task(salinity={"ece_initial": ece})
        assert s["yield_t_ha"] / base["yield_t_ha"] == pytest.approx(fao, abs=0.06)
    # near the limit (8 dS/m; FAO 29: 0.24) the crop draws on its less saline compartments instead of collapsing
    # (root-zone rule alone: 0.01)
    assert _task(salinity={"ece_initial": 8.0})["yield_t_ha"] / base["yield_t_ha"] > 0.05
    # the wrappers are idle again afterwards: the same unstressed season
    assert _task()["yield_t_ha"] == base["yield_t_ha"] and st.current() is None
