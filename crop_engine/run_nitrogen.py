#!/usr/bin/env python3
"""
Nitrogen in the seasonal outlook (DSSAT only, adapters/dssat_adapter.py): the members of the latest seasonal run
grown again by DSSAT with its nitrogen balance on, at each fertiliser level, beside DSSAT's water-limited outlook
(the run's own "dssat" results: no nitrogen limitation), and read against the same level's observed-weather normal
(climatology_dssat_n.json: the benchmark's seasons and sowings at each level, rebuilt when DSSAT's configuration or
the nitrogen settings change). The same weather, soil, starting water and sowing dates as the outlook
(run_scenarios.base_tasks).

Settings (crop_engine/dssat_cultivars.yaml): "nitrogen" levels (kg N/ha of urea) and split (days after sowing,
share), assumptions until the sites' managers report theirs (the partner questionnaire, CROP_ENGINE.md "Questions for
partners"); a site's reported practice ("nitrogen" sites) is added as its own level, "reported". The soil's organic
nitrogen: "soil" organic_n_factor (calibration/dssat.py --nitrogen), or a site's own measured value ("soil" sites).
The bean fixes nitrogen (DSSAT's symbiosis on) and gets the same rates.

Rebuilt when the run's results, DSSAT's configuration or the levels change, at most every --max-age-days with the
same configuration (weekly from crop_engine.run_all, as the management scenarios).

Output (not committed): outputs/crop_engine/nitrogen/<run id>.json; the tab's nitrogen.json (dashboard.write_nitrogen).
Usage: python -m crop_engine.run_nitrogen --workers 2 [--max-age-days 7] [--force]
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import xarray as xr

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine import run_scenarios as rs
from crop_engine.adapters import dssat_adapter as dsa

N_OUT = C.OUT / "nitrogen"
NORMAL = "climatology_dssat_n.json"


def settings():
    """(levels, split, sites' reported practice, the note on the rates) from dssat_cultivars.yaml "nitrogen"."""
    n = dsa.nitrogen_settings()
    levels = n.get("levels") or {"n0": {"label": "No fertiliser", "rate_kg_ha": 0}}
    split = {k: [tuple(x) for x in v] for k, v in (n.get("split") or {}).items()}
    return levels, split, n.get("sites") or {}, n.get("assumed") or ""


def site_levels(sid, levels, reported):
    """A site's levels: the common ones, and its reported practice as "reported" where there is one."""
    out = dict(levels)
    r = reported.get(sid)
    if r and r.get("rate_kg_ha") is not None:
        out["reported"] = {"label": r.get("label") or f"{r['rate_kg_ha']:g} kg N/ha (reported for this site)",
                           "rate_kg_ha": r["rate_kg_ha"], "source": r.get("source")}
    return out


def with_nitrogen(t, sid, lv, split):
    return dict(t, nitrogen={"rate_kg_ha": lv["rate_kg_ha"], "split": split.get(t["variety"]["aquacrop_crop"], [(0, 1.0)]),
                             "organic_n_factor": dsa.soil_factor(sid)})


def normal_hash(dhash):
    levels, split, reported, _ = settings()
    return hashlib.sha1(json.dumps([dhash, levels, split, reported, dsa.soil_settings()], sort_keys=True,
                                   default=list).encode()).hexdigest()[:12]


def nitrogen_normal(varieties, rules, workers, dhash, force=False):
    """The nitrogen-limited observed-weather normal at every level (module doc) → {level: benchmark sites}, built once
    per configuration (climatology_dssat_n.json)."""
    from crop_engine import compare_engines as ce
    from crop_engine.data import soil as soil_mod
    from crop_engine.data import weather as W
    path = C.OUT / NORMAL
    h = normal_hash(dhash)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if old and old.get("config_hash") == h and not force:
        return old["levels"]
    levels, split, reported, _ = settings()
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    inp = W.Inputs(refresh=False)
    rep = ro.cells(inp.sites)
    soils = {s.id: soil_mod.profile(s) for s, _ in rep}
    tasks, keys = ce.tasks_for(inp, years, rep, varieties, rules, soils)
    nt, nk = [], []
    for t, (sid, vk, rk, y) in zip(tasks, keys):
        for lk, lv in site_levels(sid, levels, reported).items():
            nt.append(dict(with_nitrogen(t, sid, lv, split), potential=False))
            nk.append((lk, sid, vk, rk, y))
    log(f"nitrogen normal: {len(nt)} observed seasons ({len(years)} years, {len(levels)} levels)")
    t0 = time.time()
    res = ro.run_tasks(nt, workers, engine="dssat")
    out = {}
    for lk in {k[0] for k in nk}:
        idx = [i for i, k in enumerate(nk) if k[0] == lk]
        out[lk] = ro.bench_stats([res[i] for i in idx], [nk[i][1:] for i in idx], varieties, years)
    path.write_text(json.dumps({"config_hash": h, "years": list(C.HIST_YEARS), "cal_years": list(C.CAL_YEARS),
                                "levels": out}, indent=1), encoding="utf-8")
    log(f"nitrogen normal done in {time.time() - t0:.0f} s")
    return out


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] nitrogen: {m}", flush=True)


def nitrogen_hash(results_meta, dhash):
    h = hashlib.sha1(json.dumps([results_meta.get("config_hash"), results_meta.get("created"), dhash, list(settings()),
                                 dsa.soil_settings()], sort_keys=True, default=list).encode())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:12]


def run(rid, workers=2, force=False, max_age_days=None):
    """DSSAT's nitrogen levels for run `rid` → the output's path, or None when skipped or not possible."""
    res = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))
    third = res["meta"].get("third_engine") or {}
    if not third.get("varieties"):
        log(f"{rid}: no DSSAT results in this run ({third.get('why_not', 'made before DSSAT was added')}); skipped")
        return None
    nhash = nitrogen_hash(res["meta"], third.get("config_hash"))
    path = N_OUT / f"{rid}.json"
    if path.exists() and not force:
        old = json.loads(path.read_text(encoding="utf-8"))["meta"]
        if old.get("nitrogen_hash") == nhash:
            log(f"{rid}: already made from these results; skipped")
            return None
        age = dt.datetime.now().astimezone() - dt.datetime.fromisoformat(old["created"])
        if (max_age_days is not None and old.get("dssat_config_hash") == third.get("config_hash")
                and age < dt.timedelta(days=max_age_days)):
            log(f"{rid}: made {age.days} day(s) ago with the same DSSAT configuration; kept until {max_age_days} days")
            return None
    _, varieties = ro.load_varieties()
    use = set(ro.dssat_varieties(varieties))
    varieties = {k: v for k, v in varieties.items() if k in use and k in third["varieties"]}
    rules = list(res["meta"]["planting_rules"])
    cell_of = {sid: tuple(s["cell"]) for sid, s in res["sites"].items()}
    reps = {}
    for sid in res["sites"]:
        reps.setdefault(cell_of[sid], sid)
    with xr.open_dataset(C.WEATHER_OUT / f"{rid}.nc") as ds:
        ds.load()
        base = rs.base_tasks(res, ds, varieties, rules, list(reps.values()))
    levels, split, reported, assumed = settings()
    normal = nitrogen_normal(varieties, rules, workers, third.get("config_hash"))
    tasks, keys = [], []
    for key3, t in base:
        if "rad" not in t:
            continue
        for lk, lv in site_levels(key3[0], levels, reported).items():
            tasks.append(dict(with_nitrogen(t, key3[0], lv, split), potential=False))
            keys.append((*key3, lk))
    log(f"{rid}: {len(tasks)} runs ({len(base)} site, crop and rule cells × {len(levels)} nitrogen levels)")
    t0 = time.time()
    outs = ro.run_tasks(tasks, workers, engine="dssat")
    out = {}
    for (sid, vk, rk, lk), members in zip(keys, outs):
        for m in members:
            m.pop("_canopy", None)
        summ = rs.compact(ro.summarize(members, varieties[vk], ((normal.get(lk) or {}).get(sid) or {}).get(vk, {}).get(rk)))
        for gid in [x for x in res["sites"] if cell_of[x] == cell_of[sid]]:
            entry = out.setdefault(gid, {"name": res["sites"][gid]["name"], "results": {}})
            cell = entry["results"].setdefault(vk, {}).setdefault(rk, {})
            if "water_limited" not in cell:
                d = res["sites"][gid]["results"].get(vk, {}).get(rk, {}).get("dssat")
                cell["water_limited"] = rs.compact(d["summary"]) if d else None
            cell[lk] = summ
    meta = {"id": rid, "source": res["meta"]["source"], "model_label": res["meta"]["model_label"], "run": res["meta"]["run"],
            "obs_end": res["meta"]["obs_end"], "engine": ro.THIRD_ENGINE, "config_hash": res["meta"]["config_hash"],
            "dssat_config_hash": third.get("config_hash"), "nitrogen_hash": nhash,
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "levels": levels, "split": split, "assumed": assumed,
            "reported": {sid: site_levels(sid, levels, reported)["reported"] for sid in reported if sid in out},
            "soil": {"organic_n_factor": dsa.soil_factor(), "c_to_n": dsa.C_TO_N,
                     "sites": {sid: dsa.soil_factor(sid) for sid in (dsa.soil_settings().get("sites") or {})},
                     "initial_mineral_n_ppm": {"NO3": dsa.INIT_NO3, "NH4": dsa.INIT_NH4}},
            "normal": NORMAL,
            "water_limited": "DSSAT's outlook of the same members: no nitrogen limitation",
            "varieties": {k: res["meta"]["varieties"][k] for k in varieties},
            "planting_rules": {k: res["meta"]["planting_rules"][k] for k in rules}}
    N_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "sites": out}, indent=1), encoding="utf-8")
    log(f"{rid}: done in {time.time() - t0:.0f} s → {path.relative_to(C.BASE) if path.is_relative_to(C.BASE) else path}")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run id (default: the latest seasonal run)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-age-days", type=float)
    ap.add_argument("--no-dashboard", action="store_true", help="do not rewrite the tab's nitrogen.json")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not dsa.installed():
        log(f"DSSAT is not installed ({dsa.EXE}); skipped")
        return 0
    rid = a.run or rs.latest_run()
    if not rid:
        log("no seasonal run on disk")
        return 1
    run(rid, a.workers, a.force, a.max_age_days)
    if not a.no_dashboard:
        from crop_engine import dashboard
        dashboard.write_nitrogen(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
