"""Forecast assistant chat: answers questions about the dashboard's forecasts through tools.

Claude never states a figure from memory: every figure comes from a tool that returns one of the platform's
evidence records (the outlook at a place, a comparison of runs or methods, a map layer, an advisory card) or from
the method notes. The answer's numbers are checked against those records; a failing answer gets one chance to be
revised, then the standard explanation of the evidence is returned instead.

Without a Claude key the chat still answers: a keyword router picks the matching explanation (place, changes, map
or advisory) and returns its standard text.

Request (POST /explain/chat): {"messages": [{"role": "user"|"assistant", "content": str}, ...],
                               "context": {"lat", "lon", "season", "model", "variable", "layer", "site_name"},
                               "audience": "general"|...}
"""
import json
import logging
import os
import re

from . import advisory, knowledge as kn, narrate
from . import evidence as ev

log = logging.getLogger("assistant")

MAX_TURNS = 10          # earlier messages kept from the conversation
MAX_CHARS = 2000        # longest user message accepted
MAX_TOOL_ROUNDS = 6

# Short Rains runs and methods by the names the tools use (frontend/src/shortRainsRuns.js, App.jsx ONSET_DEFS)
RUNS = {"sep01": "ECMWF SEAS5 (Sep)", "oct01": "ECMWF SEAS5 (Oct)", "oct01_sep_obs": "ECMWF SEAS5 (Oct+Obs)",
        "oct01_latest_obs": "ECMWF SEAS5 (Oct+Obs latest)"}
METHODS = {"dunning": "", "agri_rule_1": " - Agri rule 1", "agri_rule_2": " - Agri rule 2", "agri_rule_3": " - Agri rule 3",
           "fao_agricultural": " - FAO water balance (agricultural)", "fao_rainfall": " - FAO water balance (rainfall)",
           "fao_cropwater": " - FAO water balance (cropwater)"}
TABS = ["forecast", "probabilistic", "validation", "historical", "tracker", "crop", "about"]


def _nullable(t, **kw):
    return {"type": [t, "null"], **kw}


TOOLS = [
    {"name": "get_place_outlook", "strict": True,
     "description": "Onset, cessation and season-length forecast at a place: dates, 8-in-10 ranges, normal, chances of "
                    "each third (skill-weighted), whether a date is forecast or estimated from observations, and the "
                    "skill. Leave lat/lon null for the place selected on the dashboard, and method null for its method.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["lat", "lon", "method"],
                      "properties": {"lat": _nullable("number"), "lon": _nullable("number"),
                                     "method": _nullable("string", enum=list(METHODS) + [None])}}},
    {"name": "compare", "strict": True,
     "description": "What differs at the selected place between the dashboard's current run and another run "
                    "(to_run) or another onset method (to_method). Lists documented input changes and how medians "
                    "and chances moved. Kenya Short Rains only.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["to_run", "to_method"],
                      "properties": {"to_run": _nullable("string", enum=list(RUNS) + [None]),
                                     "to_method": _nullable("string", enum=list(METHODS) + [None])}}},
    {"name": "explain_map_layer", "strict": True,
     "description": "Summary of a map layer for the current run: what it shows, its spread over the grid cells, "
                    "where values are highest and lowest, and the value at each monitored site. Null arguments mean "
                    "the layer on screen.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["variable", "layer"],
                      "properties": {"variable": _nullable("string", enum=["onset", "cessation", "lgp", None]),
                                     "layer": _nullable("string", enum=list(kn.LAYERS) + [None])}}},
    {"name": "get_advisory", "strict": True,
     "description": "A DRAFT advisory card for one decision at the selected place (Kenya Short Rains): the assessment "
                    "from draft rules, and options from the experimental crop outlook ranked by the objective.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "required": ["decision", "crop", "planted", "sowing_date", "objective"],
                      "properties": {"decision": {"type": "string", "enum": ["sowing", "crop_choice", "establishment", "replanting", "water"]},
                                     "crop": {"type": "string", "enum": ["maize_early", "maize_medium", "sorghum", "bean"]},
                                     "planted": {"type": "string", "enum": ["yes", "no", "unknown"]},
                                     "sowing_date": _nullable("string", description="ISO date, when known"),
                                     "objective": {"type": "string", "enum": ["maturity", "establishment", "downside", "yield", "water"]}}}},
    {"name": "search_notes", "strict": True,
     "description": "The platform's method notes: onset methods, terciles, skill-weighted chances, hit rate, RPSS, "
                    "medians and ranges, map layers. Use for definitions and how to read a figure.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["query"],
                      "properties": {"query": {"type": "string"}}}},
    {"name": "suggest_action", "strict": True,
     "description": "Offer the user a button that opens part of the dashboard: a tab, the explain panel, an advisory "
                    "card, or another place. The user decides whether to press it.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "required": ["action", "label", "tab", "kind", "lat", "lon"],
                      "properties": {"action": {"type": "string", "enum": ["open_tab", "open_panel", "show_place"]},
                                     "label": {"type": "string", "description": "button text, at most 6 words"},
                                     "tab": _nullable("string", enum=TABS + [None]),
                                     "kind": _nullable("string", enum=["location", "changes", "map", "advisory", None]),
                                     "lat": _nullable("number"), "lon": _nullable("number")}}},
]

SYSTEM = """You are the forecast assistant of the Seasonal to Sub-seasonal Climate & Agricultural Intelligence \
System (Kenya and Ethiopia). You answer questions about the forecasts the dashboard shows: onset, cessation and \
length of the rainy season, their chances and skill, the map layers, what changed between runs, and draft crop \
advisories.

Rules:
- Get every figure from a tool. Never state a date, percentage, yield or score from memory; copy figures exactly as \
the tools give them.
- For definitions and how to read a figure, use search_notes and explain with the selected forecast's own figures.
- Keep forecast and observation apart (status estimated_from_observations means observed rain so far). A median \
date is not a promise of rain that day; a chance of the late third is not an amount later; chances are \
skill-weighted, and model agreement is not the same as skill. Say when skill is low.
- The onset methods define different events; name the method when it matters.
- Advisory cards are DRAFT guidance that no agronomist has reviewed, and the crop figures are experimental: say so \
whenever you use them, and present options as options to consider, never as instructions.
- If a question is outside what the platform covers (pests, prices, other countries, weather today), say so \
briefly and point to what the platform does cover.
- Offer a dashboard button with suggest_action when it would help the user see the evidence.
- Reply in English (other languages are planned). Plain text, no markdown, short paragraphs; at most about 150 \
words unless the user asks for more.

Reference notes (also searchable with search_notes):
""" + kn.reference_text()


# ---------------------------------------------------------------------------- tools
class Session:
    """One chat request: the dashboard context, the records the tools returned, and the suggested actions."""

    def __init__(self, context):
        c = context or {}
        self.lat, self.lon = c.get("lat"), c.get("lon")
        self.season = c.get("season") or "short_rains"
        self.model = c.get("model") or ""
        self.variable, self.layer = c.get("variable") or "onset", c.get("layer") or "median"
        self.records, self.actions, self.notes = [], [], []

    def _base(self):
        return self.model.split(" - ")[0]

    def _suffix(self):
        return self.model[len(self._base()):]

    def run(self, name, args):
        if name == "get_place_outlook":
            lat = args.get("lat") if args.get("lat") is not None else self.lat
            lon = args.get("lon") if args.get("lon") is not None else self.lon
            if lat is None or lon is None:
                return {"error": "No place is selected on the dashboard; ask the user to pick one."}
            model = self._base() + METHODS[args["method"]] if args.get("method") and self.season == "short_rains" else self.model
            rec = ev.location(float(lat), float(lon), self.season, model)
        elif name == "compare":
            if self.season != "short_rains":
                return {"error": "Comparisons are available for the Kenya Short Rains runs only."}
            other = (RUNS[args["to_run"]] if args.get("to_run") else self._base()) + \
                    (METHODS[args["to_method"]] if args.get("to_method") else self._suffix())
            if other == self.model:
                return {"error": "That is the run already on screen; choose another run or method."}
            rec = ev.changes(float(self.lat), float(self.lon), self.season, self.model, other)
        elif name == "explain_map_layer":
            rec = ev.map_layer(args.get("variable") or self.variable, args.get("layer") or self.layer, self.model, self.season)
        elif name == "get_advisory":
            if self.season != "short_rains":
                return {"error": "Advisory cards are available for the Kenya Short Rains only."}
            rec = advisory.card(float(self.lat), float(self.lon), self.season, self.model,
                                {k: args.get(k) for k in ("decision", "crop", "planted", "sowing_date", "objective")})
        elif name == "search_notes":
            return {"notes": search_notes(args.get("query", ""))}
        elif name == "suggest_action":
            a = {k: args.get(k) for k in ("action", "label", "tab", "kind", "lat", "lon")}
            self.actions.append(a)
            return {"ok": True, "shown_to_user": a["label"]}
        else:
            return {"error": f"Unknown tool {name}"}
        self.records.append(rec)
        return rec


def search_notes(query: str, k: int = 5) -> list:
    """The method notes that best match the query (word overlap)."""
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
    docs = [{"title": t, "text": x} for t, x in kn.GLOSSARY]
    docs += [{"title": m["label"], "text": f"{m['family']}. Answers: {m['question']} Onset: {m['onset']}. "
                                          f"Cessation: {m['cessation']}. Data: {m['data']}."} for m in kn.METHODS.values()]
    docs += [{"title": f"Map layer {k}", "text": what + (f" Misreading to avoid: {mis}" if mis else "")}
             for k, (what, mis) in kn.LAYERS.items()]

    def score(d):
        toks = set(re.findall(r"[a-z0-9]+", (d["title"] + " " + d["text"]).lower()))
        return len(words & toks)
    ranked = sorted(docs, key=score, reverse=True)
    return [d for d in ranked[:k] if score(d) > 0] or ranked[:2]


# ---------------------------------------------------------------------------- without Claude
_ROUTES = [("changes", r"\b(chang\w*|differ\w*|previous|earlier run|update[ds]?|moved|shift\w*)\b"),
           ("map", r"\b(map|layer|colou?rs?|legend|where)\b"),
           ("advisory", r"\b(sow\w*|plant\w*|crop\w*|maize|sorghum|beans?|irrigat\w*|replant\w*|advi[cs]e\w*|mulch|ridges?|variet\w*)\b")]


def route(text: str) -> str:
    low = (text or "").lower()
    for kind, pat in _ROUTES:
        if re.search(pat, low):
            return kind
    return "location"


def template_reply(session: Session, text: str, audience: str) -> dict:
    kind = route(text)
    if kind in ("changes", "advisory") and session.season != "short_rains":
        kind = "location"
    try:
        if kind == "changes":
            res = session.run("compare", {"to_run": _previous_run(session), "to_method": None})
            if "error" in res:
                kind, res = "location", session.run("get_place_outlook", {"lat": None, "lon": None, "method": None})
        elif kind == "map":
            res = session.run("explain_map_layer", {"variable": None, "layer": None})
        elif kind == "advisory":
            res = session.run("get_advisory", {"decision": _decision_of(text), "crop": _crop_of(text), "planted": "unknown",
                                                "sowing_date": None, "objective": "maturity"})
        else:
            res = session.run("get_place_outlook", {"lat": None, "lon": None, "method": None})
    except Exception as e:                                          # e.g. no place selected
        return {"reply": f"I could not prepare an answer: {e}", "source": "template"}
    if "error" in res:
        return {"reply": res["error"], "source": "template"}
    sec = narrate.TEMPLATES[kind](res, audience)
    reply = "\n\n".join([" ".join(sec["summary"]), " ".join(sec["local_implications"])]).strip()
    # a chat answer keeps the first cautions (the draft and experimental notes come first); the explain panel has all
    return {"reply": reply, "source": "template", "cautions": sec["cautions"][:3]}


def _crop_of(text):
    low = (text or "").lower()
    if "sorghum" in low:
        return "sorghum"
    if "bean" in low:
        return "bean"
    if re.search(r"\b(medium|late|long)[- ]?(maturing|duration)?\b.*maize|duma", low):
        return "maize_medium"
    return "maize_early"


def _decision_of(text):
    low = (text or "").lower()
    if re.search(r"replant|re-plant|resow|re-sow", low):
        return "replanting"
    if re.search(r"irrigat|water|mulch|ridge", low):
        return "water"
    if re.search(r"which crop|what crop|variet|maturity|which maize|crop fits|fits this season", low):
        return "crop_choice"
    if re.search(r"emerg|establish|already (sown|planted)", low):
        return "establishment"
    return "sowing"


def _previous_run(session):
    names = list(RUNS)
    base = session._base()
    cur = next((k for k, v in RUNS.items() if v == base), None)
    i = names.index(cur) if cur else len(names)
    return names[i - 1] if i > 0 else None


# ---------------------------------------------------------------------------- with Claude
def _clean_history(messages):
    out = []
    for m in (messages or [])[-MAX_TURNS:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip():
            out.append({"role": m["role"], "content": m["content"][:MAX_CHARS]})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _context_note(s: Session, site_name):
    place = site_name or (f"{s.lat}, {s.lon}" if s.lat is not None else "none selected")
    return (f"Dashboard now: season {kn.SEASON_LABELS.get(s.season, (s.season,))[0]}, run and method {s.model or 'default'}, "
            f"selected place {place}, map layer {s.variable}/{s.layer}.")


def _create(client, **kw):
    import anthropic
    try:
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
    except anthropic.BadRequestError as e:
        log.warning("assistant chat: request with fallbacks rejected (%s); retrying without", e.message)
        return client.messages.create(**kw)


def _text(resp):
    return "\n\n".join(b.text for b in resp.content if b.type == "text").strip()


def _loop(client, s: Session, messages, kw):
    resp = None
    for _ in range(MAX_TOOL_ROUNDS):
        resp = _create(client, messages=messages, **kw)
        if resp.stop_reason in ("end_turn", "refusal", "max_tokens", "stop_sequence"):
            return resp
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        uses = [b for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for u in uses:
            try:
                out = s.run(u.name, dict(u.input or {}))
                results.append({"type": "tool_result", "tool_use_id": u.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str),
                                **({"is_error": True} if isinstance(out, dict) and "error" in out else {})})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": u.id, "is_error": True,
                                "content": f"Error: {type(e).__name__}: {e}"})
        messages.append({"role": "user", "content": results})
    return resp


def reply(messages, context, audience="general") -> dict:
    """The assistant's answer to the last user message."""
    hist = _clean_history(messages)
    if not hist or hist[-1]["role"] != "user":
        return {"reply": "Ask a question about the forecast on screen.", "source": "template", "evidence": [], "actions": []}
    s = Session(context)
    question = hist[-1]["content"]
    st = narrate.llm_status()
    out = None
    if st["llm_enabled"] and narrate._limiter.allow(int(os.environ.get("ASSISTANT_MAX_CALLS_PER_HOUR", "200"))):
        try:
            out = _claude_reply(s, hist, (context or {}).get("site_name"), audience)
        except Exception as e:
            log.warning("assistant chat: Claude failed: %s: %s", type(e).__name__, e)
            out = None
    if out is None:
        s = Session(context)
        out = template_reply(s, question, audience)
        out["note"] = ("The conversational assistant is off here; this is the standard explanation."
                       if not st["llm_enabled"] else "The assistant could not answer; this is the standard explanation.")
    out["evidence"] = [{"kind": r.get("kind"), "id": r.get("id")} for r in s.records]
    out["actions"] = s.actions
    return out


def _claude_reply(s: Session, hist, site_name, audience):
    client = narrate._get_client()
    kw = dict(model=os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5"), max_tokens=16000,
              system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
              tools=TOOLS, output_config={"effort": os.environ.get("ASSISTANT_EFFORT", "low")})
    note = _context_note(s, site_name) + f" Write for {narrate.AUDIENCES.get(audience, narrate.AUDIENCES['general'])}."
    messages = hist[:-1] + [{"role": "user", "content": f"{note}\n\nQuestion: {hist[-1]['content']}"}]
    resp = _loop(client, s, messages, kw)
    if resp is None or resp.stop_reason != "end_turn" or not _text(resp):
        return None
    text = _text(resp)
    allowed_from = s.records + [m["content"] for m in hist if m["role"] == "user"] + [{"lat": s.lat, "lon": s.lon}]
    bad = narrate.check_numbers({"summary": [text]}, allowed_from)
    if bad:                                                        # one chance to revise
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": "Revise your answer: these figures are not in the tool results: "
                         + ", ".join(bad) + ". Use only figures from the tool results, or leave them out."})
        resp = _loop(client, s, messages, kw)
        text = _text(resp) if resp is not None and resp.stop_reason == "end_turn" else ""
        allowed_from = s.records + [m["content"] for m in hist if m["role"] == "user"] + [{"lat": s.lat, "lon": s.lon}]
        bad = narrate.check_numbers({"summary": [text]}, allowed_from) if text else ["(no answer)"]
        if bad:
            log.warning("assistant chat: unsupported numbers after revision: %s", bad)
            return None
    return {"reply": text, "source": "claude", "model": resp.model, "checks": {"numbers_supported": True}}
