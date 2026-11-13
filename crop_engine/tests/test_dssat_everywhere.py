"""DSSAT beyond the outlook: the management scenarios' files, water-stress days, the nitrogen settings per site, the
history's extra columns, the scenarios' DSSAT plan, the regional map and the bulletin's agreement, without running
DSSAT."""
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crop_engine import dashboard as D
from crop_engine import grid as G
from crop_engine import run_nitrogen as rn
from crop_engine import run_scenarios as rs
from crop_engine.adapters import dssat_adapter as ds
from crop_engine.scenarios import management as mg
from crop_engine.tests.test_dssat import LAYERS, _col

PLANT = [dt.date(2026, 10, 29)]
ARGS = ("CE000001", "MZ", "KY0018", "CESOIL0001", dt.date(2026, 8, 1), PLANT, ["W0012602"], [(5, 0.2), (60, 0.21)],
        4.4, dt.date(2027, 3, 30))


def _line(txt, head, k=1):
    lines = txt.splitlines()
    h = next(ln for ln in lines if ln.startswith(head))
    return h, lines[lines.index(h) + k]


def test_irrigation_mulch_and_ridges_reach_dssats_files():
    irr = mg.SCENARIOS["irr_full"]["irrigation"]
    txt = ds.experiment_file(*ARGS, irrigation=irr, mulch_kg_ha=ds.MULCH_KG_HA)
    assert " 1 MA              R     A     N     N     A" in txt              # automatic irrigation
    h, ir = _line(txt, "@N IRRIGATION")
    assert ir[:_col(h, "IMDEP") + 1].split()[-1] == str(ds.IRR_DEPTH_CM)
    assert ir[:_col(h, "ITHRL") + 1].split()[-1] == str(irr["SMT"][0])        # AquaCrop's first threshold
    h, ic = _line(txt, "@C   PCR ICDAT")
    assert ic[:_col(h, "ICRES") + 1].split()[-1] == str(ds.MULCH_KG_HA)
    assert ic[:_col(h, "ICRIP") + 1].split()[-1] == "0"                     # left on the surface
    plain = ds.experiment_file(*ARGS)
    assert " 1 MA              R     N     N     N     A" in plain
    assert _line(plain, "@C   PCR ICDAT")[1][:_col(h, "ICRES") + 1].split()[-1] == "-99"
    nowater = ds.experiment_file(*ARGS, water=False, irrigation=irr)        # no water balance: nothing to irrigate
    assert " 1 MA              R     N     N     N     A" in nowater
    h, r = _line(ds.soil_file("CESOIL0001", -2.21, 37.72, LAYERS, 150, curve_number=ds.RIDGES_CN), "@ SCOM")
    assert float(r[:_col(h, "SLRO") + 1].split()[-1]) == ds.RIDGES_CN
    h, r = _line(ds.soil_file("CESOIL0001", -2.21, 37.72, LAYERS, 150), "@ SCOM")
    assert float(r[:_col(h, "SLRO") + 1].split()[-1]) != ds.RIDGES_CN       # the soil's own curve number


def test_stress_days_count_days_with_transpiration_below_half():
    grow = ("*RUN   1        : M1\n"
            "@YEAR DOY   DAS   DAP   LAID  WSPD\n"
            " 2026 302    89     0   0.00  0.00\n 2026 340   127    38   2.50  0.70\n"
            " 2026 341   128    39   2.40  0.40\n 2026 342   129    40   2.30  0.90\n 2027  40   192   103   0.40  0.10\n")
    g = ds.read_plantgro(grow)[1]
    assert list(g.wspd) == [0.0, 0.7, 0.4, 0.9, 0.1]
    assert "wspd" in ds.read_plantgro(grow.replace("  WSPD", "").replace("  0.70", "").replace("  0.40", "")
                                      .replace("  0.90", "").replace("  0.10", "").replace("  0.00\n", "\n"))[1]
    dates = pd.date_range("2026-08-01", "2027-03-31")
    T = len(dates)
    task = {"rain": np.full((1, T), 2.0), "source": np.zeros(T)}
    row = {"PDAT": "2026302", "EDAT": "2026308", "ADAT": "2026365", "MDAT": "2027040", "HDAT": "2027040",
           "HWAM": "3000", "CWAM": "7000", "LAIX": "2.5", "IRCM": "120"}
    r = ds._member(task, 0, PLANT[0], row, g, dates)
    assert r["stress_days"] == 2 and r["irrigation_mm"] == 120.0 and r["status"] == "ok"


def test_soil_factor_and_nitrogen_levels_per_site(monkeypatch):
    monkeypatch.setattr(ds, "soil_settings", lambda: {"organic_n_factor": 0.06, "sites": {"kiboko": {"organic_n_factor": 0.2}}})
    assert ds.soil_factor("kiboko") == 0.2 and ds.soil_factor("kapiti") == 0.06 and ds.soil_factor() == 0.06
    monkeypatch.setattr(ds, "nitrogen_settings", lambda: {
        "levels": {"n0": {"label": "No fertiliser", "rate_kg_ha": 0}, "n50": {"label": "50", "rate_kg_ha": 50}},
        "split": {"MaizeGDD": [[0, 0.4], [30, 0.6]]}, "sites": {"kiboko": {"rate_kg_ha": 18, "source": "manager"}},
        "assumed": "assumed"})
    levels, split, reported, note = rn.settings()
    assert split["MaizeGDD"] == [(0, 0.4), (30, 0.6)] and note == "assumed"
    k = rn.site_levels("kiboko", levels, reported)
    assert set(k) == {"n0", "n50", "reported"} and k["reported"]["rate_kg_ha"] == 18
    assert set(rn.site_levels("kapiti", levels, reported)) == {"n0", "n50"}
    t = rn.with_nitrogen({"variety": {"aquacrop_crop": "MaizeGDD"}}, "kiboko", levels["n50"], split)
    assert t["nitrogen"] == {"rate_kg_ha": 50, "split": [(0, 0.4), (30, 0.6)], "organic_n_factor": 0.2}
    assert rn.with_nitrogen({"variety": {"aquacrop_crop": "DryBeanGDD"}}, "kapiti", levels["n0"],
                            split)["nitrogen"]["split"] == [(0, 1.0)]
    h = rn.normal_hash("abc")
    assert h == rn.normal_hash("abc") and h != rn.normal_hash("abd")


def test_the_cultivars_file_has_the_nitrogen_and_soil_tables():
    n, s = ds.nitrogen_settings(), ds.soil_settings()
    assert {"n0", "n25", "n50"} <= set(n["levels"]) and n["levels"]["n0"]["rate_kg_ha"] == 0
    assert all(abs(sum(sh for _, sh in v) - 1) < 1e-9 for v in n["split"].values())
    assert isinstance(n.get("sites") or {}, dict) and isinstance(s.get("sites") or {}, dict)


def test_an_older_history_is_padded_not_discarded():
    old = D.HISTORY_KEYS[:7]
    h = {"keys": list(old), "sources": {"seasonal": [{"day": "2026-11-01", "cells": {"kiboko": {"maize_early": {
        "rule1": [1.0, 0.5, 2.0, 0.2, 0.9, 1.1, 0.3]}}}}]}}
    out = D._pad_history(h)
    assert out["keys"] == D.HISTORY_KEYS
    assert out["sources"]["seasonal"][0]["cells"]["kiboko"]["maize_early"]["rule1"] == [1.0, 0.5, 2.0, 0.2, 0.9, 1.1, 0.3,
                                                                                       None, None]
    other = {"keys": ["something", "else"], "sources": {}}
    assert D._pad_history(other)["keys"] == ["something", "else"]           # not a prefix: left for a rebuild
    s = {"yield_if_sown_t_ha": {"median": 2.345, "p10": 1, "p90": 3}, "p_failure_if_sown": 0.25, "p_sowing_opportunity": 1}
    row = D._hist_row(s, None, {"yield_if_sown_t_ha": {"median": 3.0}, "p_failure_if_sown": 0.1})
    assert len(row) == len(D.HISTORY_KEYS) and row[0] == 2.35 and row[5] is None and row[7:] == [3.0, 0.1]


def test_dssat_grows_the_scenarios_it_can(monkeypatch):
    monkeypatch.setattr(ds, "installed", lambda: True)
    from crop_engine import run_outlook as ro
    _, vs = ro.load_varieties()
    res = {"sites": {"kiboko": {"results": {"maize_early": {"rule1": {"summary": {}, "dssat": {}}}}}}}
    vks, keys = rs.dssat_plan(res, vs, list(mg.SCENARIOS))
    assert vks == {"maize_early", "maize_medium", "sorghum", "bean"}
    assert "irr_full" in keys and "irr_supplementary" not in keys          # no seasonal cap in DSSAT's irrigation
    assert rs.dssat_plan({"sites": {"kiboko": {"results": {"maize_early": {"rule1": {"summary": {}}}}}}}, vs,
                         list(mg.SCENARIOS)) == (set(), [])                 # a run without DSSAT


def test_the_regional_map_publishes_dssat_beside_aquacrop(tmp_path, monkeypatch):
    cells = pd.DataFrame([dict(id="a", cell_lat=-1.125, cell_lon=37.125, area_ha=300.0, weights={"X": 300.0})])
    monkeypatch.setattr(G, "cell_rows", lambda cells, summ, bench, vk, rk: [{"id": "a", "from": bench["cells"]["name"]}])
    monkeypatch.setattr(G, "summarize_counties", lambda fc, bench, *a: {"X": {"from": bench["name"]}})
    monkeypatch.setattr(G, "verify", lambda bench, *a, **k: {"X": {"n_years": len(bench)}})
    var = {"maize_early": {"label": "Early maize", "failure_t_ha": 0.5}}
    bench = {"years": [1993, 2025], "cal_years": [1993, 2016], "cells": {"name": "aquacrop"}}
    dbench = {"years": [1993, 2025], "config_hash": "d1", "cells": {"name": "dssat"}}
    members = {"a": {"maize_early": {"fao-agricultural": []}}}
    meta = {"model_label": "SEAS5", "dssat": {"members": members, "summaries": {}}}
    out = G.publish(cells, {}, members, bench, meta, var, ["fao-agricultural"], ["X"], {}, {}, tmp_path / "g.json", dbench)
    assert out["meta"]["models"] == ["aquacrop", "dssat"] and "dssat" not in out["meta"]
    assert out["cells"][0]["from"] == "aquacrop" and out["cells_dssat"][0]["from"] == "dssat"
    assert out["counties_dssat"][0]["from"] == "dssat" and "verification" in out["counties_dssat"][0]
    assert json.loads((tmp_path / "g.json").read_text())["meta"]["models"] == ["aquacrop", "dssat"]
    plain = G.publish(cells, {}, members, bench, {"model_label": "SEAS5"}, var, ["fao-agricultural"], ["X"], {}, {},
                      tmp_path / "h.json")
    assert plain["meta"]["models"] == ["aquacrop"] and "cells_dssat" not in plain


def test_the_bulletin_reports_the_weakest_agreement():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    try:
        bc = pytest.importorskip("bulletin_crop")
    finally:
        sys.path.pop(0)
    a = {"yield_if_sown_t_ha": {"median": 2.0}, "p_failure_if_sown": 0.2}
    same = {"yield_if_sown_t_ha": {"median": 2.0}, "p_failure_if_sown": 0.2}
    far = {"yield_if_sown_t_ha": {"median": 2.0 + 3 * bc.AGREE_T}, "p_failure_if_sown": 0.2}
    assert bc.agreement_all(a, [same, None]) == "agree"
    assert bc.agreement_all(a, [same, far]) == "differ"
    assert bc.agreement_all(a, [None, None]) is None
