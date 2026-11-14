"""Water use, the harvest-index check, partial runoff reduction and the water drawn for irrigation (synthetic data)."""
import datetime as dt

import pytest

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.adapters import dssat_adapter as dsa
from crop_engine.scenarios import management as mg
from crop_engine.tests.test_engine import LAYERS, VARIETY, _task, weather

SOW = dt.date(2026, 10, 20)


@pytest.fixture(scope="module")
def wet():
    return weather(1, True)


def test_water_balance_of_a_sown_crop(wet):
    m = aq.simulate(_task(wet, [SOW]))[0]
    assert m["status"] in ("ok", "died")
    assert m["et_mm"] == pytest.approx(m["transpiration_mm"] + m["evaporation_mm"], abs=0.2)
    for k in ("et_mm", "transpiration_mm", "evaporation_mm", "runoff_mm", "drainage_mm", "capillary_rise_mm"):
        assert m[k] >= 0
    assert m["water_productivity_kg_m3"] == pytest.approx(100 * m["yield_t_ha"] / m["et_mm"], abs=0.01)
    assert 0 <= m["rain_lost_pct"] <= 100
    # the water used and lost cannot exceed the rain plus what the soil held at sowing (2 m profile, < 400 mm)
    assert m["et_mm"] + m["runoff_mm"] + m["drainage_mm"] <= m["rain_mm"] + 400
    s = ro.summarize([m], VARIETY)
    assert s["water_use"]["n"] == 1 and s["water_use"]["et_mm_median"] == pytest.approx(m["et_mm"], abs=1e-3)


def test_no_water_use_without_a_water_balance():
    assert ro.water_use([{"status": "ok", "yield_t_ha": 2.0}]) is None              # WOFOST and DSSAT members
    s = ro.summarize([{"status": "not_sown", "yield_t_ha": 0.0, "planting": None, "harvest": None, "stress_days": None,
                       "rain_mm": None, "potential_t_ha": None}], VARIETY)
    assert "water_use" not in s and "irrigation_drawn_mm_median" not in s


def test_low_harvest_index_check():
    ok = lambda y, b: {"status": "ok", "yield_t_ha": y, "biomass_t_ha": b}
    assert ro.low_harvest_index([ok(4.0, 9.0), ok(0.5, 9.0), {"status": "died", "yield_t_ha": 0.1, "biomass_t_ha": 5}]) == 50.0
    assert ro.low_harvest_index([{"status": "not_sown", "yield_t_ha": 0}]) is None
    m = aq.simulate(_task(weather(1, True), [SOW]))
    assert ro.low_harvest_index(m) in (0.0, None)                        # a normal season: no "matured" crop without grain


def test_partial_runoff_reduction_sits_between_bare_soil_and_ridges(wet):
    t = _task(wet, [SOW])
    bare = aq.simulate(t)[0]
    contour = aq.simulate(mg.apply(t, "contour_ridges"))[0]
    terraces = aq.simulate(mg.apply(t, "terraces"))[0]
    ridges = aq.simulate(mg.apply(t, "ridges"))[0]
    assert ridges["runoff_mm"] == 0
    assert bare["runoff_mm"] >= contour["runoff_mm"] >= terraces["runoff_mm"] >= ridges["runoff_mm"]
    assert bare["runoff_mm"] > terraces["runoff_mm"]                     # the synthetic rain does run off bare soil


def test_runoff_scenarios_routing():
    for k in ("contour_ridges", "terraces"):
        assert not mg.aquacrop_only(k)                                   # DSSAT lowers its own curve number
        assert mg.SCENARIOS[k]["field"]["curve_number_adj_pct"] < 0
    from crop_engine import run_scenarios as rs
    res = {"sites": {"s": {"results": {"maize_early": {"rule1": {"wofost": {}, "dssat": {}}}}}}}
    _, wk = rs.wofost_plan(res, {}, list(mg.SCENARIOS))
    _, dk = rs.dssat_plan(res, {}, list(mg.SCENARIOS))
    assert "contour_ridges" not in wk and "terraces" not in wk           # WOFOST has no curve number
    assert "contour_ridges" in dk and "terraces" in dk


def test_dssat_curve_number_adjustment():
    base = dsa.soil_file("S", -2.2, 37.7, LAYERS, 150)
    less = dsa.soil_file("S", -2.2, 37.7, LAYERS, 150, cn_adj_pct=-30)
    ridges = dsa.soil_file("S", -2.2, 37.7, LAYERS, 150, curve_number=dsa.RIDGES_CN, cn_adj_pct=-30)
    slro = lambda txt: float(txt.splitlines()[[i for i, l in enumerate(txt.splitlines()) if "SLRO" in l][0] + 1].split()[4])
    assert slro(less) == pytest.approx(slro(base) * 0.7, abs=0.1)
    assert slro(ridges) == dsa.RIDGES_CN                                 # the ridges' own value wins


def test_water_drawn_for_irrigation(wet):
    t = mg.apply(_task(wet, [SOW]), "irr_full")
    m = aq.simulate(t)
    s = ro.summarize(m, VARIETY)
    assert s["irrigation_mm_median"] > 0
    assert s["irrigation_drawn_mm_median"] == pytest.approx(s["irrigation_mm_median"] / C.IRRIGATION_EFFICIENCY, abs=0.1)


# ── rootable soil depth (a restrictive layer) ──────────────────────────────
def test_soil_depth_table_and_hash_inputs(tmp_path):
    from crop_engine.data import soil_depth as sd
    assert sd.restrictions() == []                                     # iSDAsoil: no site or grid cell under 2 m
    f = tmp_path / "d.yaml"
    f.write_text("sites:\n  a: {depth_cm: 80, source: measured}\n  b: {depth_cm: 200, source: isda}\n")
    assert sd.restrictive_cm("a", f) == 80 and sd.restrictive_cm("b", f) is None and sd.restrictive_cm("c", f) is None
    assert sd.restrictions(f) == [("a", 80.0)]


def test_a_shallow_soil_limits_every_engine(wet):
    import pickle
    from crop_engine.adapters import wofost_adapter as wf
    from crop_engine.data import soil
    shallow = soil.with_depth(LAYERS, 60.0)
    assert pickle.loads(pickle.dumps(shallow)).restrictive_cm == 60.0     # survives the worker processes
    kw, _ = aq.crop_parameters(VARIETY, 23.0)
    assert aq.rooting_limited(kw, "MaizeGDD", LAYERS) is kw              # a plain profile: unchanged
    assert aq.rooting_limited(kw, "MaizeGDD", shallow)["Zmax"] == 0.6
    assert aq.rooting_limited(kw, "MaizeGDD", soil.with_depth(LAYERS, 10.0))["Zmax"] > 0.3   # never below Zmin
    assert wf.soil_parameters(shallow, 0.5)[0]["RDMSOL"] == 60.0
    assert wf.soil_parameters(LAYERS, 0.5)[0]["RDMSOL"] == 200.0
    deep = aq.simulate(_task(wet, [SOW]))[0]
    t = dict(_task(wet, [SOW]), layers=shallow)
    limited = aq.simulate(t)[0]
    assert limited["status"] in ("ok", "died", "failed_establishment")
    assert limited["transpiration_mm"] <= deep["transpiration_mm"] + 1      # less soil water within reach of the roots


# ── temperature at flowering and the temperature spread ────────────────────
def test_heat_and_cold_days_at_flowering(wet):
    m = aq.simulate(_task(wet, [SOW]))[0]                              # synthetic weather: tmax 29, tmin 16 every day
    assert m["heat_days_flowering"] == 0 and m["cold_days_flowering"] == 0
    hot = dict(_task(wet, [SOW]))
    hot["tmax"] = hot["tmax"] * 0 + 37.0                              # above maize's ~35 °C every day
    h = aq.simulate(hot)[0]
    assert h["heat_days_flowering"] > 0
    s = ro.summarize([m, h], VARIETY)
    assert s["flowering_temperature"]["members_with_heat_pct"] == 50.0


def test_temperature_spread_ratio():
    import numpy as np
    import pandas as pd
    from crop_engine.data import seas5
    rng = np.random.default_rng(0)
    years, sites = [2001, 2002, 2003, 2004, 2005, 2006], ["a"]
    n = len(seas5.lead_dates(2001))
    hind = {y: {"tmax": (28 + 2.0 * rng.standard_normal((10, n, 1))).astype(np.float32)} for y in years}
    temps = {"a": pd.concat([pd.DataFrame({"tmax": 26 + 1.0 * rng.standard_normal(n)}, index=seas5.lead_dates(y))
                             for y in years])}
    r = seas5.spread_ratio(hind, temps, sites, years, "tmax")
    assert r.shape == (n, 1) and 0.4 < float(np.median(r)) < 0.6     # ERA5-Land's spread is half the members'
    assert seas5.TEMPERATURE_SPREAD is False                            # off until the hindcast shows it helps


# ── crop-parameter uncertainty ──────────────────────────────────────────────
def test_parameter_draws_are_seeded_and_bounded():
    kw, _ = aq.crop_parameters(VARIETY, 23.0)
    p = mg.SCENARIOS["parameters"]["perturb"]
    a = mg.parameter_draws(kw, "MaizeGDD", 25, p)
    assert a == mg.parameter_draws(kw, "MaizeGDD", 25, p) and len({x["HI0"] for x in a}) > 20
    from aquacrop.entities.crop import crop_params
    hi0 = kw.get("HI0", crop_params["MaizeGDD"]["HI0"])
    assert all(hi0 * (1 - 2 * p["HI0"]) - 1e-6 <= x["HI0"] <= hi0 * (1 + 2 * p["HI0"]) + 1e-6 for x in a)
    assert all(x["CCx"] <= 0.99 for x in a) and all("Maturity" not in x for x in a)
    assert mg.aquacrop_only("parameters")


def test_parameter_uncertainty_widens_the_yields(wet):
    t = _task(weather(4, True), [SOW] * 4)
    base = aq.simulate(t)
    drawn = aq.simulate(mg.apply(t, "parameters"))
    assert len(mg.apply(t, "parameters")["kw_member"]) == 4
    assert [m["status"] for m in drawn] and any(abs(a["yield_t_ha"] - b["yield_t_ha"]) > 0.01 for a, b in zip(base, drawn))
    assert [m["planting"] for m in base] == [m["planting"] for m in drawn]          # same sowing, same weather


# ── soil water on 1 Aug from SMAP ───────────────────────────────────────────
def test_smap_fraction_and_scenario(tmp_path, wet):
    import json
    from crop_engine import run_scenarios as rs
    from crop_engine.data import smap
    # LAYERS: field capacity 0.22, wilting point 0.12 → 0.17 m3/m3 is half the available water
    assert smap.available_fraction(0.17, LAYERS) == pytest.approx(0.5, abs=1e-6)
    assert smap.available_fraction(0.05, LAYERS) == 0.0 and smap.available_fraction(0.40, LAYERS) == 1.0
    f = tmp_path / "smap.json"
    f.write_text(json.dumps({"sites": {"s1": {"2026": 0.17}}}))
    assert smap.initial_fraction("s1", 2026, LAYERS, f) == pytest.approx(0.5)
    assert smap.initial_fraction("s1", 2025, LAYERS, f) is None and smap.available(2026, f) and not smap.available(2025, f)
    t = dict(_task(wet, [SOW]), smap_frac=0.5)
    assert mg.apply(t, "soil_smap")["initial_frac"] == 0.5
    assert mg.apply(dict(t, smap_frac=None), "soil_smap")["initial_frac"] == t["initial_frac"]   # no value: the outlook's
    assert "soil_smap" not in rs.available_keys(["soil_smap", "soil_dry"], 1990)                   # no SMAP before 2015


def test_smap_comparison():
    from crop_engine.data import smap
    r = smap.compare({"a": [(2016, 0.1, 0.3), (2017, 0.2, 0.4), (2018, 0.15, 0.35)], "b": [(2016, None, 0.2)]})
    assert r["a"]["mean_difference"] == pytest.approx(0.2) and r["a"]["correlation"] == pytest.approx(1.0)
    assert "b" not in r
