"""Forecast assistant chat: tools, the keyword router used without Claude, the number check with one revision, and
POST /explain/chat. Claude is replaced by a scripted stub client."""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import chat, narrate  # noqa: E402

LATEST = "ECMWF SEAS5 (Oct+Obs latest)"
CTX = {"lat": -2.21046, "lon": 37.7190, "season": "short_rains", "model": LATEST, "variable": "onset",
       "layer": "median", "site_name": "KALRO Kiboko, Makueni Farm"}


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    yield


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()


def test_tool_schemas_are_strict_and_complete():
    for t in chat.TOOLS:
        sch = t["input_schema"]
        assert t["strict"] is True and sch["additionalProperties"] is False
        assert set(sch["required"]) == set(sch["properties"]), t["name"]


def test_router_and_notes():
    assert chat.route("What changed since the last run?") == "changes"
    assert chat.route("What does this map show?") == "map"
    assert chat.route("Should I sow sorghum now?") == "advisory"
    assert chat.route("When will the rains start here?") == "location"
    assert chat._crop_of("Should I sow sorghum now?") == "sorghum" and chat._decision_of("Should I sow sorghum now?") == "sowing"
    assert chat._decision_of("Is mulch worth it?") == "water" and chat._decision_of("Which crop fits this season?") == "crop_choice"
    titles = [n["title"] for n in chat.search_notes("what does the tercile chance mean")]
    assert "Terciles" in titles


@pytest.mark.parametrize("q,kind", [("When will the rains start?", "location"), ("What changed?", "changes"),
                                    ("Explain the map", "map"), ("Which crop should I plant?", "advisory")])
def test_without_claude_the_matching_explanation_is_returned(q, kind):
    out = chat.reply([{"role": "user", "content": q}], CTX)
    assert out["source"] == "template" and out["reply"]
    assert out["evidence"] and out["evidence"][0]["kind"] == kind
    assert "standard explanation" in out["note"]


def _block(**kw):
    return types.SimpleNamespace(**kw)


def _resp(content, stop):
    return types.SimpleNamespace(content=content, stop_reason=stop, model="claude-opus-5-5")


class Stub:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))
        self.messages = types.SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)(kw) if callable(self.script[0]) else self.script.pop(0)


def _enable(monkeypatch, stub):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(narrate, "_get_client", lambda: stub)


def _onset_answer(kw):
    """Answer with the early-onset chance taken from the tool result the loop sent back."""
    res = json.loads(kw["messages"][-1]["content"][0]["content"])
    p = res["quantities"]["onset"]["chances_pct"]["early"]
    return _resp([_block(type="text", text=f"An early onset has a {p}% chance here (skill-weighted).")], "end_turn")


def test_claude_answers_through_tools(monkeypatch):
    stub = Stub([
        _resp([_block(type="tool_use", id="t1", name="get_place_outlook", input={"lat": None, "lon": None, "method": None}),
               _block(type="tool_use", id="t2", name="suggest_action",
                      input={"action": "open_panel", "label": "Explain this location", "tab": None, "kind": "location", "lat": None, "lon": None})],
              "tool_use"),
        _onset_answer,
    ])
    _enable(monkeypatch, stub)
    out = chat.reply([{"role": "user", "content": "Will the rains start early?"}], CTX, "farmer")
    assert out["source"] == "claude" and "% chance" in out["reply"]
    assert out["evidence"][0]["kind"] == "location"
    assert out["actions"][0]["kind"] == "location"
    first = stub.calls[0]
    assert first["tools"] is chat.TOOLS and first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "KALRO Kiboko" in first["messages"][0]["content"]          # the dashboard context goes with the question
    # both tool results go back in one user message
    results = stub.calls[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]


def test_invented_numbers_get_one_revision_then_fall_back(monkeypatch):
    bad = _resp([_block(type="text", text="Onset will be on 17 Nov with 93.5% certainty.")], "end_turn")
    stub = Stub([
        _resp([_block(type="tool_use", id="t1", name="get_place_outlook", input={"lat": None, "lon": None, "method": None})], "tool_use"),
        bad, bad,
    ])
    _enable(monkeypatch, stub)
    out = chat.reply([{"role": "user", "content": "When will the rains start?"}], CTX)
    assert out["source"] == "template"
    assert any("these figures are not in the tool results" in str(m["content"]) for m in stub.calls[2]["messages"])


def test_revision_that_fixes_the_numbers_is_used(monkeypatch):
    stub = Stub([
        _resp([_block(type="tool_use", id="t1", name="get_place_outlook", input={"lat": None, "lon": None, "method": None})], "tool_use"),
        _resp([_block(type="text", text="There is a 93.5% chance.")], "end_turn"),
        lambda kw: _resp([_block(type="text", text="The early third is the most likely outcome here.")], "end_turn"),
    ])
    _enable(monkeypatch, stub)
    out = chat.reply([{"role": "user", "content": "Will it start early?"}], CTX)
    assert out["source"] == "claude" and "most likely" in out["reply"]


def test_compare_tool_and_errors():
    s = chat.Session(CTX)
    rec = s.run("compare", {"to_run": "oct01", "to_method": None})
    assert rec["kind"] == "changes" and rec["from_run"]["model"] == "ECMWF SEAS5 (Oct)"
    m = s.run("compare", {"to_run": None, "to_method": "agri_rule_1"})
    assert m["same_event_definition"] is False
    assert "error" in s.run("compare", {"to_run": "oct01_latest_obs", "to_method": None})
    assert "error" in chat.Session({**CTX, "lat": None, "lon": None}).run("get_place_outlook", {"lat": None, "lon": None, "method": None})


def test_chat_endpoint():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        r = c.post("/explain/chat", json={"messages": [{"role": "user", "content": "What does this map show?"}], "context": CTX})
        assert r.status_code == 200
        j = r.json()
        assert j["reply"] and j["evidence"][0]["kind"] == "map"
        r = c.post("/explain/chat", json={"messages": [], "context": CTX})
        assert r.status_code == 200 and "Ask a question" in r.json()["reply"]
