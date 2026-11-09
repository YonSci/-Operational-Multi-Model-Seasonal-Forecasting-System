"""Management scenarios (crop_engine.scenarios.management, crop_engine.run_scenarios) on synthetic data."""
import datetime as dt
import json

import pandas as pd

from crop_engine import config as C
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.scenarios import management as mg
from crop_engine.tests.test_engine import DATES, LAYERS, SITE, VARIETY, _task, weather

D = dt.date


def _base(planting):
    return _task(weather(len(planting), True), planting)


def test_sowing_shift_keeps_unsown_members_and_stays_in_the_season():
    t = _base([D(2026, 10, 20), None, D(2027, 3, 25)])
    assert mg.apply(t, "sow_plus14")["planting"] == [D(2026, 11, 3), None, D(2027, 3, 31)]   # clipped to the season
    assert mg.apply(t, "sow_minus14")["planting"][0] == D(2026, 10, 6)
    assert t["planting"] == [D(2026, 10, 20), None, D(2027, 3, 25)]                           # the base is not changed


def test_calendar_sowing_sows_every_member():
    t = _base([D(2026, 10, 20), None])
    assert mg.apply(t, "sow_nov15")["planting"] == [D(2026, 11, 15)] * 2


def test_density_and_initial_water():
    kw, _ = aq.crop_parameters(dict(VARIETY, parameters={"PlantPop": 44444}), 23.0)
    t = dict(_base([D(2026, 10, 20)]), kw=kw)
    assert mg.apply(t, "density_low")["kw"]["PlantPop"] == round(44444 * 0.67)
    assert mg.apply(t, "density_high")["kw"]["PlantPop"] == round(44444 * 1.2)
    assert t["kw"]["PlantPop"] == 44444
    no_override = _base([D(2026, 10, 20)])                         # the crop file's own density (MaizeGDD: 75,000)
    assert mg.apply(no_override, "density_low")["kw"]["PlantPop"] == round(75000 * 0.67)
    assert mg.apply(t, "soil_dry")["initial_frac"] == 0.0 and mg.apply(t, "soil_wet")["initial_frac"] == 1.0
    assert all(set(mg.describe(k)) >= {"label", "group"} for k in mg.SCENARIOS)


def test_scenarios_change_the_crop_as_expected():
    t = _base([D(2026, 10, 20)])
    base, later = aq.simulate(t)[0], aq.simulate(mg.apply(t, "sow_plus28"))[0]
    assert later["planting"] == "2026-11-17" and later["harvest"] > base["harvest"]
    dry, wet = aq.simulate(mg.apply(t, "soil_dry"))[0], aq.simulate(mg.apply(t, "soil_wet"))[0]
    assert wet["yield_t_ha"] >= dry["yield_t_ha"] - 0.05


def _outlook_files(tmp_path, monkeypatch):
    """A one-site, one-variety, one-rule outlook run on disk, as run_outlook writes it."""
    from crop_engine import run_outlook as ro
    from crop_engine import run_scenarios as rs
    for k, v in {"OUT": tmp_path, "RESULTS_OUT": tmp_path / "results", "WEATHER_OUT": tmp_path / "weather",
                 "DASHBOARD_OUT": tmp_path / "crop", "BASE": tmp_path}.items():
        monkeypatch.setattr(C, k, v)
    monkeypatch.setattr(rs, "SCEN_OUT", tmp_path / "scenarios")
    monkeypatch.setattr(rs, "registered_sites", lambda: [SITE])
    monkeypatch.setattr(rs.soil_mod, "profile", lambda s: LAYERS)
    monkeypatch.setattr(ro, "load_varieties", lambda only=None: (23.0, {"maize_early": dict(
        VARIETY, kw=aq.crop_parameters(VARIETY, 23.0)[0], scale=1.0)}))
    ds = weather(2, True)
    for d in (C.RESULTS_OUT, C.WEATHER_OUT):
        d.mkdir(parents=True)
    ds.to_netcdf(C.WEATHER_OUT / "seasonal_20261001.nc")
    members = aq.simulate(_task(ds, [D(2026, 10, 20), None]))
    summ = ro.summarize(members, VARIETY)
    for m in members:
        m.pop("_canopy", None)
    meta = {"id": "seasonal_20261001", "source": "seasonal", "model_label": "test", "run": "2026-10-01",
            "obs_end": "2026-10-31", "members_kind": "ensemble", "created": "2026-11-07T15:00+03:00", "engine": "x",
            "config_hash": "abc", "varieties": {"maize_early": {"label": VARIETY["label"]}},
            "planting_rules": {"rule1": "Agri rule 1 onset"}}
    res = {"meta": meta, "sites": {SITE.id: {"name": SITE.name, "cell": [SITE.cell_lat, SITE.cell_lon],
                                              "initial_water_fraction": 0.3,
                                              "results": {"maize_early": {"rule1": {"summary": summ, "members": members}}}}}}
    (C.RESULTS_OUT / "seasonal_20261001.json").write_text(json.dumps(res))
    (C.RESULTS_OUT / "index.json").write_text(json.dumps({"runs": [{k: meta[k] for k in (
        "id", "source", "model_label", "run", "obs_end", "members_kind", "created")}]}))
    (tmp_path / "climatology.json").write_text(json.dumps({"sites": {}}))
    return rs, res


def test_run_writes_baseline_and_scenarios_and_skips_a_rerun(tmp_path, monkeypatch):
    rs, res = _outlook_files(tmp_path, monkeypatch)
    path = rs.run("seasonal_20261001", keys=["sow_plus14", "sow_nov15"], workers=1)
    d = json.loads(path.read_text())
    cell = d["sites"][SITE.id]["results"]["maize_early"]["rule1"]
    assert set(cell) == {"baseline", "sow_plus14", "sow_nov15"}
    assert cell["baseline"]["yield_t_ha"] == res["sites"][SITE.id]["results"]["maize_early"]["rule1"]["summary"]["yield_t_ha"]
    assert cell["sow_nov15"]["share"]["not_sown"] == 0                 # the calendar date sows the unsown member
    assert cell["sow_plus14"]["share"]["not_sown"] == 0.5               # a shift does not
    assert d["meta"]["scenarios"]["sow_nov15"]["sow_fixed"] == [11, 15]
    assert rs.run("seasonal_20261001", keys=["sow_plus14", "sow_nov15"], workers=1) is None


def test_dashboard_publishes_only_scenarios_of_the_current_run(tmp_path, monkeypatch):
    from crop_engine import dashboard
    rs, _ = _outlook_files(tmp_path, monkeypatch)
    rs.run("seasonal_20261001", keys=["soil_dry"], workers=1)
    assert dashboard.write_scenarios(lambda m: None) and (C.DASHBOARD_OUT / "scenarios.json").exists()
    p = C.RESULTS_OUT / "seasonal_20261001.json"
    d = json.loads(p.read_text())
    d["meta"]["obs_end"] = "2026-11-05"                                 # remade from newer observations: still shown
    p.write_text(json.dumps(d))
    assert dashboard.write_scenarios(lambda m: None)
    d["meta"]["config_hash"] = "changed"                                # another configuration: withdrawn
    p.write_text(json.dumps(d))
    assert not dashboard.write_scenarios(lambda m: None) and not (C.DASHBOARD_OUT / "scenarios.json").exists()


def test_weekly_refresh_keeps_recent_scenarios_of_the_same_configuration(tmp_path, monkeypatch):
    rs, _ = _outlook_files(tmp_path, monkeypatch)
    assert rs.run("seasonal_20261001", keys=["soil_dry"], workers=1)
    p = C.RESULTS_OUT / "seasonal_20261001.json"
    d = json.loads(p.read_text())
    d["meta"]["created"], d["meta"]["obs_end"] = "2026-11-08T15:00+03:00", "2026-11-01"   # the next day's results
    p.write_text(json.dumps(d))
    assert rs.run("seasonal_20261001", keys=["soil_dry"], workers=1, max_age_days=7) is None
    assert rs.run("seasonal_20261001", keys=["soil_dry"], workers=1) is not None        # without the limit: remade


def test_soil_is_looked_up_at_the_runs_grid_cell(tmp_path, monkeypatch):
    rs, res = _outlook_files(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(rs.soil_mod, "profile", lambda s: seen.append((s.cell_lat, s.cell_lon)) or LAYERS)
    res["sites"][SITE.id]["cell"] = [-2.25, 37.75]
    import xarray as xr
    with xr.open_dataset(C.WEATHER_OUT / "seasonal_20261001.nc") as ds:
        ds.load()
        rs.base_tasks(res, ds, {"maize_early": dict(VARIETY, kw={})}, ["rule1"], [SITE.id])
    assert seen == [(-2.25, 37.75)]


def test_an_outlook_that_is_not_reproduced_stops_the_run(tmp_path, monkeypatch):
    import pytest
    rs, res = _outlook_files(tmp_path, monkeypatch)
    for m in res["sites"][SITE.id]["results"]["maize_early"]["rule1"]["members"]:
        m["yield_t_ha"] += 0.5
    (C.RESULTS_OUT / "seasonal_20261001.json").write_text(json.dumps(res))
    with pytest.raises(RuntimeError, match="not reproduced"):
        rs.run("seasonal_20261001", keys=["soil_dry"], workers=1)
    assert not (tmp_path / "scenarios" / "seasonal_20261001.json").exists()


def test_irrigation_and_field_management_reach_aquacrop():
    """A dry season: supplementary irrigation (capped) and full irrigation raise the yield, mulch and bunds run."""
    t = _task(weather(1, False), [D(2026, 10, 20)])
    t["initial_frac"] = 0.6
    base = aq.simulate(t)[0]
    supp = aq.simulate(mg.apply(t, "irr_supplementary"))[0]
    full = aq.simulate(mg.apply(t, "irr_full"))[0]
    assert base["irrigation_mm"] == 0.0 and 0 < supp["irrigation_mm"] <= 100 + 1
    assert full["irrigation_mm"] > supp["irrigation_mm"] and full["yield_t_ha"] >= supp["yield_t_ha"] >= base["yield_t_ha"]
    assert full["status"] == "ok" and full["yield_t_ha"] > 0.8 * full["potential_t_ha"]
    for k in ("mulch", "ridges"):
        out = aq.simulate(mg.apply(t, k))[0]
        assert out["status"] != "error" and out["irrigation_mm"] == 0.0
    assert "irrigation" not in t and "field" not in t                                       # the base is not changed
