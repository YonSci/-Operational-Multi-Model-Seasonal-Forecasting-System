#!/usr/bin/env python3
"""
Other crops (WOFOST only, uncalibrated): the dryland legumes and cereals AquaCrop-OSPy has no crop file for (cowpea,
green gram, short-duration pigeonpea, pearl millet, groundnut: crop_engine/wofost_crops.yaml), grown by WOFOST in the
latest seasonal run's weather, at its sites, sown on the same planting rules' dates as the outlook's crops (the rule's
onset of each member, re-sown after a failed establishment as the outlook), and compared with each crop's own normal:
the same crop grown by WOFOST in the observed weather of 1993–2025, sown on the rule's observed dates
(compare_engines.tasks_for). Only the phenology is set (the varieties' days); the yield level is WOFOST's own crop set,
not calibrated: read the chance of failure and below / above normal, not the tonnes.

Weekly from crop_engine.run_all (--max-age-days 7), in the crop step's time left; the normal is rebuilt only when the
crops, the WOFOST adapter or PCSE change.

  python -m crop_engine.run_other_crops                     # the latest seasonal run
  python -m crop_engine.run_other_crops --crops cowpea green_gram --workers 3 --force

Outputs (not committed): outputs/crop_engine/other_crops/benchmark.json, <run id>.json; the tab's copy
frontend/public/tracker/data/crop/other_crops.json (published).
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr
import yaml

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine import run_scenarios as rs
from crop_engine.adapters import wofost_adapter as wf

CROPS_FILE = Path(__file__).with_name("wofost_crops.yaml")
OUT = C.OUT / "other_crops"
PUBLISHED = C.DASHBOARD_OUT / "other_crops.json"


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_crops(only=None):
    cfg = yaml.safe_load(CROPS_FILE.read_text(encoding="utf-8"))
    out = {}
    for k, v in cfg["crops"].items():
        if only and k not in only:
            continue
        out[k] = dict(v, kw={}, wofost=v.get("wofost") or {})
    return out


def crops_hash(crops, rules, sites):
    h = hashlib.sha1(CROPS_FILE.read_bytes())
    h.update(json.dumps(sorted(crops)).encode())
    h.update(ro.wofost_hash(rules, sites).encode())
    return h.hexdigest()[:12]


def benchmark(inp, rep_cells, crops, rules, soils, workers, force=False):
    """Each crop's normal: WOFOST in the observed weather of C.HIST_YEARS at the sites (module doc)."""
    from crop_engine import compare_engines as ce
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    h = crops_hash(crops, rules, inp.sites)
    path = OUT / "benchmark.json"
    if path.exists() and not force:
        b = json.loads(path.read_text(encoding="utf-8"))
        if b.get("config_hash") == h:
            return b
    tasks, keys = ce.tasks_for(inp, years, rep_cells, crops, rules, soils)
    t0 = time.time()
    sites = ro.bench_stats(ro.run_tasks(tasks, workers, engine="wofost"), keys, crops, years)
    for vs in sites.values():
        for rr in vs.values():
            for r in rr.values():
                r.pop("canopy", None)
    b = {"config_hash": h, "years": years, "cal_years": list(C.CAL_YEARS), "engine": ro.SECOND_ENGINE,
         "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "sites": sites}
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(b), encoding="utf-8")
    log(f"other crops: normal of {len(crops)} crops at {len(rep_cells)} sites in {time.time() - t0:.0f} s -> {path}")
    return b


def run(rid, crops, rules, workers, force=False, max_age_days=None):
    """The crops in run `rid`'s weather → its path, or None when kept or skipped."""
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.sites import registered_sites
    from crop_engine.data.weather import Inputs
    res = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))
    rules = [r for r in (rules or res["meta"]["planting_rules"]) if r in res["meta"]["planting_rules"]]
    path = OUT / f"{rid}.json"
    obs_end = res["meta"].get("obs_end")
    if path.exists() and not force:
        old = json.loads(path.read_text(encoding="utf-8"))["meta"]
        age = dt.datetime.now().astimezone() - dt.datetime.fromisoformat(old["created"])
        if old.get("obs_end") == obs_end and old.get("crops") == sorted(crops):
            log(f"{rid}: other crops already made from these observations")
            return None
        if max_age_days is not None and age < dt.timedelta(days=max_age_days) and old.get("crops") == sorted(crops):
            log(f"{rid}: other crops made {age.days} day(s) ago; kept until {max_age_days} days")
            return None
    inp = Inputs(refresh=False)
    if inp.met2 is None:
        log(f"other crops: no radiation, humidity or wind ({inp.met2_note}); skipped")
        return None
    ids = [s.id for s in inp.sites]
    cell_of = {sid: tuple(s["cell"]) for sid, s in res["sites"].items()}
    reps = {}
    for sid in res["sites"]:
        if sid in ids:
            reps.setdefault(cell_of[sid], sid)
    by_id = {s.id: s for s in registered_sites()}
    rep_cells = [(next(s for s in inp.sites if s.id == sid), [sid]) for sid in reps.values()]
    soils = {s.id: soil_mod.profile(s) for s, _ in rep_cells}
    bench = benchmark(inp, rep_cells, crops, rules, soils, workers)
    # the outlook's sowing dates of the run: a variety the run grew (each rule's dates are the same for every variety)
    base_var = next(iter(next(iter(res["sites"].values()))["results"]))
    _, bv = ro.load_varieties([base_var])
    with xr.open_dataset(C.WEATHER_OUT / f"{rid}.nc") as ds:
        ds.load()
        base = rs.base_tasks(res, ds, bv, rules, list(reps.values()))
    if not base or "rad" not in base[0][1]:
        log(f"{rid}: no radiation, humidity or wind in the run's weather; other crops skipped")
        return None
    tasks, keys = [], []
    for (sid, _, rk), t in base:
        for ck, c in crops.items():
            tasks.append(dict(t, variety=c, kw={}))
            keys.append((sid, ck, rk))
    t0 = time.time()
    out = ro.run_tasks(tasks, workers, engine="wofost")
    results = {}
    for (sid, ck, rk), members in zip(keys, out):
        members = [{k: v for k, v in m.items() if not k.startswith("_")} for m in members]
        b = bench["sites"].get(sid, {}).get(ck, {}).get(rk)
        results.setdefault(sid, {}).setdefault(ck, {})[rk] = {"summary": ro.summarize(members, crops[ck], b),
                                                              "members": members}
    meta = {"id": rid, "run": res["meta"]["run"], "model_label": res["meta"].get("model_label"), "obs_end": obs_end,
            "engine": ro.SECOND_ENGINE, "crops": sorted(crops), "rules": rules,
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "benchmark_hash": bench["config_hash"], "years": bench["years"],
            "labels": {k: {f: c.get(f) for f in ("label", "examples", "maturity_days", "flowering_days",
                                                  "reference_tmean_c", "failure_t_ha")} for k, c in crops.items()},
            "sites": {sid: {"name": by_id[sid].name if sid in by_id else sid} for sid in results},
            "note": "WOFOST only, phenology from the varieties' days; yield level not calibrated (wofost_crops.yaml)"}
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "results": results}), encoding="utf-8")
    log(f"{rid}: {len(crops)} other crops, {sum(len(m) for m in out)} member seasons in {time.time() - t0:.0f} s -> {path}")
    return path


def publish(rid, log=log):
    """other_crops.json for the tab: the summaries (no members) of the latest seasonal run, or the file removed."""
    src = OUT / f"{rid}.json" if rid else None
    if not src or not src.exists():
        if PUBLISHED.exists():
            PUBLISHED.unlink()
        return False
    d = json.loads(src.read_text(encoding="utf-8"))
    slim = {sid: {ck: {rk: r["summary"] for rk, r in rr.items()} for ck, rr in cs.items()} for sid, cs in d["results"].items()}
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED.write_text(json.dumps({"meta": d["meta"], "sites": slim}, separators=(",", ":")), encoding="utf-8")
    log(f"dashboard: other crops of {rid}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run id (default: the latest seasonal run)")
    ap.add_argument("--crops", nargs="+")
    ap.add_argument("--rules", nargs="+", choices=list(C.PLANTING_RULES))
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
    run(rid, load_crops(a.crops), a.rules, a.workers, a.force, a.max_age_days)
    if not a.no_dashboard:
        publish(rid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
