#!/usr/bin/env python3
"""
Management scenarios of a crop outlook run (crop_engine.scenarios.management): every site, variety and planting rule
of the run grown again in the run's own weather (outputs/crop_engine/weather/<run id>.nc) with one management choice
changed, sown from the run's own sowing dates (results/<run id>.json), and summarised as the outlook (summaries
against the same observed-weather benchmark).

WOFOST, the second model, grows the same scenarios for its varieties (run_outlook.wofost_varieties) when the run has
WOFOST results, except plant density (WOFOST has no plant population): its own outlook re-simulated as its control,
then each scenario, summarised against WOFOST's own benchmark (climatology_wofost.json); each cell carries
"baseline_wofost" and every scenario a "wofost" summary beside AquaCrop's. --no-wofost leaves it out.

Output (not committed): outputs/crop_engine/scenarios/<run id>.json, with the outlook's own summary as "baseline"
next to each scenario's; the Crop outlook tab's copy is written by crop_engine.dashboard (scenarios.json).
A run whose scenarios were made from the same results is skipped; with --max-age-days, so is one made from the same
configuration within that many days (how management changes the crop moves little from day to day: the daily update
refreshes them weekly, in the crop step's time left).

Usage:
  python -m crop_engine.run_scenarios                                   # the latest seasonal run, all sites
  python -m crop_engine.run_scenarios --run seasonal_20261001 --sites kalro_kiboko_makueni_farm --workers 3
  python -m crop_engine.run_scenarios --scenarios sow_plus14 soil_dry --varieties maize_early
  python -m crop_engine.run_scenarios --max-age-days 7 --workers 2          # the daily update (crop_engine.run_all)
"""
import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import xarray as xr

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.data import soil as soil_mod
from crop_engine.data.sites import registered_sites
from crop_engine.scenarios import management as mg
from crop_engine.scenarios import planting as pl

SCEN_OUT = C.OUT / "scenarios"
SUMMARY_KEYS = ("yield_t_ha", "p_failure", "p_failure_if_sown", "p_establishment_failure", "p_sowing_opportunity",
                "yield_if_sown_t_ha", "share", "planting", "harvest_median", "stress_days_median", "resown",
                "irrigation_mm_median", "vs_benchmark")
WOFOST_SKIP = {"density"}  # scenario fields WOFOST cannot represent (management.py)
REPRODUCE_TOL = 0.05      # t/ha: the outlook's member yields, re-simulated unchanged (AquaCrop moves ~0.01 t/ha with the 6th decimal of the initial water)


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] scenarios: {m}", flush=True)


def latest_run(source="seasonal"):
    """The newest run id of `source` in results/index.json (None when there is none)."""
    idx = C.RESULTS_OUT / "index.json"
    if not idx.exists():
        return None
    return next((r["id"] for r in json.loads(idx.read_text(encoding="utf-8"))["runs"] if r["source"] == source), None)


def scenario_hash(results_meta, keys):
    """Changes with the run's results (its configuration and creation) and the scenario definitions."""
    h = hashlib.sha1(json.dumps([results_meta.get("config_hash"), results_meta.get("created"),
                                 [mg.describe(k) for k in keys]]).encode())
    h.update(Path(mg.__file__).read_bytes())
    return h.hexdigest()[:12]


def compact(summary):
    return {k: summary.get(k) for k in SUMMARY_KEYS if k in summary}


def base_tasks(res, ds, varieties, rules, site_ids):
    """The outlook's AquaCrop tasks of the run, sown on its members' first sowing dates → [(site, variety, rule), task]."""
    dates = ds.time.to_index()
    sites = {s.id: s for s in registered_sites()}
    out = []
    for sid in site_ids:
        s = res["sites"][sid]
        k = list(ds.site.values).index(sid)
        rain = ds.precip_mm.isel(site=k).values
        resow = pl.sowing_opportunities(rain, dates)
        # the soil of the site's grid cell, as the outlook simulated it (a registered site alone has no cell)
        lat, lon = s["cell"]
        layers = soil_mod.profile(dataclasses.replace(sites[sid], cell_lat=lat, cell_lon=lon))
        for vk, rs in s["results"].items():
            if vk not in varieties:
                continue
            for rk, r in rs.items():
                if rk not in rules:
                    continue
                plant = [None if m["status"] == "not_sown" or not m.get("planting")
                         else dt.date.fromisoformat(m.get("first_planting") or m["planting"]) for m in r["members"]]
                t = dict(dates=dates.values, rain=rain, tmax=ds.tmax_c.isel(site=k).values, tmin=ds.tmin_c.isel(site=k).values,
                         et0=ds.et0_mm.isel(site=k).values, source=ds.precip_source.values, planting=plant, resow=resow,
                         variety=varieties[vk], kw=varieties[vk]["kw"], layers=layers,
                         initial_frac=float(s["initial_water_fraction"]))
                if "rad_mj_m2" in ds:                                   # WOFOST's weather (AquaCrop ignores it)
                    t.update(rad=ds.rad_mj_m2.isel(site=k).values, vap=ds.vap_hpa.isel(site=k).values,
                             wind2=ds.wind2_ms.isel(site=k).values, lat=sites[sid].lat, lon=sites[sid].lon,
                             elev=float(ds.elev_m.values[k]))
                out.append(((sid, vk, rk), t))
    return out


def wofost_plan(res, varieties, keys):
    """The WOFOST varieties of a run with WOFOST results, and the scenarios WOFOST can grow."""
    if not any("wofost" in x for s in res["sites"].values() for rs in s["results"].values() for x in rs.values()):
        return set(), []
    return set(ro.wofost_varieties(varieties)), [k for k in keys if not WOFOST_SKIP & set(mg.SCENARIOS[k])]


def run(rid, site_ids=None, variety_keys=None, rules=None, keys=None, workers=2, force=False, max_age_days=None,
        wofost=True):
    """Simulate the scenarios of run `rid` and write scenarios/<rid>.json → its path, or None when skipped."""
    keys = list(keys or mg.SCENARIOS)
    res = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))
    shash = scenario_hash(res["meta"], keys) + ("-wofost" if wofost else "")
    path = SCEN_OUT / f"{rid}.json"
    if path.exists() and not force:
        old = json.loads(path.read_text(encoding="utf-8"))["meta"]
        if old.get("scenario_hash") == shash:
            log(f"{rid}: already made from these results; skipped")
            return None
        age = dt.datetime.now().astimezone() - dt.datetime.fromisoformat(old["created"])
        if max_age_days is not None and old.get("config_hash") == res["meta"].get("config_hash")                 and age < dt.timedelta(days=max_age_days):
            log(f"{rid}: made {age.days} day(s) ago from the same configuration (observations to {old['obs_end']}); "
                f"kept until {max_age_days} days")
            return None
    _, varieties = ro.load_varieties(variety_keys)
    rules = list(rules or res["meta"]["planting_rules"])
    # one site per grid cell (the outlook simulates each cell once): the others of a cell share its results
    cell_of = {sid: tuple(s["cell"]) for sid, s in res["sites"].items()}
    wanted = [sid for sid in res["sites"] if not site_ids or sid in site_ids]
    reps = {}
    for sid in wanted:
        reps.setdefault(cell_of[sid], sid)
    bench = json.loads((C.OUT / "climatology.json").read_text(encoding="utf-8"))["sites"]
    with xr.open_dataset(C.WEATHER_OUT / f"{rid}.nc") as ds:
        ds.load()
        base = base_tasks(res, ds, varieties, rules, list(reps.values()))
    tasks, tkeys = [], []
    for key3, t in base:
        tasks.append(t)                                          # the outlook itself, unchanged: the control
        tkeys.append((*key3, None))
        for sk in keys:
            tasks.append(mg.apply(t, sk))
            tkeys.append((*key3, sk))
    wof_vars, wof_keys = wofost_plan(res, varieties, keys) if wofost else (set(), [])
    wtasks, wkeys = [], []
    for key3, t in base:
        if key3[1] in wof_vars and "rad" in t:
            wtasks.append(t)
            wkeys.append((*key3, None))
            for sk in wof_keys:
                wtasks.append(mg.apply(t, sk))
                wkeys.append((*key3, sk))
    log(f"{rid}: {len(tasks)} runs: {len(base)} of the outlook unchanged (the control) and the scenarios ({len(reps)} grid cells, {len(varieties)} varieties, {len(rules)} rules, "
        f"{len(keys)} scenarios, {len(base[0][1]['planting']) if base else 0} members)")
    t0 = time.time()
    outs = ro.run_tasks(tasks, workers)
    wouts = ro.run_tasks(wtasks, workers, engine="wofost") if wtasks else []
    if wtasks:
        log(f"{rid}: WOFOST {len(wtasks)} runs ({len(wof_keys)} scenarios; plant density is AquaCrop's only)")
    wbp = C.OUT / "climatology_wofost.json"
    wbench = json.loads(wbp.read_text(encoding="utf-8"))["sites"] if wbp.exists() else {}
    out, worst = {}, 0.0
    for (sid, vk, rk, sk), members in zip(tkeys, outs):
        for m in members:
            m.pop("_canopy", None)
        if sk is None:
            # the scenarios are only comparable with the outlook if its own crops are reproduced member by member
            orig = res["sites"][sid]["results"][vk][rk]["members"]
            diff = max(abs(a["yield_t_ha"] - b["yield_t_ha"]) for a, b in zip(orig, members))
            worst = max(worst, diff)
            if diff > REPRODUCE_TOL:
                raise RuntimeError(f"{rid}: the outlook of {sid} {vk} {rk} is not reproduced (member yields differ by "
                                   f"up to {diff:.2f} t/ha): scenarios not written")
            continue
        summ = ro.summarize(members, varieties[vk], bench.get(sid, {}).get(vk, {}).get(rk))
        for gid in [x for x in wanted if cell_of[x] == cell_of[sid]]:
            entry = out.setdefault(gid, {"name": res["sites"][gid]["name"], "results": {}})
            cell = entry["results"].setdefault(vk, {}).setdefault(
                rk, {"baseline": compact(res["sites"][gid]["results"][vk][rk]["summary"])})
            cell[sk] = compact(summ)
    for (sid, vk, rk, sk), members in zip(wkeys, wouts):
        for m in members:
            m.pop("_canopy", None)
        wb = wbench.get(sid, {}).get(vk, {}).get(rk)
        if sk is None:
            orig = res["sites"][sid]["results"][vk][rk].get("wofost", {}).get("members", [])
            diff = max((abs((a["yield_t_ha"] or 0) - (b["yield_t_ha"] or 0)) for a, b in zip(orig, members)), default=0.0)
            if diff > REPRODUCE_TOL:
                log(f"{rid}: WOFOST's outlook of {sid} {vk} {rk} not reproduced (up to {diff:.2f} t/ha): its scenarios left out")
                continue
            for gid in [x for x in wanted if cell_of[x] == cell_of[sid]]:
                c = out.get(gid, {}).get("results", {}).get(vk, {}).get(rk)
                if c is not None:
                    c["baseline_wofost"] = compact(res["sites"][gid]["results"][vk][rk]["wofost"]["summary"])
            continue
        summ = compact(ro.summarize(members, varieties[vk], wb))
        for gid in [x for x in wanted if cell_of[x] == cell_of[sid]]:
            c = out.get(gid, {}).get("results", {}).get(vk, {}).get(rk)
            if c is not None and "baseline_wofost" in c and sk in c:
                c[sk]["wofost"] = summ
    meta = {"id": rid, "source": res["meta"]["source"], "model_label": res["meta"]["model_label"],
            "run": res["meta"]["run"], "obs_end": res["meta"]["obs_end"], "engine": res["meta"]["engine"],
            "config_hash": res["meta"]["config_hash"], "scenario_hash": shash, "baseline_reproduced_within_t_ha": round(worst, 3),
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "baseline": "the outlook: the planting rule's sowing date, the variety's plant density, ERA5-Land soil water on 1 Aug",
            "scenarios": {k: mg.describe(k) for k in keys},
            "varieties": {k: res["meta"]["varieties"][k] for k in varieties},
            "planting_rules": {k: res["meta"]["planting_rules"][k] for k in rules},
            "second_engine": ({"engine": ro.SECOND_ENGINE, "varieties": sorted(wof_vars), "scenarios": wof_keys}
                              if wtasks else None)}
    SCEN_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "sites": out}, indent=1), encoding="utf-8")
    log(f"{rid}: done in {time.time() - t0:.0f} s → {path.relative_to(C.BASE)}")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run id (default: the latest seasonal run)")
    ap.add_argument("--sites", nargs="+")
    ap.add_argument("--varieties", nargs="+")
    ap.add_argument("--rules", nargs="+", choices=list(C.PLANTING_RULES))
    ap.add_argument("--scenarios", nargs="+", choices=list(mg.SCENARIOS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true", help="rebuild scenarios already made from the same results")
    ap.add_argument("--max-age-days", type=float, help="keep scenarios made from the same configuration this recently")
    ap.add_argument("--no-dashboard", action="store_true", help="do not rewrite the tab's scenarios.json")
    ap.add_argument("--no-wofost", action="store_true", help="AquaCrop only")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rid = a.run or latest_run()
    if not rid:
        log("no seasonal run on disk")
        return 1
    run(rid, a.sites, a.varieties, a.rules, a.scenarios, a.workers, a.force, a.max_age_days, wofost=not a.no_wofost)
    if not a.no_dashboard:
        from crop_engine import dashboard
        dashboard.write_scenarios(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
