"""Evidence records: the computed facts behind every explanation.

An evidence record holds everything an explanation may state, each value with its unit, date and source: the place
(name, grid cell, distance), the run (initialisation, observations through, valid period, method), each quantity's
median, range, normal, terciles, skill-weighted chances and status (forecast or estimated from observations), the
skill on the validation years, and the caveats that apply. Explanations, comparisons and (later) advisories and
bulletins are written from these records, so they agree with each other and with the dashboard.
"""
import datetime as dt
import hashlib
import json
import math

import numpy as np

import mam_loader as dl
from . import knowledge as kn

SCHEMA = "evidence/v1"
CELL_DEG = 0.25


# ---------------------------------------------------------------------------- helpers
def _num(v, nd=None):
    """A finite float (rounded to nd places), or None for missing, NaN and Inf."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd) if nd is not None else f


def _date(doy, year):
    """ISO date of a day of year (days past 365 run into the next year, as the search windows do)."""
    d = _num(doy)
    if d is None or year is None:
        return None
    return (dt.date(int(year), 1, 1) + dt.timedelta(days=int(round(d)) - 1)).isoformat()


def _doy(iso, year):
    """Day of year of an ISO date, counted from 1 Jan of `year` (so January of the next year is 366 on)."""
    if not iso or year is None:
        return None
    return (dt.date.fromisoformat(str(iso)[:10]) - dt.date(int(year), 1, 1)).days + 1


def _pct(p):
    v = _num(p)
    return None if v is None else round(v * 100)


def record_id(rec: dict) -> str:
    """A stable id of the record's content, so explanations can be cached and quoted by version."""
    body = json.dumps({k: v for k, v in rec.items() if k != "id"}, sort_keys=True, default=str)
    return hashlib.sha1(body.encode()).hexdigest()[:16]


def _sites():
    try:
        from kenya_api.sites import _SITES
        return list(_SITES)
    except Exception:
        return []


def _nearest_site(lat, lon, max_km=20.0):
    best = None
    for s in _sites():
        try:
            dy = (s["lat"] - lat) * 111.0
            dx = (s["lon"] - lon) * 111.0 * math.cos(math.radians(lat))
            d = math.hypot(dx, dy)
        except Exception:
            continue
        if d <= max_km and (best is None or d < best[0]):
            best = (d, s)
    if not best:
        return None
    d, s = best
    return {"name": s.get("site_name"), "county": s.get("county"), "lat": s.get("lat"), "lon": s.get("lon"),
            "distance_km": round(d, 1)}


def model_info(season, model):
    for m in dl.get_model_info(season=season) or []:
        if m.get("name") == model or m.get("raw_name") == model:
            return m
    return {}


# ---------------------------------------------------------------------------- one quantity at one place
def _quantity(key, m, px, year, obs_doy):
    q = kn.QUANTITIES[key]
    pre = {"onset": "on", "cessation": "cs", "lgp": "lg"}[key]
    pkey = {"onset": "p_on", "cessation": "p_cs", "lgp": "p_lgp"}[key]
    hr, rpss = _num(m.get(f"hr_{pre}"), 2), _num(m.get(f"rpss_{pre}"), 2)
    is_date = q["unit"] == "date"
    conv = (lambda v: _date(v, year)) if is_date else (lambda v: _num(v, 0))
    med = _num(m.get(f"{pre}_med"))
    normal = _num((px.get("chirps_clim") or {}).get(key))
    t33 = _num((px.get("t33") or {}).get(key))
    t67 = _num((px.get("t67") or {}).get(key))
    n = int(m.get("n_members") or m.get("nm") or 0)
    none = m.get(f"{pre}_none")
    probs = m.get(pkey) if isinstance(m.get(pkey), (list, tuple)) and len(m.get(pkey)) == 3 else None

    out = {
        "label": q["label"],
        "what": q["what"],
        "unit": q["unit"],
        "median": conv(med),
        "range_80": [conv(m.get(f"{pre}_p10")), conv(m.get(f"{pre}_p90"))],
        "normal": conv(normal),
        "anomaly_days": _num(m.get(f"{pre}_anom"), 1),
        "tercile_bounds": {"lower_third_until": conv(t33), "upper_third_from": conv(t67)},
        "members": n,
        "members_without": None if none is None or n == 0 else int(none),
    }
    if key == "onset":
        out["range_50"] = [conv(m.get("on_p25")), conv(m.get("on_p75"))]
    if probs is not None and t33 is not None and t67 is not None and t33 != t67:
        cats = q["cats"]
        out["chances"] = {cats[i]: _num(probs[i], 3) for i in range(3)}
        out["chances_pct"] = {cats[i]: _pct(probs[i]) for i in range(3)}
        dom = max(range(3), key=lambda i: _num(probs[i]) or 0)
        out["most_likely"] = cats[dom]
        out["chances_basis"] = "skill-weighted (alpha x members' chance + (1 - alpha) x 1/3)"
    else:
        out["chances"] = None
        out["chances_note"] = ("No tercile forecast: the observed record has no spread here (33rd = 67th percentile)"
                               if t33 is not None and t33 == t67 else "No tercile chances available")
    # members' own chance of each third, so the damping can be explained
    vals = m.get({"onset": "on_v", "cessation": "cs_v", "lgp": "lg_v"}[key])
    if isinstance(vals, list) and vals and t33 is not None and t67 is not None and t33 != t67:
        # as the landing page counts them: share of all members (a member with no date is in no third)
        v = np.array([_num(x) if _num(x) is not None else np.nan for x in vals], dtype=float)
        ok = np.isfinite(v)
        out["members_chances_pct"] = {q["cats"][0]: round(100 * float(np.sum(ok & (v < t33)) / v.size)),
                                      q["cats"][1]: round(100 * float(np.sum(ok & (v >= t33) & (v <= t67)) / v.size)),
                                      q["cats"][2]: round(100 * float(np.sum(ok & (v > t67)) / v.size))}
    # forecast or observed: where the members' dates sit against the observation cut-off
    if is_date and obs_doy is not None:
        p10, p90 = _num(m.get(f"{pre}_p10")), _num(m.get(f"{pre}_p90"))
        if p90 is not None and p90 <= obs_doy:
            out["status"] = "estimated_from_observations"
        elif p10 is not None and p10 <= obs_doy:
            out["status"] = "partly_observed"
        else:
            out["status"] = "forecast"
    else:
        out["status"] = "forecast" if med is not None else "unavailable"
    out["skill"] = {"hit_rate": hr, "rpss": rpss,
                    "beats_chance": None if hr is None else hr > 1 / 3,
                    "beats_climatology": None if rpss is None else rpss > 0,
                    "period": "validation years 2017-2024"}
    return out


# ---------------------------------------------------------------------------- location
def location(lat: float, lon: float, season: str, model: str, year=None) -> dict:
    """Evidence for one place: the forecast grid cell holding (lat, lon), for one run and method."""
    px = dl.get_pixel_stats(lat, lon, season=season, model=model or None, year=year)
    models = px.get("models") or {}
    m = models.get(model) or next(iter(models.values()), None)
    if m is None:
        raise ValueError(f"No forecast for {model or 'any model'} at ({lat}, {lon}) in {season}")
    name = model if model in models else next(iter(models))
    info = model_info(season, name)
    year = int(info.get("op_year") or year or dl._OP_YEAR)
    obs_end = info.get("obs_end")
    obs_doy = _doy(obs_end, year)
    season_label, country = kn.SEASON_LABELS.get(season, (season, None))
    method = kn.method_of(name)
    site = _nearest_site(lat, lon)

    rec = {
        "schema": SCHEMA,
        "kind": "location",
        "scope": {
            "type": "grid_cell",
            "description": f"the {CELL_DEG} degree forecast grid cell holding the point (about 28 km across)",
            "point": {"lat": round(lat, 4), "lon": round(lon, 4)},
            "cell_centre": {"lat": _num(px.get("glat"), 3), "lon": _num(px.get("glon"), 3)},
            "point_to_cell_centre_km": _num(px.get("delta_km"), 1),
            "site": site,
            "country": country,
            "climate_regime": px.get("regime_name"),
            "in_season_zone": bool(px.get("is_in_seasonal_zone", True)),
        },
        "season": {"id": season, "label": season_label, "year": year},
        "run": {
            "model": name,
            "system": "ECMWF SEAS5" if "SEAS5" in name else name,
            "initialised": info.get("init_date"),
            "observations_through": obs_end,
            "valid_period": [info.get("valid_start"), info.get("valid_end")],
            "members": int(m.get("n_members") or info.get("n_members") or 0),
            "weather_forecasts_joined": bool(info.get("weather")),
            "method": {k: method[k] for k in ("id", "label", "family", "question", "onset", "cessation", "data")},
        },
        "quantities": {k: _quantity(k, m, px, year, obs_doy) for k in ("onset", "cessation", "lgp")},
        "skill_weight_alpha": _num(m.get("alpha_on_px"), 2),
        "no_onset_share_pct": _pct(m.get("p_fail")),
    }
    rec["caveats"] = caveats(rec)
    rec["sources"] = sources(rec)
    rec["id"] = record_id(rec)
    return rec


def caveats(rec):
    """The limits that apply to this record, in plain words."""
    out = []
    q = rec["quantities"]
    if not rec["scope"]["in_season_zone"]:
        out.append("This place is outside the area where this season gives enough rain for a reliable onset.")
    on = q["onset"]
    if on.get("status") == "estimated_from_observations":
        out.append("The onset falls within the observed period: it is estimated from observed rain so far, not "
                   "forecast, and some methods can still revise it as later rain arrives.")
    for key in ("onset", "cessation", "lgp"):
        sk = q[key]["skill"]
        if sk["rpss"] is not None and sk["rpss"] <= 0:
            out.append(f"{q[key]['label']}: on the validation years the chances were no better than climatology "
                       f"(RPSS {sk['rpss']}), so read them as close to one in three.")
    if q["onset"].get("chances") is None and q["onset"].get("chances_note"):
        out.append(q["onset"]["chances_note"] + ".")
    if rec["run"]["weather_forecasts_joined"]:
        out.append("Experimental run: weather forecasts are joined in front of the seasonal forecast and the run "
                   "has not been tested on past seasons.")
    out.append("Values describe the forecast grid cell, not a measured field.")
    return out


def sources(rec):
    run = rec["run"]
    fao = "fao" in run["method"]["id"]
    return [
        {"what": "Forecast", "detail": f"{run['system']}, {run['members']} members, initialised {run['initialised']}"},
        {"what": "Observed rainfall", "detail": ("CHIRPS v3" if fao else "CHIRPS v2") +
         (f", through {run['observations_through']}" if run["observations_through"] else ", none (forecast only)")},
        {"what": "Method", "detail": f"{run['method']['label']}: {run['method']['data']}"},
        {"what": "Skill", "detail": "Hit rate and RPSS on the validation years 2017-2024; chances weighted by the "
                                    "skill fitted on the calibration years"},
    ]


# ---------------------------------------------------------------------------- what changed between two runs
def _shift(a, b):
    if not a or not b:
        return None
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def changes(lat, lon, season, model, compare_to, year=None) -> dict:
    """What changed from `compare_to` (the earlier run, or another method) to `model` at one place."""
    new = location(lat, lon, season, model, year)
    old = location(lat, lon, season, compare_to, year)
    rn, ro = new["run"], old["run"]
    inputs = []
    if ro["initialised"] != rn["initialised"]:
        inputs.append({"what": "forecast start", "from": ro["initialised"], "to": rn["initialised"]})
    if ro["observations_through"] != rn["observations_through"]:
        inputs.append({"what": "observations through", "from": ro["observations_through"] or "none",
                       "to": rn["observations_through"] or "none"})
    if ro["weather_forecasts_joined"] != rn["weather_forecasts_joined"]:
        inputs.append({"what": "weather forecasts joined", "from": ro["weather_forecasts_joined"],
                       "to": rn["weather_forecasts_joined"]})
    same_event = ro["method"]["id"] == rn["method"]["id"]
    if not same_event:
        inputs.append({"what": "method", "from": ro["method"]["label"], "to": rn["method"]["label"]})

    diffs = {}
    for key in ("onset", "cessation", "lgp"):
        a, b = old["quantities"][key], new["quantities"][key]
        d = {"label": b["label"], "unit": b["unit"], "from_median": a["median"], "to_median": b["median"],
             "from_status": a.get("status"), "to_status": b.get("status")}
        if b["unit"] == "date":
            d["median_shift_days"] = _shift(a["median"], b["median"])
            lo = _shift(a["range_80"][0], b["range_80"][0]) if a["range_80"][0] and b["range_80"][0] else None
            hi = _shift(a["range_80"][1], b["range_80"][1]) if a["range_80"][1] and b["range_80"][1] else None
            d["range_80_from"], d["range_80_to"] = a["range_80"], b["range_80"]
            wa = _shift(*a["range_80"]) if all(a["range_80"]) else None
            wb = _shift(*b["range_80"]) if all(b["range_80"]) else None
            d["range_width_change_days"] = None if wa is None or wb is None else wb - wa
            d["range_edge_shifts_days"] = [lo, hi]
        else:
            d["median_shift_days"] = None if a["median"] is None or b["median"] is None else b["median"] - a["median"]
            d["range_80_from"], d["range_80_to"] = a["range_80"], b["range_80"]
        if a.get("chances_pct") and b.get("chances_pct"):
            d["chances_pct_from"], d["chances_pct_to"] = a["chances_pct"], b["chances_pct"]
            d["chance_change_points"] = {c: b["chances_pct"][c] - a["chances_pct"][c] for c in b["chances_pct"]}
            d["most_likely_from"], d["most_likely_to"] = a.get("most_likely"), b.get("most_likely")
        diffs[key] = d

    rec = {
        "schema": SCHEMA,
        "kind": "changes",
        "scope": new["scope"],
        "season": new["season"],
        "from_run": {k: ro[k] for k in ("model", "initialised", "observations_through")} | {"method": ro["method"]["label"]},
        "to_run": {k: rn[k] for k in ("model", "initialised", "observations_through")} | {"method": rn["method"]["label"]},
        "same_event_definition": same_event,
        "input_changes": inputs,
        "differences": diffs,
        "attribution_note": ("The listed input changes are documented differences between the two runs; how much "
                             "each one moved the forecast is not computed."),
        "caveats": ([] if same_event else
                    ["The two runs use different methods, which define different events: the difference is between "
                     "definitions, not a forecast update."]) + new["caveats"],
        "sources": new["sources"],
        "from_evidence_id": old["id"],
        "to_evidence_id": new["id"],
    }
    rec["id"] = record_id(rec)
    return rec


# ---------------------------------------------------------------------------- a map layer
def _sector(lat, lon, clat, clon):
    ns = "north" if lat >= clat else "south"
    ew = "east" if lon >= clon else "west"
    return f"{ns}-{ew}"


def map_layer(variable: str, layer: str, model: str, season: str) -> dict:
    """Evidence for one map layer: what it shows, its distribution over the cells, where values are high and low,
    and its value at the monitored sites. Computed from the same grid the map draws."""
    g = dl.get_grid_stats(variable=variable, layer=layer, model=model or None, season=season)
    lats, lons = np.asarray(g["lats"], float), np.asarray(g["lons"], float)
    vals = np.asarray(g["values"], float)
    mask = np.isfinite(vals)
    if g.get("seasonal_mask") is not None:
        mask &= np.asarray(g["seasonal_mask"]).astype(bool)
    LA, LO = np.meshgrid(lats, lons, indexing="ij") if vals.shape == (lats.size, lons.size) else (None, None)
    if LA is None:
        raise ValueError("Unexpected grid shape")
    v, la, lo = vals[mask], LA[mask], LO[mask]
    if layer.startswith("prob_") or layer == "failure":
        v = v * 100.0                                  # chances as percent, as the legend shows them
    info = model_info(season, model) if model else {}
    year = int(info.get("op_year") or dl._OP_YEAR)
    is_date = variable in ("onset", "cessation") and layer in ("median", "chirps_p50")
    is_prob = layer.startswith("prob_") or layer == "failure"
    is_days = layer in ("anomaly", "spread") or (variable == "lgp" and layer in ("median", "chirps_p50"))
    fmt = ((lambda x: _date(x, year)) if is_date else (lambda x: _num(x, 0)) if is_prob
           else (lambda x: _num(x, 1 if is_days else 2)))
    season_label, country = kn.SEASON_LABELS.get(season, (season, None))
    what, misread = kn.LAYERS.get(layer, (layer, None))
    if layer in ("prob_bn", "prob_an") and variable in kn.QUANTITIES:      # name the third for this variable
        cat = kn.QUANTITIES[variable]["cats"][0 if layer == "prob_bn" else 2]
        what = (f"the chance of {'an' if cat[0] in 'aeiou' else 'a'} {cat} {kn.QUANTITIES[variable]['label'].lower()} "
                f"(the {'lower' if layer == 'prob_bn' else 'upper'} third of the observed record)")

    rec = {
        "schema": SCHEMA, "kind": "map",
        "layer": {"variable": variable, "layer": layer, "shows": f"{kn.QUANTITIES.get(variable, {}).get('label', variable)}: {what}",
                  "units": g.get("units"), "misreading_to_avoid": misread,
                  "display_unit": "date" if is_date else "%" if is_prob else "days" if is_days and variable != "rainfall" else None},
        "season": {"id": season, "label": season_label, "year": year},
        "run": {"model": model or "multi-model combination", "initialised": info.get("init_date"),
                "observations_through": info.get("obs_end"), "method": kn.method_of(model)["label"] if model else None},
        "cells": {"with_values": int(v.size), "cell_size_deg": CELL_DEG},
    }
    if v.size:
        q = np.percentile(v, [10, 50, 90])
        i_max, i_min = int(np.argmax(v)), int(np.argmin(v))
        rec["distribution"] = {"p10": fmt(q[0]), "median": fmt(q[1]), "p90": fmt(q[2]),
                               "max": {"value": fmt(v[i_max]), "lat": round(float(la[i_max]), 2), "lon": round(float(lo[i_max]), 2),
                                       "near_site": (_nearest_site(float(la[i_max]), float(lo[i_max]), 60) or {}).get("name")},
                               "min": {"value": fmt(v[i_min]), "lat": round(float(la[i_min]), 2), "lon": round(float(lo[i_min]), 2),
                                       "near_site": (_nearest_site(float(la[i_min]), float(lo[i_min]), 60) or {}).get("name")}}
        clat, clon = float(np.median(la)), float(np.median(lo))
        rec["by_sector"] = {}
        for sec in ("north-west", "north-east", "south-west", "south-east"):
            sel = np.array([_sector(a, b, clat, clon) == sec for a, b in zip(la, lo)])
            if sel.any():
                rec["by_sector"][sec] = {"cells": int(sel.sum()), "median": fmt(np.median(v[sel]))}
        rec["by_sector_note"] = f"Sectors split the mapped cells at {round(clat, 2)} N and {round(clon, 2)} E."
        if is_prob:
            rec["shares_pct"] = {"chance 50% or more": round(100 * float(np.mean(v >= 50))),
                                 "chance 40% or more": round(100 * float(np.mean(v >= 40))),
                                 "chance below 20%": round(100 * float(np.mean(v < 20)))}
        elif layer == "anomaly" and variable in ("onset", "cessation", "lgp"):
            lo_w, hi_w = ("shorter", "longer") if variable == "lgp" else ("earlier", "later")
            rec["shares_pct"] = {f"more than 7 days {lo_w} than normal": round(100 * float(np.mean(v < -7))),
                                 "within 7 days of normal": round(100 * float(np.mean(np.abs(v) <= 7))),
                                 f"more than 7 days {hi_w} than normal": round(100 * float(np.mean(v > 7)))}
        elif layer in ("rpss_val",):
            rec["shares_pct"] = {"above 0 (beats climatology)": round(100 * float(np.mean(v > 0)))}
        elif layer in ("hitrate_val",):
            rec["shares_pct"] = {"above 0.33 (beats chance)": round(100 * float(np.mean(v > 1 / 3)))}
        # the monitored sites in this country
        rec["sites"] = []
        for s in _sites():
            if country and (s.get("country") or "kenya").lower() != country.lower():
                continue
            i = int(np.abs(lats - s["lat"]).argmin()); j = int(np.abs(lons - s["lon"]).argmin())
            x = vals[i, j] * (100.0 if is_prob else 1.0)
            if np.isfinite(x):
                rec["sites"].append({"name": s.get("site_name"), "value": fmt(x)})
    rec["caveats"] = ["The map shows grid cells about 28 km across, not fields."] + (
        [misread] if misread else []) + (
        ["Chances are skill-weighted: where skill is low they sit near one in three."] if is_prob else [])
    rec["sources"] = [{"what": "Map layer", "detail": f"/grid variable={variable} layer={layer} season={season}"
                       + (f" model={model}" if model else "")}]
    rec["id"] = record_id(rec)
    return rec
