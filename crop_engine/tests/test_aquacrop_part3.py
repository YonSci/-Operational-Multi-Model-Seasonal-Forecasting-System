"""AquaCrop part 3: weeding, AquaCrop 7's salt cells, a water table that changes through the season, a site's measured
conditions in the outlook, pollination heat stress (AquaCrop 7's order, published thresholds) and transplanting.
python -m pytest crop_engine/tests"""
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crop_engine import run_outlook as ro
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.adapters import aquacrop_stress as st
from crop_engine.calibration.dssat import LOAM
from crop_engine.data import site_conditions, soil
from crop_engine.scenarios import management as mg


def _prof(n=4, dz=0.1, th_s=0.45, th_fc=0.30, th_wp=0.15, ksat=300.0):
    return SimpleNamespace(dz=[dz] * n, th_s=[th_s] * n, th_fc=[th_fc] * n, th_wp=[th_wp] * n, Ksat=[ksat] * n)


def test_salt_cells_hold_ece_and_conserve_salt():
    prof = _prof()
    th = np.full(4, 0.30)
    sp = st.SaltProfile(prof, th, 4.0)
    for i in range(4):                                   # DetermineSaltContent: ECe given back
        assert sp.ece(i) == pytest.approx(4.0, rel=1e-6)
    before = sp.totals().sum()
    salt_in = st.EQUIV * 2.0 * 30.0                      # 30 mm of irrigation at ECw 2
    flux = np.array([20.0, 15.0, 10.0, 5.0])
    drained = sp.content(th, flux, 30.0, salt_in)
    assert sp.totals().sum() + drained == pytest.approx(before + salt_in, rel=1e-6)
    assert drained > 0
    # the day dries the top: its dry cells' salt gathered into the wettest active cell, none lost
    tot = sp.totals().sum()
    dry = th.copy()
    dry[0] = 0.12
    sp.concentrate(dry)
    assert sp.totals().sum() == pytest.approx(tot, rel=1e-9)
    scp1, ul, dx, _ = sp.cells[0]
    wet = st.active_cell(0.12, scp1, ul, dx)
    assert np.all(sp.salt[0][wet:] == 0) and np.all(sp.depo[0][wet:] == 0)
    # capillary rise brings salt at ECgw
    t0 = sp.totals().sum()
    sp.capillary_rise(th, np.array([0.0, 0.0, 2.0, 3.0]), 4.0)
    assert sp.totals().sum() - t0 == pytest.approx(st.EQUIV * 4.0 * 5.0)


def test_salt_deposits_above_solubility():
    s, d = st.deposit(1.0, 150.0, 0.0)
    assert s == pytest.approx(st.SALT_SOLUB) and d == pytest.approx(50.0)
    assert st.deposit(1.0, 30.0, 10.0) == (40.0, 0.0)


def test_weeding_course():
    x = st.Context("MaizeGDD", np.arange(100.0), weeds={"rc_pct": 50, "weeding_das": [21, 42]})
    assert x.weed_fraction(0) == 0.0                     # a clean seedbed
    assert x.weed_fraction(20) == pytest.approx(20 / 28)
    after = x.weed_fraction(21)
    assert after == pytest.approx(min(1, 21 / 28) * 0.1)  # 90 % removed
    y = st.Context("MaizeGDD", np.arange(100.0), weeds={"rc_pct": 50, "weeding_das": [21]})
    assert y.weed_fraction(10, crop_cover=1.0) == 0.0    # under a closed canopy the weeds hardly regrow
    z = st.Context("MaizeGDD", np.arange(100.0), weeds={"rc_pct": 50})
    assert z.weed_fraction(30) == 1.0                    # no weeding: AquaCrop's constant cover


def test_seasonal_water_table_dates():
    start, end = pd.Timestamp("2025-08-01"), pd.Timestamp("2026-03-31")
    gw = aq.groundwater({"monthly_m": {8: 3.0, 11: 1.8, 12: 1.5, 3: 2.5}}, start, end)
    assert gw.method == "Variable" and gw.dates[0] == "2025/08/01" and gw.dates[-1] == "2026/03/31"
    assert gw.values[0] == 3.0 and gw.values[-1] == 2.5
    d = dict(zip(gw.dates, gw.values))
    assert d["2025/11/15"] == 1.8 and d["2025/12/15"] == 1.5
    assert d["2025/10/15"] in (3.0, 1.8)                 # a month without a value takes the nearest month's
    assert aq.groundwater({"depth_m": 1.5}, start).method == "Constant"


def test_pollination_heat_in_aquacrop7_order():
    aq.patch_pollination_heat()
    import aquacrop.solution.harvest_index as hi
    crop = SimpleNamespace(PolHeatStress=1, PolColdStress=0, Tmax_up=40.0, Tmax_lo=45.0, Tmin_up=10.0, Tmin_lo=5.0,
                           fshape_b=13.8135)
    assert hi.temperature_stress(crop, 39.0, 20.0)[0] == 1
    assert 0 < hi.temperature_stress(crop, 42.5, 20.0)[0] < 1
    assert hi.temperature_stress(crop, 45.0, 20.0)[0] == 0
    task = {"variety": {"aquacrop_crop": "MaizeGDD"}, "heat": {"thresholds": "literature"}}
    assert aq.heat_kw(task) == {"Tmax_up": 35.0, "Tmax_lo": 40.0}
    assert aq.heat_kw({"variety": {"aquacrop_crop": "MaizeGDD"}}) == {}      # the crop file's, by default


def test_transplant_parameters():
    _, vs = ro.load_varieties(["sorghum"])
    kw = vs["sorghum"]["kw"]
    t = aq.transplant_kw(kw, {"nursery_days": 21, "seedling_cm2": 50}, "SorghumGDD", np.full(21, 12.0))
    assert t["Maturity"] == pytest.approx(kw["Maturity"] - 252) and t["HIstart"] == pytest.approx(kw["HIstart"] - 252)
    assert t["Emergence"] >= 36 and t["SeedSize"] == 50 and t["PlantMethod"] == 0


def test_site_conditions_reach_the_task(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("sites:\n  a: {fertility: {stress_pct: 30}, weeds: {rc_pct: 20}, source: test}\n  b: {source: none}\n")
    assert site_conditions.conditions("a", p) == {"fertility": {"stress_pct": 30}, "weeds": {"rc_pct": 20}}
    assert site_conditions.conditions("b", p) == {} and len(site_conditions.in_effect(p)) == 1
    assert site_conditions.in_effect() == []             # the committed table: nothing in effect, nothing rebuilt
    layers = soil.with_depth(list(LOAM), None)
    layers.conditions = site_conditions.conditions("a", p)
    t = aq.with_conditions({"layers": layers, "weeds": {"rc_pct": 50}})
    assert t["fertility"] == {"stress_pct": 30} and t["weeds"] == {"rc_pct": 50}     # the scenario's own key wins
    assert aq.with_conditions({"layers": LOAM}) == {"layers": LOAM}


def test_new_scenarios_are_aquacrop_only():
    for k in ("weeds_50_weeded_1", "weeds_50_weeded_2", "gw_seasonal", "heat_literature", "transplanted"):
        assert mg.aquacrop_only(k)
        assert mg.describe(k)["label"]


def _season(**extra):
    _, vs = ro.load_varieties(["maize_early"])
    v = vs["maize_early"]
    d = pd.date_range("2025-08-01", "2026-03-31")
    t = dict(dates=d.values, rain=np.zeros((1, len(d))), tmax=np.full(len(d), 28.0), tmin=np.full(len(d), 16.0),
             et0=np.full(len(d), 4.5), source=np.zeros(len(d), int), planting=[dt.date(2025, 10, 25)], variety=v,
             kw=v["kw"], layers=LOAM, initial_frac=0.8, irrigation=dict(irrigation_method=1, SMT=[70] * 4, MaxIrr=50))
    t.update(extra)
    return aq.simulate(t)[0]["yield_t_ha"]


def test_weeding_recovers_yield_in_order():
    free, none = _season(), _season(weeds={"rc_pct": 50})
    once = _season(weeds={"rc_pct": 50, "weeding_das": [28]})
    twice = _season(weeds={"rc_pct": 50, "weeding_das": [21, 42]})
    assert none < once < twice <= free
    assert twice / free > 0.85                           # weeding in the critical period recovers most of the loss
