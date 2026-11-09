"""Sub-seasonal temperature (data/s2s_temperature.py), flowering set apart from maturity (both adapters) and WOFOST
beside AquaCrop in the outlook's summaries and the tab's data, on synthetic data."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from crop_engine import config as C
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.data import s2s_temperature as s2t
from crop_engine.tests.test_engine import VARIETY, _task, weather


# ── sub-seasonal temperature ────────────────────────────────────────────────
def test_daily_extremes_take_each_days_steps_by_the_day_their_period_starts():
    hours = np.r_[0, np.arange(3, 49, 3)]                       # 3-hourly to 48 h: two days
    leads = pd.to_timedelta(hours, unit="h")
    tx = np.arange(len(hours), dtype=np.float32)[None, :, None] + 20        # (member, step, point)
    tn = tx - 10
    dmax, dmin, dates = s2t.daily_extremes(tx, tn, leads.values, pd.Timestamp("2026-11-01"))
    assert list(dates) == [pd.Timestamp("2026-11-01"), pd.Timestamp("2026-11-02")]
    assert dmax[0, :, 0].tolist() == [28.0, 36.0]                # steps 1–8 (day 0), 9–16 (day 1)
    assert dmin[0, :, 0].tolist() == [11.0, 19.0]
    tx[0, 12, 0] = np.nan                                        # a missing step: that day has no value
    dmax, _, _ = s2t.daily_extremes(tx, tn, leads.values, pd.Timestamp("2026-11-01"))
    assert dmax[0, 0, 0] == 28.0 and np.isnan(dmax[0, 1, 0])


def test_daily_extremes_of_a_daily_archive():
    leads = pd.to_timedelta(np.arange(0, 4) * 24, unit="h")      # ECMWF extended range: lead 0, 24, 48, 72 h
    tx = np.array([np.nan, 30, 31, 32], np.float32)[None, :, None]
    dmax, _, dates = s2t.daily_extremes(tx, tx - 12, leads.values, pd.Timestamp("2026-11-01"))
    assert dmax[0, :, 0].tolist() == [30.0, 31.0, 32.0] and dates[0] == pd.Timestamp("2026-11-01")


def test_run_temperature_subtracts_the_bias_by_lead_day(tmp_path, monkeypatch):
    monkeypatch.setattr(s2t, "TRAIN_DIR", tmp_path)
    monkeypatch.setattr(s2t, "RUN_DIRS", {"gefs": tmp_path})
    monkeypatch.setattr(s2t, "MIN_RUNS", 3)
    days, sites = pd.date_range("2026-06-01", "2026-12-31"), ["a", "b"]
    obs = {s: pd.DataFrame({"tmax": 28.0 + k, "tmin": 15.0 + k}, index=days) for k, s in enumerate(sites)}
    inits = pd.date_range("2026-08-01", periods=4, freq="7D")
    n = 10
    lead_bias = np.linspace(1.0, 2.0, n)                          # the model runs warm, more so with lead
    tr = np.stack([np.stack([obs[s].tmax.reindex(pd.date_range(i, periods=n)).values + lead_bias for s in sites], 1)
                   for i in inits])
    xr.Dataset({"tmax": (("init", "lead", "site"), tr), "tmin": (("init", "lead", "site"), tr - 13)},
               coords={"init": inits, "lead": np.arange(n), "site": sites}).to_netcdf(tmp_path / "gefs_training.nc")
    run = pd.Timestamp("2026-11-01")
    t = np.full((3, n, 2), 30.0, np.float32)
    xr.Dataset({"tmax": (("member", "time", "site"), t), "tmin": (("member", "time", "site"), t - 12)},
               coords={"member": [0, 1, 2], "time": pd.date_range(run, periods=n), "site": sites}
               ).to_netcdf(tmp_path / "gefs_t2m_20261101_sites.nc")
    rt = s2t.RunTemperature("gefs", run, sites, obs)
    b, _ = s2t.bias("gefs", obs, sites)
    assert rt.tmax.shape == (3, n, 2) and rt.n_train == 4
    np.testing.assert_allclose(rt.tmax[0, :, 0], 30.0 - b["tmax"][:, 0], atol=1e-5)
    assert 0.9 < b["tmax"][0, 0] < 1.4 and 1.6 < b["tmax"][-1, 0] < 2.1     # smoothed along the lead
    assert (rt.tmin <= rt.tmax).all()
    assert rt.on([run, run + pd.Timedelta(days=n)]).tolist() == [0, -1]
    monkeypatch.setattr(s2t, "MIN_RUNS", 5)                       # too few training runs: no correction
    with pytest.raises(ValueError):
        s2t.RunTemperature("gefs", run, sites, obs)


# ── flowering set apart from maturity ───────────────────────────────────────
def test_flowering_days_set_the_start_of_yield_formation():
    sorghum = {"label": "Sorghum", "aquacrop_crop": "SorghumGDD", "maturity_days": 87}
    kw0, _ = aq.crop_parameters(sorghum, 21.0)
    kw, _ = aq.crop_parameters(dict(sorghum, flowering_days=59), 21.0)
    assert kw["HIstart"] == pytest.approx(59 * (21.0 - 8.0))
    assert kw["Maturity"] == kw0["Maturity"] and kw["HIstart"] + kw["YldForm"] == pytest.approx(kw["Maturity"])
    assert kw["Flowering"] <= kw["YldForm"] and kw["HIstart"] > kw0["HIstart"]
    with pytest.raises(ValueError):
        aq.crop_parameters(dict(sorghum, flowering_days=90), 21.0)


def test_wofost_flowering_days_set_tsum1():
    pytest.importorskip("pcse")
    from crop_engine.adapters import wofost_adapter as wf
    try:
        wf._cropdata()
    except Exception as exc:
        pytest.skip(f"WOFOST crop parameters unavailable: {exc}")
    sorghum = {"label": "Sorghum", "aquacrop_crop": "SorghumGDD", "maturity_days": 87}
    _, _, over0, base = wf.phenology(sorghum)
    _, _, over, _ = wf.phenology(dict(sorghum, flowering_days=59))
    emerge = base["TSUMEM"] / (wf.REFERENCE_TMEAN - base["TBASEM"])
    rate = wf._afgen(base["DTSMTB"], wf.REFERENCE_TMEAN)
    assert emerge + over["TSUM1"] / rate == pytest.approx(59, abs=0.5)
    assert over["TSUM1"] + over["TSUM2"] == pytest.approx(over0["TSUM1"] + over0["TSUM2"], abs=0.2)


# ── WOFOST beside AquaCrop ──────────────────────────────────────────────────
def test_summaries_take_members_without_potential_yield_or_stress_days():
    from crop_engine import run_outlook as ro
    m = [dict(status="ok", yield_t_ha=2.0, potential_t_ha=None, planting="2026-10-20", harvest="2027-01-30",
              stress_days=None, rain_mm=300.0, sowings=1) for _ in range(4)]
    s = ro.summarize(m, VARIETY)
    assert s["yield_t_ha"]["median"] == 2.0 and s["potential_t_ha"]["median"] is None and s["stress_days_median"] is None


def test_wofost_runs_only_for_calibrated_varieties():
    from crop_engine import run_outlook as ro
    vs = {"maize_early": {"aquacrop_crop": "MaizeGDD", "wofost": {"AMAXTB_scale": 0.5}},
          "sorghum": {"aquacrop_crop": "SorghumGDD"}, "bean": {"aquacrop_crop": "DryBeanGDD", "wofost": {"x": 1}}}
    assert ro.wofost_varieties(vs) == ["maize_early"]


def test_dashboard_carries_the_second_model(tmp_path, monkeypatch):
    from crop_engine import dashboard
    from crop_engine import run_outlook as ro
    monkeypatch.setattr(C, "RESULTS_OUT", tmp_path / "results")
    monkeypatch.setattr(C, "DASHBOARD_OUT", tmp_path / "crop")
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "BASE", tmp_path)
    out = aq.simulate(_task(weather(2, True), [dt.date(2026, 10, 20), dt.date(2026, 10, 20)]))
    wof = [{k: v for k, v in dict(m, yield_t_ha=1.0, potential_t_ha=None, stress_days=None).items() if not k.startswith("_")}
           for m in out]                                             # as run_wofost cleans them
    res = {"summary": ro.summarize(out, VARIETY), "canopy": ro.canopy_band(out, "2026-08-01"), "members": out,
           "wofost": {"summary": ro.summarize(wof, VARIETY), "members": wof}}
    meta = {"id": "seasonal_20261001", "source": "seasonal", "model_label": "SEAS5", "run": "2026-10-01", "obs_end": "2026-10-25",
            "members_kind": "ensemble", "segments": [], "created": "x", "engine": "test", "caveats": [],
            "second_engine": {"engine": "WOFOST test", "varieties": ["maize_early"]},
            "varieties": {"maize_early": VARIETY}, "planting_rules": {"rule1": "Agri rule 1"}}
    site = {"name": "Test", "cell": [-2.125, 37.625], "soil_taw_100cm_mm": 100, "topsoil": {"sand": 60, "clay": 22},
            "initial_water_fraction": 0.1, "fao_reference": {}, "results": {"maize_early": {"rule1": res}}}
    C.RESULTS_OUT.mkdir()
    (C.RESULTS_OUT / "seasonal_20261001.json").write_text(json.dumps({"meta": meta, "sites": {"test_site": site}}))
    year = {"status": "ok", "planting": "2020-10-20", "harvest": "2021-01-20", "yield_t_ha": 3.0, "potential_t_ha": 4.0}
    (tmp_path / "climatology.json").write_text(json.dumps({"years": [2020, 2020], "cal_years": [2020, 2020], "sites": {"test_site": {
        "maize_early": {"rule1": {"years": {"2020": year}, "t33": 1, "t67": 2, "median": 3, "cal_median": 3, "p_failure": 0}}}}}))
    dashboard.write_index()
    dashboard.write(log=lambda *a: None)
    idx = json.loads((C.DASHBOARD_OUT / "index.json").read_text())
    assert idx["second_engine"] == "WOFOST test"
    assert idx["wofost"]["seasonal_20261001"]["test_site"]["maize_early"]["rule1"]["yield_t_ha"]["median"] == 1.0
    d = json.loads((C.DASHBOARD_OUT / "seasonal.json").read_text())["sites"]["test_site"]["results"]["maize_early"]["rule1"]
    w = dict(zip(idx["member_keys"], d["wofost"]["members"][0]))
    assert w["yield_t_ha"] == 1.0 and w["potential_t_ha"] is None and len(d["wofost"]["members"]) == 2
