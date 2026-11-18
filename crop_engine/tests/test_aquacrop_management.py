"""AquaCrop's CO2 series, water table, irrigation methods and the AquaCrop-only scenarios: python -m pytest crop_engine/tests"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.scenarios import management as mg


def test_co2_series():
    s = pd.read_csv(aq.CO2_FILE, comment="#")
    assert list(s.columns) == ["year", "ppm"] and s.year.is_monotonic_increasing and s.year.diff().dropna().eq(1).all()
    v = s.set_index("year").ppm
    assert v[2000] == pytest.approx(369.0, abs=1.0) and v[2025] == pytest.approx(425.6, abs=0.1)
    assert 425 < v[2026] < 432 and v[2100] > v[2026]                      # joined to the observations, then rising
    assert aq.co2().co2_data.ppm.iloc[-1] == v.iloc[-1]


def test_irrigation_schedule_on_the_sowing_date():
    im = aq.irrigation({"schedule_das": [[0, 25], [20, 30]], "MaxIrr": 50}, dt.date(2026, 10, 29))
    assert im.irrigation_method == 3 and im.MaxIrr == 50
    assert list(im.Schedule.Date) == [pd.Timestamp("2026-10-29"), pd.Timestamp("2026-11-18")]
    assert list(im.Schedule.Depth) == [25.0, 30.0]
    assert aq.irrigation(None, dt.date(2026, 10, 29)) is None
    assert aq.irrigation({"irrigation_method": 2, "IrrInterval": 7}, dt.date(2026, 10, 29)).IrrInterval == 7


def test_groundwater():
    gw = aq.groundwater({"depth_m": 1.5}, pd.Timestamp("2026-08-01"))
    assert gw.water_table == "Y" and gw.values == [1.5] and gw.dates == ["2026/08/01"]
    assert aq.groundwater(None, pd.Timestamp("2026-08-01")) is None


def test_water_table_on_a_profile_with_a_thin_top_layer():
    """SoilGrids' 0-5 cm layer is thinner than a compartment: AquaCrop-OSPy's capillary rise asserted on it and every
    member with a water table errored (patch_capillary_rise)."""
    from crop_engine import run_outlook as ro
    from crop_engine.data.soil import Layer
    _, vs = ro.load_varieties(["maize_early"])
    v = vs["maize_early"]
    layers = [Layer(t, b, 40, 30, 1.5, 0, 0.32, 0.17) for t, b in ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))]
    d = pd.date_range("2025-08-01", "2026-03-31")
    rain = np.where((d >= "2025-10-15") & (d <= "2026-01-10") & (np.arange(len(d)) % 2 == 0), 9.0, 0.0)
    t = dict(dates=d.values, rain=rain[None, :], tmax=np.full(len(d), 28.0), tmin=np.full(len(d), 16.0),
             et0=np.full(len(d), 4.5), source=np.zeros(len(d), int), planting=[dt.date(2025, 10, 25)], variety=v,
             kw=v["kw"], layers=layers, initial_frac=0.3, groundwater={"depth_m": 1.0})
    r = aq.simulate(t)[0]
    assert r["status"] != "error", r.get("error")
    dry = aq.simulate(dict(t, groundwater=None))[0]
    assert r["yield_t_ha"] >= dry["yield_t_ha"]                         # the water table can only add water


def test_aquacrop_only_scenarios():
    assert not any(mg.aquacrop_only(k) for k in ("irr_supplementary", "irr_full", "mulch", "ridges", "density_low",
                                                 "sow_plus14", "soil_dry"))
    assert all(mg.aquacrop_only(k) for k in ("bunds", "irr_interval", "irr_schedule", "irr_net", "irr_constant",
                                             "gw_1_5m", "gw_2_5m"))
    t = {"dates": pd.date_range("2026-08-01", periods=10).values, "planting": [dt.date(2026, 8, 3)], "kw": {},
         "variety": {"aquacrop_crop": "MaizeGDD"}, "initial_frac": 0.2}
    assert mg.apply(t, "gw_1_5m")["groundwater"] == {"depth_m": 1.5}
    assert mg.apply(t, "bunds")["field"] == {"bunds": True, "z_bund": 0.10}
    assert "groundwater" not in mg.apply(t, "mulch")
