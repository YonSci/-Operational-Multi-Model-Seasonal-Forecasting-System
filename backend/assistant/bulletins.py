"""Bulletin Studio: bulletins composed from a snapshot of evidence records, checked, exported and versioned.

  snapshot()  gathers the evidence records a format needs (place or area outlook, what changed, draft advisory,
              attention ranking, field reports) and freezes them: the bulletin and every later check use only it
  compose()   writes the eight parts (where and when, observed, forecast, what changed, why it matters, options,
              what to monitor, what supports it) plus an SMS and an audio script: the template always, Claude when
              enabled, with every number checked against the snapshot
  check()     the advisory quality assistant: numbers not in the snapshot, wording more certain than a forecast
              can be, missing draft or experimental labels, empty parts
  export      Markdown, Word (.docx), SMS and audio-script text (print the web view for PDF)
Saved versions (Supabase table `bulletins`) need the reviewer token, so only the institution's editors keep them.
"""
import datetime as dt
import io
import json
import logging
import os
import re

from . import advisory, areas, evidence as ev, knowledge as kn, narrate, store
from . import feedback  # noqa: F401  (location records include nearby field reports)

log = logging.getLogger("assistant")
TABLE = "bulletins"

FORMATS = {
    "site_update": {"label": "Site update", "scope": "place",
                    "about": "Rain so far, the onset and season outlook, what changed and what to monitor at one place."},
    "seasonal_planning": {"label": "Seasonal planning bulletin", "scope": "place",
                          "about": "Season outlook, its chances and skill, and preparation options before sowing."},
    "crop_advisory": {"label": "Crop advisory", "scope": "place",
                      "about": "A crop- and stage-specific bulletin with the draft advisory options."},
    "technical_note": {"label": "Technical forecast note", "scope": "place",
                       "about": "Sources, method, comparison between runs, uncertainty and verification."},
    "regional": {"label": "County or regional bulletin", "scope": "area",
                 "about": "The outlook across a county or region and the areas needing attention."},
    "management_briefing": {"label": "Management briefing", "scope": "area",
                            "about": "A short account of the situation, the areas affected and the decisions approaching."},
    "multi_site": {"label": "Multi-site briefing", "scope": "sites",
                   "about": "One line per monitored site, then what they have in common."},
}
SECTIONS = [("where_when", "Where and when"), ("observed", "What has been observed"), ("forecast", "What is forecast"),
            ("what_changed", "What changed"), ("why_it_matters", "Why it matters"), ("options", "Options to consider"),
            ("monitor", "What to monitor next"), ("evidence", "What supports this")]
LENGTHS = {"short": 1, "standard": 3, "detailed": 99}


# ---------------------------------------------------------------------------- snapshot
def _previous(model):
    base, suffix = model.split(" - ")[0], model[len(model.split(" - ")[0]):]
    order = ["ECMWF SEAS5 (Sep)", "ECMWF SEAS5 (Oct)", "ECMWF SEAS5 (Oct+Obs)", "ECMWF SEAS5 (Oct+Obs latest)"]
    if base in order and order.index(base) > 0:
        return order[order.index(base) - 1] + suffix
    return None


def _sites(country):
    try:
        from kenya_api.sites import _SITES
        return [s for s in _SITES if (s.get("country") or "kenya").lower() == country.lower()]
    except Exception:
        return []


def snapshot(fmt, season, model, lat=None, lon=None, area_name=None, crop="maize_early", planted="unknown",
             sowing_date=None) -> dict:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {sorted(FORMATS)}")
    scope = FORMATS[fmt]["scope"]
    recs = {}
    if scope == "place":
        if lat is None or lon is None:
            raise ValueError("Choose a place for this bulletin")
        recs["place"] = ev.location(lat, lon, season, model)
        prev = _previous(model) if season == "short_rains" else None
        if prev and ev.model_info(season, prev):                 # only a run this method is served for
            try:
                recs["changes"] = ev.changes(lat, lon, season, model, prev)
            except Exception:
                pass
        if season == "short_rains" and fmt in ("crop_advisory", "seasonal_planning", "site_update"):
            decision = "establishment" if planted == "yes" else "sowing"
            recs["advisory"] = advisory.card(lat, lon, season, model, {"decision": decision, "crop": crop, "planted": planted,
                                                                        "sowing_date": sowing_date, "objective": "maturity"})
    elif scope == "area":
        if not area_name:
            raise ValueError("Choose a county or region for this bulletin")
        recs["area"] = areas.area(season, model, name=area_name)
        recs["attention_onset"] = areas.attention(season, model, "late_onset")
        recs["attention_season"] = areas.attention(season, model, "short_season")
    else:
        country = areas.country_of(season)
        for s in _sites(country):
            try:
                recs["site:" + s["site_name"]] = ev.location(s["lat"], s["lon"], season, model)
            except Exception as e:
                log.info("bulletin: site %s skipped: %s", s.get("site_name"), e)
        if not recs:
            raise ValueError("No monitored sites with a forecast for this season")
    info = ev.model_info(season, model)
    snap = {"format": fmt, "season": season, "model": model, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "issue_date": dt.date.today().isoformat(), "run": {"initialised": info.get("init_date"), "observations_through": info.get("obs_end"),
            "valid_period": [info.get("valid_start"), info.get("valid_end")]}, "records": recs}
    snap["id"] = ev.record_id(snap)
    return snap


# ---------------------------------------------------------------------------- template
def _place_name(rec):
    return (rec["scope"].get("site") or {}).get("name") or f"{rec['scope']['point']['lat']}, {rec['scope']['point']['lon']}"


def _q_line(name, q):
    if q.get("median") is None:
        return f"{name}: not available."
    f = narrate.fdate if q["unit"] == "date" else (lambda v: f"{v:g} days")
    s = f"{name}: {f(q['median'])}"
    lo, hi = q["range_80"]
    if lo and hi and lo != hi:
        s += f" (8 in 10 members {f(lo)} to {f(hi)})"
    if q.get("chances_pct"):
        s += "; chances " + ", ".join(f"{k} {v}%" for k, v in q["chances_pct"].items())
    return s + "."


def template(snap, audience="general", length="standard") -> dict:
    R = snap["records"]
    fmt = FORMATS[snap["format"]]
    run = snap["run"]
    sec = {k: [] for k, _ in SECTIONS}
    season_label = kn.SEASON_LABELS.get(snap["season"], (snap["season"],))[0]
    where = (_place_name(R["place"]) if "place" in R else R["area"]["scope"]["name"] if "area" in R
             else f"{len([k for k in R if k.startswith('site:')])} monitored sites")
    title = f"{fmt['label']}: {where}, {season_label}"
    sec["where_when"].append(f"{where}, {season_label}. Issued {narrate.fdate(snap['issue_date'])}; forecast initialised "
                             f"{narrate.fdate(run['initialised'])}" + (f", observations through {narrate.fdate(run['observations_through'])}." if run.get("observations_through") else "."))
    if "place" in R:
        p = R["place"]
        q = p["quantities"]
        if q["onset"].get("status") == "estimated_from_observations":
            sec["observed"].append(f"The rains have started: onset {narrate.fdate(q['onset']['median'])} under the {p['run']['method']['label']} "
                                   f"definition, from observed rain.")
        else:
            sec["observed"].append("No onset has been observed yet under the " + p["run"]["method"]["label"] + " definition.")
        fr = p.get("field_reports_nearby")
        if fr:
            sec["observed"].append(f"{fr['reports']} field report{'s' if fr['reports'] != 1 else ''} within {fr['radius_km']:g} km (" +
                                   ", ".join(f"{b['label'].lower()} {b['reports']}" for b in fr["by_type"].values()) + ").")
        for k in ("onset", "cessation", "lgp"):
            sec["forecast"].append(_q_line(q[k]["label"], q[k]))
        sk = q["onset"]["skill"]
        if sk.get("rpss") is not None:
            sec["evidence"].append(f"Onset skill here on the validation years: RPSS {sk['rpss']}, hit rate {sk['hit_rate']}.")
        lg = q["lgp"].get("chances_pct") or {}
        if lg:
            sec["why_it_matters"].append(f"The season is more likely long ({lg.get('long')}%) than short ({lg.get('short')}%)."
                                         if (lg.get("long") or 0) > (lg.get("short") or 0) else
                                         f"A short season is as likely or more likely than a long one ({lg.get('short')}% against {lg.get('long')}%).")
    if "changes" in R:
        sec["what_changed"] += narrate.template_changes(R["changes"])["local_implications"]
    elif "place" in R:
        sec["what_changed"].append("No earlier run of this season to compare with.")
    if "advisory" in R:
        a = R["advisory"]
        sec["why_it_matters"] += a["assessment"][:2]
        if a.get("best_for_objective"):
            sec["options"].append(f"Draft guidance (not yet reviewed): for reaching maturity, the option doing best in the "
                                  f"experimental crop outlook is {a['best_for_objective']}.")
        sec["options"] += a["tradeoffs"][:2]
        if not a["options"]:
            sec["options"].append(a["crop_outlook"].get("reason") or (a["caveats"][1] if len(a["caveats"]) > 1 else "No crop options here."))
        sec["monitor"] += a["review"][:2]
    if "area" in R:
        A = R["area"]
        sec["forecast"] += narrate.template_area(A)["summary"][1:]
        sec["why_it_matters"] += narrate.template_area(A)["local_implications"][:3]
        sec["what_changed"].append("Run comparisons are made per place; see the site updates.")
    for key in ("attention_onset", "attention_season"):
        if key not in R:
            continue
        att = R[key]
        if snap["format"] == "regional" and "area" in R:          # how this county or region ranks
            nm = R["area"]["scope"]["name"]
            rows = att["ranked_areas"]
            mine = next((i for i, r in enumerate(rows) if r["area"] == nm), None)
            full = areas.attention(snap["season"], snap["model"], att["criterion"]["id"], top=999)["ranked_areas"] if mine is None else rows
            mine = next((i for i, r in enumerate(full) if r["area"] == nm), None)
            if mine is not None:
                r = full[mine]
                sec["why_it_matters"].insert(0, f"{att['criterion']['label']}: {r['flagged_pct']}% of {nm}'s cells "
                                                f"({att['criterion']['test']}), rank {mine + 1} of {len(full)}.")
        else:
            t = narrate.template_attention(att)
            sec["why_it_matters"].append(t["summary"][0])
            sec["options"] += [f"Areas to watch: {x}" for x in t["local_implications"][:3]]
    sites = [(k[5:], r) for k, r in R.items() if k.startswith("site:")]
    for name, r in sites:
        q = r["quantities"]
        on = q["onset"]
        sec["forecast"].append(f"{name}: onset {narrate.fdate(on['median'])}" +
                               (" (observed)" if on.get("status") == "estimated_from_observations" else "") +
                               (f", most likely {on['most_likely']}" if on.get("most_likely") else "") +
                               (f"; season length {q['lgp']['median']:g} days." if q["lgp"]["median"] is not None else "."))
    if sites:
        started = [n for n, r in sites if r["quantities"]["onset"].get("status") == "estimated_from_observations"]
        sec["observed"].append(f"Rains already started at {len(started)} of {len(sites)} sites" + (f": {', '.join(started)}." if started else "."))
    if "area" in R and not sec["options"]:
        sec["options"].append("Draft advisory options are made per place: open the Advisory card for a site in this area.")
    if sites:
        for k in ("what_changed", "why_it_matters", "options"):
            if not sec[k]:
                sec[k].append("See each site's update for run comparisons and draft options.")
    if not sec["monitor"]:
        sec["monitor"].append("The next daily update, and the rainfall tracker for observed onset at the sites.")
    sec["evidence"].append(f"Forecast: {snap['model']}; method notes and skill in the dashboard's About and Forecast performance tabs.")
    caveats = []
    for r in R.values():
        for c in r.get("caveats", []):
            if c not in caveats:
                caveats.append(c)
    sec["evidence"] += caveats[: (2 if length == "short" else 4 if length == "standard" else 99)]
    n = LENGTHS.get(length, 3)
    sec = {k: v[:n] if k != "forecast" else v[: max(n, 3) if not sites else 99] for k, v in sec.items()}
    for k, _ in SECTIONS:
        if not sec[k]:
            sec[k] = ["Nothing to report."]
    first = sec["forecast"][0] if sec["forecast"] else ""
    sms = (f"{where}: {first}" + (" Draft advice in the full bulletin." if "advisory" in R else ""))[:300]
    audio = " ".join([sec["where_when"][0]] + sec["observed"][:1] + sec["forecast"][:3] + sec["why_it_matters"][:1] +
                     sec["monitor"][:1])
    return {"title": title, "sections": sec, "sms": sms, "audio_script": audio}


# ---------------------------------------------------------------------------- quality check
CERTAIN = re.compile(r"\b(certainly|definitely|guarantee\w*|sure to|no chance|cannot fail|will (?:definitely|surely)|"
                     r"(?:rains?|onset|season|harvest) will)\b", re.I)


def check(bulletin: dict, snap: dict) -> list:
    issues = []
    allowed = list(snap.get("records", {}).values()) + [snap.get("run"), snap.get("issue_date")]
    texts = [(k, line) for k, lines in (bulletin.get("sections") or {}).items() for line in (lines or [])]
    texts += [("sms", bulletin.get("sms") or ""), ("audio_script", bulletin.get("audio_script") or "")]
    for part, line in texts:
        bad = narrate.check_numbers({"summary": [line]}, allowed)
        if bad:
            issues.append({"part": part, "kind": "unsupported_number", "detail": f"Figures not in the evidence: {', '.join(bad)}", "text": line[:200]})
        m = CERTAIN.search(line)
        if m:
            issues.append({"part": part, "kind": "certainty", "detail": f"'{m.group(0)}' sounds more certain than a forecast can be", "text": line[:200]})
    full = " ".join(line for _, line in texts).lower()
    recs = snap.get("records", {})
    if "advisory" in recs and "draft" not in full:
        issues.append({"part": "options", "kind": "missing_label", "detail": "The advisory options must say they are draft guidance, not yet reviewed."})
    if ("advisory" in recs or "t/ha" in full) and "experimental" not in full:
        issues.append({"part": "evidence", "kind": "missing_label", "detail": "Crop figures must be labelled experimental."})
    for k, label in SECTIONS:
        if not [x for x in (bulletin.get("sections") or {}).get(k, []) if x and x.strip()]:
            issues.append({"part": k, "kind": "empty", "detail": f"'{label}' is empty."})
    if len(bulletin.get("sms") or "") > 320:
        issues.append({"part": "sms", "kind": "too_long", "detail": "The SMS is longer than two messages (320 characters)."})
    return issues


# ---------------------------------------------------------------------------- Claude
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "sections", "sms", "audio_script"],
          "properties": {"title": {"type": "string"},
                         "sections": {"type": "object", "additionalProperties": False, "required": [k for k, _ in SECTIONS],
                                      "properties": {k: {"type": "array", "items": {"type": "string"}} for k, _ in SECTIONS}},
                         "sms": {"type": "string", "description": "at most 300 characters"},
                         "audio_script": {"type": "string", "description": "to be read aloud on radio, 60 to 120 seconds"}}}


def compose(snap, audience="general", length="standard") -> dict:
    tpl = template(snap, audience, length)
    out = {**tpl, "source": "template", "model": None}
    st = narrate.llm_status()
    if st["llm_enabled"] and narrate._limiter.allow(int(os.environ.get("ASSISTANT_MAX_CALLS_PER_HOUR", "200"))):
        try:
            client = narrate._get_client()
            prompt = (f"Write a {FORMATS[snap['format']]['label']} ({FORMATS[snap['format']]['about']}) for "
                      f"{narrate.AUDIENCES.get(audience, narrate.AUDIENCES['general'])}. Length: {length}. Use the eight parts "
                      f"in the schema; each part is a list of short sentences. Start from the draft below and the "
                      f"evidence snapshot; keep every caution that applies. The SMS is at most 300 characters; the audio "
                      f"script is plain spoken text for radio.\n\nDraft:\n{json.dumps(tpl, ensure_ascii=False)}\n\n"
                      f"Evidence snapshot (JSON):\n{json.dumps(snap['records'], ensure_ascii=False, sort_keys=True)}")
            kw = dict(model=os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5"), max_tokens=16000,
                      system=[{"type": "text", "text": narrate.SYSTEM, "cache_control": {"type": "ephemeral"}}],
                      messages=[{"role": "user", "content": prompt}],
                      output_config={"effort": os.environ.get("ASSISTANT_EFFORT", "low"), "format": {"type": "json_schema", "schema": SCHEMA}})
            import anthropic
            try:
                resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
            except anthropic.BadRequestError:
                resp = client.messages.create(**kw)
            text = next((b.text for b in resp.content if b.type == "text"), None) if resp.stop_reason == "end_turn" else None
            if text:
                cand = json.loads(text)
                if not [i for i in check(cand, snap) if i["kind"] == "unsupported_number"]:
                    out = {**cand, "source": "claude", "model": resp.model}
                else:
                    out["note"] = "Standard draft shown: the assistant's draft quoted figures not in the evidence."
        except Exception as e:
            log.warning("bulletin: Claude failed: %s: %s", type(e).__name__, e)
            out["note"] = "Standard draft shown (the assistant is unavailable)."
    out["format"] = snap["format"]
    out["audience"] = audience
    out["length"] = length
    return out


# ---------------------------------------------------------------------------- export
def markdown(b: dict) -> str:
    lines = [f"# {b.get('title', 'Bulletin')}", ""]
    for k, label in SECTIONS:
        lines += [f"## {label}", ""] + [f"- {x}" for x in (b.get("sections") or {}).get(k, [])] + [""]
    lines += ["---", "Seasonal to Sub-seasonal Climate & Agricultural Intelligence System (ILRI / ICPAC)."]
    return "\n".join(lines)


def docx_bytes(b: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt
    d = Document()
    d.add_heading(b.get("title", "Bulletin"), level=1)
    for k, label in SECTIONS:
        d.add_heading(label, level=2)
        for x in (b.get("sections") or {}).get(k, []):
            d.add_paragraph(x, style="List Bullet")
    p = d.add_paragraph("Seasonal to Sub-seasonal Climate & Agricultural Intelligence System (ILRI / ICPAC).")
    p.runs[0].font.size = Pt(8)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------- versions
def save(b: dict, snap: dict, issues: list, author: str = None, parent_id: str = None, status: str = "draft") -> dict:
    if status not in ("draft", "reviewed", "published"):
        raise ValueError("status must be draft, reviewed or published")
    if status != "draft" and [i for i in issues if i["kind"] in ("unsupported_number", "missing_label")]:
        raise ValueError("Fix the unsupported figures and missing labels before marking it reviewed or published")
    version = 1
    if parent_id:
        prev = store.select(TABLE, eq={"id": parent_id}, limit=1)
        version = (prev[0].get("version") or 1) + 1 if prev else 1
    row = {"format": b.get("format"), "title": b.get("title"), "season": snap.get("season"), "audience": b.get("audience"),
           "length": b.get("length"), "sections": b.get("sections"), "sms": b.get("sms"), "audio_script": b.get("audio_script"),
           "snapshot": snap, "snapshot_id": snap.get("id"), "quality": issues, "version": version, "parent_id": parent_id,
           "status": status, "author": (author or "")[:80] or None}
    saved = store.insert(TABLE, row)
    return {"id": saved["id"], "version": version, "status": status, "storage": store.status()}


def saved(limit=50, status=None) -> list:
    rows = store.select(TABLE, eq={"status": status} if status else None, limit=limit)
    return [{k: r.get(k) for k in ("id", "created_at", "format", "title", "season", "audience", "version", "parent_id", "status", "author")}
            for r in rows]


def get(row_id: str):
    rows = store.select(TABLE, eq={"id": row_id}, limit=1)
    return rows[0] if rows else None
