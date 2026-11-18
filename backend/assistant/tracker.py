"""Near real-time rainfall tracking: evidence records from the tracking page's published data (tracker/data,
written by scripts/export_dashboard_data.py and the daily run).

  status(site)    rain since 1 Oct against normal (CHIRPS, and the range of the other satellite products), the
                  planting onset in the satellite products, recent rain and the days since the last wet day, planting
                  rains in the weather models' next days, the ECMWF ensemble's chances, and the seasonal outlook the
                  page shows
  changes(site)   what changed between the two latest weather-model runs (the same days, at the same grid cell) and
                  the rain observed in the last days

Kenya Short Rains, the page's monitoring sites. Every figure is read from the published files; nothing is modelled
here.
"""
import datetime as dt
import math
import re
import statistics

from . import crop_data, evidence as ev

WET_MM = 1.0                     # a wet day, as on the tracking page
PLANTING_RAIN = "at least 20 mm within 3 days"


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _pct(p):
    p = _f(p)
    return None if p is None else int(round(100 * p))


def _d(s):
    return dt.date.fromisoformat(str(s)[:10])


def _rows(name):
    d = crop_data.load_tracker(name)
    if d is None:
        raise ValueError(f"The rainfall tracking data ({name}) cannot be read at the moment.")
    return d


def _labels():
    """Product id -> name, for the observed (satellite) products."""
    try:
        return {r["id"]: r["name"] for r in _rows("products.csv") if r.get("kind") == "obs"}
    except ValueError:
        return {}


def _range(s):
    """'13 Nov – 16 Nov' -> ['13 Nov', '16 Nov']."""
    if not s:
        return None
    parts = [p.strip() for p in re.split(r"\s+[–-]\s+", s) if p.strip()]
    return parts if len(parts) == 2 else [s.strip()]


def sites() -> list:
    return [{"name": r["site"], "lat": _f(r["lat"]), "lon": _f(r["lon"])} for r in _rows("sites.csv")]


def find_site(name=None, lat=None, lon=None, max_km=30.0) -> dict:
    """The tracking site by name (whole or in part: 'Kiboko', 'Kapiti') or the nearest within max_km of lat, lon."""
    S = _rows("sites.csv")
    names = ", ".join(r["site"] for r in S)
    if name:
        low = name.strip().lower()
        for r in S:
            if r["site"].lower() == low:
                return r
        words = {w for w in re.findall(r"[a-z]+", low) if len(w) >= 4} - {"farm", "station", "research", "kenya"}
        scored = sorted(((len(words & set(re.findall(r"[a-z]+", r["site"].lower()))), r) for r in S),
                        key=lambda t: -t[0])
        if scored and scored[0][0] > 0:
            return scored[0][1]
    if lat is not None and lon is not None:
        best = min(S, key=lambda r: _km(lat, lon, _f(r["lat"]), _f(r["lon"])))
        if _km(lat, lon, _f(best["lat"]), _f(best["lon"])) <= max_km:
            return best
    raise ValueError(f"Rainfall tracking covers these sites only: {names}.")


def _km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _recent(site, labels):
    """Per product: data through, rain in the last 7 days, the last wet day and the days since it."""
    by = {}
    for r in _rows("rain_daily.csv"):
        if r["site"] == site and _f(r["mm"]) is not None:
            by.setdefault(r["product"], []).append((r["date"], _f(r["mm"])))
    out = {}
    for p, ser in by.items():
        ser.sort()
        last = ser[-1][0]
        wet = [d for d, v in ser if v >= WET_MM]
        cut = (_d(last) - dt.timedelta(days=7)).isoformat()
        out[p] = {"product": labels.get(p, p), "through": last,
                  "last_7_days_mm": round(sum(v for d, v in ser if d > cut), 1),
                  "last_wet_day": wet[-1] if wet else None,
                  "days_since_last_wet_day": (_d(last) - _d(wet[-1])).days if wet else None}
    return out


def _seasonal(site):
    out = {}
    for r in _rows("seasonal.csv"):
        if r["site"] != site:
            continue
        v = r["variable"]
        cats = ("short", "normal", "long") if v == "lgp" else ("early", "normal", "late")
        ch = {c: _pct(r[k]) for c, k in zip(cats, ("p_low", "p_mid", "p_high"))}
        known = {c: x for c, x in ch.items() if x is not None}
        top = sorted(known.items(), key=lambda t: -t[1])
        out[v] = {"label": r["label"], "median": r["median"] or None,
                  "middle_half_range": [r["likely_from"], r["likely_to"]] if r["likely_from"] else None,
                  "range_80": [r["wide_from"], r["wide_to"]] if r["wide_from"] else None,
                  "chances_pct": ch,
                  "most_likely": top[0][0] if len(top) > 1 and top[0][1] - top[1][1] > 3 else None,
                  "normal": r["normal"] or None, "normal_third": _range(r.get("normal_band")),
                  "skill": r["skill"] or None, "rpss": _f(r["rpss_val"]), "mean_abs_error_days": _f(r["mae_days"]),
                  "members": int(_f(r["members"]) or 0) or None, "notes": r["flags"] or None}
    return out


def status(site_name=None, lat=None, lon=None) -> dict:
    """The rainfall tracking evidence record for one monitoring site."""
    me = find_site(site_name, lat, lon)
    site = me["site"]
    year = int(me["issued"][:4])
    labels = _labels()
    others = []
    for p, label in labels.items():
        if p == "chirps":
            continue
        v = _f(me.get(f"rain_since_oct1_{p}_mm"))
        if v is not None:
            others.append({"product": label, "mm": v, "through": me.get(f"through_{p}") or None})
    rain = {"from": f"{year}-10-01", "through": me.get("through_chirps") or me.get("obs_through"),
            "chirps_mm": _f(me.get("rain_since_oct1_chirps_mm")), "normal_mm": _f(me.get("normal_same_days_mm")),
            "pct_of_normal": _f(me.get("pct_of_normal")),
            "other_products": others,
            "other_products_range_mm": [min(o["mm"] for o in others), max(o["mm"] for o in others)] if others else None,
            "products_with_planting_onset": int(_f(me.get("products_with_onset")) or 0),
            "products": int(_f(me.get("products")) or 0)}
    rec_p = _recent(site, labels)
    dry = [x["days_since_last_wet_day"] for x in rec_p.values() if x["days_since_last_wet_day"] is not None]
    recent = {"chirps": rec_p.get("chirps"), "by_product": list(rec_p.values()),
              "days_since_last_wet_day_range": [min(dry), max(dry)] if dry else None,
              "wet_day_mm": WET_MM}

    near = None
    evs = [r for r in _rows("forecast_events.csv") if r["site"] == site]
    if evs:
        H = min(int(_f(r["horizon_days"]) or 0) for r in evs)
        N = 7 if H >= 7 else 5
        vals = [_f(r[f"total_{N}d_mm"]) for r in evs if _f(r[f"total_{N}d_mm"]) is not None]
        fdates = sorted({r["date"] for r in _rows("forecast_sites.csv") if r["site"] == site})
        start = fdates[0] if fdates else None
        near = {"window_days": N, "from": start,
                "to": (_d(start) + dt.timedelta(days=N - 1)).isoformat() if start else None,
                "models": len(evs), "median_total_mm": round(statistics.median(vals), 1) if vals else None,
                "total_range_mm": [min(vals), max(vals)] if vals else None,
                "models_with_planting_rain_within_7_days": sum(r["planting_rain_within_7d"] == "1" for r in evs),
                "planting_rain_rule": PLANTING_RAIN,
                "by_model": [{"model": r["model_label"], "forecast_days": int(_f(r["horizon_days"]) or 0),
                              "total_5_days_mm": _f(r["total_5d_mm"]), "total_7_days_mm": _f(r["total_7d_mm"]),
                              "total_10_days_mm": _f(r["total_10d_mm"]) if (_f(r["horizon_days"]) or 0) >= 10 else None,
                              "first_planting_rain": r["first_planting_rain"] or None} for r in evs]}

    ens = None
    if me.get("ens_init"):
        days = [{"date": r["date"], "chance_of_rain_pct": _pct(r["p_rain"]), "chance_of_10mm_pct": _pct(r["p_10mm"]),
                 "median_mm": _f(r["median_mm"]), "chance_planting_rain_starts_pct": _pct(r["p_trigger"])}
                for r in _rows("ens_daily.csv") if r["site"] == site]
        ens = {"initialised": me["ens_init"],
               "planting_rain_within_7_days_pct": _pct(me.get("p_event_7d")),
               "planting_rain_within_15_days_pct": _pct(me.get("p_event_15d")),
               "planting_onset_within_15_days_pct": _pct(me.get("p_onset_15d")),
               "planting_onset_median": me.get("ens_onset_median") or None,
               "planting_onset_middle_half": _range(me.get("ens_onset_likely")),
               "days_with_10mm_more_likely_than_not": [d["date"] for d in days if (d["chance_of_10mm_pct"] or 0) >= 50],
               "daily": days[:15]}

    seas_run = next((r for r in _rows("products.csv") if r.get("id") == "seas5"), None)
    zone = None
    try:
        z = next((r for r in _rows("zone.csv") if r["product"] == "chirps"), None)
        if z:
            zone = {"product": z["label"], "through": z["last_day"], "pct_of_normal": _f(z["ond_zone_pct_normal"]),
                    "pct_of_zone_with_planting_onset": _f(z["ond_zone_pct_onset_detected"])}
    except ValueError:
        pass

    rec = {"schema": ev.SCHEMA, "kind": "tracker",
           "scope": {"site": site, "lat": _f(me["lat"]), "lon": _f(me["lon"]), "country": "Kenya"},
           "season": {"label": "Short Rains (OND)", "year": year},
           "issued": me["issued"], "observations_through": me.get("obs_through"),
           "rain_so_far": rain, "recent_rain": recent, "weather_models": near, "ecmwf_ensemble": ens,
           "seasonal_outlook": {"run": (seas_run or {}).get("run_date") or None, "condition": me.get("condition") or None,
                                "quantities": _seasonal(site)},
           "short_rains_zone": zone}
    rec["caveats"] = _caveats(rec)
    rec["sources"] = [{"what": "Observed rainfall", "detail": "CHIRPS (reference; normal = CHIRPS 1993-2016 for the same "
                                                              "days) and the other satellite products on the page"},
                      {"what": "Weather models", "detail": "raw 1-16 day forecasts of six global models"},
                      {"what": "ECMWF ensemble", "detail": "ECMWF ENS members, raw"},
                      {"what": "Seasonal outlook", "detail": "ECMWF SEAS5, updated with observed rain"}]
    rec["id"] = ev.record_id(rec)
    return rec


def _caveats(rec):
    c = ["Satellite rainfall describes the site's grid cell, not a rain gauge on the farm."]
    r = rec["rain_so_far"]
    rng = r.get("other_products_range_mm")
    if rng and r.get("chirps_mm") is not None and (rng[1] - rng[0]) > max(30.0, 0.5 * max(r["chirps_mm"], 1.0)):
        c.append(f"The satellite products disagree here: since 1 Oct the other products give {rng[0]:g} to {rng[1]:g} mm, "
                 f"against {r['chirps_mm']:g} mm in CHIRPS.")
    c.append("CHIRPS for the latest weeks is preliminary and can change when the final version is released.")
    if rec.get("weather_models"):
        c.append("Weather-model totals are raw model output, not bias-corrected; each model stops at the end of its range.")
    if rec.get("ecmwf_ensemble"):
        c.append("The ensemble's chances count its members; they are not adjusted for skill.")
    if rec["seasonal_outlook"]["quantities"]:
        c.append("The seasonal outlook's chances are skill-weighted. The planting onset (20 mm rule) and the Dunning "
                 "onset are different events.")
    try:
        lag = (_d(rec["issued"]) - _d(rec["observations_through"])).days
        if lag > 5:
            c.append(f"The observations end {lag} days before the page was issued.")
    except Exception:
        pass
    return c


# ---------------------------------------------------------------------------- what changed between runs
def _cell(rows, model, lat, lon):
    cand = [r for r in rows if r["model"] == model]
    if not cand:
        return None
    r = min(cand, key=lambda r: (_f(r["lat"]) - lat) ** 2 + (_f(r["lon"]) - lon) ** 2)
    if abs(_f(r["lat"]) - lat) > 0.5 or abs(_f(r["lon"]) - lon) > 0.5:
        return None
    vals = [_f(x) for x in r["rain"].split(";")]
    return {"start": r["start"], "rain": vals, "cell": [_f(r["lat"]), _f(r["lon"])]}


def changes(site_name=None, lat=None, lon=None) -> dict:
    """The two latest weather-model runs compared over the days both cover, at the site's grid cell, and the rain
    observed in the last 3 days."""
    me = find_site(site_name, lat, lon)
    site, slat, slon = me["site"], _f(me["lat"]), _f(me["lon"])
    runs = sorted((_rows("nwp_runs/index.json") or {}).get("runs") or [], key=lambda r: r["run"])
    if len(runs) < 2:
        raise ValueError("There is only one weather-model run so far; nothing to compare.")
    old, new = runs[-2], runs[-1]
    ro, rn = _rows("nwp_runs/" + old["file"]), _rows("nwp_runs/" + new["file"])
    names = {r["model"]: r["model_label"] for r in _rows("forecast_events.csv")}
    models = []
    for m in sorted(set(new["models"]) & set(old["models"])):
        a, b = _cell(ro, m, slat, slon), _cell(rn, m, slat, slon)
        if not a or not b:
            continue
        a0, b0 = _d(a["start"]), _d(b["start"])
        end = min(a0 + dt.timedelta(days=len(a["rain"]) - 1), b0 + dt.timedelta(days=len(b["rain"]) - 1))
        if end < b0:
            continue
        n = (end - b0).days + 1
        ia = (b0 - a0).days
        va, vb = a["rain"][ia:ia + n], b["rain"][:n]
        if any(x is None for x in va + vb):
            continue
        ta, tb = round(sum(va), 1), round(sum(vb), 1)
        models.append({"model": names.get(m, m), "days": [b0.isoformat(), end.isoformat()], "n_days": n,
                       "previous_run_mm": ta, "latest_run_mm": tb, "change_mm": round(tb - ta, 1),
                       "grid_cell": b["cell"]})
    wetter = [x["model"] for x in models if x["change_mm"] >= 5]
    drier = [x["model"] for x in models if x["change_mm"] <= -5]
    labels = _labels()
    rp = _recent(site, labels)
    obs = []
    for p, x in rp.items():
        ser = sorted((r["date"], _f(r["mm"])) for r in _rows("rain_daily.csv") if r["site"] == site and r["product"] == p
                     and _f(r["mm"]) is not None)
        last3 = ser[-3:]
        if last3:
            obs.append({"product": x["product"], "days": [last3[0][0], last3[-1][0]], "mm": round(sum(v for _, v in last3), 1)})
    rec = {"schema": ev.SCHEMA, "kind": "tracker_changes",
           "scope": {"site": site, "lat": slat, "lon": slon, "country": "Kenya"},
           "runs": {"previous": old["run"], "latest": new["run"]},
           "weather_models": models,
           "summary": {"models_compared": len(models), "wetter_by_5mm_or_more": wetter, "drier_by_5mm_or_more": drier,
                       "median_change_mm": round(statistics.median([x["change_mm"] for x in models]), 1) if models else None},
           "observed_last_3_days": obs,
           "caveats": ["Each model is compared with its own previous run over the days both runs cover, at the forecast "
                       "grid cell nearest the site (0.5 degree), so the totals can differ slightly from the site table.",
                       "Weather-model totals are raw model output, not bias-corrected.",
                       "A change between two runs is normal day to day; a steady shift over several runs matters more."]}
    rec["id"] = ev.record_id(rec)
    return rec
