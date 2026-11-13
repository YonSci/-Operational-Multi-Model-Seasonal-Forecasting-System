"""Analogues, end-of-season review, guided learning, scenario planning and official outlook comparison."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import extras as X, narrate  # noqa: E402

LATEST = "ECMWF SEAS5 (Oct+Obs latest)"
KIBOKO = (-2.21046, 37.7190)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    yield


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()


def test_analogues_are_past_observed_seasons_ranked_by_similarity():
    rec = X.analogues(*KIBOKO, "short_rains", LATEST)
    yrs = [a["year"] for a in rec["analogues"]]
    assert len(yrs) == 5 and len(set(yrs)) == 5 and all(1993 <= y <= 2025 for y in yrs)
    assert [a["similarity_rank"] for a in rec["analogues"]] == [1, 2, 3, 4, 5]
    assert any("not probabilities" in c for c in rec["caveats"])


def test_season_review_compares_hindcast_and_observation():
    rec = X.season_review(*KIBOKO, "short_rains", LATEST, years=5)
    assert len(rec["seasons"]) <= 5 and rec["seasons"][0]["year"] > rec["seasons"][-1]["year"]
    for r in rec["seasons"]:
        assert r["observed_third"] in ("early", "normal", "late")
        if r["forecast_most_likely"]:
            assert r["most_likely_was_right"] == (r["forecast_most_likely"] == r["observed_third"])
    assert rec["summary"]["most_likely_right"] <= rec["summary"]["seasons"]


def test_lessons_use_this_forecast():
    rec = X.lessons(*KIBOKO, "short_rains", LATEST)
    ids = [l["id"] for l in rec["lessons"]]
    assert {"chances", "median_range", "methods"} <= set(ids)
    for l in rec["lessons"]:
        q = l["question"]
        assert 0 <= q["answer"] < len(q["options"]) and l["example"]


def test_scenario_plan():
    rec = X.scenario_plan(*KIBOKO, "short_rains", LATEST, crop="maize_early")
    assert {o["outcome"] for o in rec["outcomes"] if o["quantity"] == "Onset"} == {"early", "normal", "late"}
    g = rec["crop_by_rain"]
    assert [x["group"] for x in g] == ["drier third of the members", "middle third", "wetter third"]
    assert g[0]["season_rain_mm"][1] <= g[2]["season_rain_mm"][0]
    assert len(rec["discussion_questions"]) >= 4


def test_official_outlook_upload_and_compare():
    with pytest.raises(ValueError):
        X.upload({"source": "x", "season": "short_rains", "year": 2026, "regions": [{"name": "Makueni", "below": 50, "normal": 50, "above": 50}]})
    up = X.upload({"source": "ICPAC GHACOF", "season": "short_rains", "year": 2026, "variable": "rainfall",
                   "regions": [{"name": "Makueni", "below": 20, "normal": 35, "above": 45}, {"name": "Nowhere", "below": 30, "normal": 40, "above": 30}],
                   "geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "box", "below": 0.5, "normal": 0.3, "above": 0.2},
                               "geometry": {"type": "Polygon", "coordinates": [[[37, -3], [38.5, -3], [38.5, -1.5], [37, -1.5], [37, -3]]]}}]}})
    rec = X.compare_official(up["id"], LATEST)
    names = [r["area"] for r in rec["rows"]]
    assert names == ["Makueni", "box"]                         # an unknown name is left out
    assert rec["rows"][0]["official_most_likely"] == "above" and rec["rows"][1]["official_most_likely"] == "below"
    assert rec["summary"]["comparable"] <= rec["summary"]["areas"]
    out = narrate.explain("outlook_comparison", rec)
    assert narrate.check_numbers(out["sections"], rec) == []
    assert X.outlooks("short_rains")[0]["source"] == "ICPAC GHACOF"


def test_templates_pass_the_number_check():
    for kind, rec in (("analogues", X.analogues(*KIBOKO, "short_rains", LATEST)),
                      ("season_review", X.season_review(*KIBOKO, "short_rains", LATEST))):
        assert narrate.check_numbers(narrate.explain(kind, rec)["sections"], rec) == [], kind


def test_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("ASSISTANT_ADMIN_TOKEN", "tk")
    p = {"lat": KIBOKO[0], "lon": KIBOKO[1], "model": LATEST}
    with TestClient(main.app) as c:
        assert c.get("/extras/analogues", params=p).json()["evidence"]["kind"] == "analogues"
        assert c.get("/extras/season-review", params={**p, "years": 3}).json()["evidence"]["summary"]["seasons"] <= 3
        assert c.get("/extras/lessons", params=p).json()["lessons"]
        assert c.get("/extras/scenario-plan", params=p).json()["kind"] == "scenario_plan"
        body = {"source": "KMD", "season": "short_rains", "year": 2026, "regions": [{"name": "Kitui", "below": 30, "normal": 30, "above": 40}]}
        assert c.post("/extras/outlooks", json=body).status_code == 401
        up = c.post("/extras/outlooks", json=body, headers={"X-Admin-Token": "tk"}).json()
        assert c.get("/extras/outlooks").json()["outlooks"]
        r = c.get(f"/extras/outlooks/{up['id']}/compare", params={"model": LATEST})
        assert r.status_code == 200 and r.json()["evidence"]["rows"][0]["area"] == "Kitui"
