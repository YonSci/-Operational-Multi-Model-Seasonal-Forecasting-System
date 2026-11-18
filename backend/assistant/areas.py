"""Areas: a county or region, or a drawn rectangle, and the areas needing attention on one criterion.

An area's figures come from the grid cells whose centres fall inside it. Two kinds of chance are kept apart:
  - the average of the cells' own (skill-weighted) chances: how likely a late onset is at a typical place;
  - the chance of an area-wide event, counted member by member: in what share of the forecast members does most of
    the area (more than half its cells) have a late onset. This is the regional event a planner asks about; it uses
    the members as they are (not skill-weighted), which the record says.
Boundaries: frontend/public/boundaries (Kenya counties, Ethiopia regions).
"""
import math
import threading

import numpy as np
from matplotlib.path import Path as MPath

import mam_loader as dl
from . import crop_data, evidence as ev, knowledge as kn

ADMIN = {"Kenya": ("boundaries/ke_admin1.geojson", "county"), "Ethiopia": ("boundaries/eth_admin1.geojson", "region")}
PRE = {"onset": "onset_doy", "cessation": "cessation_doy", "lgp": "lgp_days"}
TERC = {"onset": ("t33_onset", "t67_onset"), "cessation": ("t33_cess", "t67_cess"), "lgp": ("t33_lgp", "t67_lgp")}

# criteria for "areas needing attention": (variable, layer, label, test on the cell value, what it means)
CRITERIA = {
    "late_onset": ("onset", "prob_an", "Higher chance of a late onset", lambda v: v >= 0.5, "late-onset chance 50% or more"),
    "early_cessation": ("cessation", "prob_bn", "Higher chance of an early end of the rains", lambda v: v >= 0.5,
                        "early-cessation chance 50% or more"),
    "short_season": ("lgp", "prob_bn", "Higher chance of a short season", lambda v: v >= 0.5, "short-season chance 50% or more"),
    "onset_delay": ("onset", "anomaly", "Onset later than normal", lambda v: v > 7, "median onset more than 7 days later than normal"),
    "season_shorter": ("lgp", "anomaly", "Season shorter than normal", lambda v: v < -7, "median season more than 7 days shorter than normal"),
    "no_onset": ("onset", "failure", "Members finding no onset", lambda v: v >= 0.2, "20% or more of members find no onset"),
}

_lock = threading.Lock()
_masks = {}


def country_of(season):
    return kn.SEASON_LABELS.get(season, (None, "Kenya"))[1] or "Kenya"


def regions(country):
    """[(name, [matplotlib Path, ...])] of the country's first-level areas."""
    rel, _ = ADMIN.get(country, ADMIN["Kenya"])
    gj = crop_data.load_public(rel) or {"features": []}
    out = []
    for f in gj["features"]:
        g = f.get("geometry") or {}
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates", []) if g.get("type") == "MultiPolygon" else []
        paths = [MPath(np.asarray(p[0], float)) for p in polys if p and len(p[0]) > 2]
        if paths:
            out.append((f["properties"].get("name"), paths))
    return out


def region_index(lats, lons, country):
    """Index of the area holding each cell centre (-1 outside every area), and the area names; cached."""
    key = (country, len(lats), float(lats[0]), float(lats[-1]), len(lons), float(lons[0]), float(lons[-1]))
    with _lock:
        if key in _masks:
            return _masks[key]
    regs = regions(country)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    pts = np.column_stack([LO.ravel(), LA.ravel()])
    idx = np.full(pts.shape[0], -1, int)
    for k, (_, paths) in enumerate(regs):
        inside = np.zeros(pts.shape[0], bool)
        for p in paths:
            inside |= p.contains_points(pts)
        idx[(idx < 0) & inside] = k
    out = (idx.reshape(LA.shape), [n for n, _ in regs])
    with _lock:
        _masks[key] = out
    return out


def _model(season, model):
    st = dl.get_state()
    M = (st.get("MODELS") or {}).get(model)
    if M is None:
        raise ValueError(f"No model {model!r} loaded")
    info = ev.model_info(season, model)
    oi = info.get("op_idx")
    if oi is None:
        yrs = list(M.get("model_years", []))
        oi = yrs.index(int(info.get("op_year") or dl._OP_YEAR)) if yrs else -1
    return M, info, int(oi)


def _grid(variable, layer, model, season):
    g = dl.get_grid_stats(variable=variable, layer=layer, model=model or None, season=season)
    v = np.asarray(g["values"], float)
    if g.get("seasonal_mask") is not None:
        v = np.where(np.asarray(g["seasonal_mask"]).astype(bool), v, np.nan)
    return np.asarray(g["lats"], float), np.asarray(g["lons"], float), v


# ---------------------------------------------------------------------------- one area
def area(season, model, name=None, bbox=None) -> dict:
    """Evidence for a county/region (`name`) or a drawn rectangle (`bbox` = [west, south, east, north])."""
    country = country_of(season)
    M, info, oi = _model(season, model)
    lats, lons = np.asarray(M["target_lat"], float), np.asarray(M["target_lon"], float)
    if name:
        idx, names = region_index(lats, lons, country)
        match = [i for i, n in enumerate(names) if n and n.lower() == name.lower()]
        if not match:
            raise ValueError(f"No {ADMIN[country][1]} named {name!r} in {country}")
        inside = idx == match[0]
        label, kind = names[match[0]], ADMIN[country][1]
    elif bbox and len(bbox) == 4:
        w, s, e, n = map(float, bbox)
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        inside = (LA >= min(s, n)) & (LA <= max(s, n)) & (LO >= min(w, e)) & (LO <= max(w, e))
        lat = lambda v: f"{abs(round(v, 2)):g} {'S' if v < 0 else 'N'}"
        label, kind = (f"the drawn area ({lat(min(s, n))} to {lat(max(s, n))}, {round(min(w, e), 2):g} to "
                       f"{round(max(w, e), 2):g} E)"), "drawn area"
    else:
        raise ValueError("Give a county or region name, or a drawn rectangle")
    _, _, mask_vals = _grid("onset", "median", model, season)
    inside &= np.asarray(M["lm"]).astype(bool) & np.isfinite(mask_vals)
    n = int(inside.sum())
    if n == 0:
        raise ValueError(f"No forecast grid cells with a season in {label}")
    year = int(info.get("op_year") or dl._OP_YEAR)
    obs_doy = ev._doy(info.get("obs_end"), year)
    quantities = {}
    for q in ("onset", "cessation", "lgp"):
        mem = np.asarray(M[PRE[q]][:, oi], float)[:, inside]                 # members x cells
        t33 = np.asarray(M[TERC[q][0]], float)[inside]
        t67 = np.asarray(M[TERC[q][1]], float)[inside]
        is_date = q != "lgp"
        conv = (lambda x: ev._date(x, year)) if is_date else (lambda x: ev._num(x, 0))
        cell_med = np.nanmedian(mem, axis=0)
        ok = np.isfinite(t33) & np.isfinite(t67) & (t33 != t67)
        cats = kn.QUANTITIES[q]["cats"]
        rec = {"label": kn.QUANTITIES[q]["label"], "unit": kn.QUANTITIES[q]["unit"],
               "cell_medians": {"p10": conv(np.nanpercentile(cell_med, 10)), "median": conv(np.nanmedian(cell_med)),
                                "p90": conv(np.nanpercentile(cell_med, 90))}}
        if ok.any():
            m, a, b = mem[:, ok], t33[ok], t67[ok]
            fin = np.isfinite(m)
            low = (m < a) & fin
            high = (m > b) & fin
            mid = fin & ~low & ~high
            share = {cats[0]: low.mean(axis=1), cats[1]: mid.mean(axis=1), cats[2]: high.mean(axis=1)}
            rec["area_event_chances_pct"] = {f"most of the area {c}": round(100 * float(np.mean(share[c] > 0.5))) for c in cats}
            rec["area_event_basis"] = ("share of the forecast members in which more than half of the area's cells fall in "
                                       "that third (members as they are, not skill-weighted)")
        probs = {}
        for c, lay in zip(cats, ("prob_bn", "prob_nn", "prob_an")):
            _, _, pv = _grid(q, lay, model, season)
            vals = pv[inside]
            if np.isfinite(vals).any():
                probs[c] = round(100 * float(np.nanmean(vals)))
        if probs:
            rec["average_cell_chances_pct"] = probs
            rec["average_cell_chances_basis"] = "average of the cells' own skill-weighted chances (a typical place in the area)"
        if is_date and obs_doy is not None:
            p90 = np.nanpercentile(mem, 90, axis=0)
            rec["cells_estimated_from_observations_pct"] = round(100 * float(np.mean(p90 <= obs_doy)))
        quantities[q] = rec
    skill = {}
    for lay in ("rpss_val", "hitrate_val"):
        try:
            _, _, sv = _grid("onset", lay, model, season)
            vals = sv[inside]
            if np.isfinite(vals).any():
                skill[lay] = round(float(np.nanmean(vals)), 2)
        except Exception:
            pass
    season_label, _ = kn.SEASON_LABELS.get(season, (season, None))
    rec = {
        "schema": ev.SCHEMA, "kind": "area",
        "scope": {"type": kind, "name": label, "country": country, "cells": n, "cell_size_deg": ev.CELL_DEG},
        "season": {"id": season, "label": season_label, "year": year},
        "run": {"model": model, "initialised": info.get("init_date"), "observations_through": info.get("obs_end"),
                "method": kn.method_of(model)["label"]},
        "quantities": quantities,
        "onset_skill_area_mean": skill or None,
        "caveats": ["Area figures summarise the forecast grid cells whose centres fall inside the area; small areas hold "
                    "few cells.",
                    "The area-wide chances count members as they are (not skill-weighted); the average cell chances are "
                    "skill-weighted. They answer different questions."],
        "sources": [{"what": "Forecast", "detail": f"{model}, initialised {info.get('init_date')}"},
                    {"what": "Boundaries", "detail": ADMIN[country][0]}],
    }
    rec["id"] = ev.record_id(rec)
    return rec


# ---------------------------------------------------------------------------- areas needing attention
def attention(season, model, criterion, top=10) -> dict:
    if criterion not in CRITERIA:
        raise ValueError(f"criterion must be one of {sorted(CRITERIA)}")
    variable, layer, label, test, meaning = CRITERIA[criterion]
    country = country_of(season)
    lats, lons, vals = _grid(variable, layer, model, season)
    idx, names = region_index(lats, lons, country)
    flagged = np.zeros(vals.shape, bool)
    fin = np.isfinite(vals)
    flagged[fin] = test(vals[fin])
    is_prob = layer.startswith("prob_") or layer == "failure"
    show = (lambda x: round(100 * float(x))) if is_prob else (lambda x: round(float(x), 1))
    rows = []
    for k, nm in enumerate(names):
        sel = (idx == k) & fin
        if sel.sum() == 0:
            continue
        rows.append({"area": nm, "cells": int(sel.sum()), "flagged_cells": int(flagged[sel].sum()),
                     "flagged_pct": round(100 * float(flagged[sel].mean())),
                     "mean_value": show(np.nanmean(vals[sel]))})
    rows.sort(key=lambda r: (-r["flagged_pct"], -(r["mean_value"] if criterion != "season_shorter" else -r["mean_value"])))
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    order = np.argsort(np.where(flagged, -np.abs(np.nan_to_num(vals)), np.inf), axis=None)
    cells = []
    for i in order[: min(top, int(flagged.sum()))]:
        r, c = np.unravel_index(i, vals.shape)
        cells.append({"lat": round(float(LA[r, c]), 3), "lon": round(float(LO[r, c]), 3), "value": show(vals[r, c]),
                      "area": names[idx[r, c]] if idx[r, c] >= 0 else None})
    info = ev.model_info(season, model) if model else {}
    season_label, _ = kn.SEASON_LABELS.get(season, (season, None))
    rec = {
        "schema": ev.SCHEMA, "kind": "attention",
        "criterion": {"id": criterion, "label": label, "test": meaning, "variable": variable, "layer": layer,
                      "value_unit": "%" if is_prob else "days"},
        "season": {"id": season, "label": season_label, "year": int(info.get("op_year") or dl._OP_YEAR)},
        "run": {"model": model, "initialised": info.get("init_date"), "observations_through": info.get("obs_end"),
                "method": kn.method_of(model)["label"] if model else None},
        "flagged_cells": int(flagged.sum()), "cells_with_values": int(fin.sum()),
        "ranked_areas": rows[:top], "top_cells": cells,
        "caveats": ["This ranks where the forecast shows the condition; it is not a measure of impact or damage.",
                    "Areas are ranked by the share of their grid cells that meet the test, then by the average value."]
                   + (["Chances are skill-weighted: where skill is low they sit near one in three, so few cells reach 50%."]
                      if is_prob else []),
        "sources": [{"what": "Map layer", "detail": f"/grid variable={variable} layer={layer} season={season} model={model}"},
                    {"what": "Boundaries", "detail": ADMIN[country][0]}],
    }
    rec["id"] = ev.record_id(rec)
    return rec
