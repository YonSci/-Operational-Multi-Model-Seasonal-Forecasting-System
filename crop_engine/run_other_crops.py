#!/usr/bin/env python3
"""
Other crops (WOFOST only, uncalibrated): the dryland legumes and cereals AquaCrop-OSPy has no crop file for (cowpea,
green gram, short-duration pigeonpea, pearl millet, groundnut: crop_engine/wofost_crops.yaml), grown by WOFOST in the
latest seasonal run's weather, at its sites, sown on the same planting rules' dates as the outlook's crops (the rule's
onset of each member, re-sown after a failed establishment as the outlook), and compared with each crop's own normal:
the same crop grown by WOFOST in the observed weather of 1993–2025, sown on the rule's observed dates
(compare_engines.tasks_for). Only the phenology is set (the varieties' days); the yield level is WOFOST's own crop set,
not calibrated: read the chance of failure and below / above normal, not the tonnes.

Nitrogen (WOFOST 8.1, as run_nitrogen_wofost for maize): the legumes whose WOFOST 8.1 sets have nitrogen parameters
(cowpea, green gram, pigeonpea, groundnut: wofost_adapter.NITROGEN_CROPS; they fix nitrogen, NFIX_FR) grown again with
WOFOST 8.1's nitrogen balance and the soil nitrogen of wofost_nitrogen.yaml, at no fertiliser and the plain urea levels
of run_nitrogen.settings (25 and 50 kg N/ha, all at sowing as DSSAT's bean; not a site's reported maize practice),
beside WOFOST 8.1 with no nitrogen limit; each level against its own normal (the same level in the observed seasons,
benchmark_nitrogen.json). Pearl millet has no 8.1 nitrogen parameters and is left out.

DSSAT as a second model (dssat_adapter OTHER_CROPS, wofost_crops.yaml `dssat`): CROPGRO-Cowpea, -Pigeonpea, -Peanut
(groundnut) and CERES-Millet on the same tasks, a cultivar of DSSAT's file with its phases fitted to the variety's days
(calibration/dssat.py --other-crops), against its own DSSAT normal (benchmark_dssat.json); DSSAT has no mung bean.
Its yield level is DSSAT's own, uncalibrated, as WOFOST's. No yield without water stress is run (potential off).

Weekly from crop_engine.run_all (--max-age-days 7), in the crop step's time left; each normal is rebuilt only when
the crops, its engine's adapter or configuration change.

  python -m crop_engine.run_other_crops                     # the latest seasonal run
  python -m crop_engine.run_other_crops --crops cowpea green_gram --workers 3 --force
  python -m crop_engine.run_other_crops --no-nitrogen --no-dssat         # WOFOST 7.2 alone

Outputs (not committed): outputs/crop_engine/other_crops/benchmark.json, benchmark_nitrogen.json,
benchmark_dssat.json, <run id>.json; the tab's copy frontend/public/tracker/data/crop/other_crops.json (published).
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
from crop_engine import run_nitrogen_wofost as rnw
from crop_engine import run_outlook as ro
from crop_engine import run_scenarios as rs
from crop_engine.adapters import dssat_adapter as dsa
from crop_engine.adapters import wofost_adapter as wf

CROPS_FILE = Path(__file__).with_name("wofost_crops.yaml")
OUT = C.OUT / "other_crops"
PUBLISHED = C.DASHBOARD_OUT / "other_crops.json"
N_ENGINE = "WOFOST 8.1 (PCSE Wofost81_NWLP_CWB_CNB)"
D_ENGINE = "DSSAT CSM 4.8 (CROPGRO-Cowpea, -Pigeonpea, -Peanut, CERES-Millet)"
N_SPLIT = [(0, 1.0)]              # the urea all at sowing, as DSSAT's bean (dssat_cultivars.yaml nitrogen split)


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


def nitrogen_crops(crops):
    """The crops WOFOST 8.1 can grow with nitrogen (its sets with nitrogen parameters: not pearl millet)."""
    return {k: c for k, c in crops.items() if wf.crop_of(c)[0] in wf.NITROGEN_CROPS}


def dssat_crops(crops):
    """The crops with a DSSAT model and cultivar (wofost_crops.yaml `dssat`), DSSAT installed."""
    return {k: c for k, c in crops.items() if dsa.available(c)}


def n_levels():
    """{level: spec}: WOFOST 8.1 with no nitrogen limit ("unlimited") and the plain urea levels (module doc)."""
    return rnw.levels_all()[0]


def with_nitrogen(t, lv):
    """The task grown by WOFOST 8.1 at level lv: the soil's nitrogen (wofost_nitrogen.yaml; unlimited: the soil's
    supply made unlimited, as run_nitrogen_wofost), the urea at sowing."""
    s = rnw.soil_settings()
    soil = dict(s.get("soil") or {})
    if lv.get("unlimited"):
        soil["NSOILBASE"], soil["NAVAILI"] = 2000.0, 500.0
    return dict(t, nitrogen={"rate_kg_ha": lv["rate_kg_ha"], "split": N_SPLIT,
                             "recovery": s.get("recovery", wf.N_RECOVERY), **soil})


def nitrogen_hash(crops, rules, sites):
    h = hashlib.sha1(crops_hash(crops, rules, sites).encode())
    h.update(json.dumps([n_levels(), rnw.soil_settings(), N_SPLIT], sort_keys=True, default=list).encode())
    return h.hexdigest()[:12]


def dssat_hash(crops, rules, sites):
    h = hashlib.sha1(CROPS_FILE.read_bytes())
    h.update(json.dumps(sorted(crops)).encode())
    h.update(ro.dssat_hash(rules, sites).encode())
    return h.hexdigest()[:12]


def _stats(res, keys, crops, years):
    sites = ro.bench_stats(res, keys, crops, years)
    for vs in sites.values():
        for rr in vs.values():
            for r in rr.values():
                r.pop("canopy", None)
    return sites


def observed_tasks(inp, rep_cells, crops, rules, soils):
    """observed(): the observed seasons' (tasks, keys) of every crop (compare_engines.tasks_for), built once, when a
    normal needs them."""
    from crop_engine import compare_engines as ce
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    cache = []

    def observed():
        if not cache:
            cache.append(ce.tasks_for(inp, years, rep_cells, crops, rules, soils))
        return cache[0]
    return observed


def normal(name, h, observed, crops, workers, engine="wofost", levels=None, force=False):
    """A normal of `crops` (module doc), kept in OUT/<name> while its hash h holds: the observed seasons (observed())
    grown by `engine`; with levels ({level: spec}) each grown by WOFOST 8.1 at each level (with_nitrogen) →
    {"levels": {level: sites}}, else {"sites": sites}."""
    path = OUT / name
    if path.exists() and not force:
        b = json.loads(path.read_text(encoding="utf-8"))
        if b.get("config_hash") == h:
            return b
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    tasks, keys = observed()
    sel = [i for i, k in enumerate(keys) if k[1] in crops]
    tasks, keys = [tasks[i] for i in sel], [keys[i] for i in sel]
    if engine == "dssat":
        tasks = [dict(t, potential=False) for t in tasks]
    t0 = time.time()
    b = {"config_hash": h, "years": years, "cal_years": list(C.CAL_YEARS),
         "engine": N_ENGINE if levels else ro.SECOND_ENGINE if engine == "wofost" else D_ENGINE,
         "created": dt.datetime.now().astimezone().isoformat(timespec="minutes")}
    if levels:
        lks = [lk for lk in levels for _ in tasks]
        res = ro.run_tasks([with_nitrogen(t, levels[lk]) for lk in levels for t in tasks], workers, engine="wofost")
        b["levels"] = {lk: _stats([r for r, x in zip(res, lks) if x == lk], keys, crops, years) for lk in levels}
    else:
        b["sites"] = _stats(ro.run_tasks(tasks, workers, engine=engine), keys, crops, years)
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(b), encoding="utf-8")
    log(f"other crops: {name}, {len(crops)} crops, {len(tasks)} seasons{f' x {len(levels)} levels' if levels else ''} "
        f"in {time.time() - t0:.0f} s -> {path}")
    return b


def benchmark(inp, rep_cells, crops, rules, soils, workers, force=False, observed=None):
    """Each crop's normal: WOFOST in the observed weather of C.HIST_YEARS at the sites (module doc)."""
    observed = observed or observed_tasks(inp, rep_cells, crops, rules, soils)
    return normal("benchmark.json", crops_hash(crops, rules, inp.sites), observed, crops, workers, force=force)


def run(rid, crops, rules, workers, force=False, max_age_days=None, nitrogen=True, dssat=True):
    """The crops in run `rid`'s weather (WOFOST 7.2; WOFOST 8.1's nitrogen levels and DSSAT where they can, unless
    nitrogen / dssat is False) → its path, or None when kept or skipped."""
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.sites import registered_sites
    from crop_engine.data.weather import Inputs
    res = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))
    rules = [r for r in (rules or res["meta"]["planting_rules"]) if r in res["meta"]["planting_rules"]]
    ncrops = nitrogen_crops(crops) if nitrogen else {}
    dcrops = dssat_crops(crops) if dssat else {}
    path = OUT / f"{rid}.json"
    obs_end = res["meta"].get("obs_end")
    parts = {"nitrogen": sorted(ncrops), "dssat": sorted(dcrops)}
    if path.exists() and not force:
        old = json.loads(path.read_text(encoding="utf-8"))["meta"]
        age = dt.datetime.now().astimezone() - dt.datetime.fromisoformat(old["created"])
        same = old.get("crops") == sorted(crops) and old.get("parts") == parts
        if old.get("obs_end") == obs_end and same:
            log(f"{rid}: other crops already made from these observations")
            return None
        if max_age_days is not None and age < dt.timedelta(days=max_age_days) and same:
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
    observed = observed_tasks(inp, rep_cells, crops, rules, soils)
    bench = benchmark(inp, rep_cells, crops, rules, soils, workers, observed=observed)
    levels = n_levels() if ncrops else {}
    nbench = (normal("benchmark_nitrogen.json", nitrogen_hash(ncrops, rules, inp.sites), observed, ncrops, workers,
                     levels=levels) if ncrops else None)
    dbench = (normal("benchmark_dssat.json", dssat_hash(dcrops, rules, inp.sites), observed, dcrops, workers,
                     engine="dssat") if dcrops else None)
    # the outlook's sowing dates of the run: a variety the run grew (each rule's dates are the same for every variety)
    base_var = next(iter(next(iter(res["sites"].values()))["results"]))
    _, bv = ro.load_varieties([base_var])
    with xr.open_dataset(C.WEATHER_OUT / f"{rid}.nc") as ds:
        ds.load()
        base = rs.base_tasks(res, ds, bv, rules, list(reps.values()))
    if not base or "rad" not in base[0][1]:
        log(f"{rid}: no radiation, humidity or wind in the run's weather; other crops skipped")
        return None
    wtasks, wkeys, dtasks, dkeys = [], [], [], []
    for (sid, _, rk), t in base:
        for ck, c in crops.items():
            wtasks.append(dict(t, variety=c, kw={}))
            wkeys.append((sid, ck, rk, "wofost"))
            for lk in (levels if ck in ncrops else {}):
                wtasks.append(with_nitrogen(dict(t, variety=c, kw={}), levels[lk]))
                wkeys.append((sid, ck, rk, lk))
            if ck in dcrops:
                dtasks.append(dict(t, variety=c, kw={}, potential=False))
                dkeys.append((sid, ck, rk, "dssat"))
    t0 = time.time()
    out = ro.run_tasks(wtasks, workers, engine="wofost") + (ro.run_tasks(dtasks, workers, engine="dssat") if dtasks else [])
    results = {}
    for (sid, ck, rk, part), members in zip(wkeys + dkeys, out):
        members = [{k: v for k, v in m.items() if not k.startswith("_")} for m in members]
        cell = results.setdefault(sid, {}).setdefault(ck, {}).setdefault(rk, {})
        if part == "wofost":
            b = bench["sites"].get(sid, {}).get(ck, {}).get(rk)
            cell.update(summary=ro.summarize(members, crops[ck], b), members=members)
        elif part == "dssat":
            b = dbench["sites"].get(sid, {}).get(ck, {}).get(rk)
            cell["dssat"] = {"summary": ro.summarize(members, crops[ck], b), "members": members}
        else:                                                           # a nitrogen level: its summary only
            b = nbench["levels"].get(part, {}).get(sid, {}).get(ck, {}).get(rk)
            cell.setdefault("nitrogen", {})[part] = rs.compact(ro.summarize(members, crops[ck], b))
    meta = {"id": rid, "run": res["meta"]["run"], "model_label": res["meta"].get("model_label"), "obs_end": obs_end,
            "engine": ro.SECOND_ENGINE, "crops": sorted(crops), "rules": rules, "parts": parts,
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "benchmark_hash": bench["config_hash"], "years": bench["years"],
            "labels": {k: {f: c.get(f) for f in ("label", "examples", "maturity_days", "flowering_days",
                                                  "reference_tmean_c", "failure_t_ha")} for k, c in crops.items()},
            "sites": {sid: {"name": by_id[sid].name if sid in by_id else sid} for sid in results},
            "note": "WOFOST only, phenology from the varieties' days; yield level not calibrated (wofost_crops.yaml)"}
    if ncrops:
        meta["nitrogen"] = {"engine": N_ENGINE, "crops": sorted(ncrops), "split": N_SPLIT,
                            "levels": {k: {"label": v["label"], "rate_kg_ha": v["rate_kg_ha"]} for k, v in levels.items()},
                            "soil": rnw.soil_settings(), "benchmark_hash": nbench["config_hash"],
                            "note": "WOFOST 8.1 with its soil nitrogen (wofost_nitrogen.yaml, fitted to maize) and the "
                                    "legumes' own nitrogen fixation; urea at sowing; each level against its own normal"}
    if dcrops:
        meta["dssat"] = {"engine": D_ENGINE, "benchmark_hash": dbench["config_hash"],
                         "crops": {k: {"crop": c["dssat"]["crop"], "cultivar": c["dssat"]["cultivar"],
                                       "model": dsa.crop_spec(dsa.crop_key(c))[1]} for k, c in dcrops.items()},
                         "note": "DSSAT's own crop files, phenology fitted to the varieties' days "
                                 "(calibration/dssat.py --other-crops); yield level not calibrated"}
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "results": results}), encoding="utf-8")
    log(f"{rid}: {len(crops)} other crops ({len(ncrops)} with nitrogen, {len(dcrops)} in DSSAT), "
        f"{sum(len(m) for m in out)} member seasons in {time.time() - t0:.0f} s -> {path}")
    return path


def slim(d):
    """The tab's copy of a run's output: summaries only, {sites, nitrogen, dssat} (module doc)."""
    r = d["results"]
    out = {"meta": d["meta"],
           "sites": {sid: {ck: {rk: x["summary"] for rk, x in rr.items()} for ck, rr in cs.items()} for sid, cs in r.items()}}
    n = {sid: {ck: {rk: x["nitrogen"] for rk, x in rr.items() if x.get("nitrogen")} for ck, rr in cs.items()}
         for sid, cs in r.items()}
    dd = {sid: {ck: {rk: x["dssat"]["summary"] for rk, x in rr.items() if x.get("dssat")} for ck, rr in cs.items()}
          for sid, cs in r.items()}
    prune = lambda t: {sid: {ck: rr for ck, rr in cs.items() if rr} for sid, cs in t.items()}     # noqa: E731
    if d["meta"].get("nitrogen"):
        out["nitrogen"] = prune(n)
    if d["meta"].get("dssat"):
        out["dssat"] = prune(dd)
    return out


def publish(rid, log=log):
    """other_crops.json for the tab: the summaries (no members) of the latest seasonal run, or the file removed."""
    src = OUT / f"{rid}.json" if rid else None
    if not src or not src.exists():
        if PUBLISHED.exists():
            PUBLISHED.unlink()
        return False
    d = json.loads(src.read_text(encoding="utf-8"))
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED.write_text(json.dumps(slim(d), separators=(",", ":")), encoding="utf-8")
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
    ap.add_argument("--no-nitrogen", action="store_true", help="no WOFOST 8.1 nitrogen levels")
    ap.add_argument("--no-dssat", action="store_true", help="no DSSAT")
    ap.add_argument("--no-dashboard", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rid = a.run or rs.latest_run()
    if not rid:
        log("no seasonal run on disk")
        return 1
    run(rid, load_crops(a.crops), a.rules, a.workers, a.force, a.max_age_days, not a.no_nitrogen, not a.no_dssat)
    if not a.no_dashboard:
        publish(rid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
