"""
The Crop outlook tab's data (frontend/public/tracker/data/crop/, published with the daily update): compact copies of
the latest result of each forecast source and of the benchmark, read by frontend/src/components/CropOutlookTab.jsx.

  index.json        runs, every run's summaries (per site, variety, rule), sites, varieties, planting rules, outcomes,
                    caveats
  <source>.json     the source's latest run (one file per source, overwritten, so the published history does not
                    pile up): per site, variety and rule, the summary and every member as
                    [planting, harvest, yield t/ha, outcome, water-stress days, season rain mm,
                    yield without water stress t/ha, sowings], and the canopy band (weekly canopy cover of the
                    simulated members from 1 Aug: median, 10th and 90th percentiles)
  WOFOST, the second model, where the run has it (run_outlook.py): beside AquaCrop's, per site, variety and rule,
  "wofost": its summary and members (as AquaCrop's) in <source>.json, and index.json "wofost": {run id: {site:
  {variety: {rule: summary}}}} and "second_engine"; benchmark.json "wofost": WOFOST's own observed-weather
  benchmark (climatology_wofost.json), as AquaCrop's, when built.
  index.json also carries the measured yields at each site (crop_engine/yields targets.csv, when built): the trials'
  median and high-input yields per site and crop, kept apart from the simulated past seasons.
  benchmark.json    per site, variety and rule: terciles, median, the outcome rates (as the summaries), canopy band
                    and every observed
                    season as [year, planting, harvest, yield t/ha, outcome, yield without water stress t/ha]
  skill.json        how well past crop forecasts did: the seasonal and sub-seasonal hindcast scores (write_skill)
  history.json      each outlook's summary on every day its run was rebuilt (write_history)
  scenarios.json    the management scenarios of the latest seasonal run (crop_engine.run_scenarios), when made with
                    that run's configuration (refreshed weekly: their meta gives the observations they used): per site,
                    variety and rule, the outlook's summary then ("baseline") and each scenario's

Older runs are removed, so the published folder holds one run per source.
"""
import json

import pandas as pd

from crop_engine import config as C
from crop_engine.data.sites import registered_sites

OUTCOMES = [
    ("ok", "Matured", "Sown and reached maturity"),
    ("died", "Died before maturity", "Established, then died of water stress before maturity (yield so far counted)"),
    ("failed_establishment", "Failed to establish", "Died before its canopy reached 5 %: a false start, the seedlings dried out"),
    ("too_late", "Too late to mature", "Sown too late to reach maturity by 31 Mar, the season's end (counted as no yield)"),
    ("not_sown", "No sowing opportunity", "No onset by the rule's search end, 15 Jan (counted as no yield)"),
    ("error", "Model error", "AquaCrop failed for this member: no outcome, left out of every probability"),
]
MEMBER_KEYS = ("planting", "harvest", "yield_t_ha", "status", "stress_days", "rain_mm", "potential_t_ha", "sowings")


BENCH_KEYS = ("t33", "t67", "median", "cal_median", "p_failure", "p_sowing_opportunity", "p_establishment_failure",
              "p_failure_if_sown", "yield_if_sown_t_ha", "n_valid", "n_error", "n_sown", "canopy")


def observed_yields():
    """{site: {crop: [trial groups]}} from the yield build's targets.csv (measured plot yields within 25 km, dry
    t/ha), or {} before the build has run. Rainfed and unstated plots only: the engine is rainfed."""
    from crop_engine.yields import YIELD_OUT
    p = YIELD_OUT / "targets.csv"
    if not p.exists():
        return {}
    t = pd.read_csv(p, dtype={"years": str, "n_kg_ha": str})
    t = t[t.irrigated.isin(["no", "not stated"])]
    out = {}
    for r in t.itertuples():
        out.setdefault(r.site_id, {}).setdefault(r.crop, []).append({
            "n": int(r.n), "studies": int(r.studies), "years": r.years if isinstance(r.years, str) else "",
            "median_t_ha": float(r.median_t_ha), "p90_t_ha": float(r.p90_t_ha), "max_t_ha": float(r.max_t_ha),
            "n_kg_ha": r.n_kg_ha if isinstance(r.n_kg_ha, str) else "", "irrigated": r.irrigated})
    return out


def _dump(path, obj):
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def write_index():
    """outputs/crop_engine/results/index.json: every run made, newest first."""
    runs = []
    for p in sorted(C.RESULTS_OUT.glob("*_????????.json")):
        meta = json.loads(p.read_text(encoding="utf-8"))["meta"]
        runs.append({k: meta[k] for k in ("id", "source", "model_label", "run", "obs_end", "members_kind", "created")})
    runs.sort(key=lambda r: (r["run"], r["source"]), reverse=True)
    (C.RESULTS_OUT / "index.json").write_text(json.dumps({"runs": runs}, indent=1), encoding="utf-8")


HISTORY_SOURCES = ("seasonal", "s2s-ecmwf", "s2s-gefs")     # the outlooks whose day-by-day change the tab shows
HISTORY_KEYS = ["yield_if_sown_median", "yield_if_sown_p10", "yield_if_sown_p90", "p_failure_if_sown",
                "p_sowing_opportunity", "wofost_yield_if_sown_median", "wofost_p_failure_if_sown"]


def _hist_row(s, w):
    y, wy = s.get("yield_if_sown_t_ha") or {}, (w or {}).get("yield_if_sown_t_ha") or {}
    r = lambda v, n=2: None if v is None else round(float(v), n)                        # noqa: E731
    return [r(y.get("median")), r(y.get("p10")), r(y.get("p90")), r(s.get("p_failure_if_sown"), 3),
            r(s.get("p_sowing_opportunity"), 3), r(wy.get("median")), r((w or {}).get("p_failure_if_sown"), 3)]


def write_history(entries, log=print):
    """history.json: each outlook's summary on every day its run was rebuilt, so the tab can show how the outlook has
    changed through the season. Kept in outputs/crop_engine/history.json (the tab's copy is rewritten from it; if it
    is missing, it starts from the published copy). One point per source and day (the run's creation day); each
    carries the configuration hash, so a change of the crop model is shown as such, not as a change of forecast."""
    path, pub = C.OUT / "history.json", C.DASHBOARD_OUT / "history.json"
    h = None
    for f in (path, pub):
        if h is None and f.exists():
            try:
                h = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                h = None
    if not h or h.get("keys") != HISTORY_KEYS:
        h = {"keys": HISTORY_KEYS, "sources": {}}
    n = 0
    for r, chash, summ, wsumm in entries:
        if r["source"] not in HISTORY_SOURCES:
            continue
        day = r["created"][:10]
        cells = {sid: {vk: {rk: _hist_row(x, (((wsumm or {}).get(sid) or {}).get(vk) or {}).get(rk))
                            for rk, x in rs.items()} for vk, rs in vs.items()} for sid, vs in summ.items()}
        lst = [e for e in h["sources"].get(r["source"], []) if e["date"] != day]
        lst.append({"date": day, "run": r["run"], "obs_end": r["obs_end"], "config": chash, "cells": cells})
        h["sources"][r["source"]] = sorted(lst, key=lambda e: e["date"])
        n += 1
    C.OUT.mkdir(parents=True, exist_ok=True)
    _dump(path, h)
    _dump(pub, h)
    log(f"dashboard: outlook history, {', '.join(f'{k} {len(v)} days' for k, v in h['sources'].items())}")


SKILL_FILES = {"aquacrop": "hindcast_scores.json", "wofost": "hindcast_scores_wofost.json"}   # 1 Oct SEAS5, climatological T
BASELINES = {"lgp": "lgp_days", "rain": "rain_oct_dec_mm", "onset": "onset_doy"}


def _score(c):
    c = c or {}
    r = lambda v: None if v is None else round(float(v), 2)                             # noqa: E731
    return {"r": r(c.get("spearman")), "auc": r(c.get("failure_auc")), "bss": r(c.get("failure_bss")), "n": c.get("n_years")}


def write_skill(current_config, log=print):
    """skill.json: how well past crop forecasts did (crop_engine.hindcast, hindcast_s2s), compacted for the tab and the
    Forecast performance tab. Seasonal: the 1 Oct SEAS5 forecasts of the hindcast years, AquaCrop and WOFOST each
    against its own crop grown in the observed weather, and the platform's season-length, Oct-Dec rain and onset
    forecasts read as yield predictors (the baselines). Sub-seasonal: the ECMWF extended-range reforecasts by start date,
    observations only against the forecast's rain (and temperature). Each part says when it was made and whether with
    the outlook's current crop configuration. Written only from the files on disk; absent ones are left out."""
    V = C.OUT / "verification"
    out = {}
    seas = {}
    for eng, f in SKILL_FILES.items():
        path = V / f
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        seas.setdefault("made", {})[eng] = {"created": d.get("created"), "config_hash": d.get("config_hash"),
                                            "years": [d["years"][0], d["years"][-1]], "temperature": d.get("temperature")}
        for sid, vs in d["sites"].items():
            for vk, rs in vs.items():
                for rk, c in rs.items():
                    cell = seas.setdefault("sites", {}).setdefault(sid, {}).setdefault(vk, {}).setdefault(rk, {})
                    cell[eng] = _score(c.get("crop"))
                    if eng == "aquacrop":
                        cell.update({k: _score(c.get("baselines", {}).get(b)) for k, b in BASELINES.items()})
    if seas:
        seas["current_config"] = current_config
        out["seasonal"] = seas
    path = V / "hindcast_s2s.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        out["s2s"] = {"created": d.get("created"), "config_hash": d.get("config_hash"), "current_config": current_config,
                      "years": [d["years"][0], d["years"][-1]], "inits": d.get("inits"),
                      "sites": {sid: {vk: {md: {k: _score(c.get(k)) for k in ("reference", "forecast", "forecast_t") if k in c}
                                           for md, c in ms.items()} for vk, ms in vs.items()} for sid, vs in d["sites"].items()}}
    if out:
        _dump(C.DASHBOARD_OUT / "skill.json", out)
        log(f"dashboard: crop skill ({', '.join(out)})")
    return bool(out)


def write(log=print):
    idx = C.RESULTS_OUT / "index.json"
    if not idx.exists():
        return
    latest = {}
    for r in json.loads(idx.read_text(encoding="utf-8"))["runs"]:          # newest first
        latest.setdefault(r["source"], r)
    runs = sorted(latest.values(), key=lambda r: (r["source"] != "seasonal", r["source"]))
    C.DASHBOARD_OUT.mkdir(parents=True, exist_ok=True)
    meta0, sites, summaries, wofost, hist, chash0 = None, {}, {}, {}, [], None
    for r in runs:
        d = json.loads((C.RESULTS_OUT / f"{r['id']}.json").read_text(encoding="utf-8"))
        meta0 = meta0 or d["meta"]
        hist.append((r, d["meta"].get("config_hash")))
        if r["source"] == "seasonal":
            chash0 = d["meta"].get("config_hash")
        summaries[r["id"]] = {sid: {vk: {rk: x["summary"] for rk, x in rs.items()} for vk, rs in s["results"].items()}
                              for sid, s in d["sites"].items()}
        w = {sid: {vk: {rk: x["wofost"]["summary"] for rk, x in rs.items() if "wofost" in x}
                   for vk, rs in s["results"].items()} for sid, s in d["sites"].items()}
        w = {sid: {vk: rs for vk, rs in vs.items() if rs} for sid, vs in w.items()}
        if any(w.values()):
            wofost[r["id"]] = {sid: vs for sid, vs in w.items() if vs}
        out = {"meta": {k: d["meta"].get(k) for k in ("id", "source", "model_label", "run", "obs_end", "members_kind",
                                                       "segments", "created", "engine", "weather", "second_engine")},
               "sites": {}}
        for sid, s in d["sites"].items():
            sites.setdefault(sid, {"name": s["name"], "cell": s["cell"], "soil_taw_100cm_mm": s["soil_taw_100cm_mm"],
                                   "topsoil": {k: round(v) for k, v in s["topsoil"].items()}})
            out["sites"][sid] = {
                "initial_water_fraction": s["initial_water_fraction"], "fao_reference": s["fao_reference"],
                **({"soil_water": s["soil_water"]} if s.get("soil_water") else {}),
                "results": {vk: {rk: {"summary": x["summary"], "canopy": x.get("canopy"),
                                      "members": [[m.get(k) for k in MEMBER_KEYS] for m in x["members"]],
                                      **({"wofost": {"summary": x["wofost"]["summary"],
                                                     "members": [[m.get(k) for k in MEMBER_KEYS] for m in x["wofost"]["members"]]}}
                                         if "wofost" in x else {})}
                                 for rk, x in rs.items()} for vk, rs in s["results"].items()}}
        _dump(C.DASHBOARD_OUT / f"{r['source']}.json", out)
    if not meta0:
        return
    coords = {s.id: (s.lat, s.lon) for s in registered_sites()}
    for sid, s in sites.items():
        s["lat"], s["lon"] = coords.get(sid, (None, None))
    bench = json.loads((C.OUT / "climatology.json").read_text(encoding="utf-8"))

    def compact(sites_):
        return {sid: {vk: {rk: {**{k: b.get(k) for k in BENCH_KEYS},
                                "seasons": [[int(y), v["planting"], v["harvest"], v["yield_t_ha"], v["status"],
                                             v.get("potential_t_ha")]
                                            for y, v in sorted(b["years"].items())]}
                           for rk, b in rs.items()} for vk, rs in vs.items()} for sid, vs in sites_.items()}
    out_b = {"years": bench["years"], "cal_years": bench["cal_years"], "sites": compact(bench["sites"])}
    wpath = C.OUT / "climatology_wofost.json"
    if wpath.exists():
        out_b["wofost"] = compact(json.loads(wpath.read_text(encoding="utf-8"))["sites"])
    _dump(C.DASHBOARD_OUT / "benchmark.json", out_b)
    _dump(C.DASHBOARD_OUT / "index.json", {
        "runs": [{**{k: r[k] for k in ("id", "source", "model_label", "run", "obs_end", "members_kind", "created")},
                  "file": f"{r['source']}.json"} for r in runs],
        "summaries": summaries, "wofost": wofost, "second_engine": meta0.get("second_engine", {}).get("engine"),
        "sites": sites, "varieties": meta0["varieties"], "planting_rules": meta0["planting_rules"],
        "outcomes": [{"id": i, "label": a, "title": t} for i, a, t in OUTCOMES], "member_keys": list(MEMBER_KEYS),
        "observed_yields": observed_yields(),
        "caveats": meta0["caveats"], "engine": meta0["engine"]})
    write_history([(r, ch, summaries.get(r["id"], {}), wofost.get(r["id"])) for r, ch in hist], log)
    write_skill(chash0, log)
    keep = {f"{r['source']}.json" for r in runs} | {"index.json", "benchmark.json", "scenarios.json", "history.json", "skill.json"}
    for p in C.DASHBOARD_OUT.glob("*.json"):
        if p.name not in keep:
            p.unlink()
    write_scenarios(log)
    size = sum(p.stat().st_size for p in C.DASHBOARD_OUT.glob("*.json")) / 1024
    log(f"dashboard: {len(runs)} runs → {C.DASHBOARD_OUT.relative_to(C.BASE)} ({size:.0f} kB)")


def write_scenarios(log=print):
    """scenarios.json: the latest seasonal run's management scenarios, only when they were made with that run's
    configuration (they may be from older observations: refreshed weekly); otherwise the file is removed, so the tab
    never shows scenarios of another run or configuration."""
    out = C.DASHBOARD_OUT / "scenarios.json"
    idx = C.RESULTS_OUT / "index.json"
    rid = next((r["id"] for r in json.loads(idx.read_text(encoding="utf-8"))["runs"] if r["source"] == "seasonal"),
               None) if idx.exists() else None
    src = C.OUT / "scenarios" / f"{rid}.json"
    if rid and src.exists():
        d = json.loads(src.read_text(encoding="utf-8"))
        meta = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))["meta"]
        if d["meta"].get("config_hash") == meta.get("config_hash"):
            C.DASHBOARD_OUT.mkdir(parents=True, exist_ok=True)
            _dump(out, d)
            log(f"dashboard: scenarios of {rid} ({len(d['meta']['scenarios'])} scenarios)")
            return True
    if out.exists():
        out.unlink()
    return False


if __name__ == "__main__":
    write()
