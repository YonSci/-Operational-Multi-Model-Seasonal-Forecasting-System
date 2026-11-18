"""Forecast assistant: evidence records, template explanations, number checks and the /explain endpoints.

Runs on the demo dataset the backend ships with (about 5 s to load). Claude is never called: the LLM path is tested
with a stub client.
"""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import evidence as ev, narrate  # noqa: E402

KIBOKO = (-2.21046, 37.7190)
LATEST = "ECMWF SEAS5 (Oct+Obs latest)"
OCT = "ECMWF SEAS5 (Oct)"


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


def test_location_record_has_the_dashboard_figures():
    rec = ev.location(*KIBOKO, "short_rains", LATEST)
    px = dl.get_pixel_stats(*KIBOKO, season="short_rains", model=LATEST)
    m = px["models"][LATEST]
    on = rec["quantities"]["onset"]
    assert rec["scope"]["site"]["name"].startswith("KALRO Kiboko")
    assert rec["run"]["initialised"] == "2026-10-01"
    assert on["median"] == ev._date(m["on_med"], 2026)
    # chances are the pixel's skill-weighted ones, as percent, and sum to about 100
    assert on["chances_pct"]["early"] == round(m["p_on"][0] * 100)
    assert 98 <= sum(on["chances_pct"].values()) <= 102
    assert on["status"] in ("forecast", "partly_observed", "estimated_from_observations")
    assert rec["id"] == ev.record_id(rec)


def test_status_follows_the_observation_cutoff():
    rec = ev.location(*KIBOKO, "short_rains", LATEST)
    on = rec["quantities"]["onset"]
    obs = rec["run"]["observations_through"]
    if on["range_80"][1] and obs and on["range_80"][1] <= obs:
        assert on["status"] == "estimated_from_observations"
    early = ev.location(*KIBOKO, "short_rains", OCT)
    assert early["run"]["observations_through"] in (None, "")  or early["quantities"]["onset"]["status"]


def test_method_is_read_from_the_model_name():
    rec = ev.location(*KIBOKO, "short_rains", LATEST + " - Agri rule 1")
    assert rec["run"]["method"]["label"] == "Agri rule 1"
    assert ev.location(*KIBOKO, "short_rains", LATEST)["run"]["method"]["id"] == "dunning"


def test_changes_lists_documented_inputs_and_shifts():
    rec = ev.changes(*KIBOKO, "short_rains", LATEST, OCT)
    whats = {c["what"] for c in rec["input_changes"]}
    assert "observations through" in whats
    assert rec["same_event_definition"] is True
    d = rec["differences"]["onset"]
    if d["from_median"] and d["to_median"]:
        assert d["median_shift_days"] == ev._shift(d["from_median"], d["to_median"])
    other = ev.changes(*KIBOKO, "short_rains", LATEST + " - Agri rule 1", LATEST)
    assert other["same_event_definition"] is False
    assert any("different events" in c for c in other["caveats"])


def test_map_record_summarises_the_grid():
    rec = ev.map_layer("onset", "prob_bn", LATEST, "short_rains")
    assert rec["cells"]["with_values"] > 0
    assert set(rec["shares_pct"]) == {"chance 50% or more", "chance 40% or more", "chance below 20%"}
    assert rec["layer"]["misreading_to_avoid"]
    med = ev.map_layer("onset", "median", LATEST, "short_rains")
    assert med["distribution"]["median"].startswith("2026-")


def test_template_explanations_pass_their_own_number_check():
    for kind, rec in (("location", ev.location(*KIBOKO, "short_rains", LATEST)),
                      ("changes", ev.changes(*KIBOKO, "short_rains", LATEST, OCT)),
                      ("map", ev.map_layer("onset", "anomaly", LATEST, "short_rains"))):
        out = narrate.explain(kind, rec)
        assert out["source"] == "template"
        assert narrate.check_numbers(out["sections"], rec) == [], kind


def test_number_check_flags_invented_figures():
    rec = ev.location(*KIBOKO, "short_rains", LATEST)
    p = rec["quantities"]["onset"]["chances_pct"]["early"]
    ok = {"summary": [f"The chance of an early onset is {p}%."], "local_implications": [], "cautions": []}
    bad = {"summary": ["The chance of an early onset is 87.3%."], "local_implications": [], "cautions": []}
    assert narrate.check_numbers(ok, rec) == []
    assert "87.3" in narrate.check_numbers(bad, rec)


def _stub_client(text, stop="end_turn"):
    msg = types.SimpleNamespace(stop_reason=stop, model="claude-opus-5-5",
                                content=[types.SimpleNamespace(type="text", text=text)])
    calls = []

    def create(**kw):
        calls.append(kw)
        return msg
    client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create)),
                                   messages=types.SimpleNamespace(create=create))
    return client, calls


def test_claude_text_is_used_when_its_numbers_check_out(monkeypatch):
    pytest.importorskip("anthropic")
    rec = ev.location(*KIBOKO, "short_rains", LATEST)
    p = rec["quantities"]["onset"]["chances_pct"]["early"]
    body = {"summary": [f"An early start has a {p}% chance."], "local_implications": ["x"], "cautions": ["y"]}
    client, calls = _stub_client(json.dumps(body))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(narrate, "_get_client", lambda: client)
    out = narrate.explain("location", rec, "farmer")
    assert out["source"] == "claude" and out["sections"] == body
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "farmer" in kw["messages"][0]["content"]


def test_claude_text_with_invented_numbers_falls_back(monkeypatch):
    pytest.importorskip("anthropic")
    rec = ev.location(*KIBOKO, "short_rains", LATEST)
    body = {"summary": ["Rain will start on 17 Nov with 93.5% certainty."], "local_implications": [], "cautions": []}
    client, _ = _stub_client(json.dumps(body))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(narrate, "_get_client", lambda: client)
    out = narrate.explain("location", rec)
    assert out["source"] == "template"
    assert out["checks"]["numbers_supported"] is False and "93.5" in out["checks"]["unsupported_numbers"]


def test_refusal_and_call_cap_fall_back(monkeypatch):
    pytest.importorskip("anthropic")
    rec = ev.location(*KIBOKO, "short_rains", LATEST)
    client, _ = _stub_client("", stop="refusal")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(narrate, "_get_client", lambda: client)
    assert narrate.explain("location", rec)["source"] == "template"
    narrate._cache.clear()
    monkeypatch.setenv("ASSISTANT_MAX_CALLS_PER_HOUR", "0")
    out = narrate.explain("location", rec)
    assert out["source"] == "template" and "busy" in out["note"]


def test_endpoints():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        assert c.get("/explain/status").json()["llm_enabled"] is False
        r = c.get("/explain/location", params={"lat": KIBOKO[0], "lon": KIBOKO[1], "season": "short_rains", "model": LATEST})
        assert r.status_code == 200 and r.json()["evidence"]["kind"] == "location"
        r = c.get("/explain/changes", params={"lat": KIBOKO[0], "lon": KIBOKO[1], "season": "short_rains",
                                              "model": LATEST, "compare_to": OCT})
        assert r.status_code == 200 and r.json()["explanation"]["sections"]["local_implications"]
        assert c.get("/explain/changes", params={"lat": 0, "lon": 37, "model": LATEST, "compare_to": LATEST}).status_code == 400
        r = c.get("/explain/map", params={"variable": "onset", "layer": "anomaly", "model": LATEST, "season": "short_rains"})
        assert r.status_code == 200 and r.json()["evidence"]["distribution"]
