"""Kiswahili and Amharic for the assistant's text: Claude translates the checked English text with the reviewed-terms
glossary (glossary.yaml), keeping every number; the translation is used only if its numbers are exactly the
English text's numbers. Until a language's glossary is reviewed, every translated text says "Machine translation,
not yet reviewed". Without Claude there is no translation: the English is returned with a note.
"""
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

import yaml

from . import narrate

log = logging.getLogger("assistant")
GLOSSARY_FILE = Path(__file__).with_name("glossary.yaml")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_lock = threading.Lock()

NOTICE = {"sw": "Tafsiri ya mashine, bado haijakaguliwa (Machine translation, not yet reviewed).",
          "am": "የማሽን ትርጉም፣ ገና ያልተገመገመ (Machine translation, not yet reviewed)."}


def glossary():
    return yaml.safe_load(GLOSSARY_FILE.read_text(encoding="utf-8"))


def languages():
    g = glossary()
    out = {"en": {"name": "English", "native": "English", "speech": "en-KE", "status": "source"}}
    for code, meta in g["languages"].items():
        out[code] = {**meta, "notice": NOTICE.get(code)}
    return out


def _numbers(texts):
    return sorted(n.rstrip("0").rstrip(".") if "." in n else n for t in texts for n in _NUM.findall(t or ""))


def same_numbers(src: list, dst: list) -> bool:
    """The translation has exactly the source's numbers (as a multiset)."""
    return _numbers(src) == _numbers(dst)


def _flatten(d):
    """[(path, text)] of every string in a nested dict/list of strings."""
    out = []

    def walk(x, p):
        if isinstance(x, str):
            out.append((p, x))
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v, p + (k,))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, p + (i,))
    walk(d, ())
    return out


def _put(d, path, value):
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value


def translate(obj, lang: str):
    """`obj` (strings nested in dicts and lists) in `lang`, or (None, reason)."""
    if lang in (None, "", "en"):
        return obj, None
    langs = glossary()["languages"]
    if lang not in langs:
        return None, f"language must be one of en, {', '.join(langs)}"
    st = narrate.llm_status()
    if not st["llm_enabled"]:
        return None, "Translation needs the assistant (Claude), which is off on this server."
    items = _flatten(obj)
    key = (lang, json.dumps(items, ensure_ascii=False))
    with _lock:
        if key in _cache:
            return json.loads(json.dumps(_cache[key])), None
    if not narrate._limiter.allow(int(os.environ.get("ASSISTANT_MAX_CALLS_PER_HOUR", "200"))):
        return None, "The assistant is busy; the text is shown in English."
    g = glossary()
    terms = "\n".join(f"- {en}: {t.get(lang)}" for en, t in g["terms"].items() if t.get(lang))
    texts = [t for _, t in items]
    schema = {"type": "object", "additionalProperties": False, "required": ["texts"],
              "properties": {"texts": {"type": "array", "items": {"type": "string"}}}}
    system = (f"You translate agricultural weather-forecast text from English into {langs[lang]['name']} for farmers and "
              f"extension staff in {'Kenya' if lang == 'sw' else 'Ethiopia'}. Use the glossary's terms. Keep every number "
              f"exactly as written, in Western digits (0-9): do not convert, round or spell out numbers, and keep "
              f"percent signs. Keep dates in the Gregorian calendar exactly as given (day number and month; never convert to "
              f"another calendar). Keep acronyms (RPSS, CHIRPS, ECMWF, SEAS5) and place names. Keep the meaning and the "
              f"caution of each sentence; do not add or drop information. Return the texts in the same order, one "
              f"translation per input text.\n\nGlossary (English: {langs[lang]['name']}):\n{terms}")
    try:
        client = narrate._get_client()
        resp = client.messages.create(
            model=os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5"), max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": json.dumps({"texts": texts}, ensure_ascii=False)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}})
        if resp.stop_reason != "end_turn":
            return None, "The translation could not be made; the text is shown in English."
        out = json.loads(next(b.text for b in resp.content if b.type == "text"))["texts"]
    except Exception as e:
        log.warning("translate: %s: %s", type(e).__name__, e)
        return None, "The translation could not be made; the text is shown in English."
    if len(out) != len(texts) or not all(same_numbers([a], [b]) for a, b in zip(texts, out)):
        log.warning("translate: numbers changed in translation to %s", lang)
        return None, "The translation changed some figures, so the English text is shown."
    res = json.loads(json.dumps(obj))
    for (path, _), t in zip(items, out):
        _put(res, path, t)
    with _lock:
        _cache[key] = res
        while len(_cache) > 512:
            _cache.popitem(last=False)
    return json.loads(json.dumps(res)), None


def localise(explanation: dict, lang: str) -> dict:
    """An explanation ({sections, ...}) in `lang`, with its translation status."""
    if lang in (None, "", "en"):
        return {**explanation, "language": "en"}
    sec, err = translate(explanation["sections"], lang)
    if sec is None:
        return {**explanation, "language": "en", "translation_note": err}
    return {**explanation, "sections": sec, "language": lang, "translation_status": "machine translation, not yet reviewed",
            "translation_notice": NOTICE.get(lang)}
