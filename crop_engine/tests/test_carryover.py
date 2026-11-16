"""Soil water carried between seasons (crop_engine/carryover.py): AquaCrop's stages, the chain from year to year, the
scenario and CROP_INITIAL_WATER's fractions. python -m pytest crop_engine/tests"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from crop_engine import carryover as co
from crop_engine import run_outlook as ro
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.calibration.dssat import LOAM
from crop_engine.scenarios import management as mg


def _wx(start="2024-08-01", end="2026-07-31", wet_months=(3, 4, 5, 10, 11, 12)):
    d = pd.date_range(start, end)
    rain = np.where((np.arange(len(d)) % 4 == 0) & d.month.isin(wet_months), 14.0, 0.0)
    return {"dates": d, "rain": rain, "tmax": np.full(len(d), 28.0), "tmin": np.full(len(d), 15.0),
            "et0": np.full(len(d), 4.5)}


@pytest.fixture(scope="module")
def varieties():
    return ro.load_varieties(["maize_early"])[1]


def test_a_long_rains_crop_leaves_the_soil_drier_than_fallow(varieties):
    wx, v = _wx(), varieties["maize_early"]
    a, b = dt.date(2025, 3, 1), dt.date(2025, 7, 31)
    fallow, y0 = co.stage(wx, a, b, LOAM, v, None, {"frac": 0.3})
    crop, y1 = co.stage(wx, a, b, LOAM, v, dt.date(2025, 3, 10), {"frac": 0.3})
    assert y0 is None and y1 is not None and y1 > 0
    for s in (fallow, crop):
        assert 0 <= s["frac_100cm"] <= 1 and 0 <= s["frac_200cm"] <= 1 and len(s["z_m"]) == len(s["th"])
    assert crop["frac_200cm"] < fallow["frac_200cm"]
    # the next stage starts from the profile itself
    nxt, _ = co.stage(wx, dt.date(2025, 8, 1), dt.date(2026, 2, 28), LOAM, v, None, crop)
    assert 0 <= nxt["frac_200cm"] <= 1


def test_chain_two_years(varieties):
    wx = _wx("2023-08-01")
    out = co.chain(("s", "maize", wx, LOAM, varieties, {"frac": 0.2}, [2025, 2026]))
    assert sorted(out) == ["2025", "2026"]
    for y in out.values():
        assert set(y) >= {"z_m", "th", "frac_100cm", "frac_200cm", "short_rains", "long_rains"}
        assert y["long_rains"]["sown"] is None or y["long_rains"]["sown"][5:7] in ("03", "04")


def test_fractions_and_hash(monkeypatch):
    data = {"sites": {"a": {"2026": {"frac_200cm": 0.42, "frac_100cm": 0.5, "z_m": [0.05], "th": [0.2]}}}}
    monkeypatch.setattr(co, "load", lambda plan=co.DEFAULT_PLAN: data)
    assert co.fractions(["a", "b"], 2026, [0.1, 0.2]).tolist() == [0.42, 0.2]   # ERA5-Land's where none
    assert co.fractions(["a"], 2025, [0.1]).tolist() == [0.1]
    assert co.available(2026) and not co.available(2025)
    assert co.hash_part() == ""                                                 # off by default: nothing rebuilt


def test_scenario_starts_from_the_profile():
    task = {"planting": [None], "dates": pd.date_range("2026-08-01", "2027-03-31").values, "initial_frac": 0.1,
            "carryover": {"frac_200cm": 0.55, "z_m": [0.05, 0.15], "th": [0.2, 0.25]}}
    t = mg.apply(task, "soil_carryover")
    assert t["initial_frac"] == 0.55 and t["initial_profile"] == {"z_m": [0.05, 0.15], "th": [0.2, 0.25]}
    assert mg.apply(dict(task, carryover=None), "soil_carryover")["initial_frac"] == 0.1
    assert not mg.aquacrop_only("soil_carryover")


def test_the_season_starts_from_the_profile(varieties):
    v = varieties["maize_early"]
    d = pd.date_range("2025-08-01", "2026-03-31")
    rain = np.where((np.arange(len(d)) % 4 == 0) & d.month.isin([10, 11, 12]), 12.0, 0.0)
    base = dict(dates=d.values, rain=rain[None], tmax=np.full(len(d), 28.0), tmin=np.full(len(d), 15.0),
                et0=np.full(len(d), 4.5), source=np.zeros(len(d), int), planting=[dt.date(2025, 10, 20)], variety=v,
                kw=v["kw"], layers=LOAM, initial_frac=0.1)
    z = (np.cumsum([0.1] * 12 + [0.2] * 4) - np.array([0.05] * 12 + [0.1] * 4)).round(3).tolist()
    # the same topsoil just above the loam's wilting point (0.13); the subsoil dry, or wet as a good Long Rains leaves it
    dry = aq.simulate(dict(base, initial_profile={"z_m": z, "th": [0.15] * 6 + [0.135] * (len(z) - 6)}))[0]
    wet_deep = aq.simulate(dict(base, initial_profile={"z_m": z, "th": [0.15] * 6 + [0.26] * (len(z) - 6)}))[0]
    assert wet_deep["yield_t_ha"] > dry["yield_t_ha"]      # water stored deep, carried over, feeds the crop
