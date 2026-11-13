"""Watches ("Did the advice change?") and the decision calendar.

A watch keeps a place, crop, field stage and decision with a baseline: the forecast and advisory figures when the
user last looked. Checking a watch compares today's evidence with that baseline and says what kind of change it is:
  forecast_changed     the forecast moved past the user's thresholds, but the advice is the same
  options_changed      new evidence changes which option does best (or none is available any more)
  stage_changed        a sowing was reported near the place since the baseline: the advice moves from preparation
                       to establishment
  status_changed       the onset went from forecast to observed
  stale                the evidence behind the advice is old or missing
Triggers are computed from the figures; the explanation is written from them. Watches are anonymous: each has a
private key, kept in the user's browser, needed to read, acknowledge or delete it (only its hash is stored).

The calendar lists the decisions and dates ahead for a crop at a place (sowing window, flowering and harvest,
end of the rains, next updates), each with its range and source.
"""
import datetime as dt
import hashlib
import secrets

from . import advisory, evidence as ev, feedback, narrate, store

TABLE = "watches"
DEFAULTS = {"chance_points": 15, "median_days": 7, "maturity_points": 10, "stale_days": 21}


def _hash(key):
    return hashlib.sha256(str(key).encode()).hexdigest()


def state(w) -> dict:
    """The figures a watch compares, today."""
    loc = ev.location(w["lat"], w["lon"], w["season"], w["model"])
    q = loc["quantities"]
    out = {"evidence_id": loc["id"], "observations_through": loc["run"]["observations_through"],
           "onset": {k: q["onset"].get(k) for k in ("median", "status", "chances_pct", "most_likely")},
           "cessation": {k: q["cessation"].get(k) for k in ("median", "chances_pct", "most_likely")},
           "lgp": {k: q["lgp"].get(k) for k in ("median", "chances_pct", "most_likely")}}
    if w["season"] == "short_rains":
        try:
            card = advisory.card(w["lat"], w["lon"], w["season"], w["model"],
                                 {"decision": w.get("decision"), "crop": w.get("crop"), "planted": w.get("planted"),
                                  "sowing_date": w.get("sowing_date"), "objective": w.get("objective") or "maturity"})
            ref = next((o for o in card["options"] if o.get("is_baseline")), None)
            out["advice"] = {"best": card.get("best_for_objective"), "options": [o["label"] for o in card["options"] if o.get("rank")][:3],
                             "reference_maturity_pct": ref.get("p_mature_pct") if ref else None,
                             "crop_outlook_available": card["crop_outlook"]["available"], "rules": [r["id"] for r in card["rules_used"]],
                             "card_id": card["id"]}
        except Exception as e:
            out["advice"] = {"error": str(e)}
    return out


def _days(a, b):
    return None if not a or not b else (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def compare(w: dict, base: dict, now: dict) -> list:
    th = {**DEFAULTS, **(w.get("thresholds") or {})}
    out = []
    for key, label in (("onset", "Onset"), ("cessation", "Cessation"), ("lgp", "Season length")):
        a, b = base.get(key) or {}, now.get(key) or {}
        ca, cb = a.get("chances_pct") or {}, b.get("chances_pct") or {}
        moved = [(c, ca[c], cb[c]) for c in cb if c in ca and abs(cb[c] - ca[c]) >= th["chance_points"]]
        if moved:
            out.append({"kind": "forecast_changed", "what": f"{label} chances",
                        "detail": "; ".join(f"{c} {x}% -> {y}%" for c, x, y in moved)})
        if key != "lgp":
            sh = _days(a.get("median"), b.get("median"))
        else:
            sh = None if a.get("median") is None or b.get("median") is None else b["median"] - a["median"]
        if sh is not None and abs(sh) >= th["median_days"]:
            out.append({"kind": "forecast_changed", "what": f"{label} median",
                        "detail": f"moved {abs(sh):g} days {'later' if sh > 0 else 'earlier'}" if key != "lgp"
                        else f"{abs(sh):g} days {'longer' if sh > 0 else 'shorter'}"})
    if (base.get("onset") or {}).get("status") != (now.get("onset") or {}).get("status") and \
            (now.get("onset") or {}).get("status") == "estimated_from_observations":
        out.append({"kind": "status_changed", "what": "Onset", "detail": "the rains have now started under this method (observed)"})
    ab, an = base.get("advice") or {}, now.get("advice") or {}
    if an.get("error"):
        out.append({"kind": "stale", "what": "Advice", "detail": "the advisory card could not be made: " + an["error"]})
    elif ab and an:
        if ab.get("best") != an.get("best"):
            out.append({"kind": "options_changed", "what": "Best option",
                        "detail": f"{ab.get('best') or 'none'} -> {an.get('best') or 'none'}"})
        if ab.get("crop_outlook_available") and not an.get("crop_outlook_available"):
            out.append({"kind": "stale", "what": "Crop options", "detail": "the crop outlook is not available at the moment"})
        x, y = ab.get("reference_maturity_pct"), an.get("reference_maturity_pct")
        if x is not None and y is not None and abs(y - x) >= th["maturity_points"]:
            out.append({"kind": "forecast_changed", "what": "Chance of reaching maturity (as sown by the rule)", "detail": f"{x}% -> {y}%"})
    obs = now.get("observations_through")
    age = _days(obs, dt.date.today().isoformat()) if obs else None
    if age is not None and age > th["stale_days"]:
        out.append({"kind": "stale", "what": "Observations", "detail": f"the forecast uses observations through {narrate.fdate(obs)}, {age} days ago"})
    if w.get("planted") != "yes":
        near = feedback.nearby(w["lat"], w["lon"], radius_km=10) or {}
        sd = near.get("sowing_dates_reported") or {}
        if sd.get("latest") and sd["latest"] >= str(w.get("baseline_at") or "")[:10]:
            out.append({"kind": "stage_changed", "what": "Field stage",
                        "detail": f"sowing reported nearby on {narrate.fdate(sd['latest'])}: if this field is sown, switch the watch to establishment"})
    return out


def verdict(changes: list) -> dict:
    kinds = {c["kind"] for c in changes}
    if not changes:
        return {"status": "unchanged", "headline": "No material change since you last looked."}
    if "options_changed" in kinds or "stage_changed" in kinds:
        return {"status": "advice_changed", "headline": "The advice has changed: review the options."}
    if "stale" in kinds:
        return {"status": "needs_review", "headline": "The evidence behind the advice is stale or missing: review before acting."}
    return {"status": "forecast_changed", "headline": "The forecast changed, but the advice is the same."}


# ---------------------------------------------------------------------------- storage operations
FIELDS = ("name", "lat", "lon", "place_name", "season", "model", "crop", "planted", "sowing_date", "decision", "objective")


def create(spec: dict) -> dict:
    w = {k: spec.get(k) for k in FIELDS}
    if w["lat"] is None or w["lon"] is None or not w["model"]:
        raise ValueError("A watch needs a place and a forecast run")
    w["lat"], w["lon"] = round(float(w["lat"]), 4), round(float(w["lon"]), 4)
    w["season"] = w["season"] or "short_rains"
    w["planted"] = w["planted"] if w["planted"] in ("yes", "no", "unknown") else "unknown"
    w["decision"] = w["decision"] or ("establishment" if w["planted"] == "yes" else "sowing")
    w["thresholds"] = {k: float(v) for k, v in (spec.get("thresholds") or {}).items() if k in DEFAULTS}
    key = secrets.token_urlsafe(24)
    w["key_hash"] = _hash(key)
    w["baseline"] = state(w)
    w["baseline_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    saved = store.insert(TABLE, w)
    return {"id": saved["id"], "key": key, "storage": store.status()}


def _get(wid, key):
    rows = store.select(TABLE, eq={"id": wid}, limit=1)
    if not rows or rows[0].get("key_hash") != _hash(key):
        raise PermissionError("No such watch, or the key is wrong")
    return rows[0]


def check(wid, key) -> dict:
    w = _get(wid, key)
    now = state(w)
    ch = compare(w, w.get("baseline") or {}, now)
    store.update(TABLE, wid, {"last_checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    return {"id": wid, "watch": {k: w.get(k) for k in FIELDS}, "baseline_at": w.get("baseline_at"), "changes": ch, **verdict(ch),
            "current": now}


def acknowledge(wid, key) -> dict:
    w = _get(wid, key)
    now = state(w)
    store.update(TABLE, wid, {"baseline": now, "baseline_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    return {"id": wid, "status": "acknowledged"}


def edit(wid, key, patch: dict) -> dict:
    w = _get(wid, key)
    upd = {k: patch[k] for k in ("name", "crop", "planted", "sowing_date", "decision", "objective") if k in patch}
    if "thresholds" in patch:
        upd["thresholds"] = {k: float(v) for k, v in (patch["thresholds"] or {}).items() if k in DEFAULTS}
    merged = {**w, **upd}
    upd["baseline"] = state(merged)
    upd["baseline_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    store.update(TABLE, wid, upd)
    return {"id": wid, "status": "updated"}


def remove(wid, key) -> None:
    _get(wid, key)
    store.delete(TABLE, wid)


# ---------------------------------------------------------------------------- the decision calendar
def calendar(lat, lon, season, model, crop="maize_early", planted="unknown", sowing_date=None) -> dict:
    loc = ev.location(lat, lon, season, model)
    q = loc["quantities"]
    today = dt.date.today().isoformat()
    events = []

    def add(what, date, rng=None, kind="forecast", note=None, source=None):
        if date:
            events.append({"what": what, "date": date, "range": rng, "kind": kind, "note": note, "source": source,
                           "past": date < today})
    on = q["onset"]
    if on["median"]:
        add("Onset of the rains (" + loc["run"]["method"]["label"] + ")", on["median"], on["range_80"],
            "observed" if on.get("status") == "estimated_from_observations" else "forecast",
            "from observed rain" if on.get("status") == "estimated_from_observations" else "8 in 10 members in the range",
            "seasonal forecast")
    cs = q["cessation"]
    if cs["median"]:
        add("End of the rains", cs["median"], cs["range_80"], "forecast", "cessation is harder to forecast than onset", "seasonal forecast")
    if season == "short_rains":
        try:
            card = advisory.card(lat, lon, season, model, {"decision": "establishment" if planted == "yes" else "sowing", "crop": crop,
                                                            "planted": planted, "sowing_date": sowing_date})
            c = advisory._crop(lat, lon, crop, advisory.sowing_rule_of(loc["run"]["method"]["id"]))
            if c.get("available"):
                summ = (c["summaries"].get(crop) or {}).get(c["rule"]) or {}
                sow = (summ.get("planting") or {})
                if planted != "yes":
                    add(f"Sowing by the {c['rules'].get(c['rule'], c['rule'])}", sow.get("median"), [sow.get("p10"), sow.get("p90")],
                        "forecast", "crop outlook (experimental)", "crop outlook")
                else:
                    add("Your sowing", sowing_date, None, "reported", None, "your watch")
                add(f"Harvest ({c['varieties'].get(crop, {}).get('label', crop)})", summ.get("harvest_median"), None, "forecast",
                    "median of the members that mature (experimental)", "crop outlook")
                from . import crop_data
                seas = crop_data.load("seasonal.json") or {}
                can = ((((seas.get("sites") or {}).get(c["site_id"]) or {}).get("results") or {}).get(crop, {}).get(c["rule"]) or {}).get("canopy") or {}
                if can.get("median"):
                    i = max(range(len(can["median"])), key=lambda k: can["median"][k])
                    peak = (dt.date.fromisoformat(can["start"]) + dt.timedelta(days=i * int(can.get("step_days", 7)))).isoformat()
                    add("Full canopy (water need at its peak, around flowering)", peak, None, "forecast",
                        "most sensitive stage to dry spells (experimental)", "crop outlook")
            for r in card["review"][:2]:
                events.append({"what": "Review the advice", "date": None, "range": None, "kind": "review", "note": r,
                               "source": "draft advisory rules", "past": False})
        except Exception:
            pass
    nxt = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    add("Next forecast update (daily, after 12:30 EAT)", nxt, None, "update", None, "platform")
    events.sort(key=lambda e: (e["date"] is None, e["date"] or ""))
    rec = {"schema": ev.SCHEMA, "kind": "calendar", "scope": loc["scope"], "season": loc["season"],
           "run": {k: loc["run"][k] for k in ("model", "initialised", "observations_through")},
           "crop": crop, "planted": planted, "events": events,
           "caveats": ["Dates are medians of the forecast members, with the 8-in-10 range where shown; crop dates come from "
                       "the experimental crop outlook."]}
    rec["id"] = ev.record_id(rec)
    return rec
