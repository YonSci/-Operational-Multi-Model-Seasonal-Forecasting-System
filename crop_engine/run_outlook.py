#!/usr/bin/env python3
"""
Crop outlook: AquaCrop at the Kenya monitored sites for the 2026 Short Rains, for every variety (varieties.yaml) and
planting rule (config.PLANTING_RULES), driven by each forecast run's 25 rainfall members, and compared with a
benchmark of the same crops grown in the observed weather of 1993–2025.

Runs: the seasonal forecast itself (ECMWF SEAS5, Oct 01 + latest observations) and the latest run of every
sub-seasonal and medium-range model on disk (scripts/forecast_runs.py). A run whose results were made from the same
observations and configuration is skipped.

Second model: WOFOST 7.2 (adapters/wofost_adapter.py) grows the same members, sown on the same dates, for every
variety with a WOFOST calibration in varieties.yaml (`wofost:`), when the run's weather has radiation, humidity and
wind; its summary and members go beside AquaCrop's (results[variety][rule]["wofost"]), so the Crop outlook tab shows
how far the two models agree. AquaCrop stays the published outlook. WOFOST has its own observed-weather benchmark
(climatology_wofost.json: the same observed seasons, sown as AquaCrop's benchmark, rebuilt when WOFOST's own
configuration changes, wofost_hash), so its summaries carry their own normal range. --no-wofost leaves it out.

Outputs (not committed; outputs/crop_engine/):
  weather/<run id>.nc        the standard daily weather of the run (crop_engine.data.weather)
  results/<run id>.json      per site, variety and rule: every member's outcome and a summary
  results/index.json         the runs, newest first
  climatology.json           the observed-weather benchmark (rebuilt when the configuration changes)
  climatology_wofost.json    WOFOST's, for its varieties (rebuilt when WOFOST's configuration changes)
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
from crop_engine.adapters import wofost_adapter as wf
from crop_engine.data import soil as soil_mod
from crop_engine.data import weather as W
from crop_engine.scenarios import planting as pl

import forecast_runs as fr  # noqa: E402
import onset_rules as orl  # noqa: E402

ENGINE = f"AquaCrop-OSPy {version('aquacrop')}"
SECOND_ENGINE = f"WOFOST 7.2 (PCSE {version('pcse')}, Wofost72_WLP_CWB)"
CAVEATS = [
    "Experimental: maize is calibrated against trials at Kiboko (phenology and harvest index), sorghum only set "
    "against them; the crop forecasts have not been verified against observed crop outcomes.",
    "Varieties are maturity classes (AquaCrop crop files with Kenyan plant densities), not calibrated cultivars.",
    "Yields are water-limited: no nutrient stress, pests, diseases or management losses; they are an upper bound for "
    "smallholder fields.",
    "Past seasons are simulated: AquaCrop grown in the observed weather of 1993–2025, not measured yields.",
    "A crop season runs from 1 Aug to 31 Mar: a crop that cannot mature by 31 Mar is counted as too late.",
    "After the last ERA5-Land day, temperature is the sub-seasonal model's own in its range (ECMWF extended range or "
    "GEFS runs, bias-corrected to ERA5-Land), then ECMWF SEAS5 member by member, bias-corrected to ERA5-Land, and ET0 "
    "the ERA5-Land climatology scaled by that temperature (Hargreaves); 1 Jan – 28 Feb rain is SEAS5 (bias-corrected), "
    "as for the Agri rules, and March rain SEAS5 quantile-mapped to CHIRPS. Where the SEAS5 files are missing, "
    "temperature is the 1993–2016 climatology and March rain the observed March of a past year (see each run's weather).",
    "Soil is the 0.25° SoilGrids average of the site's grid cell, not a field measurement.",
    "A second crop model, WOFOST 7.2, grows the same maize and sorghum members on the same dates; where the two "
    "disagree, the outlook depends on the model as much as on the weather.",
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
    """Changes when the varieties, rules, sites, season end, AquaCrop version or the adapter change: results made
    before are rebuilt."""
    h = hashlib.sha1(C.VARIETIES_FILE.read_bytes())
    h.update(json.dumps(sorted(rules)).encode())
    h.update(json.dumps(sorted((s.id, s.lat, s.lon) for s in sites)).encode())
    h.update(ENGINE.encode())
    h.update(json.dumps([C.RESOW_RULE, C.RESOW_MAX, list(C.SEASON_END)]).encode())
    h.update(Path(aq.__file__).read_bytes())
    h.update(Path(pl.__file__).read_bytes())
    return h.hexdigest()[:12]


def wofost_hash(rules, sites):
    """Changes when the varieties, rules, sites, season end, PCSE or the WOFOST adapter change: WOFOST's benchmark is
    rebuilt (AquaCrop's is not)."""
    h = hashlib.sha1(C.VARIETIES_FILE.read_bytes())
    h.update(json.dumps(sorted(rules)).encode())
    h.update(json.dumps(sorted((s.id, s.lat, s.lon) for s in sites)).encode())
    h.update(SECOND_ENGINE.encode())
    h.update(json.dumps([C.RESOW_RULE, C.RESOW_MAX, list(C.SEASON_END)]).encode())
    h.update(Path(wf.__file__).read_bytes())
    h.update(Path(pl.__file__).read_bytes())
    return h.hexdigest()[:12]


def cells(sites):
    """[(representative site, [site ids sharing its grid cell])]: each cell is simulated once."""
    groups = {}
    for s in sites:
        groups.setdefault(s.cell, []).append(s)
    return [(g[0], [s.id for s in g]) for g in groups.values()]


def run_tasks(tasks, workers, engine="aquacrop"):
    """Simulate the tasks with AquaCrop (default) or WOFOST (adapters/wofost_adapter.py)."""
    if engine == "wofost":
        from crop_engine.adapters import wofost_adapter as wf
        fn = wf.simulate
    else:
        fn = aq.simulate
    if workers <= 1:
        return [fn(t) for t in tasks]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(fn, tasks, chunksize=1))


# ── summaries ───────────────────────────────────────────────────────────────
def _q(a, q):
    if isinstance(a, list):
        a = [x for x in a if x is not None]                               # WOFOST has no potential yield or stress days
    return round(float(np.quantile(a, q)), 3) if len(a) else None


def _date_q(ds, q):
    if not ds:
        return None
    o = np.array([dt.date.fromisoformat(d).toordinal() for d in ds])
    return dt.date.fromordinal(int(round(np.quantile(o, q)))).isoformat()


SIMULATED = ("ok", "died", "failed_establishment")


def effective_yield(m):
    return m["yield_t_ha"] if m["status"] in SIMULATED else 0.0


def canopy_band(members, start=None):
    """Takes each member's `_canopy` (weekly canopy cover of a simulated member) off it, so it is not written,
    and returns their median and 10th / 90th percentiles per week, or None when no member was simulated."""
    rows = [m.pop("_canopy") for m in members if m.get("_canopy") is not None]
    for m in members:
        m.pop("_canopy", None)
    if not rows:
        return None
    n = max(map(len, rows))                                   # a shorter season (fewer days): no value past its end
    a = np.array([np.pad(np.asarray(r, np.float32), (0, n - len(r)), constant_values=np.nan) for r in rows])
    q = lambda p: [None if np.isnan(x) else round(float(x), 3) for x in np.nanquantile(a, p, axis=0)]
    band = {"step_days": aq.CANOPY_STEP, "n": len(rows), "median": q(0.5), "p10": q(0.1), "p90": q(0.9)}
    return {"start": start, **band} if start else band


def outcome_rates(records, failure_t_ha):
    """The outcome probabilities, each with its own denominator (members or seasons; model errors left out of all):
      p_sowing_opportunity      sown or sowable (an onset by the rule's search end), of the valid ones
      p_establishment_failure   failed to establish, of the sown crops
      p_failure_if_sown         yield below the failure threshold, of the sown crops
      yield_if_sown_t_ha        the sown crops' yield
      p_failure                 no crop (no sowing opportunity, too late) or a failed one, of the valid ones
    No sowing opportunity is the rule's outcome, not a farmer's: it is reported apart from crop failure."""
    valid = [r for r in records if r["status"] != "error"]
    sown = [r for r in valid if r["status"] in SIMULATED]
    ys = np.array([r["yield_t_ha"] for r in sown])
    ny = np.array([effective_yield(r) for r in valid])
    rate = lambda k, n: round(k / n, 3) if n else None
    return {"n_valid": len(valid), "n_error": len(records) - len(valid), "n_sown": len(sown),
            "p_sowing_opportunity": rate(sum(1 for r in valid if r["status"] != "not_sown"), len(valid)),
            "p_establishment_failure": rate(sum(1 for r in sown if r["status"] == "failed_establishment"), len(sown)),
            "p_failure_if_sown": rate(int((ys < failure_t_ha).sum()), len(sown)),
            "yield_if_sown_t_ha": {"median": _q(ys, 0.5), "p10": _q(ys, 0.1), "p90": _q(ys, 0.9)},
            "p_failure": rate(int((ny < failure_t_ha).sum()), len(valid))}


def summarize(members, variety, bench=None):
    valid = [m for m in members if m["status"] != "error"]          # a model error is no outcome: left out
    y = np.array([effective_yield(m) for m in valid])
    st = [m["status"] for m in members]
    sown = [m for m in members if m["status"] in SIMULATED]
    n = len(members)
    rates = outcome_rates(members, variety["failure_t_ha"])
    s = {"members": n,
         "share": {k: round(st.count(k) / n, 3) for k in SIMULATED + ("too_late", "not_sown", "error")},
         **rates,
         "yield_t_ha": {"median": _q(y, 0.5), "p10": _q(y, 0.1), "p90": _q(y, 0.9),
                        "mean": round(float(y.mean()), 3) if len(y) else None},
         # AquaCrop's yield without water stress, over the sown crops: the gap to their yield is what water costs
         "potential_t_ha": {"median": _q([m["potential_t_ha"] for m in sown], 0.5),
                            "yield_median": _q([m["yield_t_ha"] for m in sown], 0.5)},
         "planting": {"median": _date_q([m["planting"] for m in members if m["planting"]], 0.5),
                      "p10": _date_q([m["planting"] for m in members if m["planting"]], 0.1),
                      "p90": _date_q([m["planting"] for m in members if m["planting"]], 0.9)},
         "resown": round(sum(1 for m in members if m.get("sowings", 0) > 1) / n, 3),
         "harvest_median": _date_q([m["harvest"] for m in sown], 0.5),
         "stress_days_median": _q([m["stress_days"] for m in sown], 0.5),
         "rain_mm_median": _q([m["rain_mm"] for m in sown], 0.5),
         "irrigation_mm_median": _q([m.get("irrigation_mm") or 0.0 for m in sown], 0.5)}
    if bench and bench.get("t33") is not None:
        s["vs_benchmark"] = {"benchmark_p_failure": bench["p_failure"], "benchmark_median": bench["median"],
                             **{f"benchmark_{k}": bench.get(k) for k in ("p_sowing_opportunity", "p_establishment_failure",
                                                                         "p_failure_if_sown", "yield_if_sown_t_ha")},
                             "t33": bench["t33"], "t67": bench["t67"], "p_below_normal": None, "p_above_normal": None}
        # terciles only when they separate yields: not when a third or more of the benchmark years failed
        if len(y) and bench["t33"] >= variety["failure_t_ha"] and bench["t67"] > bench["t33"]:
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
                    tasks.append(dict(dates=dates.values, rain=rain, tmax=ds.tmax_c.values[:, k], tmin=ds.tmin_c.values[:, k],
                                      et0=ds.et0_mm.values[:, k], source=ds.precip_source.values, planting=[plant],
                                      resow=resow, variety=v,
                                      kw=v["kw"], layers=soils[s.id], initial_frac=float(frac[k])))
                    keys.append((s.id, vk, rk, y))
    log(f"benchmark: {len(tasks)} observed seasons to simulate ({len(years)} years)")
    t0 = time.time()
    res = run_tasks(tasks, workers)
    log(f"benchmark done in {time.time() - t0:.0f} s")
    return bench_stats(res, keys, varieties, years)


def wofost_benchmark(inp, rep_cells, varieties, rules, soils, workers):
    """WOFOST's observed-weather benchmark: the same seasons and sowings as benchmark() (compare_engines.tasks_for),
    for the WOFOST varieties."""
    from crop_engine import compare_engines as ce
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    use = {vk: varieties[vk] for vk in wofost_varieties(varieties)}
    tasks, keys = ce.tasks_for(inp, years, rep_cells, use, rules, soils)
    log(f"WOFOST benchmark: {len(tasks)} observed seasons to simulate")
    t0 = time.time()
    res = run_tasks(tasks, workers, engine="wofost")
    log(f"WOFOST benchmark done in {time.time() - t0:.0f} s")
    return bench_stats(res, keys, use, years)


def bench_stats(res, keys, varieties, years):
    """Outcomes of the observed seasons (keys: site, variety, rule, year) → the benchmark's per-cell statistics."""
    out, canopy = {}, {}
    for (sid, vk, rk, y), r in zip(keys, res):
        m = r[0]
        canopy.setdefault((sid, vk, rk), []).append(m)
        out.setdefault(sid, {}).setdefault(vk, {}).setdefault(rk, {"years": {}})["years"][str(y)] = {
            k: m.get(k) for k in ("status", "planting", "harvest", "yield_t_ha", "potential_t_ha", "stress_days",
                                  "rain_mm", "sowings", "first_planting")}
    for sid, vs in out.items():
        for vk, rs in vs.items():
            for rk, b in rs.items():
                b["canopy"] = canopy_band(canopy[(sid, vk, rk)])     # by week of the season (every year from 1 Aug)
                cal = [effective_yield(b["years"][str(y)]) for y in years if C.CAL_YEARS[0] <= y <= C.CAL_YEARS[1]]
                allv = [effective_yield(v) for v in b["years"].values()]
                b.update(t33=_q(cal, 1 / 3), t67=_q(cal, 2 / 3), median=_q(allv, 0.5), cal_median=_q(cal, 0.5),
                         **outcome_rates(list(b["years"].values()), varieties[vk]["failure_t_ha"]))
    return out


# ── a forecast run ──────────────────────────────────────────────────────────
def forecast_runs_to_do(b, sources):
    todo = [("seasonal", b.lead0, None)]
    latest, _ = fr.candidates(False, None)
    todo += [(s, r, p) for s, r, p in latest]
    return [t for t in todo if not sources or t[0] in sources]


def wofost_varieties(varieties):
    """The varieties WOFOST grows beside AquaCrop: a WOFOST crop set and a WOFOST calibration (varieties.yaml)."""
    return [vk for vk, v in varieties.items() if wf.available(v) and v.get("wofost")]


def run_wofost(ds, tasks, keys, rep_cells, inp, varieties, workers):
    """WOFOST on the AquaCrop tasks of the WOFOST varieties → {(site, variety, rule): members}, or {} and why not."""
    if "rad_mj_m2" not in ds:
        return {}, f"no radiation, humidity or wind in the weather ({ds.attrs.get('radiation')})"
    use = set(wofost_varieties(varieties))
    if not use:
        return {}, "no variety with a WOFOST calibration"
    ids = [x.id for x in inp.sites]
    cell = {s.id: s for s, _ in rep_cells}
    wt, wk = [], []
    for t, key in zip(tasks, keys):
        sid, vk, _ = key
        if vk not in use:
            continue
        k, s = ids.index(sid), cell[sid]
        wt.append(dict(t, rad=ds.rad_mj_m2.values[:, k], vap=ds.vap_hpa.values[:, k], wind2=ds.wind2_ms.values[:, k],
                       lat=s.lat, lon=s.lon, elev=float(ds.elev_m.values[k])))
        wk.append(key)
    res = run_tasks(wt, workers, engine="wofost")
    clean = lambda m: {k: v for k, v in m.items() if not k.startswith("_")}  # noqa: E731
    return {key: [clean(m) for m in r] for key, r in zip(wk, res)}, ""


def run_one(inp, meth, source, run, path, nwp_cache, rep_cells, varieties, rules, soils, bench, workers, chash,
            wofost=True, wbench=None):
    b = inp.b
    if source == "seasonal":
        P, segs = b.seas, [{"kind": "obs", "label": "Observed rainfall (CHIRPS)", "start": f"{b.win0}", "end": f"{b.obs_end}"},
                           {"kind": "seas", "label": "ECMWF SEAS5 seasonal forecast", "start": f"{b.obs_end + dt.timedelta(days=1)}",
                            "end": f"{b.last}"}]
        label, members = "ECMWF SEAS5 (Oct 01 + latest obs)", "ensemble (SEAS5)"
        info = None
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
    s2s, s2s_note = inp.s2s_temperature(source, info) if info else (None, "")
    if s2s_note and s2s is None:
        log(f"{rid}: {s2s_note}")
    ds = inp.forecast(P, segs, attrs, s2s)
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
                tasks.append(dict(dates=dates.values, rain=ds.precip_mm.values[:, k], tmax=ds.tmax_c.values[:, k],
                                  tmin=ds.tmin_c.values[:, k], et0=ds.et0_mm.values[:, k], source=ds.precip_source.values,
                                  planting=plant[rk][s.id], resow=resow, variety=v, kw=v["kw"], layers=soils[s.id],
                                  initial_frac=float(frac[k])))
                keys.append((s.id, vk, rk))
    t0 = time.time()
    res = run_tasks(tasks, workers)
    t_aq = time.time() - t0
    wof, why = run_wofost(ds, tasks, keys, rep_cells, inp, varieties, workers) if wofost else ({}, "left out (--no-wofost)")
    if why:
        log(f"{rid}: WOFOST {why}")
    out_sites = {}
    fao_on = meth_res["fao-agricultural"]
    try:                                    # the FAO water balance's plant-available water now (the tab's season strip)
        sw_now = dict(zip(ids, inp.soil_water_now(b.obs_end)))
    except Exception as exc:                                   # never stops a run
        log(f"{rid}: soil water now not read ({type(exc).__name__}: {str(exc)[:120]})")
        sw_now = {}
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
                 "initial_water_fraction": round(float(frac[ids.index(s.id)]), 6),   # exact enough to re-simulate (run_scenarios)
                 "fao_reference": {"agricultural": ref}, "results": {}}
        if sw_now.get(s.id):
            entry["soil_water"] = {"paw_fraction": round(sw_now[s.id][0], 3), "date": sw_now[s.id][1].isoformat(),
                                   "source": "FAO water balance (CHIRPS v3, ERA5-Land ET0)"}
        for sid in group:
            out_sites[sid] = {"name": next(x.name for x in inp.sites if x.id == sid), **entry}
    for (sid, vk, rk), outcomes in zip(keys, res):
        group = next(g for s, g in rep_cells if s.id == sid)
        summ = summarize(outcomes, varieties[vk], bench.get(sid, {}).get(vk, {}).get(rk))
        band = canopy_band(outcomes, f"{dates[0]:%Y-%m-%d}")
        entry = {"summary": summ, "canopy": band, "members": outcomes}
        if (sid, vk, rk) in wof:
            w = wof[(sid, vk, rk)]
            wb = (wbench or {}).get(sid, {}).get(vk, {}).get(rk)
            entry["wofost"] = {"summary": summarize(w, varieties[vk], wb), "members": w}
        for gid in group:
            out_sites[gid]["results"].setdefault(vk, {})[rk] = entry
    meta = {"id": rid, "source": source, "model_label": label, "run": f"{run}", "obs_end": f"{b.obs_end}",
            "members_kind": members, "segments": segs, "engine": ENGINE, "config_hash": chash,
            "second_engine": ({"engine": SECOND_ENGINE, "varieties": sorted({vk for _, vk, _ in wof})} if wof
                              else {"engine": SECOND_ENGINE, "varieties": [], "why_not": why}),
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "varieties": {k: {x: v[x] for x in ("label", "examples", "maturity_days", "failure_t_ha", "aquacrop_crop")} |
                          {"phenology_scale": round(v["scale"], 3)} for k, v in varieties.items()},
            "planting_rules": {k: C.PLANTING_RULES[k]["label"] for k in rules}, "caveats": CAVEATS,
            "weather_file": f"outputs/crop_engine/weather/{rid}.nc",
            "weather": {"march_rain": ds.attrs.get("march_rain"), "temperature": ds.attrs.get("temperature_forecast")}}
    C.RESULTS_OUT.mkdir(parents=True, exist_ok=True)
    (C.RESULTS_OUT / f"{rid}.json").write_text(json.dumps({"meta": meta, "sites": out_sites}, indent=1), encoding="utf-8")
    log(f"{rid}: {len(tasks) * P.shape[0]} member seasons in {t_aq:.0f} s"
        + (f"; WOFOST {len(wof) * P.shape[0]} in {time.time() - t0 - t_aq:.0f} s" if wof else ""))
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
    ap.add_argument("--no-wofost", action="store_true", help="AquaCrop only: no second model beside it")
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
    wbench = None
    if not a.no_wofost and wofost_varieties(varieties):
        wpath, whash = C.OUT / "climatology_wofost.json", wofost_hash(a.rules, inp.sites)
        wbench = json.loads(wpath.read_text(encoding="utf-8")) if wpath.exists() else None
        if a.climatology or not wbench or wbench.get("config_hash") != whash:
            try:
                wbench = {"config_hash": whash, "engine": SECOND_ENGINE, "years": list(C.HIST_YEARS),
                          "cal_years": list(C.CAL_YEARS),
                          "sites": wofost_benchmark(inp, rep_cells, varieties, a.rules, soils, a.workers)}
                wpath.write_text(json.dumps(wbench, indent=1), encoding="utf-8")
            except Exception as exc:                                   # the outlook goes on without it
                log(f"WOFOST benchmark failed ({type(exc).__name__}: {str(exc)[:200]}); WOFOST summaries without it")
                wbench = None
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
                          bench["sites"], a.workers, chash, wofost=not a.no_wofost,
                          wbench=(wbench or {}).get("sites"))
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
