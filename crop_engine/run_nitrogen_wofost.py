#!/usr/bin/env python3
"""
Nitrogen in the seasonal outlook, WOFOST 8.1 (adapters/wofost_adapter.py, nitrogen): the members of the latest seasonal
run grown again by WOFOST 8.1 with its nitrogen balance, at DSSAT's fertiliser levels and split (dssat_cultivars.yaml
"nitrogen", run_nitrogen.settings: assumed rates until the sites report theirs), beside WOFOST 8.1 with no nitrogen
limit (the soil's supply made unlimited), each read against the same level's observed-weather normal
(climatology_wofost_n.json, rebuilt when WOFOST's configuration, the levels or the soil's values change). The soil's
nitrogen: crop_engine/wofost_nitrogen.yaml (calibration/wofost_nitrogen.py). Maize only: PCSE's sorghum set has no
WOFOST 8.1 nitrogen parameters, and WOFOST has no dry bean.
Weekly from crop_engine.run_all, as DSSAT's levels. Output (not committed): outputs/crop_engine/nitrogen_wofost/<run>.json;
the tab's nitrogen_wofost.json.
  python -m crop_engine.run_nitrogen_wofost --workers 2 [--max-age-days 7] [--force]
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import xarray as xr
import yaml

from crop_engine import config as C
from crop_engine import run_nitrogen as rn
from crop_engine import run_outlook as ro
from crop_engine import run_scenarios as rs
from crop_engine.adapters import wofost_adapter as wf

N_OUT = C.OUT / "nitrogen_wofost"
NORMAL = "climatology_wofost_n.json"
SETTINGS = Path(__file__).with_name("wofost_nitrogen.yaml")
PUBLISHED = C.DASHBOARD_OUT / "nitrogen_wofost.json"
UNLIMITED = {"label": "No nitrogen limit (WOFOST 8.1)", "rate_kg_ha": 0, "unlimited": True}


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] nitrogen (WOFOST): {m}", flush=True)


def soil_settings():
    s = yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    return s or {}


def with_nitrogen(t, lv, split):
    s = soil_settings()
    soil = dict(s.get("soil") or {})
    if lv.get("unlimited"):
        soil["NSOILBASE"], soil["NAVAILI"] = 2000.0, 500.0
    return dict(t, nitrogen={"rate_kg_ha": lv["rate_kg_ha"], "split": split.get(t["variety"]["aquacrop_crop"], [(0, 1.0)]),
                             "recovery": s.get("recovery", wf.N_RECOVERY), **soil})


def maize(varieties):
    return {k: v for k, v in varieties.items() if k in ro.wofost_varieties(varieties) and v["aquacrop_crop"] == "MaizeGDD"}


def levels_all():
    levels, split, reported, assumed = rn.settings()
    return {"unlimited": UNLIMITED, **levels}, split, reported, assumed


def config(rules, sites):
    h = hashlib.sha1(json.dumps([ro.wofost_hash(rules, sites), levels_all()[:3], soil_settings()], sort_keys=True,
                                default=list).encode())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:12]


def normal(varieties, rules, workers, chash, force=False):
    from crop_engine import compare_engines as ce
    from crop_engine.data import soil as soil_mod
    from crop_engine.data import weather as W
    path = C.OUT / NORMAL
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if old and old.get("config_hash") == chash and not force:
        return old["levels"]
    levels, split, reported, _ = levels_all()
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    inp = W.Inputs(refresh=False)
    rep = ro.cells(inp.sites)
    soils = {s.id: soil_mod.profile(s) for s, _ in rep}
    tasks, keys = ce.tasks_for(inp, years, rep, varieties, rules, soils)
    nt, nk = [], []
    for t, (sid, vk, rk, y) in zip(tasks, keys):
        for lk, lv in rn.site_levels(sid, levels, reported).items():
            nt.append(with_nitrogen(t, lv, split))
            nk.append((lk, sid, vk, rk, y))
    log(f"normal: {len(nt)} observed seasons ({len(years)} years, {len(levels)} levels)")
    t0 = time.time()
    res = ro.run_tasks(nt, workers, engine="wofost")
    out = {}
    for lk in {k[0] for k in nk}:
        idx = [i for i, k in enumerate(nk) if k[0] == lk]
        out[lk] = ro.bench_stats([res[i] for i in idx], [nk[i][1:] for i in idx], varieties, years)
    path.write_text(json.dumps({"config_hash": chash, "years": list(C.HIST_YEARS), "levels": out}), encoding="utf-8")
    log(f"normal done in {time.time() - t0:.0f} s")
    return out


def run(rid, workers=2, force=False, max_age_days=None):
    res = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))
    if not (res["meta"].get("second_engine") or {}).get("varieties"):
        log(f"{rid}: no WOFOST results in this run; skipped")
        return None
    if not soil_settings().get("soil"):
        log(f"no soil nitrogen in {SETTINGS.name} (python -m crop_engine.calibration.wofost_nitrogen); skipped")
        return None
    _, varieties = ro.load_varieties()
    varieties = maize(varieties)
    rules = list(res["meta"]["planting_rules"])
    from crop_engine.data.sites import registered_sites
    chash = config(rules, registered_sites())
    path = N_OUT / f"{rid}.json"
    if path.exists() and not force:
        old = json.loads(path.read_text(encoding="utf-8"))["meta"]
        age = dt.datetime.now().astimezone() - dt.datetime.fromisoformat(old["created"])
        if old.get("obs_end") == res["meta"]["obs_end"] and old.get("nitrogen_hash") == chash:
            log(f"{rid}: already made from these results; skipped")
            return None
        if max_age_days is not None and old.get("nitrogen_hash") == chash and age < dt.timedelta(days=max_age_days):
            log(f"{rid}: made {age.days} day(s) ago; kept until {max_age_days} days")
            return None
    cell_of = {sid: tuple(s["cell"]) for sid, s in res["sites"].items()}
    reps = {}
    for sid in res["sites"]:
        reps.setdefault(cell_of[sid], sid)
    with xr.open_dataset(C.WEATHER_OUT / f"{rid}.nc") as ds:
        ds.load()
        base = rs.base_tasks(res, ds, varieties, rules, list(reps.values()))
    levels, split, reported, assumed = levels_all()
    norm = normal(varieties, rules, workers, chash)
    tasks, keys = [], []
    for key3, t in base:
        if "rad" not in t:
            continue
        for lk, lv in rn.site_levels(key3[0], levels, reported).items():
            tasks.append(with_nitrogen(t, lv, split))
            keys.append((*key3, lk))
    log(f"{rid}: {len(tasks)} runs ({len(base)} site, crop and rule cells x {len(levels)} levels)")
    t0 = time.time()
    outs = ro.run_tasks(tasks, workers, engine="wofost")
    out = {}
    for (sid, vk, rk, lk), members in zip(keys, outs):
        for m in members:
            m.pop("_canopy", None)
        summ = rs.compact(ro.summarize(members, varieties[vk], ((norm.get(lk) or {}).get(sid) or {}).get(vk, {}).get(rk)))
        for gid in [x for x in res["sites"] if cell_of[x] == cell_of[sid]]:
            entry = out.setdefault(gid, {"name": res["sites"][gid]["name"], "results": {}})
            cell = entry["results"].setdefault(vk, {}).setdefault(rk, {})
            cell["water_limited" if lk == "unlimited" else lk] = summ
    meta = {"id": rid, "source": res["meta"]["source"], "model_label": res["meta"]["model_label"], "run": res["meta"]["run"],
            "obs_end": res["meta"]["obs_end"], "engine": "WOFOST 8.1 (PCSE Wofost81_NWLP_CWB_CNB)",
            "config_hash": res["meta"]["config_hash"], "nitrogen_hash": chash,
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "levels": {k: v for k, v in levels.items() if k != "unlimited"}, "split": split, "assumed": assumed,
            "soil": soil_settings(), "normal": NORMAL,
            "water_limited": "WOFOST 8.1 with the soil's nitrogen unlimited, the same members",
            "varieties": {k: res["meta"]["varieties"][k] for k in varieties if k in res["meta"]["varieties"]},
            "planting_rules": {k: res["meta"]["planting_rules"][k] for k in rules}}
    N_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "sites": out}), encoding="utf-8")
    log(f"{rid}: done in {time.time() - t0:.0f} s -> {path}")
    return path


def publish(rid):
    src = N_OUT / f"{rid}.json" if rid else None
    if src and src.exists():
        d = json.loads(src.read_text(encoding="utf-8"))
        res = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))["meta"]
        if d["meta"].get("config_hash") == res.get("config_hash"):
            PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
            PUBLISHED.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
            log(f"dashboard: WOFOST nitrogen levels of {rid}")
            return True
    if PUBLISHED.exists():
        PUBLISHED.unlink()
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-age-days", type=float)
    ap.add_argument("--no-dashboard", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rid = a.run or rs.latest_run()
    if not rid:
        log("no seasonal run on disk")
        return 1
    run(rid, a.workers, a.force, a.max_age_days)
    if not a.no_dashboard:
        publish(rid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
