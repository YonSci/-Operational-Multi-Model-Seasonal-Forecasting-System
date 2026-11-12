#!/usr/bin/env python3
"""
Nitrogen in the seasonal outlook (DSSAT only, adapters/dssat_adapter.py): the members of the latest seasonal run
grown again by DSSAT with its nitrogen balance on, at the fertiliser rates LEVELS, beside DSSAT's water-limited
outlook (the run's own "dssat" results: no nitrogen limitation). The same weather, soil, starting water and sowing
dates as the outlook (run_scenarios.base_tasks); urea split as SPLIT (days after sowing, share); the soil's organic
nitrogen from dssat_cultivars.yaml "soil" (organic_n_factor, calibration/dssat.py --nitrogen).

The rates are assumptions until the sites' managers report theirs (the partner questionnaire, CROP_ENGINE.md
"Questions for partners"): no fertiliser (most smallholder fields in the drylands), a low rate (micro-dosing or a
little top dressing), and a moderate rate. The bean fixes nitrogen (DSSAT's symbiosis on) and gets the same rates.

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
LEVELS = {
    "n0": {"label": "No fertiliser", "rate_kg_ha": 0},
    "n25": {"label": "25 kg N/ha (low)", "rate_kg_ha": 25},
    "n50": {"label": "50 kg N/ha (moderate)", "rate_kg_ha": 50},
}
SPLIT = {"MaizeGDD": [(0, 0.4), (30, 0.6)], "SorghumGDD": [(0, 0.4), (30, 0.6)], "DryBeanGDD": [(0, 1.0)]}
ASSUMED = ("Assumed rates, until the sites' managers report theirs; urea, 40 % at sowing and 60 % 30 days after "
           "(the bean all at sowing)")


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] nitrogen: {m}", flush=True)


def nitrogen_hash(results_meta, dhash):
    h = hashlib.sha1(json.dumps([results_meta.get("config_hash"), results_meta.get("created"), dhash, LEVELS,
                                 SPLIT, dsa.soil_settings()]).encode())
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
    factor = float(dsa.soil_settings().get("organic_n_factor", 1.0))
    tasks, keys = [], []
    for key3, t in base:
        if "rad" not in t:
            continue
        for lk, lv in LEVELS.items():
            tasks.append(dict(t, nitrogen={"rate_kg_ha": lv["rate_kg_ha"], "split": SPLIT[t["variety"]["aquacrop_crop"]],
                                           "organic_n_factor": factor}))
            keys.append((*key3, lk))
    log(f"{rid}: {len(tasks)} runs ({len(base)} site, crop and rule cells × {len(LEVELS)} nitrogen levels)")
    t0 = time.time()
    outs = ro.run_tasks(tasks, workers, engine="dssat")
    out = {}
    for (sid, vk, rk, lk), members in zip(keys, outs):
        for m in members:
            m.pop("_canopy", None)
        summ = rs.compact(ro.summarize(members, varieties[vk], None))
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
            "levels": LEVELS, "split": SPLIT, "assumed": ASSUMED,
            "soil": {"organic_n_factor": factor, "c_to_n": dsa.C_TO_N,
                     "initial_mineral_n_ppm": {"NO3": dsa.INIT_NO3, "NH4": dsa.INIT_NH4}},
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
