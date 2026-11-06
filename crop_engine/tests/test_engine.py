"""Unit tests of the crop engine on synthetic data (no forecast pipeline needed): python -m pytest crop_engine/tests"""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from crop_engine import config as C
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.data import era5land, soil
from crop_engine.data.sites import Site, on_grid, registered_sites, slug
from crop_engine.data.weather import jan_feb_index, season_length, to_dataset, validate
from crop_engine.scenarios import planting as pl
from crop_engine.scenarios.planting import doy_to_date

DATES = pd.date_range("2026-08-01", "2027-03-31")
SITE = Site("test_site", "Test site", -2.21, 37.72, "kenya", 0, 0, -2.125, 37.625)
LAYERS = [soil.Layer(t, b, 60, 22, 1.2, 5, 0.22, 0.12) for t, b in ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))]
VARIETY = {"label": "Early-maturing maize", "aquacrop_crop": "MaizeGDD", "maturity_days": 90, "failure_t_ha": 0.5}


def weather(n_mem=2, wet=True):
    rng = np.random.default_rng(1)
    rain = rng.gamma(0.4, 14, (n_mem, 1, len(DATES))).astype(np.float32)
    rain[..., ~DATES.month.isin([10, 11, 12])] = 0
    if not wet:
        rain[:] = 0
    T = len(DATES)
    tmax, tmin, et0 = np.full((1, T), 29.0, np.float32), np.full((1, T), 16.0, np.float32), np.full((1, T), 4.5, np.float32)
    src = np.zeros(T, np.int8)
    met = np.zeros((1, T), np.int8)
    return to_dataset(rain, tmax, tmin, et0, src, met, met, DATES, [SITE], {"forecast_source": "test", "season_year": 2026})


# ── weather contract ────────────────────────────────────────────────────────
def test_valid_dataset_passes():
    assert validate(weather()) == []


def test_contract_catches_problems():
    ds = weather()
    ds["precip_mm"].values[0, 0, 5] = np.nan
    ds["tmin_c"].values[0, 0, 10] = 40.0
    p = validate(ds)
    assert any("precip_mm" in x for x in p) and any("tmin above tmax" in x for x in p)
    ds2 = weather().drop_vars("et0_mm")
    assert "missing et0_mm" in validate(ds2)


def test_provenance_attrs():
    ds = weather()
    assert json.loads(ds.attrs["precip_sources"]) == C.PRECIP_SOURCES
    assert ds.precip_mm.attrs["units"] == "mm/day"


# ── varieties ───────────────────────────────────────────────────────────────
def test_variety_scaling_hits_maturity_days():
    kw, f = aq.crop_parameters(VARIETY, 23.0)
    g = aq.gdd(np.full(200, 29.0), np.full(200, 17.0), 8.0, 30.0)       # mean 23 °C
    days = int(np.argmax(np.cumsum(g) > kw["Maturity"])) + 1
    assert abs(days - 90) <= 1
    from aquacrop.entities.crop import crop_params
    p = crop_params["MaizeGDD"]
    assert kw["CGC"] == pytest.approx(p["CGC"] / f) and kw["Flowering"] == pytest.approx(p["Flowering"] * f)


# ── planting dates ──────────────────────────────────────────────────────────
def test_season_runs_to_its_end():
    import fao_water_balance as fw
    t0 = fw.season_days(fw.load_config())[0]
    T = season_length(t0)
    assert T == 243 and season_length(t0, (2, 28)) == fw.season_days(fw.load_config())[1]   # 28 Feb: the FAO window
    assert fw.season_dates(2026, t0, T)[-1] == pd.Timestamp("2027-03-31")
    assert fw.season_dates(2027, t0, T)[-1] == pd.Timestamp("2028-03-30")                   # a leap year: one day short


def test_jan_feb_members_map_by_day_and_29_feb_repeats_28_feb():
    d = pd.date_range("2028-01-01", "2028-02-29")
    i = jan_feb_index(d, 2027)
    assert i[0] == 0 and i[-2] == 58 and i[-1] == 58 and len(i) == 60


def test_doy_to_date():
    assert doy_to_date(227, 2026) == dt.date(2026, 8, 15)
    assert doy_to_date(366, 2026) == dt.date(2027, 1, 1)
    assert doy_to_date(np.nan, 2026) is None and doy_to_date(500, 2026) is None
    assert doy_to_date(244, 1996) == dt.date(1996, 9, 1)                  # no-leap DOY numbering from 1 Aug


# ── sites and soil ──────────────────────────────────────────────────────────
def test_registered_sites():
    s = registered_sites()
    assert len(s) >= 6 and all(x.country == "kenya" for x in s)
    assert slug("KALRO Kiboko, Makueni Farm") == "kalro_kiboko_makueni_farm"
    kiboko = [x for x in s if x.id == "kalro_kiboko_makueni_farm"]                  # -2.21046, 37.7190
    g = on_grid(kiboko, np.array([-2.375, -2.125]), np.array([37.375, 37.625]))[0]
    assert (g.cell_lat, g.cell_lon) == (-2.125, 37.625)


def test_soil_check():
    soil.check(LAYERS)
    assert soil.taw_mm(LAYERS) == pytest.approx(100.0)
    bad = [soil.Layer(0, 5, 60, 50, 1, 0, 0.2, 0.1)] + LAYERS[1:]
    with pytest.raises(ValueError):
        soil.check(bad)


@pytest.mark.skipif(not soil.SOIL_FILE.exists(), reason="no SoilGrids file")
def test_site_profile_from_file():
    s = on_grid(registered_sites()[:1], np.arange(-4.875, 5.4, 0.25), np.arange(33.625, 41.9, 0.25))[0]
    L = soil.profile(s)
    assert [x.bottom_cm for x in L] == [5, 15, 30, 60, 100, 200] and 30 < soil.taw_mm(L) < 250


def test_climatology_is_smooth_and_complete():
    idx = pd.date_range("1993-01-01", "2016-12-31")
    s = pd.Series(20 + 5 * np.sin(2 * np.pi * idx.dayofyear / 365), index=idx)
    c = era5land.climatology(s)
    assert len(c) == 366 and np.isfinite(c).all() and np.abs(np.diff(c[:365])).max() < 0.2


# ── AquaCrop ────────────────────────────────────────────────────────────────
def _task(ds, planting):
    kw, _ = aq.crop_parameters(VARIETY, 23.0)
    return dict(dates=ds.time.values, rain=ds.precip_mm.values[:, 0], tmax=ds.tmax_c.values[:, 0], tmin=ds.tmin_c.values[:, 0],
                et0=ds.et0_mm.values[:, 0], source=ds.precip_source.values, planting=planting, variety=VARIETY, kw=kw,
                layers=LAYERS, initial_frac=0.3)


def test_aquacrop_wet_beats_dry_and_statuses():
    wet = aq.simulate(_task(weather(1, True), [dt.date(2026, 10, 20)]))[0]
    dry = aq.simulate(_task(weather(1, False), [dt.date(2026, 10, 20)]))[0]
    assert wet["status"] in ("ok", "died") and wet["yield_t_ha"] > dry["yield_t_ha"]
    assert wet["stress_days"] < dry["stress_days"] or dry["status"] in ("died", "failed_establishment")
    late, none = aq.simulate(_task(weather(2, True), [dt.date(2027, 3, 1), None]))
    assert late["status"] == "too_late" and none["status"] == "not_sown" and none["yield_t_ha"] == 0.0


# ── re-sowing ───────────────────────────────────────────────────────────────
def _false_start(n_mem=1):
    """A 30 mm sowing rain on 1 Oct, six dry weeks, then a wet season from 15 Nov."""
    ds = weather(n_mem, True)
    r = ds.precip_mm.values
    r[:] = 0
    r[..., DATES.get_loc(pd.Timestamp("2026-10-01"))] = 30
    wet = (DATES >= pd.Timestamp("2026-11-15")) & (DATES <= pd.Timestamp("2027-01-31"))
    r[..., wet] = np.where(np.arange(wet.sum()) % 2 == 0, 12.0, 3.0)
    return ds


def test_sowing_opportunities_in_turn():
    ds = _false_start()
    opp = pl.sowing_opportunities(ds.precip_mm.values[:, 0], DATES)[0]
    assert opp[0] == dt.date(2026, 11, 15)                 # 1 Oct is followed by a dry spell: not an opportunity
    assert opp == sorted(set(opp)) and len(opp) > 10       # each 12 mm day to 15 Jan (27 mm in 3 days), once
    assert opp[-1] <= dt.date(2027, 1, 15)                                         # the rules' search end


def test_resowing_after_a_false_start():
    ds = _false_start()
    t = dict(_task(ds, [dt.date(2026, 10, 1)]), initial_frac=0.05)
    first = aq.simulate(dict(t, resow=None))[0]
    assert first["status"] == "failed_establishment" and first["sowings"] == 1
    again = aq.simulate(dict(t, resow=pl.sowing_opportunities(ds.precip_mm.values[:, 0], DATES)))[0]
    assert again["sowings"] == 2 and again["first_planting"] == "2026-10-01"
    assert again["planting"] >= "2026-11-15" and again["status"] in ("ok", "died") and again["yield_t_ha"] > 0


def test_variety_parameters_override():
    kw, _ = aq.crop_parameters(dict(VARIETY, parameters={"PlantPop": 44000, "HI0": 0.4}), 23.0)
    assert kw["PlantPop"] == 44000 and kw["HI0"] == 0.4
    with pytest.raises(ValueError):
        aq.crop_parameters(dict(VARIETY, parameters={"PlantPopulation": 44000}), 23.0)


def test_canopy_band_and_potential():
    from crop_engine import run_outlook as ro
    out = aq.simulate(_task(weather(2, True), [dt.date(2026, 10, 20), None]))
    sown, none = out
    assert len(sown["_canopy"]) == len(DATES[::aq.CANOPY_STEP]) and 0 < max(sown["_canopy"]) <= 1
    assert "_canopy" not in none
    assert sown["potential_t_ha"] >= sown["yield_t_ha"]
    s = ro.summarize(out, VARIETY)
    assert s["potential_t_ha"]["median"] == pytest.approx(sown["potential_t_ha"], abs=1e-3)
    band = ro.canopy_band(out, "2026-08-01")
    assert band["n"] == 1 and band["start"] == "2026-08-01" and band["step_days"] == aq.CANOPY_STEP
    assert len(band["median"]) == len(sown.get("_canopy", band["median"])) and band["p10"] <= band["p90"]
    assert all("_canopy" not in m for m in out)                    # taken off: not written to the results
    json.dumps(out)


def test_dashboard_carries_the_new_outputs(tmp_path, monkeypatch):
    from crop_engine import dashboard, run_outlook as ro
    monkeypatch.setattr(C, "RESULTS_OUT", tmp_path / "results")
    monkeypatch.setattr(C, "DASHBOARD_OUT", tmp_path / "crop")
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "BASE", tmp_path)
    out = aq.simulate(_task(weather(2, True), [dt.date(2026, 10, 20), None]))
    summ, band = ro.summarize(out, VARIETY), ro.canopy_band(out, "2026-08-01")
    res = {"summary": summ, "canopy": band, "members": out}
    meta = {"id": "seasonal_20261001", "source": "seasonal", "model_label": "SEAS5", "run": "2026-10-01", "obs_end": "2026-10-25",
            "members_kind": "ensemble", "segments": [], "created": "x", "engine": "test", "caveats": [],
            "varieties": {"maize_early": VARIETY}, "planting_rules": {"rule1": "Agri rule 1"}}
    site = {"name": "Test", "cell": [-2.125, 37.625], "soil_taw_100cm_mm": 100, "topsoil": {"sand": 60, "clay": 22},
            "initial_water_fraction": 0.1, "fao_reference": {}, "results": {"maize_early": {"rule1": res}}}
    C.RESULTS_OUT.mkdir()
    (C.RESULTS_OUT / "seasonal_20261001.json").write_text(json.dumps({"meta": meta, "sites": {"test_site": site}}))
    year = {"status": "ok", "planting": "2020-10-20", "harvest": "2021-01-20", "yield_t_ha": 3.0, "potential_t_ha": 4.0}
    (tmp_path / "climatology.json").write_text(json.dumps({"years": [2020, 2020], "cal_years": [2020, 2020], "sites": {"test_site": {
        "maize_early": {"rule1": {"years": {"2020": year}, "t33": 1, "t67": 2, "median": 3, "cal_median": 3, "p_failure": 0,
                                  "canopy": band}}}}}))
    dashboard.write_index()
    dashboard.write(log=lambda *a: None)
    d = json.loads((C.DASHBOARD_OUT / "seasonal.json").read_text())["sites"]["test_site"]["results"]["maize_early"]["rule1"]
    keys = json.loads((C.DASHBOARD_OUT / "index.json").read_text())["member_keys"]
    m = dict(zip(keys, d["members"][0]))
    assert m["potential_t_ha"] == out[0]["potential_t_ha"] and m["sowings"] == 1
    assert d["canopy"]["median"] == band["median"] and "potential_t_ha" in d["summary"]
    b = json.loads((C.DASHBOARD_OUT / "benchmark.json").read_text())["sites"]["test_site"]["maize_early"]["rule1"]
    assert b["seasons"][0][5] == 4.0 and b["canopy"]["n"] == 1


def test_outcome_rates_have_their_own_denominators():
    from crop_engine import run_outlook as ro
    m = lambda st, y=0.0: {"status": st, "yield_t_ha": y, "planting": None if st == "not_sown" else "2026-11-01"}
    recs = [m("ok", 3.0), m("ok", 0.2), m("died", 1.0), m("failed_establishment"), m("not_sown"), m("too_late"), m("error")]
    r = ro.outcome_rates(recs, 0.5)
    assert (r["n_valid"], r["n_error"], r["n_sown"]) == (6, 1, 4)               # the error is in no denominator
    assert r["p_sowing_opportunity"] == round(5 / 6, 3)                         # too late had an onset: sowable
    assert r["p_establishment_failure"] == 0.25 and r["p_failure_if_sown"] == 0.5   # of the 4 sown crops
    assert r["p_failure"] == round(4 / 6, 3)                                    # overall: no crop or a failed one
    assert r["yield_if_sown_t_ha"]["median"] == pytest.approx(0.6)
    assert ro.outcome_rates([m("error")], 0.5)["p_failure"] is None


# ── regression: fixed synthetic seasons against stored outputs ──────────────────────────────────────────────────
REFERENCE = json.loads((__import__("pathlib").Path(__file__).with_name("reference") / "aquacrop_synthetic.json").read_text())


def _reference_cases():
    from crop_engine import run_outlook as ro
    _, vs = ro.load_varieties(["maize_early", "sorghum"])
    cases = {"wet_20oct": _task(weather(1, True), [dt.date(2026, 10, 20)])}
    ds = _false_start()
    cases["false_start_resown"] = dict(_task(ds, [dt.date(2026, 10, 1)]), initial_frac=0.05,
                                       resow=pl.sowing_opportunities(ds.precip_mm.values[:, 0], DATES))
    for vk, v in vs.items():
        cases[f"{vk}_wet_20oct"] = dict(_task(weather(1, True), [dt.date(2026, 10, 20)]), variety=v,
                                        kw=aq.crop_parameters(v, 23.0)[0])
    return cases


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_regression_against_reference(name):
    """A change of the adapter, AquaCrop or varieties.yaml that moves these outputs must be deliberate: regenerate
    crop_engine/tests/reference/aquacrop_synthetic.json and say why in the commit."""
    r = aq.simulate(_reference_cases()[name])[0]
    ref = REFERENCE[name]
    for k in ("status", "planting", "harvest", "sowings"):
        assert r[k] == ref[k], (name, k)
    for k in ("yield_t_ha", "potential_t_ha", "biomass_t_ha", "max_canopy"):
        assert r[k] == pytest.approx(ref[k], abs=0.02), (name, k)
    assert abs(r["stress_days"] - ref["stress_days"]) <= 1
