#!/usr/bin/env python3
"""
AquaCrop and WOFOST on the same observed seasons: the benchmark's seasons (climatology.json, 1993–2025 at every
site, sown by each rule in that season's observed weather, re-sown after a failed establishment) simulated again
with WOFOST (adapters/wofost_adapter.py), and the two engines compared season by season. WOFOST's weather adds the
ERA5-Land solar radiation, vapour pressure and wind (crop_engine.data.era5land.site_met).

Per site, crop and rule: the median yield (all seasons, a failure or no sowing counting zero), the failure rate
(effective yield below the variety's threshold), the share of seasons the engines agree on failure or not, the
rank correlation of the two engines' yields, their median days to harvest, and the yields against the Kiboko
trials where there are some (crop_engine/yields targets).

Output (not committed): outputs/crop_engine/verification/engines.json and a table in the log.
Usage: python -m crop_engine.compare_engines --workers 3 [--sites ...] [--varieties ...] [--years 1993 2025]
"""
import argparse
import datetime as dt
import json
import sys
import time

import numpy as np
from scipy.stats import spearmanr

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import wofost_adapter as wf
from crop_engine.data import soil as soil_mod
from crop_engine.data import weather as W
from crop_engine.scenarios import planting as pl

import onset_rules as orl  # noqa: E402

OUT = C.OUT / "verification"


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] engines: {m}", flush=True)


def tasks_for(inp, years, rep_cells, varieties, rules, soils):
    """WOFOST tasks of the benchmark's observed seasons, sown exactly as the benchmark (run_outlook.benchmark)."""
    pet = orl.load_pet(inp.lat, inp.lon, orl.EXT_DAYS)
    fao = pl.observed_fao_dates([s for s, _ in rep_cells], years)
    tasks, keys = [], []
    for y in years:
        ds = inp.observed(y)
        if "rad_mj_m2" not in ds:
            raise RuntimeError(f"no radiation, humidity or wind in the {y} weather ({ds.attrs.get('radiation')})")
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
                    tasks.append(dict(
                        dates=dates.values, rain=rain, tmax=ds.tmax_c.values[:, k], tmin=ds.tmin_c.values[:, k],
                        et0=ds.et0_mm.values[:, k], source=ds.precip_source.values, planting=[plant], resow=resow,
                        variety=v, kw=v["kw"], layers=soils[s.id], initial_frac=float(frac[k]),
                        rad=ds.rad_mj_m2.values[:, k], vap=ds.vap_hpa.values[:, k], wind2=ds.wind2_ms.values[:, k],
                        lat=s.lat, lon=s.lon, elev=float(ds.elev_m.values[k])))
                    keys.append((s.id, vk, rk, y))
    return tasks, keys


def _days(m):
    if m.get("harvest") and m.get("planting") and m["status"] in ro.SIMULATED:
        return (dt.date.fromisoformat(m["harvest"]) - dt.date.fromisoformat(m["planting"])).days
    return None


def compare(aqua, wof, thr):
    """Seasons {year: outcome} of the two engines (the same years) → their comparison."""
    yrs = sorted(set(aqua) & set(wof))
    a = np.array([ro.effective_yield(aqua[y]) for y in yrs])
    w = np.array([ro.effective_yield(wof[y]) for y in yrs])
    sown = np.array([aqua[y]["status"] in ro.SIMULATED for y in yrs])
    fa, fw_ = a < thr, w < thr
    r = (round(float(spearmanr(a[sown], w[sown])[0]), 3)
         if sown.sum() >= 5 and np.ptp(a[sown]) > 0 and np.ptp(w[sown]) > 0 else None)
    da = [d for d in (_days(aqua[y]) for y in yrs) if d]
    dw = [d for d in (_days(wof[y]) for y in yrs) if d]
    st = lambda e: {k: sum(e[y]["status"] == k for y in yrs) for k in ("ok", "died", "failed_establishment", "too_late", "not_sown", "error")}
    return {"n_years": len(yrs), "n_sown": int(sown.sum()),
            "median_t_ha": {"aquacrop": round(float(np.median(a)), 2), "wofost": round(float(np.median(w)), 2)},
            "median_sown_t_ha": {"aquacrop": round(float(np.median(a[sown])), 2) if sown.any() else None,
                                 "wofost": round(float(np.median(w[sown])), 2) if sown.any() else None},
            "failure_rate": {"aquacrop": round(float(fa.mean()), 3), "wofost": round(float(fw_.mean()), 3)},
            "agree_on_failure": round(float((fa == fw_).mean()), 3), "spearman_sown": r,
            "median_days_to_harvest": {"aquacrop": float(np.median(da)) if da else None,
                                       "wofost": float(np.median(dw)) if dw else None},
            "status": {"aquacrop": st(aqua), "wofost": st(wof)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs=2, type=int, default=list(C.HIST_YEARS))
    ap.add_argument("--sites", nargs="+")
    ap.add_argument("--varieties", nargs="+")
    ap.add_argument("--rules", nargs="+", default=list(C.PLANTING_RULES))
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    years = list(range(a.years[0], a.years[1] + 1))
    _, varieties = ro.load_varieties(a.varieties)
    skipped = [vk for vk, v in varieties.items() if not wf.available(v)]
    varieties = {vk: v for vk, v in varieties.items() if wf.available(v)}
    if skipped:
        log(f"no WOFOST parameter set for {', '.join(skipped)}: left out")
    bench = json.loads((C.OUT / "climatology.json").read_text(encoding="utf-8"))
    inp = W.Inputs(refresh=False)
    rep_cells = [(s, g) for s, g in ro.cells(inp.sites) if not a.sites or s.id in a.sites]
    soils = {s.id: soil_mod.profile(s) for s, _ in rep_cells}
    tasks, keys = tasks_for(inp, years, rep_cells, varieties, a.rules, soils)
    log(f"{len(tasks)} observed seasons to simulate with WOFOST")
    t0 = time.time()
    res = ro.run_tasks(tasks, a.workers, engine="wofost")
    log(f"simulated in {time.time() - t0:.0f} s")
    wof = {}
    for (sid, vk, rk, y), r in zip(keys, res):
        m = {k: v for k, v in r[0].items() if not k.startswith("_")}
        wof.setdefault(sid, {}).setdefault(vk, {}).setdefault(rk, {})[str(y)] = m
    out = {}
    log(f"{'site':16s} {'crop':13s} {'rule':6s} | median t/ha AQ  WO | sown AQ  WO | fail AQ  WO | agree | r_sown | days AQ  WO")
    f = lambda x: "  — " if x is None else f"{x:4.2f}"
    for sid, vs in wof.items():
        for vk, rs in vs.items():
            for rk, ys in rs.items():
                aqua = bench["sites"][sid][vk][rk]["years"]
                c = compare({y: aqua[y] for y in ys if y in aqua}, ys, varieties[vk]["failure_t_ha"])
                out.setdefault(sid, {}).setdefault(vk, {})[rk] = c
                d = c["median_days_to_harvest"]
                log(f"{sid[:16]:16s} {vk:13s} {rk[:6]:6s} |          {f(c['median_t_ha']['aquacrop'])} {f(c['median_t_ha']['wofost'])} | "
                    f"{f(c['median_sown_t_ha']['aquacrop'])} {f(c['median_sown_t_ha']['wofost'])} | "
                    f"{f(c['failure_rate']['aquacrop'])} {f(c['failure_rate']['wofost'])} | {f(c['agree_on_failure'])}  | "
                    f"{f(c['spearman_sown'])}  | {d['aquacrop'] or 0:4.0f} {d['wofost'] or 0:4.0f}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "engines.json").write_text(json.dumps({
        "years": years, "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "aquacrop": "the benchmark (climatology.json)", "wofost": "Wofost72_WLP_CWB (PCSE), adapters/wofost_adapter.py",
        "left_out": skipped, "sites": out, "wofost_seasons": wof}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
