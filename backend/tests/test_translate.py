"""Kiswahili and Amharic: the glossary, the number check on translations, and translation through the explain,
chat and studio endpoints (Claude replaced by a stub that 'translates')."""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import bulletins as B, narrate, translate  # noqa: E402

LATEST = "ECMWF SEAS5 (Oct+Obs latest)"
KIBOKO = (-2.21046, 37.7190)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    yield


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()
    translate._cache.clear()


def _swahili(text):
    return ("[sw] " + text.replace("Draft guidance (not yet reviewed)", "Ushauri wa awali (rasimu), bado haujakaguliwa")
            .replace("experimental", "ya majaribio").replace("Experimental", "Ya majaribio"))


def _stub(fn):
    def create(**kw):
        texts = json.loads(kw["messages"][0]["content"])["texts"]
        out = json.dumps({"texts": [fn(t) for t in texts]}, ensure_ascii=False)
        return types.SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                     content=[types.SimpleNamespace(type="text", text=out)])
    return types.SimpleNamespace(messages=types.SimpleNamespace(create=create), beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create)))


def _enable(monkeypatch, fn):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = _stub(fn)
    monkeypatch.setattr(narrate, "_get_client", lambda: client)
    # explanations themselves stay templates in these tests: only translation calls the stub
    monkeypatch.setattr(narrate, "_call_claude", lambda *a, **k: (None, "off in tests"))


def test_glossary_covers_both_languages_and_is_draft():
    g = translate.glossary()
    assert set(g["languages"]) == {"sw", "am"}
    assert all(v["status"] in ("draft", "reviewed") for v in g["languages"].values())
    missing = [t for t, v in g["terms"].items() if not v.get("sw") or not v.get("am")]
    assert missing == []
    langs = translate.languages()
    assert langs["sw"]["speech"] == "sw-KE" and langs["am"]["speech"] == "am-ET" and langs["sw"]["notice"]


def test_number_check():
    assert translate.same_numbers(["Onset 29 Oct, chance 68%"], ["Mvua kuanza 29 Oktoba, uwezekano 68%"])
    assert not translate.same_numbers(["Onset 29 Oct, chance 68%"], ["Mvua kuanza 29 Oktoba, uwezekano 86%"])
    assert not translate.same_numbers(["8 in 10 members"], ["matokeo nane kati ya 10"])      # a number spelt out
    assert translate.same_numbers(["0.50"], ["0.5"])


def test_without_claude_the_english_stays():
    out, err = translate.translate({"a": ["Onset 29 Oct."]}, "sw")
    assert out is None and "off" in err
    ex = translate.localise({"sections": {"summary": ["x"]}}, "am")
    assert ex["language"] == "en" and ex["translation_note"]
    assert translate.translate({"a": "x"}, "fr")[0] is None


def test_translation_used_only_when_numbers_match(monkeypatch):
    _enable(monkeypatch, _swahili)
    out, err = translate.translate({"summary": ["Onset 29 Oct, 68%."], "n": {"x": "8 in 10"}}, "sw")
    assert err is None and out["summary"][0].startswith("[sw] ") and out["n"]["x"] == "[sw] 8 in 10"
    translate._cache.clear()
    _enable(monkeypatch, lambda t: "[sw] " + t.replace("68", "86"))
    out, err = translate.translate({"summary": ["Onset 29 Oct, 68%."]}, "sw")
    assert out is None and "figures" in err


def test_endpoints_in_swahili(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        assert set(c.get("/explain/languages").json()["languages"]) == {"en", "sw", "am"}
        r = c.get("/explain/location", params={"lat": KIBOKO[0], "lon": KIBOKO[1], "model": LATEST, "language": "sw"}).json()
        assert r["explanation"]["language"] == "en" and r["explanation"]["translation_note"]      # no Claude: English
        _enable(monkeypatch, _swahili)
        r = c.get("/explain/location", params={"lat": KIBOKO[0], "lon": KIBOKO[1], "model": LATEST, "language": "sw"}).json()
        ex = r["explanation"]
        assert ex["language"] == "sw" and ex["sections"]["summary"][0].startswith("[sw] ") and "not yet reviewed" in ex["translation_notice"]
        j = c.post("/studio/compose", json={"format": "crop_advisory", "model": LATEST, "lat": KIBOKO[0], "lon": KIBOKO[1],
                                            "language": "sw"}).json()
        assert j["bulletin"]["language"] == "sw" and j["bulletin"]["title"].startswith("[sw] ")
        assert j["quality"] == []                     # the draft and experimental labels are found in Kiswahili


def test_chat_in_swahili(monkeypatch):
    from assistant import chat
    ctx = {"lat": KIBOKO[0], "lon": KIBOKO[1], "season": "short_rains", "model": LATEST}
    out = chat.reply([{"role": "user", "content": "When will the rains start?"}], ctx, language="sw")
    assert out["source"] == "template" and out.get("translation_note")
    _enable(monkeypatch, _swahili)
    monkeypatch.setattr(chat, "_claude_reply", lambda *a, **k: None)          # the answer is the template's
    out = chat.reply([{"role": "user", "content": "When will the rains start?"}], ctx, language="sw")
    assert out["language"] == "sw" and out["reply"].startswith("[sw] ")
