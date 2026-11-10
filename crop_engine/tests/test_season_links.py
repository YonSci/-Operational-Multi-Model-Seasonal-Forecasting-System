"""The Crop outlook tab's links to the rest of the platform: the FAO water balance's soil water now (data/weather.py)
and the outlook's day-by-day history (dashboard.write_history), on synthetic data."""
import datetime as dt
import json
import types

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from crop_engine import config as C
from crop_engine import dashboard
from crop_engine.data import weather as W


def test_soil_water_now_takes_each_sites_last_observed_day(tmp_path, monkeypatch):
    lat, lon = np.array([-2.0, -1.75]), np.array([37.5, 37.75, 38.0])
    t = pd.date_range("2026-10-28", periods=6)                       # 28 Oct – 2 Nov
    a = np.full((6, 2, 3), np.nan, np.float32)
    a[:4, 0, 1] = [0.2, 0.3, 0.4, 0.5]                                # site 1: observed to 31 Oct
    a[:2, 1, 2] = [1.2, 1.1]                                          # site 2: to 29 Oct, clipped to 1
    xr.Dataset({"PAW_fraction": (("time", "lat", "lon"), a)}, coords={"time": t, "lat": lat, "lon": lon}) \
        .to_netcdf(tmp_path / "daily_2026.nc")
    monkeypatch.setattr(W.fw, "OUT_HIST", tmp_path)
    inp = types.SimpleNamespace(year=2026, lat=lat, lon=lon, ii=np.array([0, 1, 0]), jj=np.array([1, 2, 0]), sites=[1, 2, 3])
    out = W.Inputs.soil_water_now(inp, dt.date(2026, 10, 30))
    assert out[0][0] == pytest.approx(0.4) and out[0][1] == dt.date(2026, 10, 30)      # not past `until`
    assert out[1] == (1.0, dt.date(2026, 10, 29))
    assert out[2] is None                                             # no observed day there
    monkeypatch.setattr(W.fw, "OUT_HIST", tmp_path / "none")
    assert W.Inputs.soil_water_now(inp, dt.date(2026, 10, 30)) == [None] * 3


def _summary(y, pf):
    return {"yield_if_sown_t_ha": {"median": y, "p10": y / 2, "p90": y * 1.5}, "p_failure_if_sown": pf,
            "p_sowing_opportunity": 1.0}


def test_history_keeps_one_point_per_source_and_day(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "DASHBOARD_OUT", tmp_path / "dash")
    (tmp_path / "dash").mkdir()

    def entries(created, y, chash="a"):
        run = {"source": "seasonal", "run": "2026-10-01", "obs_end": created[:10], "created": created}
        mr = {"source": "mr-gfs_global", "run": created[:10], "obs_end": created[:10], "created": created}
        summ = {"kiboko": {"maize_early": {"rule1": _summary(y, 0.2)}}}
        wof = {"kiboko": {"maize_early": {"rule1": _summary(y - 1, 0.1)}}}
        return [(run, chash, summ, wof), (mr, chash, summ, None)]

    dashboard.write_history(entries("2026-11-09T13:54+03:00", 3.0), log=lambda m: None)
    dashboard.write_history(entries("2026-11-09T18:00+03:00", 3.2), log=lambda m: None)     # same day: replaced
    dashboard.write_history(entries("2026-11-10T13:00+03:00", 2.5, chash="b"), log=lambda m: None)
    h = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert list(h["sources"]) == ["seasonal"]                        # medium-range runs are not kept
    pts = h["sources"]["seasonal"]
    assert [(p["date"], p["config"]) for p in pts] == [("2026-11-09", "a"), ("2026-11-10", "b")]
    row = dict(zip(h["keys"], pts[0]["cells"]["kiboko"]["maize_early"]["rule1"]))
    assert row["yield_if_sown_median"] == 3.2 and row["wofost_yield_if_sown_median"] == 2.2
    assert row["p_failure_if_sown"] == 0.2 and row["wofost_p_failure_if_sown"] == 0.1
    assert (tmp_path / "dash" / "history.json").read_text(encoding="utf-8") == (tmp_path / "history.json").read_text(encoding="utf-8")
    # the master copy lost (a new machine): the published copy is the start
    (tmp_path / "history.json").unlink()
    dashboard.write_history(entries("2026-11-11T13:00+03:00", 2.0, chash="b"), log=lambda m: None)
    h = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [p["date"] for p in h["sources"]["seasonal"]] == ["2026-11-09", "2026-11-10", "2026-11-11"]
