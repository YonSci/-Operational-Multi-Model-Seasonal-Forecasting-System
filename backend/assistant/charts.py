"""Chart evidence: what a dashboard chart shows, from the same data the chart draws.

  member_dates   the members' onset, cessation or season-length values at a place (the member-dates and
                 onset-distribution charts): the spread week by week, median and 8-in-10 range, members with no
                 date, the observed cut-off and the thirds of the observed record
  crop_outcomes  the crop outlook's members at the nearest crop site (yield distribution, outcomes, harvest dates,
                 canopy curve)
  rain_plume     the members' daily rainfall (precipitation and accumulated-anomaly plumes): rain so far, season
                 total and dry spells ahead. Only from the real forecast members: a server started without them
                 (LOAD_BC_DAILY=0) draws an illustrative plume from climatology, and the record says so instead
"""
import datetime as dt
import math

import numpy as np

import mam_loader as dl
from . import advisory, crop_data, evidence as ev, knowledge as kn

KINDS = ("member_dates", "crop_outcomes", "rain_plume")


def _base(rec_kind, season, model, extra):
    info = ev.model_info(season, model)
    season_label, _ = kn.SEASON_LABELS.get(season, (season, None))
    rec = {"schema": ev.SCHEMA, "kind": "chart", "chart": rec_kind,
           "season": {"id": season, "label": season_label, "year": int(info.get("op_year") or dl._OP_YEAR)},
           "run": {"model": model, "initialised": info.get("init_date"), "observations_through": info.get("obs_end"),
                   "method": kn.method_of(model)["label"]}}
    rec.update(extra)
    rec["id"] = ev.record_id(rec)
    return rec


def member_dates(lat, lon, season, model, quantity="onset"):
    if quantity not in kn.QUANTITIES:
        raise ValueError("quantity must be onset, cessation or lgp")
    loc = ev.location(lat, lon, season, model)
    year = loc["season"]["year"]
    px = dl.get_pixel_stats(lat, lon, season=season, model=model or None)
    m = (px.get("models") or {}).get(model) or next(iter((px.get("models") or {}).values()))
    vals = np.array([ev._num(v) if ev._num(v) is not None else np.nan for v in (m.get({"onset": "on_v", "cessation": "cs_v", "lgp": "lg_v"}[quantity]) or [])], float)
    fin = vals[np.isfinite(vals)]
    q = loc["quantities"][quantity]
    is_date = quantity != "lgp"
    bins = []
    if fin.size:
        step = 7
        lo, hi = int(np.floor(fin.min())), int(np.ceil(fin.max()))
        for a in range(lo, hi + 1, step):
            c = int(np.sum((fin >= a) & (fin < a + step)))
            if c:
                bins.append({"from": ev._date(a, year) if is_date else a,
                             "to": ev._date(a + step - 1, year) if is_date else a + step - 1, "members": c})
    extra = {
        "scope": loc["scope"],
        "quantity": {"id": quantity, "label": q["label"], "unit": q["unit"]},
        "members": int(vals.size), "members_with_value": int(fin.size),
        "median": q["median"], "range_80": q["range_80"], "normal": q["normal"],
        "tercile_bounds": q["tercile_bounds"], "status": q.get("status"),
        "members_by_week": bins,
        "reads": ["Each member is one possible season; the chart shows how they spread, not a single forecast.",
                  "Members to the left of the observation cut-off are taken from observed rain."],
        "caveats": [c for c in loc["caveats"] if "grid cell" in c or "observed period" in c],
        "sources": loc["sources"],
    }
    return _base("member_dates", season, model, extra)


def crop_outcomes(lat, lon, season, model, crop="maize_early", rule=None):
    loc = ev.location(lat, lon, season, model)
    rule = rule or advisory.sowing_rule_of(loc["run"]["method"]["id"])
    c = advisory._crop(lat, lon, crop, rule)
    if not c.get("available"):
        raise ValueError(c.get("reason", "No crop outlook here"))
    seas = crop_data.load("seasonal.json") or {}
    res = (((seas.get("sites") or {}).get(c["site_id"]) or {}).get("results") or {}).get(crop, {}).get(c["rule"]) or {}
    keys = (crop_data.load("index.json") or {}).get("member_keys") or ["planting", "harvest", "yield_t_ha", "status"]
    mem = [dict(zip(keys, r)) for r in res.get("members") or []]
    if not mem:
        raise ValueError("No crop members for this choice")
    ys = np.array([x.get("yield_t_ha") or 0.0 for x in mem], float)
    harv = sorted(x["harvest"] for x in mem if x.get("harvest"))
    status = {}
    for x in mem:
        status[x.get("status")] = status.get(x.get("status"), 0) + 1
    can = res.get("canopy") or {}
    peak = None
    if can.get("median"):
        i = int(np.argmax(can["median"]))
        peak = {"cover": round(float(can["median"][i]), 2),
                "week_of": (dt.date.fromisoformat(can["start"]) + dt.timedelta(days=i * int(can.get("step_days", 7)))).isoformat()}
    labels = {o["id"]: o["label"] for o in (crop_data.load("index.json") or {}).get("outcomes", [])}
    extra = {
        "scope": {"crop_site": c["site"], "distance_km": c["distance_km"]},
        "crop": (c["varieties"].get(crop) or {}).get("label", crop), "sowing_rule": c["rules"].get(c["rule"], c["rule"]),
        "members": len(mem),
        "yield_t_ha": {"p10": round(float(np.percentile(ys, 10)), 2), "median": round(float(np.median(ys)), 2),
                       "p90": round(float(np.percentile(ys, 90)), 2)},
        "outcomes": {labels.get(k, k): v for k, v in status.items()},
        "harvest_range": [harv[int(0.1 * (len(harv) - 1))], harv[int(0.9 * (len(harv) - 1))]] if harv else None,
        "canopy_peak": peak,
        "reads": ["Yields are those of crops grown in each forecast member, water-limited unless stated."],
        "caveats": [(c.get("caveats") or ["Experimental crop outlook."])[0]],
        "sources": [{"what": "Crop outlook", "detail": f"{c.get('engine')}, {(c.get('run') or {}).get('model_label')}"}],
    }
    return _base("crop_outcomes", season, model, extra)


def bc_is_real() -> bool:
    """Whether this server holds the forecast members' daily rain (else the plume is drawn from climatology)."""
    return bool(dl._LOAD_BC)


def rain_plume(lat, lon, season, model):
    loc = ev.location(lat, lon, season, model)
    if not bc_is_real():
        extra = {"scope": loc["scope"], "illustrative": True,
                 "reads": ["On this server the rainfall plume is illustrative: drawn from the observed climatology with "
                           "random variation, not from the forecast members (their daily rain is not loaded here)."],
                 "caveats": ["Use the onset, cessation and season-length figures, which do come from the forecast members."],
                 "sources": loc["sources"]}
        return _base("rain_plume", season, model, extra)
    px = dl.get_pixel_stats(lat, lon, season=season, model=model or None)
    m = (px.get("models") or {}).get(model) or next(iter((px.get("models") or {}).values()))
    bc = np.asarray(m.get("bc_pixel") or [], float)
    if bc.ndim != 2 or bc.size == 0:
        raise ValueError("No daily rainfall members here")
    year = loc["season"]["year"]
    w0 = int(m.get("win_doy_start") or px.get("win_doy_start") or 1)
    obs_end = loc["run"]["observations_through"]
    k_obs = (ev._doy(obs_end, year) - w0 + 1) if obs_end else 0
    k_obs = max(0, min(k_obs, bc.shape[1]))
    tot = np.nansum(bc, axis=1)
    so_far = np.nansum(bc[:, :k_obs], axis=1) if k_obs else np.zeros(bc.shape[0])
    ahead = bc[:, k_obs:k_obs + 30]

    def longest_dry(r):
        best = cur = 0
        for x in r:
            cur = cur + 1 if (not np.isfinite(x) or x < 1.0) else 0
            best = max(best, cur)
        return best
    dry = np.array([longest_dry(r) for r in ahead]) if ahead.size else np.array([])
    extra = {
        "scope": loc["scope"], "illustrative": False,
        "window": [ev._date(w0, year), ev._date(w0 + bc.shape[1] - 1, year)],
        "rain_so_far_mm": round(float(np.median(so_far)), 1) if k_obs else None,
        "season_total_mm": {"p10": round(float(np.percentile(tot, 10)), 1), "median": round(float(np.median(tot)), 1),
                            "p90": round(float(np.percentile(tot, 90)), 1)},
        "next_30_days": None if not dry.size else {
            "longest_dry_spell_days_median": int(np.median(dry)),
            "members_with_dry_spell_10_days_or_more_pct": round(100 * float(np.mean(dry >= 10)))},
        "reads": ["Days up to the observation cut-off are observed rain; after it, each line is one forecast member."],
        "caveats": ["Dry spell: consecutive days below 1 mm in a member's forecast, at the grid cell."],
        "sources": loc["sources"],
    }
    return _base("rain_plume", season, model, extra)


def chart(kind, lat, lon, season, model, quantity="onset", crop="maize_early"):
    if kind == "member_dates":
        return member_dates(lat, lon, season, model, quantity)
    if kind == "crop_outcomes":
        return crop_outcomes(lat, lon, season, model, crop)
    if kind == "rain_plume":
        return rain_plume(lat, lon, season, model)
    raise ValueError(f"chart must be one of {KINDS}")
