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
    _enable(monkeypatch, lambda t: "[sw] " + t.replace("⟦1⟧", "86"))       # a figure written by the translator
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


def test_decimal_comma_and_partial_fallback(monkeypatch):
    assert translate.same_numbers(["0.87 of the time"], ["0,87 ya wakati"])
    # one sentence of three changes a figure: only that one stays in English
    _enable(monkeypatch, lambda t: "[sw] " + (t.replace("⟦1⟧", "35") if "chance" in t else t))
    out, note = translate.translate({"s": ["Onset 29 Oct.", "End 26 Dec, chance 53%.", "Normal 12 Nov."]}, "sw")
    assert out["s"][0].startswith("[sw] ") and out["s"][1] == "End 26 Dec, chance 53%." and out["s"][2].startswith("[sw] ")
    assert note and "1 sentence" in note
    ex = translate.localise({"sections": {"summary": ["Onset 29 Oct.", "End 26 Dec, chance 53%.", "Normal 12 Nov."]}}, "sw")
    assert ex["language"] == "sw" and ex["translation_note"]
    # most sentences change: no translation at all
    translate._cache.clear()
    _enable(monkeypatch, lambda t: "[sw] " + t.replace("⟦0⟧", "7"))
    assert translate.translate({"s": ["Onset 29 Oct.", "End 26 Dec.", "12 Nov."]}, "sw")[0] is None


def test_figures_never_reach_the_translator(monkeypatch):
    seen = []

    def oktoba(t):                       # moves the marker, as Kiswahili word order does
        seen.append(t)
        return t.replace("Onset ⟦0⟧ Oct", "Mvua kuanza Oktoba ⟦0⟧").replace("hit rate", "kiwango")
    _enable(monkeypatch, oktoba)
    out, note = translate.translate({"s": ["Onset 29 Oct, hit rate 0.87, 44.0 days."]}, "sw")
    assert seen and not any(ch.isdigit() for t in seen for ch in translate._MARK.sub('', t))   # markers only
    assert out["s"][0] == "Mvua kuanza Oktoba 29, kiwango 0.87, 44.0 days." and note is None
    # a marker dropped, repeated, or an Ethiopic numeral added: that text stays in English
    for bad in (lambda t: t.replace("⟦1⟧", ""), lambda t: t + " ⟦0⟧", lambda t: t + " ፩"):
        translate._cache.clear()
        _enable(monkeypatch, bad)
        assert translate.translate({"s": ["Onset 29 Oct, 68%."]}, "am")[0] is None


def test_numbers_written_in_words_may_become_digits(monkeypatch):
    # "Eight in ten" -> "8 kati ya 10": allowed, the English spells out both numbers
    _enable(monkeypatch, lambda t: "[sw] " + t.replace("Eight in ten", "8 kati ya 10"))
    out, note = translate.translate({"s": ["Eight in ten members fall before 12 Nov."]}, "sw")
    assert out["s"][0] == "[sw] 8 kati ya 10 members fall before 12 Nov." and note is None
    # a digit the English does not spell out is still rejected
    translate._cache.clear()
    _enable(monkeypatch, lambda t: "[sw] " + t.replace("Eight in ten", "9 kati ya 10"))
    assert translate.translate({"s": ["Eight in ten members fall before 12 Nov."]}, "sw")[0] is None
    # Ge'ez numerals are never accepted
    translate._cache.clear()
    _enable(monkeypatch, lambda t: t.replace("Eight in ten", "\u1370 \u1372"))
    assert translate.translate({"s": ["Eight in ten members fall before 12 Nov."]}, "am")[0] is None
