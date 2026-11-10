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


# ── the two models as a confidence signal, the skill file, the bulletin's crop page ──
def _bulletin_crop():
    """backend/bulletin_crop.py of this checkout (the backend is not a package)."""
    import importlib
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
    return importlib.import_module("bulletin_crop")


def test_model_agreement_rule():
    bc = _bulletin_crop()
    s = lambda y, p: {"yield_if_sown_t_ha": {"median": y}, "p_failure_if_sown": p}           # noqa: E731
    assert bc.agreement(s(3.2, 0.24), s(2.3, 0.12)) == "agree"          # within 1 t/ha and 15 points
    assert bc.agreement(s(3.3, 0.24), s(3.2, 0.08)) == "partly"         # 16 points apart
    assert bc.agreement(s(1.6, 0.0), s(0.1, 0.4)) == "differ"           # 40 points apart
    assert bc.agreement(s(5.0, 0.1), s(2.5, 0.1)) == "differ"           # 2.5 t/ha apart
    assert bc.agreement(s(1.0, 0.1), {"yield_if_sown_t_ha": None, "p_failure_if_sown": 0.1}) is None


def test_skill_file_from_the_hindcasts(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "DASHBOARD_OUT", tmp_path / "dash")
    (tmp_path / "dash").mkdir()
    (tmp_path / "verification").mkdir()
    cell = {"crop": {"spearman": 0.513, "failure_auc": 0.8, "failure_bss": 0.32, "n_years": 24},
            "baselines": {"lgp_days": {"spearman": 0.62, "failure_auc": 0.85}, "rain_oct_dec_mm": {"spearman": 0.5},
                          "onset_doy": {"spearman": 0.49}}}
    for f, h in (("hindcast_scores.json", "old"), ("hindcast_scores_wofost.json", "w1")):
        (tmp_path / "verification" / f).write_text(json.dumps({"years": [1993, 2016], "config_hash": h, "created": "2026-11-08T19:52",
                                                               "sites": {"kiboko": {"maize_early": {"rule1": cell}}}}))
    assert dashboard.write_skill("new", log=lambda m: None)
    d = json.loads((tmp_path / "dash" / "skill.json").read_text(encoding="utf-8"))
    c = d["seasonal"]["sites"]["kiboko"]["maize_early"]["rule1"]
    assert c["aquacrop"] == {"r": 0.51, "auc": 0.8, "bss": 0.32, "n": 24} and c["wofost"]["r"] == 0.51
    assert c["lgp"]["r"] == 0.62 and c["rain"]["r"] == 0.5 and c["onset"]["r"] == 0.49
    assert d["seasonal"]["made"]["aquacrop"]["config_hash"] == "old" and d["seasonal"]["current_config"] == "new"
    assert "s2s" not in d                                              # no sub-seasonal hindcast on disk: left out


def test_bulletin_crop_page_only_near_a_crop_site(tmp_path, monkeypatch):
    bc = _bulletin_crop()
    (tmp_path / "crop").mkdir()
    summ = {"yield_if_sown_t_ha": {"median": 3.2, "p10": 0.0, "p90": 5.6}, "p_failure_if_sown": 0.24, "planting": {"median": "2026-10-29"}}
    ix = {"runs": [{"id": "seasonal_20261001", "source": "seasonal", "run": "2026-10-01", "obs_end": "2026-11-05",
                    "model_label": "ECMWF SEAS5"}],
          "sites": {"kiboko": {"name": "KALRO Kiboko", "lat": -2.21, "lon": 37.72}},
          "varieties": {"maize_early": {"label": "Early maize", "failure_t_ha": 0.5}},
          "planting_rules": {"fao-agricultural": "FAO agricultural onset"},
          "summaries": {"seasonal_20261001": {"kiboko": {"maize_early": {"fao-agricultural": summ}}}},
          "wofost": {"seasonal_20261001": {"kiboko": {"maize_early": {"fao-agricultural": {**summ, "p_failure_if_sown": 0.12}}}}}}
    (tmp_path / "crop" / "index.json").write_text(json.dumps(ix))
    (tmp_path / "crop" / "benchmark.json").write_text(json.dumps({"sites": {"kiboko": {"maize_early": {"fao-agricultural": {
        "seasons": [[1993, "1993-10-20", "1994-01-20", 2.0, "ok", 5.0], [1994, "1994-10-20", None, 0.1, "died", 4.0],
                    [1995, None, None, None, "not_sown", None]]}}}}}))
    monkeypatch.setattr(bc, "LOCAL", tmp_path)
    monkeypatch.setattr(bc, "REMOTE", "http://127.0.0.1:9/")             # never the network in a test
    bc._CACHE.clear()
    d = bc.page_data(-2.214, 37.721)
    assert d["crops"][0]["agree"] == "agree" and d["crops"][0]["past_yield"] == 1.05 and d["crops"][0]["past_fail"] == 0.5
    assert bc.page_data(9.0, 38.7) is None                               # Addis Ababa: no crop site within MAX_KM
    png = bc.crop_page_png(-2.214, 37.721, tmp_path)
    from PIL import Image
    with Image.open(png) as im:
        assert im.width == 1650 and 600 < im.height < 2200


def test_dashboard_makes_one_crop_bulletin_per_site(tmp_path, monkeypatch):
    import pathlib
    crop = tmp_path / "crop"
    crop.mkdir()
    summ = {"yield_if_sown_t_ha": {"median": 3.2, "p10": 0.0, "p90": 5.6}, "p_failure_if_sown": 0.24, "planting": {"median": "2026-10-29"}}
    ix = {"runs": [{"id": "seasonal_20261001", "source": "seasonal", "run": "2026-10-01", "obs_end": "2026-11-05", "model_label": "ECMWF SEAS5"}],
          "sites": {"kiboko": {"name": "KALRO Kiboko", "lat": -2.21, "lon": 37.72}, "nowhere": {"name": "No coordinates", "lat": None}},
          "varieties": {"maize_early": {"label": "Early maize", "failure_t_ha": 0.5}},
          "planting_rules": {"fao-agricultural": "FAO agricultural onset"},
          "summaries": {"seasonal_20261001": {"kiboko": {"maize_early": {"fao-agricultural": summ}}}}}
    (crop / "index.json").write_text(json.dumps(ix))
    (crop / "bulletins").mkdir()
    (crop / "bulletins" / "old_site.pdf").write_bytes(b"%PDF-")             # a site no longer in the outlook: removed
    monkeypatch.setattr(C, "DASHBOARD_OUT", crop)
    monkeypatch.setattr(C, "BASE", pathlib.Path(__file__).resolve().parents[2])
    dashboard.write_bulletins(log=lambda m: None)
    assert sorted(p.name for p in (crop / "bulletins").iterdir()) == ["kiboko.pdf"]
    assert (crop / "bulletins" / "kiboko.pdf").read_bytes()[:5] == b"%PDF-"
    assert json.loads((crop / "index.json").read_text(encoding="utf-8"))["bulletins"] == {"kiboko": "bulletins/kiboko.pdf"}
