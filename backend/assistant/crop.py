"""The crop outlook page: evidence records from the published crop outlook (tracker/data/crop, written by the crop
engine and the daily run).

  outlook(site, variety, rule, run)   one crop at one site as the page shows it: how the members end (matured, died,
                                      failed to establish, too late, no sowing opportunity), the sowing window, yields
                                      if sown and over all members, the chance of a failed crop, harvest, against the
                                      past seasons (the same crop grown in the observed weather), the other crop models
                                      and how often they agree, how past forecasts did, the change since the previous
                                      update, and measured trial yields at the site
  compare(site, run)                  every crop and sowing rule at the site side by side

Every figure is read from the published files; nothing is modelled here. Experimental: the crop figures have not
been verified against observed crop outcomes.
"""
import math
import re

from . import crop_data, evidence as ev

SIMULATED = ("ok", "died", "failed_establishment")
MODELS = (("aquacrop", "AquaCrop"), ("wofost", "WOFOST"), ("dssat", "DSSAT"))
AGREE_LOW = 0.7                   # below this share of members agreeing on failure, the models disagree


def _pct(p):
    return None if p is None else int(round(100 * p))


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _index():
    ix = crop_data.load("index.json")
    if not ix:
        raise ValueError("The crop outlook cannot be read at the moment.")
    return ix


def find_site(ix, site=None, lat=None, lon=None, max_km=30.0):
    """(site id, site) by id, name (whole or part) or the nearest crop site within max_km."""
    S = ix.get("sites") or {}
    names = ", ".join(s["name"] for s in S.values())
    if site:
        if site in S:
            return site, S[site]
        low = site.strip().lower()
        for sid, s in S.items():
            if s["name"].lower() == low:
                return sid, s
        words = {w for w in re.findall(r"[a-z]+", low) if len(w) >= 4} - {"farm", "station", "research", "kenya"}
        best = max(S.items(), key=lambda kv: len(words & set(re.findall(r"[a-z]+", kv[1]["name"].lower()))), default=None)
        if best and words & set(re.findall(r"[a-z]+", best[1]["name"].lower())):
            return best
    if lat is not None and lon is not None:
        cand = [(sid, s, _km(lat, lon, s["lat"], s["lon"])) for sid, s in S.items() if s.get("lat") is not None]
        if cand:
            sid, s, d = min(cand, key=lambda t: t[2])
            if d <= max_km:
                return sid, s
    raise ValueError(f"The crop outlook covers these sites only: {names}.")


def _run(ix, run=None):
    runs = ix.get("runs") or []
    r = next((x for x in runs if x["id"] == run or x["source"] == run), None) if run else None
    return r or next((x for x in runs if x["source"] == "seasonal"), None) or (runs[0] if runs else None)


def _run_info(r):
    kind = ("seasonal forecast" if r["source"] == "seasonal" else "medium-range weather forecast" if r["source"].startswith("mr-")
            else "sub-seasonal forecast")
    return {"id": r["id"], "label": r["model_label"], "kind": kind, "initialised": r.get("run"),
            "observations_through": r.get("obs_end"), "members": r.get("members_kind")}


LABELS = {"ok": "matured", "died": "died before maturity", "failed_establishment": "failed to establish",
          "too_late": "too late to mature", "not_sown": "no sowing opportunity", "error": "model error"}


def _figures(s, fail_t):
    """The comparable figures of one summary (AquaCrop, WOFOST or DSSAT)."""
    if not s:
        return None
    ys, ya = s.get("yield_if_sown_t_ha") or {}, s.get("yield_t_ha") or {}
    sh = s.get("share") or {}
    pl = s.get("planting") or {}
    return {"members": s.get("members"), "members_sown": s.get("n_sown"), "members_with_model_error": s.get("n_error"),
            "outcomes_pct": {LABELS.get(k, k): _pct(v) for k, v in sh.items() if v is not None and not (k == "error" and not v)},
            "chance_of_sowing_opportunity_pct": _pct(s.get("p_sowing_opportunity")),
            "sowing": {"median": pl.get("median"), "p10": pl.get("p10"), "p90": pl.get("p90")} if pl.get("median") else None,
            "chance_establishment_fails_pct": _pct(s.get("p_establishment_failure")),
            "yield_if_sown_t_ha": {k: _r(ys.get(k)) for k in ("median", "p10", "p90")} if ys else None,
            "chance_of_failure_if_sown_pct": _pct(s.get("p_failure_if_sown")),
            "yield_all_members_t_ha": {k: _r(ya.get(k)) for k in ("median", "p10", "p90")} if ya else None,
            "chance_of_failure_pct": _pct(s.get("p_failure")),
            "failure_means_below_t_ha": fail_t,
            "harvest_median": s.get("harvest_median"),
            "season_rain_mm_median": _r(s.get("rain_mm_median"), 0),
            "water_stress_days_median": _r(s.get("stress_days_median"), 0),
            "irrigation_mm_median": _r(s.get("irrigation_mm_median"), 0),
            "water_limited_potential_t_ha_median": _r((s.get("potential_t_ha") or {}).get("median"))}


def _past(b, fail_t):
    if not b:
        return None
    ys = b.get("yield_if_sown_t_ha") or {}
    return {"yield_if_sown_t_ha": {k: _r(ys.get(k)) for k in ("median", "p10", "p90")},
            "chance_of_failure_if_sown_pct": _pct(b.get("p_failure_if_sown")),
            "chance_of_failure_pct": _pct(b.get("p_failure")),
            "chance_of_sowing_opportunity_pct": _pct(b.get("p_sowing_opportunity")),
            "chance_establishment_fails_pct": _pct(b.get("p_establishment_failure")),
            "seasons": b.get("n_valid"), "failure_means_below_t_ha": fail_t}


def _eff(m):
    return (m[2] or 0.0) if m[3] in SIMULATED else 0.0


def _agreement(a, b, fail_t):
    """Share of members on which two crop models give the same verdict (failed or not)."""
    pairs = [(x, y) for x, y in zip(a or [], b or []) if x and y and x[3] != "error" and y[3] != "error"]
    if not pairs:
        return None
    same = sum((_eff(x) < fail_t) == (_eff(y) < fail_t) for x, y in pairs)
    return {"members_compared": len(pairs), "same_verdict_pct": _pct(same / len(pairs))}


def _history(sid, variety, rule, source):
    h = crop_data.load("history.json") or {}
    keys = h.get("keys") or []
    out = []
    for e in (h.get("sources") or {}).get(source) or []:
        v = (((e.get("cells") or {}).get(sid) or {}).get(variety) or {}).get(rule)
        if v:
            d = dict(zip(keys, v))
            out.append({"date": e["date"], "observations_through": e.get("obs_end"),
                        "yield_if_sown_median_t_ha": d.get("yield_if_sown_median"),
                        "chance_of_failure_if_sown_pct": _pct(d.get("p_failure_if_sown")),
                        "chance_of_sowing_opportunity_pct": _pct(d.get("p_sowing_opportunity")),
                        "same_config_as_latest": e.get("config") == ((h.get("sources") or {}).get(source) or [{}])[-1].get("config")})
    return out


def outlook(site=None, variety="maize_early", rule=None, run=None, lat=None, lon=None) -> dict:
    """The crop outlook evidence record for one crop, sowing rule and forecast run at one crop site."""
    ix = _index()
    sid, s = find_site(ix, site, lat, lon)
    V = ix.get("varieties") or {}
    if variety not in V:
        raise ValueError(f"Crop must be one of {', '.join(V)}.")
    r = _run(ix, run)
    if not r:
        raise ValueError("The crop outlook has no forecast run.")
    summ = ((ix.get("summaries") or {}).get(r["id"]) or {}).get(sid, {}).get(variety) or {}
    rules = ix.get("planting_rules") or {}
    rule = rule if rule in summ else ("fao-agricultural" if "fao-agricultural" in summ else next(iter(summ), None))
    if not rule:
        raise ValueError(f"No crop outlook for {V[variety]['label']} at {s['name']} in this run.")
    v = V[variety]
    fail_t = v.get("failure_t_ha")
    main = _figures(summ[rule], fail_t)
    engines = {"AquaCrop": ix.get("engine")}
    others = {}
    runfile = crop_data.load(r.get("file") or (r["source"] + ".json")) or {}
    res = (((runfile.get("sites") or {}).get(sid) or {}).get("results") or {}).get(variety, {}).get(rule) or {}
    for key, name, label in (("wofost", "WOFOST", ix.get("second_engine")), ("dssat", "DSSAT", ix.get("third_engine"))):
        o = ((ix.get(key) or {}).get(r["id"]) or {}).get(sid, {}).get(variety, {}).get(rule)
        if o:
            engines[name] = label
            others[name] = {k: x for k, x in _figures(o, fail_t).items()
                            if k in ("yield_if_sown_t_ha", "chance_of_failure_if_sown_pct", "chance_of_failure_pct",
                                     "outcomes_pct", "harvest_median")}
            others[name]["agreement_with_aquacrop"] = _agreement(res.get("members"), (res.get(key) or {}).get("members"), fail_t)
    bench = crop_data.load("benchmark.json") or {}
    past = _past(((bench.get("sites") or {}).get(sid) or {}).get(variety, {}).get(rule), fail_t)
    skill = None
    sk = crop_data.load("skill.json") or {}
    if r["source"] == "seasonal":
        c = (((sk.get("seasonal") or {}).get("sites") or {}).get(sid) or {}).get(variety, {}).get(rule)
        if c and c.get("aquacrop"):
            made = (sk["seasonal"].get("made") or {}).get("aquacrop") or {}
            skill = {"forecast": "ECMWF SEAS5 1 Oct", "years": made.get("years"), "seasons": c["aquacrop"].get("n"),
                     "rank_correlation": {n: (c.get(k) or {}).get("r") for k, n in MODELS if c.get(k)},
                     "failure_roc_area": {n: (c.get(k) or {}).get("auc") for k, n in MODELS if c.get(k)},
                     "climate_predictors_rank_correlation": {"season length": (c.get("lgp") or {}).get("r"),
                                                             "Oct-Dec rain": (c.get("rain") or {}).get("r"),
                                                             "onset": (c.get("onset") or {}).get("r")},
                     "made_with_current_crop_configuration": made.get("config_hash") == sk["seasonal"].get("current_config"),
                     "how_to_read": "1 is a perfect ranking, 0 none; a failure ROC area of 0.5 is no better than chance"}
    hist = _history(sid, variety, rule, r["source"])
    since = None
    if len(hist) >= 2:
        a, b = hist[-2], hist[-1]
        since = {"previous_update": a["date"], "latest_update": b["date"],
                 "yield_if_sown_median_t_ha": [a["yield_if_sown_median_t_ha"], b["yield_if_sown_median_t_ha"]],
                 "chance_of_failure_if_sown_pct": [a["chance_of_failure_if_sown_pct"], b["chance_of_failure_if_sown_pct"]],
                 "chance_of_sowing_opportunity_pct": [a["chance_of_sowing_opportunity_pct"], b["chance_of_sowing_opportunity_pct"]],
                 "observations_through": [a["observations_through"], b["observations_through"]],
                 "same_crop_configuration": a["same_config_as_latest"]}
    crop_kind = "maize" if variety.startswith("maize") else variety
    trials = [{"crop": crop_kind, "median_t_ha": t.get("median_t_ha"), "p90_t_ha": t.get("p90_t_ha"), "trials": t.get("n"),
               "studies": t.get("studies"), "years": t.get("years")}
              for t in ((ix.get("observed_yields") or {}).get(sid) or {}).get(crop_kind) or []]
    rec = {"schema": ev.SCHEMA, "kind": "crop",
           "scope": {"site": s["name"], "site_id": sid, "lat": s.get("lat"), "lon": s.get("lon"),
                     "soil_water_holding_mm_per_m": s.get("soil_taw_100cm_mm")},
           "crop": {"id": variety, "label": v["label"], "examples": v.get("examples"), "maturity_days": v.get("maturity_days")},
           "sowing_rule": {"id": rule, "label": rules.get(rule, rule)},
           "run": _run_info(r), "engines": engines,
           "outlook": main, "past_seasons": past, "other_crop_models": others, "skill": skill,
           "since_previous_update": since, "trial_yields_at_site": trials}
    rec["caveats"] = _caveats(rec, ix)
    rec["sources"] = [{"what": "Crop outlook", "detail": f"{ix.get('engine')} with the members of {r['model_label']}"},
                      {"what": "Past seasons", "detail": "the same crop grown in the observed weather of past seasons"}]
    rec["id"] = ev.record_id(rec)
    return rec


def _caveats(rec, ix):
    c = ["Experimental: the crop figures have not been verified against observed crop outcomes.",
         "Yields are water-limited: no nutrient stress, pests, diseases or management losses, so they are an upper "
         "bound for smallholder fields.",
         "The crop is a maturity class, not a calibrated variety; the soil is the grid cell's average, not the field's."]
    low = [n for n, o in (rec["other_crop_models"] or {}).items()
           if (o.get("agreement_with_aquacrop") or {}).get("same_verdict_pct") is not None
           and o["agreement_with_aquacrop"]["same_verdict_pct"] < 100 * AGREE_LOW]
    if low:
        c.append(f"The crop models disagree here ({', '.join(low)} against AquaCrop on whether the crop fails): the "
                 f"outlook depends on the model as much as on the weather.")
    sk = rec.get("skill")
    if sk and not sk["made_with_current_crop_configuration"]:
        c.append("The skill scores were computed with an earlier crop configuration; they are rebuilt weekly.")
    if rec["run"]["kind"] != "seasonal forecast":
        c.append("A weather forecast covers only its first days or weeks; the rest of the season is the seasonal forecast.")
    sp = rec.get("since_previous_update")
    if sp and not sp["same_crop_configuration"]:
        c.append("The crop configuration changed between the two updates, so part of the change comes from the model setup.")
    return c


def compare(site=None, run=None, lat=None, lon=None) -> dict:
    """Every crop and sowing rule at one crop site, side by side (one run)."""
    ix = _index()
    sid, s = find_site(ix, site, lat, lon)
    r = _run(ix, run)
    summ = ((ix.get("summaries") or {}).get(r["id"]) or {}).get(sid) or {}
    V, rules = ix.get("varieties") or {}, ix.get("planting_rules") or {}
    rows = []
    for vk, by_rule in summ.items():
        for rk, x in by_rule.items():
            f = _figures(x, (V.get(vk) or {}).get("failure_t_ha"))
            rows.append({"crop": (V.get(vk) or {}).get("label", vk), "crop_id": vk, "sowing_rule": rules.get(rk, rk), "rule_id": rk,
                         "matured_pct": (f["outcomes_pct"] or {}).get("matured"),
                         "chance_of_sowing_opportunity_pct": f["chance_of_sowing_opportunity_pct"],
                         "yield_if_sown_median_t_ha": (f["yield_if_sown_t_ha"] or {}).get("median"),
                         "yield_if_sown_p10_t_ha": (f["yield_if_sown_t_ha"] or {}).get("p10"),
                         "chance_of_failure_pct": f["chance_of_failure_pct"],
                         "sowing_median": (f["sowing"] or {}).get("median"), "harvest_median": f["harvest_median"]})
    if not rows:
        raise ValueError(f"No crop outlook at {s['name']} in this run.")
    best = lambda key, rev=True: max(rows, key=lambda x: (x[key] is not None, (x[key] or 0) * (1 if rev else -1)))
    rec = {"schema": ev.SCHEMA, "kind": "crop_compare",
           "scope": {"site": s["name"], "site_id": sid, "lat": s.get("lat"), "lon": s.get("lon")},
           "run": _run_info(r), "rows": rows,
           "highest_maturity": {k: best("matured_pct")[k] for k in ("crop", "sowing_rule", "matured_pct")},
           "lowest_failure": {k: best("chance_of_failure_pct", rev=False)[k] for k in ("crop", "sowing_rule", "chance_of_failure_pct")},
           "highest_yield_if_sown": {k: best("yield_if_sown_median_t_ha")[k] for k in ("crop", "sowing_rule", "yield_if_sown_median_t_ha")},
           "caveats": ["Experimental: the crop figures have not been verified against observed crop outcomes.",
                       "Each crop is judged against its own failure threshold, so failure chances are not the same "
                       "yardstick across crops; compare yields with care across crops (a tonne of beans is not a "
                       "tonne of maize).",
                       "The sowing rules sow on different dates: they are different strategies, not different forecasts."]}
    rec["id"] = ev.record_id(rec)
    return rec
