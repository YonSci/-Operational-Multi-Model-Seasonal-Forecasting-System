"""Area summaries (county / region / drawn rectangle), areas needing attention, and chart explanations."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import areas, charts, chat, narrate  # noqa: E402

LATEST = "ECMWF SEAS5 (Oct+Obs latest)"
KIBOKO = (-2.21046, 37.7190)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    if not areas.regions("Kenya"):
        pytest.skip("boundaries not available")
    yield


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()


def test_counties_hold_the_grid_cells():
    M = dl.get_state()["MODELS"][LATEST]
    idx, names = areas.region_index(np.asarray(M["target_lat"]), np.asarray(M["target_lon"]), "Kenya")
    assert len(names) == 47 and "Makueni" in names
    land = np.asarray(M["lm"]).astype(bool)
    assert (idx[land] >= 0).mean() > 0.9                     # nearly every land cell is in a county


def test_area_event_chances_are_member_counts():
    rec = areas.area("short_rains", LATEST, name="makueni")      # names match case-insensitively
    on = rec["quantities"]["onset"]
    assert rec["scope"]["name"] == "Makueni" and rec["scope"]["cells"] > 0
    ev_ch = on["area_event_chances_pct"]
    n = 25
    assert all(abs(v * n / 100 - round(v * n / 100)) < 0.05 * n for v in ev_ch.values())   # whole members
    assert sum(ev_ch.values()) <= 100
    assert set(on["average_cell_chances_pct"]) == {"early", "normal", "late"}


def test_drawn_rectangle_and_errors():
    rec = areas.area("short_rains", LATEST, bbox=[37.0, -3.0, 38.5, -1.5])
    assert rec["scope"]["type"] == "drawn area" and rec["scope"]["cells"] > 10
    with pytest.raises(ValueError):
        areas.area("short_rains", LATEST, name="Atlantis")
    with pytest.raises(ValueError):
        areas.area("short_rains", LATEST, bbox=[10, 10, 10.1, 10.1])     # no cells


def test_attention_ranks_by_share_of_cells():
    rec = areas.attention("short_rains", LATEST, "season_shorter")
    pcts = [r["flagged_pct"] for r in rec["ranked_areas"]]
    assert pcts == sorted(pcts, reverse=True)
    assert all(c["value"] < -7 for c in rec["top_cells"])
    with pytest.raises(ValueError):
        areas.attention("short_rains", LATEST, "nonsense")


def test_charts():
    md = charts.chart("member_dates", *KIBOKO, "short_rains", LATEST, quantity="onset")
    assert sum(b["members"] for b in md["members_by_week"]) == md["members_with_value"]
    co = charts.chart("crop_outcomes", *KIBOKO, "short_rains", LATEST, crop="sorghum")
    assert co["crop"] == "Sorghum" and sum(co["outcomes"].values()) == co["members"]
    rp = charts.chart("rain_plume", *KIBOKO, "short_rains", LATEST)
    assert rp["illustrative"] is True and "season_total_mm" not in rp      # no daily members on this server


def test_templates_pass_the_number_check():
    for kind, rec in (("area", areas.area("short_rains", LATEST, name="Kitui")),
                      ("attention", areas.attention("short_rains", LATEST, "late_onset")),
                      ("chart", charts.chart("member_dates", *KIBOKO, "short_rains", LATEST, quantity="lgp")),
                      ("chart", charts.chart("crop_outcomes", *KIBOKO, "short_rains", LATEST)),
                      ("chart", charts.chart("rain_plume", *KIBOKO, "short_rains", LATEST))):
        out = narrate.explain(kind, rec)
        assert narrate.check_numbers(out["sections"], rec) == [], (kind, rec.get("chart"))


def test_chat_tools_for_areas_and_charts():
    s = chat.Session({"lat": KIBOKO[0], "lon": KIBOKO[1], "season": "short_rains", "model": LATEST})
    assert s.run("explain_area", {"name": "Machakos"})["kind"] == "area"
    assert s.run("find_attention_areas", {"criterion": "late_onset"})["kind"] == "attention"
    assert s.run("explain_chart", {"chart": "member_dates", "quantity": "onset", "crop": "maize_early"})["kind"] == "chart"


def test_endpoints():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        r = c.get("/explain/regions", params={"season": "short_rains"})
        assert r.status_code == 200 and "Makueni" in r.json()["names"]
        assert c.get("/explain/regions", params={"season": "kiremt"}).json()["kind"] == "region"
        r = c.get("/explain/area", params={"season": "short_rains", "model": LATEST, "bbox": "37,-3,38.5,-1.5"})
        assert r.status_code == 200 and r.json()["evidence"]["kind"] == "area"
        assert c.get("/explain/area", params={"season": "short_rains", "model": LATEST}).status_code == 400
        r = c.get("/explain/attention", params={"season": "short_rains", "model": LATEST, "criterion": "short_season"})
        assert r.status_code == 200
        r = c.get("/explain/chart", params={"chart": "member_dates", "lat": KIBOKO[0], "lon": KIBOKO[1], "model": LATEST})
        assert r.status_code == 200 and r.json()["evidence"]["chart"] == "member_dates"
