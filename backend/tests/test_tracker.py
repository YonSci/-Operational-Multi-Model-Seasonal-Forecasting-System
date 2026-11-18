"""The assistant on the near real-time rainfall tracking page: evidence from the page's published data, the
standard explanations (number check), the chat's routing, tracking watches and the endpoints. The data changes
daily, so the tests check structure and consistency, not values."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import chat, narrate, tracker, watches  # noqa: E402

SITES = [s["name"] for s in tracker.sites()]


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    yield


@pytest.fixture(autouse=True)
def no_claude(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()


def test_sites_and_matching():
    assert len(SITES) >= 5
    assert tracker.find_site("Kiboko")["site"].startswith("KALRO Kiboko")
    assert tracker.find_site("kapiti")["site"] == "Kapiti Research Station Farm"
    s = tracker.sites()[0]
    assert tracker.find_site(None, s["lat"] + 0.05, s["lon"])["site"] == s["name"]       # nearest, ~5 km
    with pytest.raises(ValueError, match="covers these sites only"):
        tracker.find_site("Addis Ababa", 9.0, 38.7)


@pytest.mark.parametrize("site", SITES)
def test_status_record_is_consistent(site):
    rec = tracker.status(site)
    r = rec["rain_so_far"]
    assert rec["kind"] == "tracker" and rec["scope"]["site"] == site and len(rec["id"]) == 16
    assert 0 <= r["products_with_planting_onset"] <= r["products"]
    if r["other_products"]:
        lo, hi = r["other_products_range_mm"]
        assert lo == min(o["mm"] for o in r["other_products"]) and hi == max(o["mm"] for o in r["other_products"])
    for p in rec["recent_rain"]["by_product"]:
        if p["last_wet_day"]:
            assert p["days_since_last_wet_day"] == (dt.date.fromisoformat(p["through"]) - dt.date.fromisoformat(p["last_wet_day"])).days >= 0
    w = rec["weather_models"]
    if w:
        assert w["total_range_mm"][0] <= w["median_total_mm"] <= w["total_range_mm"][1]
        assert 0 <= w["models_with_planting_rain_within_7_days"] <= w["models"] == len(w["by_model"])
    for q in rec["seasonal_outlook"]["quantities"].values():
        vals = [v for v in q["chances_pct"].values() if v is not None]
        assert not vals or 97 <= sum(vals) <= 103
    sec = narrate.TEMPLATES["tracker"](rec)
    assert narrate.check_numbers(sec, rec) == []
    assert any("rain gauge" in c for c in sec["cautions"])


def test_disagreeing_products_are_flagged():
    rec = tracker.status(SITES[0])
    r = rec["rain_so_far"]
    rec2 = {**rec, "rain_so_far": {**r, "chirps_mm": 10.0, "other_products_range_mm": [5.0, 200.0]}}
    assert any("disagree" in c for c in tracker._caveats(rec2))
    rec3 = {**rec, "rain_so_far": {**r, "chirps_mm": 100.0, "other_products_range_mm": [95.0, 110.0]}}
    assert not any("disagree" in c for c in tracker._caveats(rec3))


def test_changes_between_runs():
    rec = tracker.changes("Kapiti")
    assert rec["runs"]["previous"] < rec["runs"]["latest"]
    for m in rec["weather_models"]:
        assert m["change_mm"] == round(m["latest_run_mm"] - m["previous_run_mm"], 1)
        assert m["days"][0] <= m["days"][1] and m["n_days"] == (dt.date.fromisoformat(m["days"][1]) - dt.date.fromisoformat(m["days"][0])).days + 1
    sm = rec["summary"]
    assert set(sm["wetter_by_5mm_or_more"]).isdisjoint(sm["drier_by_5mm_or_more"])
    sec = narrate.TEMPLATES["tracker_changes"](rec)
    assert narrate.check_numbers(sec, rec) == []


def test_chat_routes_to_the_tracker():
    assert chat.route("anything at all", page="tracker") == "tracker"
    assert chat.route("what changed since yesterday?", page="tracker") == "tracker_changes"
    assert chat.route("How much rain so far?") == "tracker"
    assert chat.route("Will planting rains come in the next 7 days?") == "tracker"
    assert chat.route("When will the rains start?") == "location"
    out = chat.reply([{"role": "user", "content": "Has it rained here?"}], {"page": "tracker", "tracker_site": "Kapiti Research Station Farm"})
    assert out["source"] == "template" and out["evidence"][0]["kind"] == "tracker" and "Kapiti" in out["reply"]
    s = chat.Session({"page": "tracker"})
    assert "error" in s.run("get_rain_tracking", {"site": None})       # no site on screen and no place: a clear error


def test_tracking_watch_triggers():
    w = {"thresholds": {"dry_days": 10}}
    base = {"products_with_planting_onset": 3, "products": 8, "days_since_last_wet_day": 4, "next_days_median_mm": 30.0,
            "ensemble_planting_rain_7_days_pct": 40, "observations_through": dt.date.today().isoformat()}
    now = {**base, "products_with_planting_onset": 5, "days_since_last_wet_day": 11, "last_wet_day": "2026-11-01",
           "next_days_median_mm": 50.0, "next_days_window": 7, "ensemble_planting_rain_7_days_pct": 70}
    kinds = [c["kind"] for c in watches.tracker_compare(w, base, now)]
    assert kinds == ["onset_detected", "dry_spell", "outlook_changed", "outlook_changed"]
    assert watches.tracker_verdict(watches.tracker_compare(w, base, now))["status"] == "onset_detected"
    assert watches.tracker_compare(w, base, base) == [] and watches.tracker_verdict([])["status"] == "unchanged"
    late = {**base, "observations_through": (dt.date.today() - dt.timedelta(days=9)).isoformat()}
    assert watches.tracker_verdict(watches.tracker_compare(w, late, late))["status"] == "needs_review"


def test_tracking_watch_round_trip():
    s = tracker.sites()[1]
    made = watches.create({"lat": s["lat"], "lon": s["lon"], "place_name": "", "model": "tracker", "decision": "rain_tracking",
                           "thresholds": {"dry_days": 7, "not_a_threshold": 1}})
    got = watches.check(made["id"], made["key"])
    assert got["watch"]["place_name"] == s["name"] and got["watch"]["crop"] is None
    assert got["current"]["site"] == s["name"] and got["status"] in ("unchanged", "needs_review")
    watches.remove(made["id"], made["key"])


def test_endpoints():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        assert len(c.get("/explain/tracker/sites").json()["sites"]) == len(SITES)
        j = c.get("/explain/tracker", params={"site": "Kiboko"}).json()
        assert j["kind"] == "tracker" and j["explanation"]["source"] == "template" and j["explanation"]["sections"]["summary"]
        j = c.get("/explain/tracker/changes", params={"site": "Kiboko"}).json()
        assert j["kind"] == "tracker_changes"
        assert c.get("/explain/tracker", params={"site": "Nowhere"}).status_code == 404
        r = c.post("/watches", json={"lat": 0.0, "lon": 0.0, "model": "tracker", "decision": "rain_tracking"})
        assert r.status_code == 400                                      # far from every tracking site
