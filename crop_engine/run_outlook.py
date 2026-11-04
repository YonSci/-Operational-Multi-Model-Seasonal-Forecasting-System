#!/usr/bin/env python3
"""
Crop outlook: AquaCrop at the Kenya monitored sites for the 2026 Short Rains, for every variety (varieties.yaml) and
planting rule (config.PLANTING_RULES), driven by each forecast run's 25 rainfall members, and compared with a
benchmark of the same crops grown in the observed weather of 1993–2025.

Runs: the seasonal forecast itself (ECMWF SEAS5, Oct 01 + latest observations) and the latest run of every
sub-seasonal and medium-range model on disk (scripts/forecast_runs.py). A run whose results were made from the same
observations and configuration is skipped.

Outputs (not committed; outputs/crop_engine/):
  weather/<run id>.nc        the standard daily weather of the run (crop_engine.data.weather)
  results/<run id>.json      per site, variety and rule: every member's outcome and a summary
  results/index.json         the runs, newest first
  climatology.json           the observed-weather benchmark (rebuilt when the configuration changes)
and the Crop outlook tab's copy of the latest runs (frontend/public/tracker/data/crop/, crop_engine.dashboard).

Usage:
  python -m crop_engine.run_outlook                         # all runs, 2 worker processes
  python -m crop_engine.run_all --workers 1                 # one process per source (the daily update)
  python -m crop_engine.run_outlook --sources seasonal s2s-ecmwf --workers 3
  python -m crop_engine.run_outlook --climatology --force   # rebuild the benchmark and every run
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from importlib.metadata import version
from pathlib import Path

import numpy as np
import yaml

from crop_engine import config as C
from crop_engine import dashboard
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.data import soil as soil_mod
from crop_engine.data import weather as W
from crop_engine.scenarios import planting as pl

import forecast_runs as fr  # noqa: E402
import onset_rules as orl  # noqa: E402

ENGINE = f"AquaCrop-OSPy {version('aquacrop')}"
CAVEATS = [
    "Experimental: the crop model is not calibrated for these sites or varieties, and the forecast runs have not been "
    "verified for crop outcomes.",
    "Varieties are maturity classes built from AquaCrop's default crop parameters, not calibrated cultivars.",
    "Yields are water-limited: no nutrient stress, pests or management losses, AquaCrop default plant density; they are "
    "an upper bound for smallholder fields.",
    "Temperature and ET0 after the last ERA5-Land day are the 1993–2016 day-of-year climatology; March rain is a "
    "climatological continuation (observed CHIRPS of a calibration year).",
    "Soil is the 0.25° SoilGrids average of the site's grid cell, not a field measurement.",
    "Deterministic weather models are the same forecast in every member: their spread comes from SEAS5 only.",
]


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] crop: {m}", flush=True)


def load_varieties(only=None):
    cfg = yaml.safe_load(C.VARIETIES_FILE.read_text(encoding="utf-8"))
    vs = {k: v for k, v in cfg["varieties"].items() if not only or k in only}
    ref = float(cfg["reference_tmean_c"])
    for v in vs.values():
        v["kw"], v["scale"] = aq.crop_parameters(v, ref)
    return ref, vs


def config_hash(rules, sites):
    """Changes when the varieties, rules, sites, AquaCrop version or the adapter change: results made before are rebuilt."""
    h = hashlib.sha1(C.VARIETIES_FILE.read_bytes())
    h.update(json.dumps(sorted(rules)).encode())
    h.update(json.dumps(sorted((s.id, s.lat, s.lon) for s in sites)).encode())
    h.update(ENGINE.encode())
    h.update(json.dumps([C.RESOW_RULE, C.RESOW_MAX]).encode())
    h.update(Path(aq.__file__).read_bytes())
    h.update(Path(pl.__file__).read_bytes())
    return h.hexdigest()[:12]


def cells(sites):
    """[(representative site, [site ids sharing its grid cell])]: each cell is simulated once."""
    groups = {}
    for s in sites:
        groups.setdefault(s.cell, []).append(s)
    return [(g[0], [s.id for s in g]) for g in groups.values()]


def run_tasks(tasks, workers):
    if workers <= 1:
        return [aq.simulate(t) for t in tasks]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(aq.simulate, tasks, chunksize=1))


# ── summaries ───────────────────────────────────────────────────────────────
def _q(a, q):
    return round(float(np.quantile(a, q)), 3) if len(a) else None


def _date_q(ds, q):
    if not ds:
        return None
    o = np.array([dt.date.fromisoformat(d).toordinal() for d in ds])
    return dt.date.fromordinal(int(round(np.quantile(o, q)))).isoformat()


SIMULATED = ("ok", "died", "failed_establishment")


def effective_yield(m):
    return m["yield_t_ha"] if m["status"] in SIMULATED else 0.0


def summarize(members, variety, bench=None):
    y = np.array([effective_yield(m) for m in members])
    st = [m["status"] for m in members]
    sown = [m for m in members if m["status"] in SIMULATED]
    n = len(members)
    s = {"members": n,
         "share": {k: round(st.count(k) / n, 3) for k in SIMULATED + ("too_late", "not_sown", "error")},
         "yield_t_ha": {"median": _q(y, 0.5), "p10": _q(y, 0.1), "p90": _q(y, 0.9), "mean": round(float(y.mean()), 3)},
         "p_failure": round(float((y < variety["failure_t_ha"]).mean()), 3),
         "planting": {"median": _date_q([m["planting"] for m in members if m["planting"]], 0.5),
                      "p10": _date_q([m["planting"] for m in members if m["planting"]], 0.1),
                      "p90": _date_q([m["planting"] for m in members if m["planting"]], 0.9)},
         "resown": round(sum(1 for m in members if m.get("sowings", 0) > 1) / n, 3),
         "harvest_median": _date_q([m["harvest"] for m in sown], 0.5),
         "stress_days_median": _q([m["stress_days"] for m in sown], 0.5),
         "rain_mm_median": _q([m["rain_mm"] for m in sown], 0.5)}
    if bench and bench.get("t33") is not None:
        s["vs_benchmark"] = {"benchmark_p_failure": bench["p_failure"], "benchmark_median": bench["median"],
                             "t33": bench["t33"], "t67": bench["t67"], "p_below_normal": None, "p_above_normal": None}
        # terciles only when they separate yields: not when a third or more of the benchmark years failed
        if bench["t33"] >= variety["failure_t_ha"] and bench["t67"] > bench["t33"]:
            s["vs_benchmark"].update(p_below_normal=round(float((y < bench["t33"]).mean()), 3),
                                     p_above_normal=round(float((y > bench["t67"]).mean()), 3))
    return s


# ── benchmark: the same crops in the observed weather of past seasons ──────
def benchmark(inp, rep_cells, varieties, rules, soils, workers):
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    pet = orl.load_pet(inp.lat, inp.lon, orl.EXT_DAYS)
    fao = pl.observed_fao_dates([s for s, _ in rep_cells], years)
    tasks, keys = [], []
    for y in years:
        ds = inp.observed(y)
        dates = ds.time.to_index()
        frac = inp.initial_water(y)
        for s, _ in rep_cells:
            k = [x.id for x in inp.sites].index(s.id)
            rain = ds.precip_mm.values[:, k]
            resow = pl.sowing_opportunities(rain, dates)
            for rk in rules:
                plant = (pl.observed_rule_date(rain[0], dates, pet[:, s.i, s.j], rk) if rk.startswith("rule")
                         else fao[s.id].get(y))
                for vk, v in varieties.items():
                    tasks.append(dict(dates=dates.values, rain=rain, tmax=ds.tmax_c.values[k], tmin=ds.tmin_c.values[k],
                                      et0=ds.et0_mm.values[k], source=ds.precip_source.values, planting=[plant],
                                      resow=resow, variety=v,
                                      kw=v["kw"], layers=soils[s.id], initial_frac=float(frac[k])))
                    keys.append((s.id, vk, rk, y))
    log(f"benchmark: {len(tasks)} observed seasons to simulate ({len(years)} years)")
    t0 = time.time()
    res = run_tasks(tasks, workers)
    log(f"benchmark done in {time.time() - t0:.0f} s")
    out = {}
    for (sid, vk, rk, y), r in zip(keys, res):
        m = r[0]
        out.setdefault(sid, {}).setdefault(vk, {}).setdefault(rk, {"years": {}})["years"][str(y)] = {
            k: m.get(k) for k in ("status", "planting", "harvest", "yield_t_ha", "stress_days", "rain_mm", "sowings",
                                  "first_planting")}
    for sid, vs in out.items():
        for vk, rs in vs.items():
            for rk, b in rs.items():
                cal = [effective_yield(b["years"][str(y)]) for y in years if C.CAL_YEARS[0] <= y <= C.CAL_YEARS[1]]
                allv = [effective_yield(v) for v in b["years"].values()]
                b.update(t33=_q(cal, 1 / 3), t67=_q(cal, 2 / 3), median=_q(allv, 0.5), cal_median=_q(cal, 0.5),
                         p_failure=round(float(np.mean(np.array(allv) < varieties[vk]["failure_t_ha"])), 3))
    return out


# ── a forecast run ──────────────────────────────────────────────────────────
def forecast_runs_to_do(b, sources):
    todo = [("seasonal", b.lead0, None)]
    latest, _ = fr.candidates(False, None)
    todo += [(s, r, p) for s, r, p in latest]
    return [t for t in todo if not sources or t[0] in sources]


def run_one(inp, meth, source, run, path, nwp_cache, rep_cells, varieties, rules, soils, bench, workers, chash):
    b = inp.b
    if source == "seasonal":
        P, segs = b.seas, [{"kind": "obs", "label": "Observed rainfall (CHIRPS)", "start": f"{b.win0}", "end": f"{b.obs_end}"},
                           {"kind": "seas", "label": "ECMWF SEAS5 seasonal forecast", "start": f"{b.obs_end + dt.timedelta(days=1)}",
                            "end": f"{b.last}"}]
        label, members = "ECMWF SEAS5 (Oct 01 + latest obs)", "ensemble (SEAS5)"
    else:
        got = fr.joined_rain(b, source, run, path, nwp_cache)
        if isinstance(got, str):
            log(f"{source} {run}: {got}; skipped")
            return None
        P, info, segs, _ = got
        label, members = fr.SOURCES[source][1], fr.members_kind(source)
    rid = f"{source}_{run:%Y%m%d}"
    meth_res = meth.run(P, (P != b.seas).any(axis=(0, 2, 3)))
    attrs = {"forecast_source": source, "model_label": label, "run_date": f"{run}", "obs_end": f"{b.obs_end}",
             "members_kind": members, "segments": segs}
    ds = inp.forecast(P, segs, attrs)
    problems = W.validate(ds)
    if problems:
        raise ValueError(f"{rid}: weather inputs invalid: {'; '.join(problems)}")
    C.WEATHER_OUT.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(C.WEATHER_OUT / f"{rid}.nc", encoding={"precip_mm": {"zlib": True, "complevel": 4}})
    frac = inp.initial_water(inp.year)
    dates = ds.time.to_index()
    plant = {rk: pl.forecast_dates(meth_res, [s for s, _ in rep_cells], inp.year, rk) for rk in rules}
    tasks, keys = [], []
    ids = [x.id for x in inp.sites]
    for s, _ in rep_cells:
        k = ids.index(s.id)
        resow = pl.sowing_opportunities(ds.precip_mm.values[:, k], dates)
        for rk in rules:
            for vk, v in varieties.items():
                tasks.append(dict(dates=dates.values, rain=ds.precip_mm.values[:, k], tmax=ds.tmax_c.values[k],
                                  tmin=ds.tmin_c.values[k], et0=ds.et0_mm.values[k], source=ds.precip_source.values,
                                  planting=plant[rk][s.id], resow=resow, variety=v, kw=v["kw"], layers=soils[s.id],
                                  initial_frac=float(frac[k])))
                keys.append((s.id, vk, rk))
    t0 = time.time()
    res = run_tasks(tasks, workers)
    out_sites = {}
    fao_on = meth_res["fao-agricultural"]
    for s, group in rep_cells:
        # the FAO water balance's own agricultural onset / cessation / LGP for this run: the reference the crop
        # model is read against (medians over the members that have them)
        ref = {}
        for v in ("onset", "cessation", "lgp"):
            a = fao_on[v][0][:, s.i, s.j]
            med = float(np.nanmedian(a)) if np.isfinite(a).any() else np.nan
            if v == "lgp":
                ref["lgp_days_median"] = None if np.isnan(med) else round(med)
            else:
                d = pl.doy_to_date(med, inp.year)
                ref[f"{v}_median"] = d.isoformat() if d else None
        entry = {"cell": [s.cell_lat, s.cell_lon], "soil_taw_100cm_mm": round(soil_mod.taw_mm(soils[s.id]), 0),
                 "topsoil": {"sand": soils[s.id][0].sand, "clay": soils[s.id][0].clay},
                 "initial_water_fraction": round(float(frac[ids.index(s.id)]), 3),
                 "fao_reference": {"agricultural": ref}, "results": {}}
        for sid in group:
            out_sites[sid] = {"name": next(x.name for x in inp.sites if x.id == sid), **entry}
    for (sid, vk, rk), outcomes in zip(keys, res):
        group = next(g for s, g in rep_cells if s.id == sid)
        summ = summarize(outcomes, varieties[vk], bench.get(sid, {}).get(vk, {}).get(rk))
        for gid in group:
            out_sites[gid]["results"].setdefault(vk, {})[rk] = {"summary": summ, "members": outcomes}
    meta = {"id": rid, "source": source, "model_label": label, "run": f"{run}", "obs_end": f"{b.obs_end}",
            "members_kind": members, "segments": segs, "engine": ENGINE, "config_hash": chash,
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "varieties": {k: {x: v[x] for x in ("label", "examples", "maturity_days", "failure_t_ha", "aquacrop_crop")} |
                          {"phenology_scale": round(v["scale"], 3)} for k, v in varieties.items()},
            "planting_rules": {k: C.PLANTING_RULES[k]["label"] for k in rules}, "caveats": CAVEATS,
            "weather_file": f"outputs/crop_engine/weather/{rid}.nc"}
    C.RESULTS_OUT.mkdir(parents=True, exist_ok=True)
    (C.RESULTS_OUT / f"{rid}.json").write_text(json.dumps({"meta": meta, "sites": out_sites}, indent=1), encoding="utf-8")
    log(f"{rid}: {len(tasks) * P.shape[0]} member seasons in {time.time() - t0:.0f} s")
    return rid


def report(rid, sites=("kapiti_research_station_farm", "kalro_kiboko_makueni_farm")):
    d = json.loads((C.RESULTS_OUT / f"{rid}.json").read_text(encoding="utf-8"))
    for sid in sites:
        if sid not in d["sites"]:
            continue
        log(f"  {d['sites'][sid]['name']}:")
        for vk, rs in d["sites"][sid]["results"].items():
            for rk, r in rs.items():
                s = r["summary"]
                vb = s.get("vs_benchmark", {})
                bn = vb.get("p_below_normal")
                log(f"    {vk:13s} {rk:16s} sow {s['planting']['median']}  yield median {s['yield_t_ha']['median']} t/ha "
                    f"(p10 {s['yield_t_ha']['p10']}, p90 {s['yield_t_ha']['p90']}; benchmark {vb.get('benchmark_median')})  "
                    f"failure {s['p_failure']:.0%} (benchmark {vb.get('benchmark_p_failure', float('nan')):.0%})  "
                    f"below normal {'n/a' if bn is None else f'{bn:.0%}'}  "
                    f"too late {s['share']['too_late']:.0%}  not sown {s['share']['not_sown']:.0%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", nargs="+", help="seasonal and/or forecast-run sources (default: all)")
    ap.add_argument("--varieties", nargs="+")
    ap.add_argument("--rules", nargs="+", choices=list(C.PLANTING_RULES), default=list(C.PLANTING_RULES))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--climatology", action="store_true", help="rebuild the observed-weather benchmark")
    ap.add_argument("--force", action="store_true", help="rebuild runs already made from the same observations")
    ap.add_argument("--no-refresh", action="store_true", help="do not top up the ERA5-Land temperature series")
    ap.add_argument("--list-sources", action="store_true", help="print the sources with a run on disk (JSON) and exit")
    ap.add_argument("--no-dashboard", action="store_true", help="do not rewrite the results index and the tab's data")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.list_sources:
        print(json.dumps(["seasonal"] + sorted({s for s, _, _ in fr.candidates(False, None)[0]})))
        return 0
    ref, varieties = load_varieties(a.varieties)
    inp = W.Inputs(refresh=not a.no_refresh)
    chash = config_hash(a.rules, inp.sites)
    rep_cells = cells(inp.sites)
    soils = {s.id: soil_mod.profile(s) for s, _ in rep_cells}
    log(f"{len(inp.sites)} sites in {len(rep_cells)} grid cells; varieties {', '.join(varieties)}; rules {', '.join(a.rules)}; "
        f"observations to {inp.b.obs_end}")
    bpath = C.OUT / "climatology.json"
    bench = json.loads(bpath.read_text(encoding="utf-8")) if bpath.exists() else None
    if a.climatology or not bench or bench.get("config_hash") != chash:
        bench = {"config_hash": chash, "years": list(C.HIST_YEARS), "cal_years": list(C.CAL_YEARS),
                 "sites": benchmark(inp, rep_cells, varieties, a.rules, soils, a.workers)}
        C.OUT.mkdir(parents=True, exist_ok=True)
        bpath.write_text(json.dumps(bench, indent=1), encoding="utf-8")
    meth = fr.Methods(inp.year)
    nwp_cache = {}
    done = []
    for source, run, path in forecast_runs_to_do(inp.b, a.sources):
        rid = f"{source}_{run:%Y%m%d}"
        p = C.RESULTS_OUT / f"{rid}.json"
        if p.exists() and not a.force:
            meta = json.loads(p.read_text(encoding="utf-8"))["meta"]
            if meta.get("obs_end") == f"{inp.b.obs_end}" and meta.get("config_hash") == chash:
                log(f"{rid}: already made from these observations; skipped")
                continue
        try:
            got = run_one(inp, meth, source, run, path, nwp_cache, rep_cells, varieties, a.rules, soils,
                          bench["sites"], a.workers, chash)
            if got:
                done.append(got)
        except Exception as exc:                                         # one run must not stop the others
            log(f"{rid}: failed ({type(exc).__name__}: {str(exc)[:200]})")
    if not a.no_dashboard:
        dashboard.write_index()
        dashboard.write(log)
    for rid in done[:1]:
        report(rid)


if __name__ == "__main__":
    sys.exit(main() or 0)
