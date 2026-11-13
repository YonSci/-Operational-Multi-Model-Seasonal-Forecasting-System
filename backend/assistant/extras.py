"""The extra assistant features, all built on the same evidence records:

  analogues        past seasons (CHIRPS 1993-2025) most like this season's forecast at a place
  season_review    end-of-season review: the hindcast for each past season against what was observed
  lessons          guided learning: how to read each figure, with this forecast's own numbers and a check question
  scenario_plan    participatory scenario planning: the season's possible outcomes with their chances and what each
                   means for the crop, with discussion questions for a workshop
  official         official outlooks (ICPAC GHACOF, KMD, EMI) uploaded by hand, and their comparison with the platform
"""
import datetime as dt
import math

import numpy as np

import mam_loader as dl
from . import advisory, areas, crop_data, evidence as ev, knowledge as kn, narrate, store


def _cell(M, lat, lon):
    return int(np.abs(np.asarray(M["target_lat"]) - lat).argmin()), int(np.abs(np.asarray(M["target_lon"]) - lon).argmin())


def _state(season, model):
    M, info, oi = areas._model(season, model)
    return M, info, oi, int(info.get("op_year") or dl._OP_YEAR)


def _base(kind, loc, extra):
    rec = {"schema": ev.SCHEMA, "kind": kind, "scope": loc["scope"], "season": loc["season"],
           "run": {k: loc["run"][k] for k in ("model", "initialised", "observations_through")} | {"method": loc["run"]["method"]["label"]}}
    rec.update(extra)
    rec["id"] = ev.record_id(rec)
    return rec


# ---------------------------------------------------------------------------- analogues
def analogues(lat, lon, season, model, top=5) -> dict:
    loc = ev.location(lat, lon, season, model)
    M, info, oi, year = _state(season, model)
    i, j = _cell(M, lat, lon)
    ch = M["chirps_hist"]
    yrs = [int(y) for y in np.asarray(ch["chirps_years"])]
    on = np.asarray(ch["onset_doy"], float)[:, i, j]
    cs = np.asarray(ch["cessation_doy"], float)[:, i, j]
    lg = np.asarray(ch["lgp_days"], float)[:, i, j]
    q = loc["quantities"]
    f_on = ev._doy(q["onset"]["median"], year) if q["onset"]["median"] else None
    f_lg = q["lgp"]["median"]
    ok = np.isfinite(on) & np.isfinite(lg)
    if f_on is None or f_lg is None or ok.sum() < 5:
        raise ValueError("Not enough observed seasons or forecast here for analogues")
    sd_on, sd_lg = max(np.nanstd(on[ok]), 3.0), max(np.nanstd(lg[ok]), 3.0)
    d = np.sqrt(((on - f_on) / sd_on) ** 2 + ((lg - f_lg) / sd_lg) ** 2)
    order = [k for k in np.argsort(np.where(ok, d, np.inf)) if ok[k]][:top]
    rows = [{"year": yrs[k], "onset": ev._date(on[k], yrs[k]), "cessation": ev._date(cs[k], yrs[k]) if np.isfinite(cs[k]) else None,
             "season_length_days": int(lg[k]), "similarity_rank": r + 1} for r, k in enumerate(order)]
    return _base("analogues", loc, {
        "target": {"onset": q["onset"]["median"], "season_length_days": f_lg},
        "seasons_compared": int(ok.sum()), "years": [yrs[0], yrs[-1]], "analogues": rows,
        "how": "past seasons whose observed onset and season length (CHIRPS, at this grid cell) were closest to this "
               "season's forecast medians, each difference scaled by its year-to-year spread",
        "caveats": ["Analogue years are examples of seasons like this one, not probabilities: what happened in them need "
                    "not happen this year.", "Only onset and season length are matched, at one grid cell."],
        "sources": [{"what": "Observed seasons", "detail": f"CHIRPS {yrs[0]}-{yrs[-1]}, {loc['run']['method']['label']} method"}]})


# ---------------------------------------------------------------------------- end-of-season review
def season_review(lat, lon, season, model, years=5) -> dict:
    loc = ev.location(lat, lon, season, model)
    M, info, oi, year = _state(season, model)
    i, j = _cell(M, lat, lon)
    ch = M["chirps_hist"]
    obs_years = [int(y) for y in np.asarray(ch["chirps_years"])]
    myears = [int(y) for y in np.asarray(M["model_years"])]
    t33, t67 = float(M["t33_onset"][i, j]), float(M["t67_onset"][i, j])
    cats = ("early", "normal", "late")
    rows = []
    for y in sorted(set(obs_years) & set(myears), reverse=True):
        if len(rows) >= years:
            break
        yo, ym = obs_years.index(y), myears.index(y)
        o = float(np.asarray(ch["onset_doy"])[yo, i, j])
        mem = np.asarray(M["onset_doy"], float)[:, ym, i, j]
        if not np.isfinite(o) or not np.isfinite(mem).any() or not (math.isfinite(t33) and math.isfinite(t67)) or t33 == t67:
            continue
        probs = np.asarray(M["probs_damped"]["onset"], float)[:, ym, i, j]
        likely = cats[int(np.nanargmax(probs))] if np.isfinite(probs).all() else None
        seen = "early" if o < t33 else "late" if o > t67 else "normal"
        med = float(np.nanmedian(mem))
        rows.append({"year": y, "forecast_median": ev._date(med, y), "forecast_most_likely": likely,
                     "forecast_chances_pct": {c: round(100 * float(p)) for c, p in zip(cats, probs)} if np.isfinite(probs).all() else None,
                     "observed_onset": ev._date(o, y), "observed_third": seen,
                     "most_likely_was_right": likely == seen if likely else None, "median_error_days": int(round(med - o))})
    if not rows:
        raise ValueError("No past season with both a forecast and an observation here")
    judged = [r for r in rows if r["most_likely_was_right"] is not None]
    return _base("season_review", loc, {
        "quantity": "onset", "seasons": rows,
        "summary": {"seasons": len(rows), "most_likely_right": sum(r["most_likely_was_right"] for r in judged),
                    "median_abs_error_days": int(np.median([abs(r["median_error_days"]) for r in rows]))},
        "caveats": ["The forecasts reviewed are the hindcasts made the same way for past seasons, not the bulletins issued "
                    "at the time (those were not archived).", "A few seasons say little about skill: see the Forecast "
                    "performance tab for the validation over 2017-2024."],
        "sources": [{"what": "Hindcasts", "detail": f"{model}, same initialisation each year"},
                    {"what": "Observed", "detail": "CHIRPS onset at the grid cell"}]})


# ---------------------------------------------------------------------------- guided learning
def lessons(lat, lon, season, model) -> dict:
    loc = ev.location(lat, lon, season, model)
    q = loc["quantities"]
    on, lg = q["onset"], q["lgp"]
    f = narrate.fdate
    L = []
    if on.get("tercile_bounds", {}).get("lower_third_until"):
        tb = on["tercile_bounds"]
        L.append({"id": "terciles", "title": "Early, normal and late",
                  "text": dict(kn.GLOSSARY)["Terciles"],
                  "example": f"Here an onset before {f(tb['lower_third_until'])} counts as early and after {f(tb['upper_third_from'])} as late.",
                  "question": {"prompt": f"An onset on {f(tb['upper_third_from'])} or later here would be...", "options": ["early", "normal", "late"],
                               "answer": 2, "why": "It falls in the upper third of the observed record."}})
    if on.get("chances_pct"):
        c = on["chances_pct"]
        L.append({"id": "chances", "title": "What a chance means",
                  "text": "A chance of the late third is the chance the onset falls in that third. It is not how many days later, and "
                          "it is not a promise.",
                  "example": f"Here: early {c['early']}%, normal {c['normal']}%, late {c['late']}%.",
                  "question": {"prompt": f"A {c['late']}% chance of a late onset means...",
                               "options": [f"the onset will be {c['late']}% later", f"in about {c['late']} of 100 seasons like this, the onset would be late",
                                           "rain on fewer days"], "answer": 1, "why": "It is the share of outcomes in the late third."}})
    if on.get("members_chances_pct") and loc.get("skill_weight_alpha") is not None:
        mc = on["members_chances_pct"]
        L.append({"id": "skill_weighting", "title": "Why chances are pulled toward one in three",
                  "text": dict(kn.GLOSSARY)["Skill-weighted chances"],
                  "example": f"The members alone give early {mc['early']}%; with the skill weight {loc['skill_weight_alpha']} the chance shown is "
                             f"{on['chances_pct']['early']}%.",
                  "question": {"prompt": "Where the forecast has had little skill, the chances shown are...",
                               "options": ["close to one in three", "close to 100%", "unchanged"], "answer": 0,
                               "why": "Low skill moves every chance toward climatology."}})
    if on["median"]:
        lo, hi = on["range_80"]
        L.append({"id": "median_range", "title": "A median date is not a promise",
                  "text": dict(kn.GLOSSARY)["Median and range"],
                  "example": f"Median onset {f(on['median'])}" + (f"; 8 in 10 members between {f(lo)} and {f(hi)}." if lo and hi and lo != hi else "."),
                  "question": {"prompt": f"Will it rain on {f(on['median'])}?", "options": ["yes", "not necessarily: it is the middle of the members' dates"],
                               "answer": 1, "why": "The median is the middle of many possible seasons."}})
    if on.get("status"):
        L.append({"id": "observed", "title": "Forecast or observed?", "text": dict(kn.GLOSSARY)["Estimated from observations so far"],
                  "example": "Here the onset is " + ("estimated from observed rain so far." if on["status"] == "estimated_from_observations" else "still a forecast."),
                  "question": {"prompt": "An onset 'estimated from observations so far'...", "options": ["is certain and final", "comes from rain that has fallen, and can still be revised by some methods"],
                               "answer": 1, "why": "Later rain can change it under methods that look at the whole season."}})
    sk = on["skill"]
    if sk.get("rpss") is not None:
        L.append({"id": "skill", "title": "How good has this forecast been?", "text": dict(kn.GLOSSARY)["RPSS"] + " " + dict(kn.GLOSSARY)["Hit rate"],
                  "example": f"Here: RPSS {sk['rpss']}, hit rate {sk['hit_rate']}.",
                  "question": {"prompt": f"An RPSS of {sk['rpss']} means the forecast was...",
                               "options": ["better than climatology" if sk["rpss"] > 0 else "no better than climatology", "always right"],
                               "answer": 0, "why": "Above 0 beats climatology; 0 or below does not."}})
    L.append({"id": "methods", "title": "Methods answer different questions", "text": dict(kn.GLOSSARY)["Methods"],
              "example": f"This forecast uses {loc['run']['method']['label']}: {loc['run']['method']['question']}",
              "question": {"prompt": "Two methods give different onset dates. That means...", "options": ["one is wrong", "they define different events"],
                           "answer": 1, "why": "Each method answers its own question."}})
    return _base("lessons", loc, {"lessons": L})


# ---------------------------------------------------------------------------- participatory scenario planning
QUESTIONS = ["What would you do differently if the onset is late? If it is early?",
             "Which crops or varieties fit a short season here? A long one?",
             "What would make you decide to replant, and by which date is it too late?",
             "Which options in the table can households here actually afford and do (seed, labour, water)?",
             "What will you watch in the coming weeks, and who will tell whom when it changes?"]


def scenario_plan(lat, lon, season, model, crop="maize_early") -> dict:
    loc = ev.location(lat, lon, season, model)
    q = loc["quantities"]
    outcomes = []
    for key in ("onset", "lgp"):
        x = q[key]
        if x.get("chances_pct"):
            for cat, p in x["chances_pct"].items():
                outcomes.append({"quantity": x["label"], "outcome": cat, "chance_pct": p})
    crop_groups = None
    c = advisory._crop(lat, lon, crop, advisory.sowing_rule_of(loc["run"]["method"]["id"])) if season == "short_rains" else {"available": False}
    if c.get("available"):
        seas = crop_data.load("seasonal.json") or {}
        res = (((seas.get("sites") or {}).get(c["site_id"]) or {}).get("results") or {}).get(crop, {}).get(c["rule"]) or {}
        keys = (crop_data.load("index.json") or {}).get("member_keys") or []
        mem = [dict(zip(keys, r)) for r in res.get("members") or []]
        mem = [m for m in mem if m.get("rain_mm") is not None]
        if len(mem) >= 9:
            mem.sort(key=lambda m: m["rain_mm"])
            k = len(mem) // 3
            crop_groups = []
            for name, g in (("drier third of the members", mem[:k]), ("middle third", mem[k:len(mem) - k]), ("wetter third", mem[len(mem) - k:])):
                ys = [m.get("yield_t_ha") or 0.0 for m in g]
                crop_groups.append({"group": name, "members": len(g), "season_rain_mm": [round(g[0]["rain_mm"]), round(g[-1]["rain_mm"])],
                                    "median_yield_t_ha": round(float(np.median(ys)), 2),
                                    "matured_pct": round(100 * sum(1 for m in g if m.get("status") == "ok") / len(g))})
    return _base("scenario_plan", loc, {
        "outcomes": outcomes, "crop": (c.get("varieties", {}).get(crop) or {}).get("label", crop) if c.get("available") else None,
        "crop_site": c.get("site"), "crop_by_rain": crop_groups, "discussion_questions": QUESTIONS,
        "caveats": ["The outcome chances are the forecast's skill-weighted chances.",
                    "Crop groups split the crop outlook's members by their season rain; the crop figures are experimental.",
                    "The options to discuss come from the participants: the platform's draft advisories are a starting point only."]})


# ---------------------------------------------------------------------------- official outlooks
TABLE = "official_outlooks"
CATS = {"below": 0, "normal": 1, "above": 2, "early": 0, "late": 2}


def _norm_probs(d):
    """{'below','normal','above'} (or early/normal/late) in percent -> [p0, p1, p2] in 0-1."""
    out = [None, None, None]
    for k, v in d.items():
        if k in CATS and v is not None:
            out[CATS[k]] = float(v) / (100.0 if float(v) > 1 else 1.0)
    if None in out:
        raise ValueError("each area needs below/normal/above (or early/normal/late) chances")
    s = sum(out)
    if not 0.9 <= s <= 1.1:
        raise ValueError(f"chances must add up to 100 (got {round(100 * s)})")
    return out


def upload(spec: dict) -> dict:
    src = (spec.get("source") or "").strip()
    if not src or not spec.get("season") or not spec.get("year"):
        raise ValueError("source, season and year are required")
    variable = spec.get("variable") or "rainfall"
    if variable not in ("rainfall", "onset"):
        raise ValueError("variable must be rainfall or onset")
    regions = []
    for r in spec.get("regions") or []:
        regions.append({"name": r["name"], "probs": _norm_probs(r)})
    feats = []
    for f in (spec.get("geojson") or {}).get("features") or []:
        props = f.get("properties") or {}
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {"name": props.get("name"), "probs": _norm_probs(props)}})
    if not regions and not feats:
        raise ValueError("give the chances by area name (regions) or as GeoJSON polygons")
    row = {"source": src[:80], "season": spec["season"], "year": int(spec["year"]), "issued_on": spec.get("issued_on"),
           "variable": variable, "regions": regions, "geojson": {"type": "FeatureCollection", "features": feats} if feats else None,
           "uploaded_by": (spec.get("uploaded_by") or "")[:80] or None}
    saved = store.insert(TABLE, row)
    return {"id": saved["id"], "storage": store.status()}


def outlooks(season=None) -> list:
    rows = store.select(TABLE, eq={"season": season} if season else None, limit=50)
    return [{k: r.get(k) for k in ("id", "created_at", "source", "season", "year", "issued_on", "variable")} for r in rows]


def compare_official(outlook_id, model) -> dict:
    rows = store.select(TABLE, eq={"id": outlook_id}, limit=1)
    if not rows:
        raise ValueError("No such outlook")
    o = rows[0]
    season = o["season"]
    country = areas.country_of(season)
    lats, lons, _ = areas._grid("onset", "median", model, season)
    idx, names = areas.region_index(lats, lons, country)
    layers = [areas._grid(o["variable"], lay, model, season)[2] for lay in ("prob_bn", "prob_nn", "prob_an")]
    cats = ("below", "normal", "above") if o["variable"] == "rainfall" else ("early", "normal", "late")
    units = []
    for r in o.get("regions") or []:
        k = next((n for n, nm in enumerate(names) if nm and nm.lower() == r["name"].lower()), None)
        if k is not None:
            units.append((r["name"], idx == k, r["probs"]))
    if o.get("geojson"):
        from matplotlib.path import Path as MPath
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        pts = np.column_stack([LO.ravel(), LA.ravel()])
        for f in o["geojson"]["features"]:
            g = f["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            inside = np.zeros(pts.shape[0], bool)
            for p in polys:
                inside |= MPath(np.asarray(p[0], float)).contains_points(pts)
            units.append((f["properties"].get("name") or "area", inside.reshape(LA.shape), f["properties"]["probs"]))
    out_rows = []
    for name, mask, probs in units:
        plat = [float(np.nanmean(L[mask])) if np.isfinite(L[mask]).any() else None for L in layers]
        if None in plat:
            continue
        def likely(ps):                                   # no most likely third when the top two are within 3 points
            o = sorted(range(3), key=lambda k: -ps[k])
            return o[0] if ps[o[0]] - ps[o[1]] >= 0.03 else None
        a, b = likely(probs), likely(plat)
        out_rows.append({"area": name, "cells": int(mask.sum()),
                         "official_pct": {c: round(100 * p) for c, p in zip(cats, probs)},
                         "platform_pct": {c: round(100 * p) for c, p in zip(cats, plat)},
                         "official_most_likely": cats[a] if a is not None else None,
                         "platform_most_likely": cats[b] if b is not None else None,
                         "agree": (a == b) if a is not None and b is not None else None})
    if not out_rows:
        raise ValueError("No area of the outlook matches the platform's grid")
    info = ev.model_info(season, model)
    rec = {"schema": ev.SCHEMA, "kind": "outlook_comparison",
           "official": {k: o.get(k) for k in ("source", "season", "year", "issued_on", "variable")},
           "platform": {"model": model, "initialised": info.get("init_date"), "observations_through": info.get("obs_end")},
           "rows": out_rows, "summary": {"areas": len(out_rows), "comparable": sum(r["agree"] is not None for r in out_rows),
                                         "agree": sum(bool(r["agree"]) for r in out_rows)},
           "season_label": kn.SEASON_LABELS.get(season, (season,))[0],
           "caveats": ["The official outlook is a consensus of several models and expert judgement; the platform's chances "
                       "come from one forecast system, skill-weighted. Differences are expected and worth discussing.",
                       "Check that both describe the same quantity and period (e.g. October-December rainfall totals).",
                       "The platform's chances for an area are the average over its grid cells."],
           "sources": [{"what": "Official outlook", "detail": f"{o.get('source')}, issued {o.get('issued_on') or 'date not given'} (uploaded by hand)"},
                       {"what": "Platform", "detail": f"{model}, {o['variable']} tercile chances"}]}
    rec["id"] = ev.record_id(rec)
    return rec
