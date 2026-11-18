"""Field reports: validation, storage (local and the Supabase request shapes), counts near a place, review, the
location evidence that shows them, and the /feedback endpoints."""
import base64
import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import evidence as ev, feedback, narrate, store  # noqa: E402

KIBOKO = (-2.21046, 37.7190)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()
    feedback._rate.by.clear()


def sowing(**kw):
    r = {"report_type": "sowing", "lat": KIBOKO[0] + 0.05, "lon": KIBOKO[1], "crop": "maize_early", "reporter_role": "farmer",
         "payload": {"sown_on": "2026-11-02", "area_ha": 0.8}}
    r.update(kw)
    return r


def test_validation():
    with pytest.raises(ValueError, match="report_type"):
        feedback.validate({"report_type": "gossip", "lat": 0, "lon": 37})
    with pytest.raises(ValueError, match="sown_on is required"):
        feedback.validate(sowing(payload={}))
    with pytest.raises(ValueError, match="between"):
        feedback.validate({"report_type": "rainfall", "lat": -1, "lon": 37, "payload": {"observed_on": "2026-11-01", "rain_mm": 900, "measured_by": "rain gauge"}})
    with pytest.raises(ValueError, match="outside"):
        feedback.validate(sowing(lat=40.0, lon=-3.0))
    tomorrow2 = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    with pytest.raises(ValueError, match="out of range"):
        feedback.validate(sowing(payload={"sown_on": tomorrow2}))
    row = feedback.validate(sowing(reporter_contact="0700 000000"))
    assert row["reporter_contact"] is None                     # no consent, no contact kept
    assert feedback.validate(sowing(reporter_contact="0700 000000", consent=True))["reporter_contact"] == "0700 000000"


def test_submit_nearby_and_review():
    a = feedback.submit(sowing())
    feedback.submit(sowing(payload={"sown_on": "2026-10-30"}))
    feedback.submit({"report_type": "rainfall", "lat": KIBOKO[0], "lon": KIBOKO[1], "reporter_role": "extension",
                     "payload": {"observed_on": "2026-11-05", "rain_mm": 23, "measured_by": "rain gauge"}})
    feedback.submit(sowing(lat=0.5, lon=35.0))                  # far away
    assert a["verification"] == "unverified" and a["storage"]["permanent"] is False
    near = feedback.nearby(*KIBOKO)
    assert near["reports"] == 3 and near["by_type"]["sowing"]["reports"] == 2
    assert near["sowing_dates_reported"] == {"earliest": "2026-10-30", "latest": "2026-11-02", "reports": 2}
    assert "reporter_contact" not in json.dumps(near)
    feedback.review(a["id"], "verified", "KALRO reviewer")
    assert feedback.nearby(*KIBOKO)["by_type"]["sowing"]["verified"] == 1
    feedback.review(a["id"], "rejected", "KALRO reviewer", "duplicate")
    assert feedback.nearby(*KIBOKO)["by_type"]["sowing"]["reports"] == 1   # rejected reports are left out
    rows = feedback.for_review("rejected")
    assert len(rows) == 1 and rows[0]["evidence_kind"] == "farmer's observation"


def test_location_evidence_shows_reports_and_passes_the_check():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    feedback.submit(sowing())
    rec = ev.location(*KIBOKO, "short_rains", "ECMWF SEAS5 (Oct+Obs latest)")
    assert rec["field_reports_nearby"]["reports"] == 1
    out = narrate.explain("location", rec)
    assert any("Field reports within" in x for x in out["sections"]["local_implications"])
    assert narrate.check_numbers(out["sections"], rec) == []
    assert any("unverified" in c for c in rec["caveats"])


def test_supabase_request_shapes(monkeypatch):
    calls = []

    def fake(method, path, body=None, headers=None, raw=None, content_type="application/json"):
        calls.append((method, path, body, headers, content_type))
        return [dict(body or {}, id="x1")] if method == "POST" and path.startswith("/rest") else [{"id": "x1"}]
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(store, "_req", fake)
    assert store.status()["permanent"] is True
    store.insert("field_reports", {"report_type": "sowing"})
    store.select("field_reports", eq={"verification": "verified"}, limit=5)
    store.update("field_reports", "x1", {"verification": "verified"})
    store.upload("field-photos", "2026/11/a.png", PNG, "image/png")
    assert calls[0][0] == "POST" and calls[0][1] == "/rest/v1/field_reports" and calls[0][3]["Prefer"] == "return=representation"
    assert calls[1][1].startswith("/rest/v1/field_reports?verification=eq.verified&order=created_at.desc&limit=5")
    assert calls[2][0] == "PATCH" and calls[2][1] == "/rest/v1/field_reports?id=eq.x1"
    assert calls[3][1] == "/storage/v1/object/field-photos/2026/11/a.png" and calls[3][4] == "image/png"


def test_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("ASSISTANT_ADMIN_TOKEN", "secret-token")
    with TestClient(main.app) as c:
        st = c.get("/feedback/status").json()
        assert "sowing" in st["types"] and st["review_enabled"] is True
        r = c.post("/feedback/report", data={"report": json.dumps(sowing())}, files={"photo": ("p.png", PNG, "image/png")})
        assert r.status_code == 200 and r.json()["photo_described"] is False      # no Claude key in tests
        assert c.post("/feedback/report", data={"report": "{not json"}).status_code == 400
        assert c.post("/feedback/report", data={"report": json.dumps(sowing())}, files={"photo": ("p.gif", b"GIF89a", "image/gif")}).status_code == 400
        n = c.get("/feedback/nearby", params={"lat": KIBOKO[0], "lon": KIBOKO[1]}).json()
        assert n["reports"] == 1
        assert c.get("/feedback/reports").status_code == 401
        assert c.get("/feedback/reports", headers={"X-Admin-Token": "wrong"}).status_code == 401
        rows = c.get("/feedback/reports", headers={"X-Admin-Token": "secret-token"}).json()["reports"]
        assert rows and rows[0]["photo_path"]
        rid = rows[0]["id"]
        r = c.post(f"/feedback/reports/{rid}/review", json={"verification": "verified", "reviewer": "me"}, headers={"X-Admin-Token": "secret-token"})
        assert r.status_code == 200
        monkeypatch.setenv("FEEDBACK_PER_IP_PER_HOUR", "0")
        assert c.post("/feedback/report", data={"report": json.dumps(sowing())}).status_code == 429
