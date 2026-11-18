"""Bulletin Studio: snapshots per format, composition, the quality check, exports and saved versions."""
import copy
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import bulletins as B, narrate  # noqa: E402

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


def _snap(fmt):
    kw = {"place": dict(lat=KIBOKO[0], lon=KIBOKO[1]), "area": dict(area_name="Makueni"), "sites": {}}[B.FORMATS[fmt]["scope"]]
    return B.snapshot(fmt, "short_rains", LATEST, **kw)


@pytest.mark.parametrize("fmt", list(B.FORMATS))
def test_every_format_composes_cleanly(fmt):
    s = _snap(fmt)
    b = B.compose(s, length="detailed")
    assert b["source"] == "template" and set(b["sections"]) == {k for k, _ in B.SECTIONS}
    assert all(b["sections"][k] for k, _ in B.SECTIONS)
    assert len(b["sms"]) <= 300 and b["audio_script"]
    assert B.check(b, s) == [], fmt


def test_snapshot_contents_and_errors():
    s = _snap("site_update")
    assert {"place", "changes", "advisory"} <= set(s["records"]) and s["id"]
    assert set(_snap("regional")["records"]) == {"area", "attention_onset", "attention_season"}
    assert len([k for k in _snap("multi_site")["records"] if k.startswith("site:")]) >= 5
    with pytest.raises(ValueError):
        B.snapshot("site_update", "short_rains", LATEST)                 # no place
    with pytest.raises(ValueError):
        B.snapshot("poster", "short_rains", LATEST, lat=0, lon=37)
    # a method served for the latest run only has no earlier run to compare with
    fao = B.snapshot("site_update", "short_rains", LATEST + " - FAO water balance (agricultural)", lat=KIBOKO[0], lon=KIBOKO[1])
    assert "changes" not in fao["records"]


def test_quality_check_catches_edits():
    s = _snap("crop_advisory")
    b = B.compose(s)
    bad = copy.deepcopy(b)
    bad["sections"]["forecast"].append("Rain will start on 17 Nov with 93.5% certainty.")
    bad["sections"]["options"] = ["Plant sorghum now."]
    bad["sections"]["evidence"] = [x for x in bad["sections"]["evidence"] if "xperimental" not in x]
    bad["sms"] = "x" * 400
    kinds = {i["kind"] for i in B.check(bad, s)}
    assert {"unsupported_number", "certainty", "missing_label", "too_long"} <= kinds
    bad["sections"]["monitor"] = []
    assert "empty" in {i["kind"] for i in B.check(bad, s)}


def test_exports():
    s = _snap("site_update")
    b = B.compose(s)
    md = B.markdown(b)
    assert md.startswith("# ") and "## What is forecast" in md
    pytest.importorskip("docx")
    from docx import Document
    doc = Document(io.BytesIO(B.docx_bytes(b)))
    assert doc.paragraphs[0].text == b["title"]


def test_versions_and_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("ASSISTANT_ADMIN_TOKEN", "t0k")
    with TestClient(main.app) as c:
        assert "regional" in c.get("/studio/formats").json()["formats"]
        r = c.post("/studio/compose", json={"format": "site_update", "model": LATEST, "lat": KIBOKO[0], "lon": KIBOKO[1], "length": "short"})
        assert r.status_code == 200
        j = r.json()
        assert j["quality"] == [] and j["bulletin"]["title"].startswith("Site update")
        assert c.post("/studio/compose", json={"format": "regional", "model": LATEST}).status_code == 400
        body = {"bulletin": j["bulletin"], "snapshot": j["snapshot"]}
        assert c.post("/studio/check", json=body).json()["quality"] == []
        d = c.post("/studio/export?fmt=docx", json=body)
        if d.status_code == 200:
            assert d.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert c.post("/studio/export?fmt=md", json=body).text.startswith("# ")
        assert c.post("/studio/save", json=body).status_code == 401
        h = {"X-Admin-Token": "t0k"}
        v1 = c.post("/studio/save", json=body, headers=h).json()
        v2 = c.post("/studio/save", json={**body, "parent_id": v1["id"], "status": "published"}, headers=h).json()
        assert (v1["version"], v2["version"]) == (1, 2)
        broken = {**body, "bulletin": {**j["bulletin"], "sms": "Onset on 3 Dec at 87.5%"}}
        assert c.post("/studio/save", json={**broken, "status": "published"}, headers=h).status_code == 400
        assert [b["id"] for b in c.get("/studio/published").json()["bulletins"]] == [v2["id"]]
        assert c.get(f"/studio/saved/{v2['id']}").status_code == 200            # published: open to all
        assert c.get(f"/studio/saved/{v1['id']}").status_code == 401            # a draft needs the token
        assert len(c.get("/studio/saved", headers=h).json()["bulletins"]) == 2
