"""Watches ("Did the advice change?") and the decision calendar."""
import copy
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import feedback, narrate, store, watches  # noqa: E402

LATEST = "ECMWF SEAS5 (Oct+Obs latest)"
KIBOKO = (-2.21046, 37.7190)
SPEC = {"lat": KIBOKO[0], "lon": KIBOKO[1], "place_name": "Kiboko", "season": "short_rains", "model": LATEST,
        "crop": "maize_early", "planted": "no"}


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


def test_new_watch_is_unchanged_and_needs_its_key():
    w = watches.create(SPEC)
    r = watches.check(w["id"], w["key"])
    assert r["status"] == "unchanged" and r["changes"] == []
    assert r["watch"]["decision"] == "sowing"
    with pytest.raises(PermissionError):
        watches.check(w["id"], "not-the-key")
    row = store.select(watches.TABLE, eq={"id": w["id"]})[0]
    assert "key" not in row and row["key_hash"] != w["key"]           # only the hash is kept


def test_changes_are_classified():
    w = watches.create(SPEC)
    row = store.select(watches.TABLE, eq={"id": w["id"]})[0]
    base = copy.deepcopy(row["baseline"])
    on = base["onset"]
    first = next(iter(on["chances_pct"]))
    on["chances_pct"][first] = max(0, on["chances_pct"][first] - 40)          # the chance moved by 40 points
    base["onset"]["status"] = "forecast"                                       # then the onset was observed
    store.update(watches.TABLE, w["id"], {"baseline": base})
    r = watches.check(w["id"], w["key"])
    kinds = {c["kind"] for c in r["changes"]}
    assert "forecast_changed" in kinds
    if r["current"]["onset"]["status"] == "estimated_from_observations":
        assert "status_changed" in kinds
    assert r["status"] in ("forecast_changed", "advice_changed")
    base["advice"]["best"] = "Something else"
    store.update(watches.TABLE, w["id"], {"baseline": base})
    r = watches.check(w["id"], w["key"])
    assert r["status"] == "advice_changed" and any(c["kind"] == "options_changed" for c in r["changes"])
    watches.acknowledge(w["id"], w["key"])
    assert watches.check(w["id"], w["key"])["status"] == "unchanged"


def test_reported_sowing_moves_the_stage():
    w = watches.create(SPEC)
    feedback.submit({"report_type": "sowing", "lat": KIBOKO[0], "lon": KIBOKO[1] + 0.02, "reporter_role": "farmer",
                     "payload": {"sown_on": dt.date.today().isoformat()}})
    r = watches.check(w["id"], w["key"])
    assert r["status"] == "advice_changed" and any(c["kind"] == "stage_changed" for c in r["changes"])
    watches.edit(w["id"], w["key"], {"planted": "yes", "decision": "establishment", "sowing_date": dt.date.today().isoformat()})
    r = watches.check(w["id"], w["key"])
    assert r["watch"]["decision"] == "establishment" and not any(c["kind"] == "stage_changed" for c in r["changes"])


def test_thresholds_and_delete():
    w = watches.create({**SPEC, "thresholds": {"stale_days": 1, "nonsense": 3}})
    row = store.select(watches.TABLE, eq={"id": w["id"]})[0]
    assert row["thresholds"] == {"stale_days": 1.0}
    r = watches.check(w["id"], w["key"])
    if r["current"]["observations_through"]:
        assert any(c["kind"] == "stale" for c in r["changes"]) and r["status"] == "needs_review"
    watches.remove(w["id"], w["key"])
    with pytest.raises(PermissionError):
        watches.check(w["id"], w["key"])


def test_calendar():
    cal = watches.calendar(*KIBOKO, "short_rains", LATEST, crop="sorghum")
    dated = [e for e in cal["events"] if e["date"]]
    assert [e["date"] for e in dated] == sorted(e["date"] for e in dated)
    whats = " ".join(e["what"] for e in cal["events"])
    assert "Onset" in whats and "End of the rains" in whats and "Next forecast update" in whats
    assert any("Harvest" in e["what"] for e in cal["events"])
    sown = watches.calendar(*KIBOKO, "short_rains", LATEST, crop="sorghum", planted="yes", sowing_date="2026-11-02")
    assert any(e["what"] == "Your sowing" and e["date"] == "2026-11-02" for e in sown["events"])


def test_endpoints():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        w = c.post("/watches", json=SPEC).json()
        assert w["key"] and w["storage"]["permanent"] is False
        assert c.get(f"/watches/{w['id']}", headers={"X-Watch-Key": w["key"]}).json()["status"] == "unchanged"
        assert c.get(f"/watches/{w['id']}", headers={"X-Watch-Key": "x"}).status_code == 404
        assert c.post(f"/watches/{w['id']}/acknowledge", headers={"X-Watch-Key": w["key"]}).status_code == 200
        assert c.post(f"/watches/{w['id']}/edit", json={"patch": {"crop": "bean"}}, headers={"X-Watch-Key": w["key"]}).status_code == 200
        cal = c.get("/watches/calendar/for", params={"lat": KIBOKO[0], "lon": KIBOKO[1], "model": LATEST}).json()
        assert cal["kind"] == "calendar" and cal["events"]
        assert c.delete(f"/watches/{w['id']}", headers={"X-Watch-Key": w["key"]}).status_code == 200
