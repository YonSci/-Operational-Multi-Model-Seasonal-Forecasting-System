"""Advisory cards: conditional guidance and option comparisons for one decision at one place.

A card joins three things, each kept apart in the record:
  - the evidence: the onset, cessation and season-length forecast at the place (evidence.location) and, near one of
    the monitored crop sites, the crop outlook and its management scenarios under the same forecast;
  - the guidance: the draft rules of advisory_rules.yaml whose conditions hold (text filled from the evidence);
  - the options: the decision's scenarios or crops, evaluated from the crop outlook and ranked by the user's
    objective, with the outlook as published (the baseline) kept for reference.

Nothing here is reviewed agronomic advice: every rule is a draft, and the crop outlook is experimental. The card
says both.
"""
import datetime as dt
import math
from pathlib import Path

import yaml

from . import crop_data
from . import evidence as ev

RULES_FILE = Path(__file__).with_name("advisory_rules.yaml")
CROP_SITE_KM = 25.0                        # as the Forecast tab's crop card (CropOutlookTab.jsx LINK_KM)
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def library():
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


def _fd(iso):
    if not iso:
        return None
    d = dt.date.fromisoformat(str(iso)[:10])
    return f"{d.day} {_MON[d.month - 1]}"


def _pct(p):
    return None if p is None else round(100 * float(p))


def _km(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def sowing_rule_of(method_id: str) -> str:
    """The crop outlook's sowing rule for the dashboard's onset method (as CropOutlookTab.jsx SOWING_RULE_OF)."""
    return "rule1" if method_id == "agri rule 1" else "fao-agricultural"


# ---------------------------------------------------------------------------- profile
PLANTED = ("yes", "no", "unknown")
WATER = ("rainfed", "irrigated")


def normalise(profile: dict, lib: dict) -> dict:
    p = dict(profile or {})
    p["planted"] = p.get("planted") if p.get("planted") in PLANTED else "unknown"
    p["water"] = p.get("water") if p.get("water") in WATER else "rainfed"
    p["crop"] = p.get("crop") or "maize_early"
    if p.get("decision") not in lib["decisions"]:
        p["decision"] = "establishment" if p["planted"] == "yes" else "sowing"
    if p.get("objective") not in lib["objectives"]:
        p["objective"] = "maturity"
    sd = p.get("sowing_date")
    try:
        p["sowing_date"] = dt.date.fromisoformat(sd).isoformat() if sd else None
    except ValueError:
        p["sowing_date"] = None
    return p


# ---------------------------------------------------------------------------- crop outlook
def _crop(lat, lon, variety, rule):
    """The crop outlook near (lat, lon): site, run, the variety's summary and its scenarios, or a reason."""
    index = crop_data.load("index.json")
    if not index:
        return {"available": False, "reason": "The crop outlook could not be read."}
    near = sorted(((sid, s, _km(lat, lon, s["lat"], s["lon"])) for sid, s in (index.get("sites") or {}).items()
                   if s.get("lat") is not None), key=lambda x: x[2])
    if not near:
        return {"available": False, "reason": "No crop sites in the crop outlook."}
    sid, site, km = near[0]
    if km > CROP_SITE_KM:
        return {"available": False, "nearest_site": site["name"], "nearest_km": round(km),
                "reason": f"Crop options exist only at the monitored crop sites; the nearest, {site['name']}, is "
                          f"{round(km)} km away."}
    run = next((r for r in index.get("runs") or [] if r.get("source") == "seasonal"), None)
    summ = (((index.get("summaries") or {}).get(run["id"] if run else "", {}).get(sid) or {}))
    scen_all = crop_data.load("scenarios.json") or {}
    scen = (((scen_all.get("sites") or {}).get(sid) or {}).get("results") or {})
    if variety not in summ:
        return {"available": False, "reason": f"No crop outlook for {variety} at {site['name']}."}
    return {"available": True, "site_id": sid, "site": site["name"], "distance_km": round(km, 1),
            "run": run, "varieties": index.get("varieties") or {}, "rules": index.get("planting_rules") or {},
            "summaries": summ, "scenarios": scen, "rule": rule if rule in (summ[variety] or {}) else next(iter(summ[variety])),
            "caveats": index.get("caveats") or [], "engine": index.get("engine")}


def metrics(r: dict) -> dict:
    """Comparable figures of one crop result (a summary or a scenario)."""
    if not r:
        return {}
    y = r.get("yield_if_sown_t_ha") or r.get("yield_t_ha") or {}
    share = r.get("share") or {}
    return {
        "yield_median": None if y.get("median") is None else round(y["median"], 2),
        "yield_p10": None if y.get("p10") is None else round(y["p10"], 2),
        "yield_p90": None if y.get("p90") is None else round(y["p90"], 2),
        "p_mature_pct": _pct(share.get("ok")),
        "p_failure_if_sown_pct": _pct(r.get("p_failure_if_sown")),
        "p_establishment_failure_pct": _pct(r.get("p_establishment_failure")),
        "p_too_late_pct": _pct(share.get("too_late")),
        "p_not_sown_pct": _pct(share.get("not_sown")),
        "irrigation_mm": None if r.get("irrigation_mm_median") is None else round(r["irrigation_mm_median"]),
        "sowing_median": (r.get("planting") or {}).get("median"),
        "harvest_median": r.get("harvest_median"),
    }


def options(decision: dict, crop: dict, variety: str, lib: dict) -> list:
    """The decision's options evaluated from the crop outlook."""
    if not crop.get("available"):
        return []
    rule = crop["rule"]
    names = lib.get("scenarios") or {}
    vlabel = lambda v: (crop["varieties"].get(v) or {}).get("label", v)
    out = []
    sc_keys = decision.get("scenario_options") or []
    v_keys = decision.get("variety_options") or []
    if v_keys and sc_keys:                                    # late sowings of each variety (replanting)
        for v in v_keys:
            for k in sc_keys:
                r = (((crop["scenarios"].get(v) or {}).get(rule) or {}).get(k))
                if r:
                    out.append({"id": f"{v}:{k}", "label": f"{vlabel(v)}: {names.get(k, k).lower()}",
                                "variety": v, "scenario": k, **metrics(r)})
    elif v_keys:                                              # crops / maturity classes sown by the rule
        for v in v_keys:
            r = ((crop["summaries"].get(v) or {}).get(rule))
            if r:
                out.append({"id": v, "label": vlabel(v), "variety": v, "scenario": "baseline",
                            "is_baseline": v == variety, **metrics(r)})
    else:                                                     # management scenarios for the chosen crop
        res = ((crop["scenarios"].get(variety) or {}).get(rule) or {})
        for k in sc_keys:
            r = res.get(k) if k != "baseline" else (res.get("baseline") or (crop["summaries"].get(variety) or {}).get(rule))
            if r:
                out.append({"id": k, "label": names.get(k, k), "variety": variety, "scenario": k,
                            "is_baseline": k == "baseline", **metrics(r)})
    return out


def rank(opts: list, objective: dict) -> list:
    key, higher = objective["key"], objective["better"] == "higher"

    def score(o):
        v = o.get(key)
        if v is None:
            return (1, 0, 0, 0)
        return (0, -v if higher else v, -(o.get("p_mature_pct") or 0), -(o.get("yield_median") or 0))
    ranked = sorted(opts, key=score)
    for i, o in enumerate(ranked):
        o["rank"] = i + 1
    return ranked


def tradeoffs(ranked: list, objective: dict) -> list:
    """Plain comparisons of the leading options with the reference (the baseline, or the chosen crop)."""
    ref = next((o for o in ranked if o.get("is_baseline")), None)
    lines = []
    for o in [x for x in ranked if not x.get("is_baseline") and not x.get("past")][:3]:
        parts = []
        if o.get("p_mature_pct") is not None:
            parts.append(f"{o['p_mature_pct']}% reach maturity" + (f" (reference {ref['p_mature_pct']}%)" if ref and ref.get("p_mature_pct") is not None else ""))
        if o.get("yield_median") is not None:
            parts.append(f"median yield {o['yield_median']} t/ha" + (f" (reference {ref['yield_median']})" if ref and ref.get("yield_median") is not None else ""))
        if o.get("yield_p10") is not None:
            parts.append(f"poor-year yield (1 in 10) {o['yield_p10']} t/ha")
        if o.get("irrigation_mm"):
            parts.append(f"{o['irrigation_mm']} mm of irrigation")
        if o.get("p_too_late_pct"):
            parts.append(f"{o['p_too_late_pct']}% too late to mature")
        if parts:
            lines.append(f"{o['label']}: " + "; ".join(parts) + ".")
    return lines


# ---------------------------------------------------------------------------- context and rules
def context(loc: dict, profile: dict, crop: dict, variety: str) -> tuple:
    """Flat values for the rule conditions (numbers) and for the text (formatted)."""
    q = loc["quantities"]
    on, cs, lg = q["onset"], q["cessation"], q["lgp"]
    val, txt = {}, {}

    def put(k, v, t=None):
        if v is not None:
            val[k] = v
            txt[k] = t if t is not None else (str(v) if not isinstance(v, float) else f"{v:g}")
    put("planted", profile["planted"])
    put("onset_status", on.get("status"))
    put("onset_median", on.get("median"), _fd(on.get("median")))
    put("onset_p10", on["range_80"][0], _fd(on["range_80"][0]))
    put("onset_p90", on["range_80"][1], _fd(on["range_80"][1]))
    if all(on["range_80"]):
        put("onset_range_days", ev._shift(*on["range_80"]))
    put("onset_rpss", on["skill"].get("rpss"))
    for name, x in (("onset", on), ("cessation", cs), ("lgp", lg)):
        for cat, p in (x.get("chances_pct") or {}).items():
            put(f"p_{name}_{cat}_pct", p)
        put(f"{name}_most_likely", x.get("most_likely"))
    put("lgp_median", lg.get("median"))
    put("method", loc["run"]["method"]["label"])
    if profile.get("sowing_date"):
        put("sowing_date", profile["sowing_date"], _fd(profile["sowing_date"]))
        txt["sown_on"] = f" on {_fd(profile['sowing_date'])}"
    else:
        txt["sown_on"] = ""
    if crop.get("available"):
        m = metrics((crop["summaries"].get(variety) or {}).get(crop["rule"]))
        put("crop_site", crop["site"])
        put("crop_label", (crop["varieties"].get(variety) or {}).get("label", variety))
        put("sowing_rule", crop["rules"].get(crop["rule"], crop["rule"]))
        for k in ("p_failure_if_sown_pct", "p_establishment_failure_pct", "p_mature_pct", "yield_median"):
            put("crop_" + k, m.get(k))
    return val, txt


def _holds(c, val):
    k, op, want = c["key"], c["op"], c.get("value")
    if op == "present":
        return k in val
    if op == "absent":
        return k not in val
    if k not in val:
        return False
    v = val[k]
    try:
        return {"in": lambda: v in want, "not_in": lambda: v not in want, "eq": lambda: v == want, "ne": lambda: v != want,
                "lt": lambda: v < want, "le": lambda: v <= want, "gt": lambda: v > want, "ge": lambda: v >= want}[op]()
    except TypeError:
        return False


class _Missing(dict):
    def __missing__(self, key):
        raise KeyError(key)


def apply_rules(lib, decision_id, val, txt) -> list:
    used = []
    for r in lib.get("rules") or []:
        if r["decision"] != decision_id or not all(_holds(c, val) for c in r.get("when") or []):
            continue
        try:
            filled = {f: " ".join(str(r.get(f) or "").split()).format_map(_Missing(txt))
                      for f in ("assessment", "why", "could_change", "review")}
        except KeyError:
            continue                                   # a figure the rule needs is not in the evidence here
        used.append({"id": r["id"], "status": r.get("status", "draft"), "reviewed_by": r.get("reviewed_by"), **filled})
    return used


# ---------------------------------------------------------------------------- the card
def card(lat: float, lon: float, season: str, model: str, profile: dict, year=None, today=None) -> dict:
    """The advisory card for one decision; `today` (a date) decides which sowing options are already past."""
    lib = library()
    p = normalise(profile, lib)
    dec = lib["decisions"][p["decision"]]
    obj = lib["objectives"][p["objective"]]
    loc = ev.location(lat, lon, season, model, year)
    crop = _crop(lat, lon, p["crop"], sowing_rule_of(loc["run"]["method"]["id"])) if season == "short_rains" else {
        "available": False, "reason": "Crop options are modelled for the Kenya Short Rains only."}
    val, txt = context(loc, p, crop, p["crop"])
    rules = apply_rules(lib, p["decision"], val, txt)
    today = (today or dt.date.today()).isoformat()
    opts = options(dec, crop, p["crop"], lib)
    past = []
    if p["decision"] in ("sowing", "replanting"):           # a sowing date already gone is no longer an option
        past = [o for o in opts if o.get("sowing_median") and o["sowing_median"] < today and not o.get("is_baseline")]
        for o in past:
            o["past"], o["rank"] = True, None
    opts = rank([o for o in opts if o not in past], obj) + past
    best = next((o for o in opts if o.get("rank") == 1), None)
    q = loc["quantities"]

    caveats = ["Draft guidance: these rules have not yet been reviewed by an agronomist or extension service."]
    if crop.get("available"):
        caveats.append("Crop options come from the experimental crop outlook (" + (crop.get("engine") or "AquaCrop") +
                       "); their modelled differences need field evidence before they are taken as established.")
        caveats += crop.get("caveats") or []
        if p["decision"] in ("sowing", "replanting"):
            caveats.append("Sowing-date options are counted from each forecast member's onset under the sowing rule, "
                           "not from today.")
        if p.get("sowing_date") and crop["run"]:
            sm = metrics((crop["summaries"].get(p["crop"]) or {}).get(crop["rule"])).get("sowing_median")
            if sm and abs(ev._shift(sm, p["sowing_date"])) > 7:
                caveats.append(f"Your sowing date ({_fd(p['sowing_date'])}) differs from the modelled sowing "
                               f"({_fd(sm)}) by more than a week, so the crop figures fit your field less well.")
    else:
        caveats.append(crop.get("reason", "No crop options here."))
    if past:
        caveats.append(f"{len(past)} sowing option(s) fall before today and are listed for reference only.")
    if p["decision"] == "crop_choice" and crop.get("available"):
        sm = metrics((crop["summaries"].get(p["crop"]) or {}).get(crop["rule"])).get("sowing_median")
        if sm and sm < today:
            caveats.append(f"The crops are modelled as sown at the rule's onset ({_fd(sm)}), which is already past; "
                           "later sowings shorten the season (see When to sow and Replanting).")
    if p["water"] == "irrigated":
        caveats.append("The crop outlook is rainfed unless an option adds irrigation.")
    caveats += [c for c in loc["caveats"] if c not in caveats]

    rec = {
        "schema": ev.SCHEMA,
        "kind": "advisory",
        "status": "draft",
        "decision": {"id": p["decision"], "label": dec["label"], "question": dec["question"]},
        "objective": {"id": p["objective"], "label": obj["label"]},
        "profile": p,
        "applies_to": {
            "place": loc["scope"]["site"]["name"] if loc["scope"].get("site") else loc["scope"]["point"],
            "crop_site": crop.get("site"), "crop_site_km": crop.get("distance_km"),
            "crop": (crop.get("varieties", {}).get(p["crop"]) or {}).get("label", p["crop"]),
            "stage": {"yes": "sown", "no": "not yet sown", "unknown": "sowing not stated"}[p["planted"]]
                     + (f" on {_fd(p['sowing_date'])}" if p.get("sowing_date") else ""),
            "water": p["water"],
            "season": f"{loc['season']['label']} {loc['season']['year']}",
            "method": loc["run"]["method"]["label"],
            "sowing_rule": crop.get("rules", {}).get(crop.get("rule")) if crop.get("available") else None,
        },
        "climate": {k: {"median": q[k]["median"], "range_80": q[k]["range_80"], "status": q[k].get("status"),
                        "chances_pct": q[k].get("chances_pct"), "most_likely": q[k].get("most_likely")}
                    for k in ("onset", "cessation", "lgp")},
        "assessment": [r["assessment"] for r in rules if r["assessment"]],
        "why": [r["why"] for r in rules if r["why"]],
        "options": opts,
        "best_for_objective": best["label"] if best else None,
        "tradeoffs": tradeoffs(opts, obj),
        "could_change": list(dict.fromkeys(r["could_change"] for r in rules if r["could_change"])),
        "review": list(dict.fromkeys(r["review"] for r in rules if r["review"])),
        "rules_used": [{"id": r["id"], "status": r["status"], "reviewed_by": r["reviewed_by"]} for r in rules],
        "crop_outlook": {"available": crop.get("available", False), "run": (crop.get("run") or {}).get("model_label"),
                         "observations_through": (crop.get("run") or {}).get("obs_end"), "engine": crop.get("engine"),
                         "reason": None if crop.get("available") else crop.get("reason")},
        "caveats": caveats,
        "sources": loc["sources"] + ([{"what": "Crop outlook", "detail": f"{crop.get('engine')}, {crop['run'].get('model_label')}, "
                                       f"observations to {crop['run'].get('obs_end')}, site {crop['site']}"}]
                                     if crop.get("available") and crop.get("run") else []) +
                   [{"what": "Advisory rules", "detail": f"advisory_rules.yaml version {lib.get('version')} (draft)"}],
        "location_evidence_id": loc["id"],
    }
    rec["id"] = ev.record_id(rec)
    return rec
