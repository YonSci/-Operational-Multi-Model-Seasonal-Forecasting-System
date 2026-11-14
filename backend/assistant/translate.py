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


_DEC_COMMA = re.compile(r"(?<=\d),(?=\d)")


def _numbers(texts):
    """The numbers of the texts as a sorted list; a decimal comma (0,87) reads as a decimal point."""
    return sorted(n.rstrip("0").rstrip(".") if "." in n else n
                  for t in texts for n in _NUM.findall(_DEC_COMMA.sub(".", t or "")))


def same_numbers(src: list, dst: list) -> bool:
    """The translation has exactly the source's numbers (as a multiset)."""
    return _numbers(src) == _numbers(dst)


# Figures never pass through the translator: each number is replaced by a marker (⟦0⟧, ⟦1⟧ ...) before translation
# and put back afterwards, so a figure cannot be reformatted (0,87; 44 for 44.0), converted (Ethiopic numerals) or
# changed. A translated text is used only if it has every marker exactly once and no digit of its own.
_MARK = re.compile(r"⟦(\d+)⟧")
_ANY_DIGIT = re.compile(r"[0-9፩-፼]")             # Western digits and Ethiopic numerals


def _mask(text):
    nums = []

    def sub(m):
        nums.append(m.group(0))
        return f"⟦{len(nums) - 1}⟧"
    return _NUM.sub(sub, text or ""), nums


def _unmask(text, nums):
    """The translated text with its figures back, or None if a marker is missing, repeated or new, or a digit was added."""
    found = [int(k) for k in _MARK.findall(text)]
    if sorted(found) != list(range(len(nums))):
        return None
    if _ANY_DIGIT.search(_MARK.sub("", text)):
        return None
    return _MARK.sub(lambda m: nums[int(m.group(1))], text)


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
    """(`obj` in `lang`, note) on success, the note saying if any sentence stayed in English; or (None, reason)."""
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
            val, note = _cache[key]
            return json.loads(json.dumps(val)), note
    if not narrate._limiter.allow(int(os.environ.get("ASSISTANT_MAX_CALLS_PER_HOUR", "200"))):
        return None, "The assistant is busy; the text is shown in English."
    g = glossary()
    terms = "\n".join(f"- {en}: {t.get(lang)}" for en, t in g["terms"].items() if t.get(lang))
    texts = [t for _, t in items]
    masked = [_mask(t) for t in texts]
    schema = {"type": "object", "additionalProperties": False, "required": ["texts"],
              "properties": {"texts": {"type": "array", "items": {"type": "string"}}}}
    system = (f"You translate agricultural weather-forecast text from English into {langs[lang]['name']} for farmers and "
              f"extension staff in {'Kenya' if lang == 'sw' else 'Ethiopia'}. Use the glossary's terms. Every number in the "
              f"texts has been replaced by a marker such as ⟦0⟧ or ⟦12⟧: copy each marker exactly once, unchanged, into "
              f"the place its number belongs in your sentence, and write no digits or numerals of your own (write "
              f"'first', 'third' and the like in words). Keep percent signs and units next to their markers. Dates are a "
              f"marker and a Gregorian month (⟦3⟧ Oct): translate the month name and never convert to another calendar. "
              f"Keep acronyms (RPSS, CHIRPS, ECMWF, SEAS5) and place names. Keep the meaning and the "
              f"caution of each sentence; do not add or drop information. Return the texts in the same order, one "
              f"translation per input text.\n\nGlossary (English: {langs[lang]['name']}):\n{terms}")
    try:
        client = narrate._get_client()
        resp = client.messages.create(
            model=os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5"), max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": json.dumps({"texts": [m for m, _ in masked]}, ensure_ascii=False)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}})
        if resp.stop_reason != "end_turn":
            return None, "The translation could not be made; the text is shown in English."
        out = json.loads(next(b.text for b in resp.content if b.type == "text"))["texts"]
    except Exception as e:
        log.warning("translate: %s: %s", type(e).__name__, e)
        return None, "The translation could not be made; the text is shown in English."
    if len(out) != len(texts):
        log.warning("translate: %d texts in, %d out (%s)", len(texts), len(out), lang)
        return None, "The translation could not be made; the text is shown in English."
    out = [_unmask(t, nums) for t, (_, nums) in zip(out, masked)]
    bad = [k for k, (a, b) in enumerate(zip(texts, out)) if b is None or not same_numbers([a], [b])]
    for k in bad[:3]:                                         # what went wrong, for the logs
        log.warning("translate (%s): figures not kept in text %d of %d (%d markers)", lang, k + 1, len(texts),
                    len(masked[k][1]))
    if len(bad) > len(texts) / 2:
        return None, "The translation changed some figures, so the English text is shown."
    res = json.loads(json.dumps(obj))
    for k, ((path, _), t) in enumerate(zip(items, out)):
        _put(res, path, texts[k] if k in bad else t)          # a sentence whose figures changed stays in English
    if bad:
        res = {"__value__": res, "__kept_english__": len(bad)}
    note = None
    if isinstance(res, dict) and "__kept_english__" in res:
        note = f"{res['__kept_english__']} sentence(s) kept in English because a figure changed in translation."
        res = res["__value__"]
    with _lock:
        _cache[key] = (res, note)
        while len(_cache) > 512:
            _cache.popitem(last=False)
    return json.loads(json.dumps(res)), note


def localise(explanation: dict, lang: str) -> dict:
    """An explanation ({sections, ...}) in `lang`, with its translation status."""
    if lang in (None, "", "en"):
        return {**explanation, "language": "en"}
    sec, msg = translate(explanation["sections"], lang)
    if sec is None:
        return {**explanation, "language": "en", "translation_note": msg}
    out = {**explanation, "sections": sec, "language": lang, "translation_status": "machine translation, not yet reviewed",
           "translation_notice": NOTICE.get(lang)}
    if msg:
        out["translation_note"] = msg
    return out
