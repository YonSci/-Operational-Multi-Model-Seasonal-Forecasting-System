"""Explanations written from an evidence record.

The template explanation is always made. When ANTHROPIC_API_KEY is set (and ASSISTANT_LLM is not "0"), Claude
rewrites it for the chosen audience from the same evidence; every number in Claude's text must appear in the
evidence (checks below), or the template is returned instead. Results are cached by evidence id and audience, and
Claude calls are capped per hour, because the endpoint is public.

Environment:
  ANTHROPIC_API_KEY              enables Claude (keep it a server secret, e.g. a Render environment variable)
  ASSISTANT_LLM=0                turns Claude off (template only)
  ASSISTANT_MODEL                default claude-opus-5-5
  ASSISTANT_EFFORT               default low (the numbers are computed; the model only explains them)
  ASSISTANT_MAX_CALLS_PER_HOUR   default 200
"""
import datetime as dt
import json
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict, deque

from . import knowledge as kn

log = logging.getLogger("assistant")

AUDIENCES = {
    "general": "a general reader: plain language, short sentences, no jargon",
    "farmer": "a farmer: very plain language, local and practical, no technical terms, no acronyms",
    "extension": "an agricultural extension officer: plain but precise, name the method and what it means locally",
    "technical": "a researcher or forecaster: precise, name the method, skill scores and how the chances are made",
}

# ---------------------------------------------------------------------------- formatting
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fdate(iso):
    if not iso:
        return "not available"
    d = dt.date.fromisoformat(str(iso)[:10])
    return f"{d.day} {_MON[d.month - 1]}"


def _fmt(q, v):
    return fdate(v) if q["unit"] == "date" else (f"{int(v)} days" if v is not None else "not available")


def _days(n):
    n = abs(n)
    return f"{n:g} day" if n == 1 else f"{n:g} days"


def _val(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, str) and len(v) == 10 and v[4] == "-":
        return fdate(v)
    return v


def _mv(rec, v):
    """A map value as the map's legend reads it: a date, a percent or a number with its unit."""
    if v is None:
        return "not available"
    u = rec["layer"].get("display_unit")
    if u == "date":
        return fdate(v)
    if u == "%":
        return f"{v:g}%"
    if u == "days":
        return f"{v:g} days"
    return f"{v:g}"


def _where(x):
    if x.get("near_site"):
        return f"near {x['near_site']}"
    lat, lon = x["lat"], x["lon"]
    return f"at {abs(lat):g} {'S' if lat < 0 else 'N'}, {abs(lon):g} E"


def _status_phrase(status):
    return {"estimated_from_observations": "estimated from observed rain so far",
            "partly_observed": "partly within the observed period",
            "forecast": "forecast"}.get(status, "")


# ---------------------------------------------------------------------------- templates
def template_location(rec, audience="general"):
    q, run = rec["quantities"], rec["run"]
    place = rec["scope"]["site"]["name"] if rec["scope"].get("site") else (
        f"{rec['scope']['cell_centre']['lat']}, {rec['scope']['cell_centre']['lon']}")
    summary = [f"{rec['season']['label']} {rec['season']['year']} at {place}, {run['method']['label']} method, "
               f"run initialised {fdate(run['initialised'])}"
               + (f" with observations through {fdate(run['observations_through'])}." if run["observations_through"] else ".")]
    for key in ("onset", "cessation", "lgp"):
        x = q[key]
        if x["median"] is None:
            summary.append(f"{x['label']}: not available here.")
            continue
        s = f"{x['label']}, {_status_phrase(x.get('status'))}: {_fmt(x, x['median'])}"
        lo, hi = x["range_80"]
        if lo and hi and lo != hi:
            s += f", 8 in 10 members between {_fmt(x, lo)} and {_fmt(x, hi)}"
        elif lo and hi:
            s += ", 8 in 10 members on that date"
        if x["normal"] is not None and x["anomaly_days"] is not None:
            a = x["anomaly_days"]
            word = ("earlier" if a < 0 else "later") if x["unit"] == "date" else ("shorter" if a < 0 else "longer")
            s += f"; normal {_fmt(x, x['normal'])}, {_days(a)} {word}" if a else f"; normal {_fmt(x, x['normal'])}"
        summary.append(s + ".")
    on = q["onset"]
    if on.get("chances_pct"):
        c = on["chances_pct"]
        cats = list(c)
        s = (f"Chance of an {cats[0]}, {cats[1]} or {cats[2]} onset: {c[cats[0]]}%, {c[cats[1]]}% and {c[cats[2]]}% "
             f"(skill-weighted; most likely {on['most_likely']}).")
        if on.get("members_chances_pct") and rec.get("skill_weight_alpha") is not None:
            mc = on["members_chances_pct"]
            s += (f" The members alone give {mc[cats[0]]}%, {mc[cats[1]]}% and {mc[cats[2]]}%; the skill weight "
                  f"{rec['skill_weight_alpha']} pulls them toward one in three.")
        summary.append(s)

    local = []
    lg = q["lgp"]
    if on.get("status") == "estimated_from_observations":
        local.append(f"Under the {run['method']['label']} definition the rains here have already started "
                     f"({fdate(on['median'])}), judged from observed rain.")
    elif on.get("most_likely"):
        local.append(f"Under the {run['method']['label']} definition the forecast leans toward a {on['most_likely']} "
                     f"onset here.")
    if lg.get("chances_pct"):
        c = lg["chances_pct"]
        local.append(f"Season length: {c.get('short')}% chance of a short season, {c.get('long')}% of a long one.")
    sk = on["skill"]
    if sk["hit_rate"] is not None or sk["rpss"] is not None:
        parts = []
        if sk["hit_rate"] is not None:
            parts.append(f"hit rate {sk['hit_rate']} (chance 0.33)")
        if sk["rpss"] is not None:
            parts.append(f"RPSS {sk['rpss']} (above 0 beats climatology)")
        local.append("Onset skill here on the validation years: " + ", ".join(parts) + ".")
    if rec.get("no_onset_share_pct"):
        local.append(f"{rec['no_onset_share_pct']}% of members found no onset in the search window.")
    fr = rec.get("field_reports_nearby")
    if fr:
        parts = [f"{b['label'].lower()} {b['reports']}" + (f" (latest {fdate(b['latest_observed'])})" if b.get("latest_observed") else "")
                 for b in fr["by_type"].values()]
        ver = sum(b["verified"] for b in fr["by_type"].values())
        local.append(f"Field reports within {fr['radius_km']:g} km: " + "; ".join(parts) + f"; {ver} verified.")
        if fr.get("sowing_dates_reported"):
            sd = fr["sowing_dates_reported"]
            local.append(f"Reported sowing dates nearby: {fdate(sd['earliest'])} to {fdate(sd['latest'])}.")
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def template_changes(rec, audience="general"):
    fr, to = rec["from_run"], rec["to_run"]
    summary = [f"Comparing {fr['model']} with {to['model']}."]
    if rec["input_changes"]:
        summary.append("What differs between the runs: " + "; ".join(
            f"{c['what']} {_val(c['from'])} -> {_val(c['to'])}" for c in rec["input_changes"]) + ".")
    else:
        summary.append("The two runs have the same start, observations and method.")
    local = []
    for key, d in rec["differences"].items():
        if d["from_median"] is None or d["to_median"] is None:
            continue
        q = kn.QUANTITIES[key]
        f = (lambda v: fdate(v)) if d["unit"] == "date" else (lambda v: f"{int(v)} days")
        sh = d.get("median_shift_days")
        move = ("unchanged" if not sh else f"{_days(sh)} {'later' if sh > 0 else 'earlier'}" if d["unit"] == "date"
                else f"{_days(sh)} {'longer' if sh > 0 else 'shorter'}")
        s = f"{q['label']}: median {f(d['from_median'])} -> {f(d['to_median'])} ({move})"
        if d.get("chance_change_points"):
            cc = d["chance_change_points"]
            s += "; chances " + ", ".join(f"{c} {d['chances_pct_from'][c]}% -> {d['chances_pct_to'][c]}%"
                                          for c in cc)
            if d.get("most_likely_from") != d.get("most_likely_to"):
                local.append(f"{q['label']}: the most likely third is now {d['most_likely_to']} "
                             f"(it was {d['most_likely_from']}).")
        if d.get("from_status") != d.get("to_status") and d.get("to_status"):
            local.append(f"{q['label']}: now {_status_phrase(d['to_status'])} "
                         f"(was {_status_phrase(d.get('from_status')) or 'not available'}).")
        summary.append(s + ".")
    if not local:
        local.append("The most likely third and the forecast-or-observed status are the same in both runs.")
    if not rec["same_event_definition"]:
        local.append("The two methods define different events, so the difference is between definitions, not an update.")
    return {"summary": summary, "local_implications": local,
            "cautions": [rec["attribution_note"]] + list(rec["caveats"])}


def template_map(rec, audience="general"):
    L, run = rec["layer"], rec["run"]
    summary = [f"This map shows {L['shows']}, {rec['season']['label']} {rec['season']['year']}, "
               f"{run['model']}" + (f", {run['method']} method" if run.get("method") else "") + "."]
    d = rec.get("distribution")
    if d:
        summary.append(f"Across {rec['cells']['with_values']} grid cells the middle value is {_mv(rec, d['median'])}, "
                       f"and 8 in 10 cells lie between {_mv(rec, d['p10'])} and {_mv(rec, d['p90'])}.")
        summary.append(f"Highest {_mv(rec, d['max']['value'])} {_where(d['max'])}; "
                       f"lowest {_mv(rec, d['min']['value'])} {_where(d['min'])}.")
    local = []
    if rec.get("shares_pct"):
        local.append("Share of mapped cells: " + "; ".join(f"{k} {v}%" for k, v in rec["shares_pct"].items()) + ".")
    if rec.get("by_sector"):
        local.append("By part of the map (middle value): " + "; ".join(f"{k} {_mv(rec, v['median'])}" for k, v in rec["by_sector"].items()) + ".")
    if rec.get("sites"):
        local.append("At the monitored sites: " + "; ".join(f"{s['name']} {_mv(rec, s['value'])}" for s in rec["sites"]) + ".")
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def template_advisory(rec, audience="general"):
    a = rec["applies_to"]
    summary = [f"{rec['decision']['label']} for {a['crop']} ({a['stage']}) at {a['place']}, {a['season']}, "
               f"{a['method']} method."] + list(rec["assessment"])
    local = list(rec["why"])
    if rec.get("best_for_objective"):
        local.append(f"For the objective '{rec['objective']['label'].lower()}', the option that does best in the "
                     f"crop outlook is: {rec['best_for_objective']}.")
    local += list(rec["tradeoffs"])
    if rec["could_change"]:
        local.append("What could change this: " + " ".join(rec["could_change"]))
    if rec["review"]:
        local.append("When to look again: " + " ".join(rec["review"]))
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def _pcts(d):
    return ", ".join(f"{k} {v}%" for k, v in (d or {}).items())


def template_area(rec, audience="general"):
    sc, run = rec["scope"], rec["run"]
    nm = sc["name"][:1].upper() + sc["name"][1:]
    summary = [f"{nm} ({sc['cells']} grid cells), "
               f"{rec['season']['label']} {rec['season']['year']}, {run['method']} method."]
    local = []
    for key, q in rec["quantities"].items():
        cm = q["cell_medians"]
        f = (lambda v: fdate(v)) if q["unit"] == "date" else (lambda v: f"{v:g} days" if v is not None else "n/a")
        summary.append(f"{q['label']}: middle of the area {f(cm['median'])}; 8 in 10 cells between {f(cm['p10'])} and "
                       f"{f(cm['p90'])}.")
        if q.get("area_event_chances_pct"):
            local.append(f"{q['label']}, area-wide: {_pcts(q['area_event_chances_pct'])} of the members.")
        if q.get("average_cell_chances_pct"):
            local.append(f"{q['label']}, at a typical place (skill-weighted): {_pcts(q['average_cell_chances_pct'])}.")
        if q.get("cells_estimated_from_observations_pct"):
            local.append(f"{q['label']}: {q['cells_estimated_from_observations_pct']}% of the cells are already "
                         f"estimated from observed rain.")
    sk = rec.get("onset_skill_area_mean") or {}
    if sk:
        local.append("Onset skill, area average: " + ", ".join(
            f"{'RPSS' if k == 'rpss_val' else 'hit rate'} {v}" for k, v in sk.items()) + ".")
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def template_attention(rec, audience="general"):
    c = rec["criterion"]
    summary = [f"{c['label']} ({c['test']}): {rec['flagged_cells']} of {rec['cells_with_values']} grid cells, "
               f"{rec['season']['label']} {rec['season']['year']}, {rec['run']['method']} method."]
    u = "%" if c["value_unit"] == "%" else " days"
    local = [f"{r['area']}: {r['flagged_pct']}% of its {r['cells']} cells (average {r['mean_value']:g}{u})."
             for r in rec["ranked_areas"][:5] if r["flagged_cells"]]
    if not local:
        local = ["No area meets the test in this run."]
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def template_chart(rec, audience="general"):
    k = rec["chart"]
    if k == "member_dates":
        q = rec["quantity"]
        f = (lambda v: fdate(v)) if q["unit"] == "date" else (lambda v: f"{v:g} days" if v is not None else "n/a")
        summary = [f"The chart shows the {rec['members']} forecast members' {q['label'].lower()} at "
                   f"{(rec['scope'].get('site') or {}).get('name') or 'this place'}: median {f(rec['median'])}, 8 in 10 "
                   f"between {f(rec['range_80'][0])} and {f(rec['range_80'][1])}."]
        if rec["members"] > rec["members_with_value"]:
            summary.append(f"{rec['members'] - rec['members_with_value']} members have no date in the window.")
        busiest = max(rec["members_by_week"], key=lambda b: b["members"]) if rec["members_by_week"] else None
        local = ([f"Most members fall between {f(busiest['from'])} and {f(busiest['to'])} ({busiest['members']} members)."]
                 if busiest else []) + list(rec["reads"])
    elif k == "crop_outcomes":
        y = rec["yield_t_ha"]
        summary = [f"{rec['crop']} at {rec['scope']['crop_site']}, sown by the {rec['sowing_rule']}: median yield "
                   f"{y['median']} t/ha, 8 in 10 members between {y['p10']} and {y['p90']} t/ha."]
        local = ["Outcomes across the members: " + ", ".join(f"{k2} {v}" for k2, v in rec["outcomes"].items()) + "."]
        if rec.get("harvest_range"):
            local.append(f"Harvest between {fdate(rec['harvest_range'][0])} and {fdate(rec['harvest_range'][1])}.")
        if rec.get("canopy_peak"):
            local.append(f"The canopy peaks at {rec['canopy_peak']['cover']:g} of the ground in the week of "
                         f"{fdate(rec['canopy_peak']['week_of'])}.")
        local += list(rec["reads"])
    else:
        if rec.get("illustrative"):
            summary, local = list(rec["reads"]), []
        else:
            t = rec["season_total_mm"]
            summary = [f"Season rainfall in the members: median {t['median']} mm, 8 in 10 between {t['p10']} and {t['p90']} mm."]
            if rec.get("rain_so_far_mm") is not None:
                summary.append(f"Observed so far: {rec['rain_so_far_mm']} mm.")
            local = []
            if rec.get("next_30_days"):
                n = rec["next_30_days"]
                local.append(f"Next 30 days: longest dry spell in the median member {n['longest_dry_spell_days_median']} days; "
                             f"{n['members_with_dry_spell_10_days_or_more_pct']}% of members have a dry spell of 10 days or more.")
            local += list(rec["reads"])
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def template_analogues(rec, audience="general"):
    t = rec["target"]
    summary = [f"Past seasons most like this one (forecast onset {fdate(t['onset'])}, season {t['season_length_days']:g} days), "
               f"from {rec['seasons_compared']} observed seasons {rec['years'][0]}-{rec['years'][1]}:"]
    summary += [f"{a['year']}: onset {fdate(a['onset'])}" + (f", end {fdate(a['cessation'])}" if a.get("cessation") else "")
                + f", {a['season_length_days']} days." for a in rec["analogues"]]
    return {"summary": summary, "local_implications": [f"How they were chosen: {rec['how']}."], "cautions": list(rec["caveats"])}


def template_season_review(rec, audience="general"):
    sm = rec["summary"]
    summary = [f"Onset forecasts for the last {sm['seasons']} seasons at this place: the most likely third was right "
               f"{sm['most_likely_right']} times; the median was off by {sm['median_abs_error_days']} days in a typical season."]
    local = [f"{r['year']}: forecast {fdate(r['forecast_median'])}" + (f" (most likely {r['forecast_most_likely']})" if r.get("forecast_most_likely") else "")
             + f"; observed {fdate(r['observed_onset'])} ({r['observed_third']})." for r in rec["seasons"]]
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


def template_outlook_comparison(rec, audience="general"):
    o, sm = rec["official"], rec["summary"]
    summary = [f"{o['source']} {o['variable']} outlook for the {rec.get('season_label', o['season'])} {o['year']} against the "
               f"platform: the most likely third agrees in {sm['agree']} of the {sm['comparable']} areas where both have one "
               f"({sm['areas']} areas compared)."]
    local = [f"{r['area']}: official " + ", ".join(f"{k} {v}%" for k, v in r["official_pct"].items()) + "; platform "
             + ", ".join(f"{k} {v}%" for k, v in r["platform_pct"].items())
             + ("." if r["agree"] else " (they differ)." if r["agree"] is False else " (no clear most likely third in one of them).")
             for r in rec["rows"]]
    return {"summary": summary, "local_implications": local, "cautions": list(rec["caveats"])}


TEMPLATES = {"location": template_location, "changes": template_changes, "map": template_map,
             "advisory": template_advisory, "area": template_area, "attention": template_attention,
             "chart": template_chart, "analogues": template_analogues, "season_review": template_season_review,
             "outlook_comparison": template_outlook_comparison}

# ---------------------------------------------------------------------------- number checks
_NUM = re.compile(r"\d+(?:\.\d+)?")


def allowed_numbers(rec) -> set:
    """Every number an explanation may state: the record's values in the forms they can be written, and the numbers
    of the method notes."""
    out = set(str(i) for i in range(0, 13))
    out |= {"33", "0.33", "1", "3", "8", "10", "50", "80", "100"}

    def add(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            f = abs(float(x))
            if math.isnan(f) or math.isinf(f):
                return
            for nd in (0, 1, 2, 3):
                out.add(_norm(f"{round(f, nd):.{nd}f}"))
            out.add(str(math.floor(f))); out.add(str(math.ceil(f)))
            if f <= 1:                                     # a probability or score may be written as a percent
                for v in (round(f * 100), math.floor(f * 100), math.ceil(f * 100)):
                    out.add(str(v))
        elif isinstance(x, str):
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", x[:10]) if len(x) >= 10 else None
            if m:
                out.update({m.group(1), str(int(m.group(3))), str(int(m.group(2)))})
            for n in _NUM.findall(x):
                out.add(_norm(n))
        elif isinstance(x, dict):
            for v in x.values():
                add(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                add(v)
    add(rec)
    add(kn.reference_text())
    return out


def _norm(s):
    s = s.lstrip("0") or "0"
    if s.startswith("."):
        s = "0" + s
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def check_numbers(sections: dict, rec) -> list:
    """Numbers in the text that the evidence does not hold (empty when every number is supported)."""
    ok = allowed_numbers(rec)
    bad = []
    for sec in ("summary", "local_implications", "cautions"):
        for line in sections.get(sec) or []:
            for n in _NUM.findall(line):
                if _norm(n) not in ok:
                    bad.append(n)
    return sorted(set(bad))


# ---------------------------------------------------------------------------- Claude
SYSTEM = """You explain seasonal rainfall forecasts from the Seasonal to Sub-seasonal Climate & Agricultural \
Intelligence System (Kenya and Ethiopia: onset, cessation and length of the rainy season, rainfall tracking and crop \
outlooks).

You receive an evidence record (JSON) computed by the platform, a task and an audience. Write the explanation from \
that record only.

Rules:
- Every number, date and percentage you write must appear in the evidence record. Copy them exactly; do not round, \
add, subtract or estimate new numbers. If a figure you would like to give is not in the record, leave it out.
- Keep forecast and observation apart: when a quantity's status is estimated_from_observations, say it comes from \
observed rain so far, not from the forecast.
- The chances are skill-weighted. A chance of the early (or late) third is the chance the event falls in that third; \
it is not an amount earlier or later. A median date is not a promise of rain on that day.
- Name the onset method when it matters: the methods define different events.
- State the forecast's skill where the record gives it, and say plainly when it is low (RPSS at or below 0).
- Do not give farming instructions. Beyond what the forecast implies for timing and season length, mention only \
the options and guidance the record itself contains, as options to consider under the stated conditions.
- Keep every caution in the record that applies; put them in "cautions".
- Write dates as day and month (29 Oct), not as 2026-10-29.
- Plain text only: no markdown, no headings, no bullet characters. Short sentences.

Reference notes (the platform's documentation):
""" + kn.reference_text()

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": {"type": "string"}, "description": "2 to 5 sentences: what the evidence says"},
        "local_implications": {"type": "array", "items": {"type": "string"},
                               "description": "1 to 4 sentences: what it means at this place or on this map"},
        "cautions": {"type": "array", "items": {"type": "string"}, "description": "the limits that apply"},
    },
    "required": ["summary", "local_implications", "cautions"],
    "additionalProperties": False,
}

TASKS = {
    "location": "Explain what the current outlook means at this location.",
    "changes": "Explain what changed between the two forecast runs and why, using only the documented input changes. "
               "Do not claim how much each input caused the change.",
    "map": "Explain what this map shows, where the main patterns are, and how to read it correctly.",
    "area": "Explain the outlook for this area. Keep the two kinds of chance apart: the area-wide chances count "
            "members in which most of the area is in a third (not skill-weighted); the average cell chances are a "
            "typical place's skill-weighted chances.",
    "attention": "Explain which areas meet the criterion and how strongly, and what the ranking does and does not "
                 "mean (it is where the forecast shows the condition, not impact or damage).",
    "analogues": "Explain which past seasons were most like this one and how they turned out; say clearly that "
                 "analogues are examples, not probabilities.",
    "season_review": "Review how the onset forecasts did in past seasons at this place, plainly, without overstating "
                     "what a few seasons show.",
    "outlook_comparison": "Compare the official outlook with the platform's chances area by area, and explain why "
                          "they may differ without saying which is right.",
    "chart": "Explain what this chart shows and how to read it, with its figures. If the record says the chart is "
             "illustrative, say so plainly and give no rainfall figures.",
    "advisory": "Write the advisory card's text: the current assessment (summary) and, in local_implications, why "
                "these options, their trade-offs, what could change the assessment and when to look again. Present "
                "the options as options to consider, never as instructions. The guidance is a draft that no "
                "agronomist has reviewed, and the crop figures are experimental model results: say both in cautions.",
}


class _Limiter:
    def __init__(self):
        self.calls = deque()
        self.lock = threading.Lock()

    def allow(self, per_hour):
        now = time.time()
        with self.lock:
            while self.calls and now - self.calls[0] > 3600:
                self.calls.popleft()
            if len(self.calls) >= per_hour:
                return False
            self.calls.append(now)
            return True


_limiter = _Limiter()
_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()
_client = None


def llm_status() -> dict:
    on = bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("ASSISTANT_LLM", "1") != "0"
    return {"llm_enabled": on, "model": os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5") if on else None,
            "effort": os.environ.get("ASSISTANT_EFFORT", "low") if on else None}


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(timeout=60.0, max_retries=2)
    return _client


def _call_claude(kind, rec, audience):
    """Claude's sections for this record, or (None, reason)."""
    import anthropic
    client = _get_client()
    model = os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5")
    effort = os.environ.get("ASSISTANT_EFFORT", "low")
    user = (f"Task: {TASKS[kind]}\nAudience: {AUDIENCES.get(audience, AUDIENCES['general'])}\n"
            f"Evidence record (JSON):\n{json.dumps(rec, ensure_ascii=False, sort_keys=True)}")
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        # server-side fallback: if a safety classifier declines, the API retries on a fallback model in the same call
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError as e:
        log.warning("assistant: request with fallbacks rejected (%s); retrying without", e.message)
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        return None, "declined"
    if resp.stop_reason == "max_tokens":
        return None, "too long"
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None, "empty"
    return json.loads(text), resp.model


def explain(kind: str, rec: dict, audience: str = "general") -> dict:
    """The explanation of an evidence record: {source, model, sections, checks}."""
    audience = audience if audience in AUDIENCES else "general"
    key = (kind, rec["id"], audience)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    template = TEMPLATES[kind](rec, audience)
    out = {"source": "template", "model": None, "audience": audience, "sections": template,
           "checks": {"numbers_supported": True, "unsupported_numbers": []}}
    st = llm_status()
    if st["llm_enabled"]:
        if not _limiter.allow(int(os.environ.get("ASSISTANT_MAX_CALLS_PER_HOUR", "200"))):
            out["note"] = "The assistant is busy: showing the standard explanation."
        else:
            try:
                sections, info = _call_claude(kind, rec, audience)
                if sections is None:
                    out["note"] = f"Standard explanation shown (assistant: {info})."
                else:
                    bad = check_numbers(sections, rec)
                    if bad:
                        log.warning("assistant: unsupported numbers %s for %s", bad, rec["id"])
                        out["checks"] = {"numbers_supported": False, "unsupported_numbers": bad}
                        out["note"] = "Standard explanation shown: the assistant's text quoted figures not in the evidence."
                    else:
                        out.update(source="claude", model=info, sections=sections)
            except Exception as e:                               # never fail the request because of the model
                log.warning("assistant: Claude call failed: %s: %s", type(e).__name__, e)
                out["note"] = "Standard explanation shown (the assistant is unavailable)."
    out["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if out["source"] == "claude" or not st["llm_enabled"]:
        with _cache_lock:                                        # cache answers, not transient failures
            _cache[key] = out
            while len(_cache) > 512:
                _cache.popitem(last=False)
    return out
