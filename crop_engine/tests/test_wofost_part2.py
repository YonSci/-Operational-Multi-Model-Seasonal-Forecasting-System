"""WOFOST part 2 (crop_engine.adapters.wofost_adapter): stones, AquaCrop's irrigation methods 2-5, bunds, the
curve-number runoff option, plant density, weeds and a saline soil (approximations), seedling death (option), and
which scenarios WOFOST grows. Needs PCSE and its crop parameter library; skipped without them."""
import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pcse")
from crop_engine.adapters import wofost_adapter as wf  # noqa: E402
from crop_engine.scenarios import management as mg  # noqa: E402
from crop_engine.tests.test_wofost import LAYERS, task  # noqa: E402

try:
    wf._cropdata()
except Exception as exc:                                                 # no network for the crop parameters
    pytest.skip(f"WOFOST crop parameters unavailable: {exc}", allow_module_level=True)


def test_stones_hold_no_water():
    stony = [dataclasses.replace(L, cfvo=20) for L in LAYERS]
    clean = [dataclasses.replace(L, cfvo=0) for L in LAYERS]
    a, _ = wf.soil_parameters(stony, 0.5)
    b, _ = wf.soil_parameters(clean, 0.5)
    assert a["SMFCF"] == pytest.approx(0.8 * b["SMFCF"]) and a["SMW"] == pytest.approx(0.8 * b["SMW"])


def test_irrigation_methods():
    plant, smw, smfc = dt.date(2026, 10, 20), 0.13, 0.26
    day = lambda n: plant + dt.timedelta(days=n)                       # noqa: E731
    m1 = {"irrigation_method": 1, "SMT": [30, 30, 30, 0], "MaxIrr": 25, "start_stage": 2}
    assert wf.irrigation_today(m1, day(3), plant, -0.1, 0.14, 50, smw, smfc) == 0       # before emergence: none
    assert wf.irrigation_today(m1, day(30), plant, 0.3, 0.14, 50, smw, smfc) == 25      # dry: refilled, capped
    assert wf.irrigation_today(m1, day(30), plant, 0.3, 0.24, 50, smw, smfc) == 0       # wet enough
    m2 = {"irrigation_method": 2, "IrrInterval": 7, "MaxIrr": 30}
    assert wf.irrigation_today(m2, day(14), plant, 0.3, 0.20, 50, smw, smfc) == pytest.approx(30)
    assert wf.irrigation_today(m2, day(15), plant, 0.3, 0.20, 50, smw, smfc) == 0
    m3 = {"schedule_das": [[0, 25], [20, 30]]}
    assert wf.irrigation_today(m3, day(20), plant, 0.3, 0.2, 50, smw, smfc) == 30
    m4 = {"irrigation_method": 4, "NetIrrSMT": 60}
    assert wf.irrigation_today(m4, day(5), plant, 0.3, 0.15, 50, smw, smfc) == pytest.approx((0.13 + 0.6 * 0.13 - 0.15) * 500)
    m5 = {"irrigation_method": 5, "depth": 3}
    assert wf.irrigation_today(m5, day(5), plant, 1.0, 0.2, 50, smw, smfc) == 3
    assert wf.irrigation_today(m5, day(90), plant, 2.0, 0.2, 50, smw, smfc) == 0        # mature


def test_runoff_by_curve_number():
    assert 46 <= wf.curve_number(LAYERS) <= 77
    assert wf.curve_number(LAYERS, -30) == pytest.approx(0.7 * wf.curve_number(LAYERS))
    rain = np.array([0, 5, 60, 0, 0, 0, 0, 80.0])
    q = wf.scs_runoff(rain, 72)
    assert q[0] == 0 and q[1] == 0 and q[2] > 0 and np.all(q <= rain)
    assert np.all(wf.scs_runoff(rain, 50) <= q)                         # a lower curve number runs off less


def test_seedlings_dying_in_a_dry_spell():
    d = pd.date_range("2026-10-20", periods=40)
    grow = pd.DataFrame({"DVS": np.r_[-0.1, np.linspace(0.01, 0.3, 39)], "LAI": 0.02, "SM": 0.13}, index=d)
    assert wf.seedling_died(grow, {"SMW": 0.13}) == d[10]
    assert wf.seedling_died(grow.assign(SM=0.2), {"SMW": 0.13}) is None
    assert wf.seedling_died(grow.assign(LAI=0.5), {"SMW": 0.13}) is None  # established: WOFOST's crop slows, not dies


def test_salt_and_weed_approximations():
    assert wf.salt_factor("MaizeGDD", 4.0) == pytest.approx(1 - (4 - 1.7) / (10 - 1.7))
    assert wf.salt_factor("MaizeGDD", 1.0) == 1.0 and wf.salt_factor("MaizeGDD", 12.0) == 0.0
    t = task()
    d = pd.DatetimeIndex(t["dates"])
    assert np.all(wf.weed_light(dict(t, weeds={"rc_pct": 40}), d, 0) == 0.6)
    w = wf.weed_light(dict(t, weeds={"rc_pct": 40, "weeding_das": [21]}), d, 0)
    k0 = int(d.get_indexer([pd.Timestamp(t["planting"][0])])[0])
    assert w[k0] == 1.0 and w[k0 + 20] < w[k0 + 22] and w[-1] == pytest.approx(0.6)


def test_scenarios_wofost_grows():
    for k in ("irr_interval", "irr_schedule", "irr_net", "irr_constant", "bunds", "density_low", "weeds_50",
              "weeds_50_weeded_2", "saline_soil", "soil_carryover"):
        assert mg.wofost_can(k), k
    for k in ("gw_1_5m", "gw_seasonal", "fert_no_n", "saline_irrigation", "saline_water_table", "parameters",
              "heat_literature", "transplanted", "contour_ridges"):
        assert not mg.wofost_can(k), k


def test_whole_seasons():
    base = wf.simulate(task(25.0, n=1))[0]
    weedy = wf.simulate(dict(task(25.0, n=1), weeds={"rc_pct": 50}))[0]
    salty = wf.simulate(dict(task(25.0, n=1), salinity={"ece_initial": 6.0}))[0]
    dense = wf.simulate(dict(task(25.0, n=1), density=1.2))[0]
    sparse = wf.simulate(dict(task(25.0, n=1), density=0.67))[0]
    assert base["status"] == "ok" and weedy["yield_t_ha"] < base["yield_t_ha"]
    assert salty["yield_t_ha"] == pytest.approx(base["yield_t_ha"] * wf.salt_factor("MaizeGDD", 6.0), rel=1e-3)
    assert dense["yield_t_ha"] != sparse["yield_t_ha"]
    irr = wf.simulate(dict(task(5.0, n=1), irrigation={"irrigation_method": 2, "IrrInterval": 7, "MaxIrr": 30}))[0]
    assert irr["irrigation_mm"] > 100
    bunded = wf.prepare(dict(task(), field={"bunds": True, "z_bund": 0.1}))
    assert bunded["site"]["SSMAX"] == pytest.approx(10.0)


def test_nitrogen_levels():
    ev = wf.nitrogen_events({"rate_kg_ha": 50, "split": [[0, 0.4], [30, 0.6]], "recovery": 0.6}, dt.date(2026, 10, 20))
    tab = ev[0]["events_table"]
    assert ev[0]["event_signal"] == "apply_n" and len(tab) == 2
    assert tab[1] == {dt.date(2026, 11, 19): {"N_amount": 30.0, "N_recovery": 0.6}}
    assert wf.nitrogen_events({"rate_kg_ha": 0}, dt.date(2026, 10, 20)) is None
    soil = {"NSOILBASE": 10.0, "NSOILBASE_FR": 0.025, "NAVAILI": 5.0, "BG_N_SUPPLY": 0.02}
    y = [wf.simulate(dict(task(30.0, n=1), nitrogen={"rate_kg_ha": r, "split": [[0, 0.4], [30, 0.6]], **soil}))[0]
         for r in (0, 60)]
    assert y[0]["status"] == "ok" and y[1]["yield_t_ha"] > y[0]["yield_t_ha"]
    sorghum = dict(task(30.0, n=1), variety={"label": "Sorghum", "aquacrop_crop": "SorghumGDD", "maturity_days": 100,
                                              "failure_t_ha": 0.5, "kw": {}}, nitrogen={"rate_kg_ha": 0, **soil})
    assert wf.simulate(sorghum)[0]["status"] == "error"                    # no WOFOST 8.1 nitrogen parameters
