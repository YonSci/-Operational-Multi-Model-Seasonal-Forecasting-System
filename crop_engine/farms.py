"""Daily crop runs for the farms saved online (My farms; backend/assistant/farms.py).

Each farm in the backend's queue (daily runs on, sown this season, not harvested) is grown by AquaCrop from its own
sowing date, with its recorded irrigation, in the weather of its 0.25-degree cell (observed CHIRPS rain to the latest
day, then the 25 bias-corrected ECMWF SEAS5 members of the 1 Oct run, as the published crop outlook) and the cell's
soil (SoilGrids). No re-sowing: the farmer's own next sowing, when recorded, starts a new run. The normal is the same
crop sown on the same calendar day, with the same irrigation (days after sowing), in each observed season 1993-2025;
it is cached per cell, crop, sowing day and irrigation (outputs/crop_engine/farms/normals.json). Nitrogen recorded in
the diary is passed on but not modelled: AquaCrop here is water-limited, as the crop outlook.

    python -m crop_engine.farms                      the queue from the backend; results posted back
    python -m crop_engine.farms --queue farms.json --out results.json      offline: a queue file, results to a file

Backend: FARM_API (default the live API) and the batch token FARM_BATCH_TOKEN, or the first line of
~/.config/cai/farm_batch_token. At most MAX_FARMS farms a day (the oldest results first).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

import numpy as np

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.data import grid_temperature as gt
from crop_engine.data import soil as soil_mod
from crop_engine.data import weather as W
from crop_engine.data.sites import Site

API = os.environ.get("FARM_API", "https://operational-multi-model-seasonal-1t6w.onrender.com").rstrip("/")
TOKEN_FILE = Path.home() / ".config" / "cai" / "farm_batch_token"
MAX_FARMS = 60
MAX_CELL_KM = 25                 # km from the nearest land cell's centre (half a cell's diagonal is ~20): beyond, outside the area
BOX = (-5.0, 5.5, 33.5, 42.0)    # lat, lat, lon, lon: the Kenya forecast grid (0.25-degree cells -4.875..5.375, 33.625..41.875)
CACHE = C.OUT / "farms" / "normals.json"
NORMAL_VERSION = 1               # bump when the normal's definition changes (the cache is then rebuilt)


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] farms: {msg}", flush=True)


def token():
    t = os.environ.get("FARM_BATCH_TOKEN", "")
    if not t and TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8").splitlines()[0].strip()
    return t


def _api(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"X-Batch-Token": token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _season_day(sow: dt.date, season_year: int) -> dt.date:
    """The sowing's calendar day in season `season_year` (1 Aug of that year to 31 Mar of the next)."""
    y = season_year if sow.month >= 8 else season_year + 1
    try:
        return sow.replace(year=y)
    except ValueError:                                   # 29 Feb
        return sow.replace(year=y, day=28)


def _irrigation(events, sow):
    """The diary's irrigation after sowing -> the AquaCrop adapter's schedule (days after sowing, mm), or None."""
    das = sorted(((dt.date.fromisoformat(e["date"]) - sow).days, float(e["mm"])) for e in events or [])
    das = [(d, mm) for d, mm in das if d >= 0 and mm > 0]
    return {"schedule_das": das, "MaxIrr": max(mm for _, mm in das)} if das else None


def _normal_key(cell, vk, sow, irr):
    s = json.dumps([NORMAL_VERSION, cell, vk, f"{sow:%m-%d}", irr and irr["schedule_das"], list(C.HIST_YEARS),
                    version("aquacrop")], default=str)
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def run(queue, workers=1):
    """queue: the backend's farms (id, lat, lon, crop, sowing_date, irrigation, nitrogen, ...) -> {farm id: result}"""
    out = {}
    _, V = ro.load_varieties(None)
    todo = []
    for f in queue:
        if f.get("crop") not in V:
            out[f["id"]] = {"error": f"no crop model for {f.get('crop')}"}
        elif not (BOX[0] <= float(f["lat"]) <= BOX[1] and BOX[2] <= float(f["lon"]) <= BOX[3]):
            out[f["id"]] = {"error": "the farm is outside the forecast area (Kenya)"}
        else:
            todo.append(f)
    if not todo:
        return out
    sites = [Site(f"farm_{f['id'].replace('-', '')}", "farm", float(f["lat"]), float(f["lon"]), "kenya") for f in todo]
    t0 = time.time()
    inp = W.Inputs(sites=sites, refresh=False, temps=gt.cell_series, with_met=False)
    b = inp.b
    ids = [s.id for s in inp.sites]
    near = {s.id: 111.2 * np.hypot(s.lat - s.cell_lat, (s.lon - s.cell_lon) * np.cos(np.radians(s.lat))) <= MAX_CELL_KM
            for s in inp.sites}
    segs = [{"kind": "obs", "label": "Observed rainfall (CHIRPS)", "start": f"{b.win0}", "end": f"{b.obs_end}"},
            {"kind": "seas", "label": "ECMWF SEAS5 seasonal forecast", "start": f"{b.obs_end + dt.timedelta(days=1)}", "end": f"{b.last}"}]
    attrs = {"forecast_source": "seasonal", "model_label": "ECMWF SEAS5 (Oct 01 + latest obs)", "run_date": f"{b.lead0}",
             "obs_end": f"{b.obs_end}", "members_kind": "ensemble (SEAS5)", "segments": segs}
    ds = inp.forecast(b.seas, segs, attrs)
    problems = W.validate(ds)                                     # a farm with gaps in its weather is skipped below
    if problems:
        log(f"weather inputs: {'; '.join(problems)}")
    gaps = np.isnan(ds.precip_mm.values).any(axis=(0, 2)) | np.isnan(ds.tmax_c.values).any(axis=(0, 2)) | np.isnan(ds.et0_mm.values).any(axis=(0, 2))
    dates = ds.time.to_index()
    frac = inp.initial_water(inp.year)
    M = ds.sizes["member"]
    log(f"{len(todo)} farms; weather to {b.obs_end} then SEAS5 ({M} members) in {time.time() - t0:.0f} s")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    observed = {}
    for f, s in zip(todo, inp.sites):
        k = ids.index(s.id)
        try:
            if not near[s.id]:
                raise ValueError("the farm is outside the forecast area")
            if gaps[k]:
                raise ValueError("the weather of the farm's cell has gaps (no rain or temperature data there)")
            v = V[f["crop"]]
            sow = dt.date.fromisoformat(f["sowing_date"])
            sow = _season_day(sow, inp.year) if sow.year not in (inp.year, inp.year + 1) else sow
            if not dates[0].date() <= sow <= dates[-1].date():
                raise ValueError(f"the sowing date {sow} is outside this season ({dates[0]:%d %b %Y} to {dates[-1]:%d %b %Y})")
            irr = _irrigation(f.get("irrigation"), sow)
            soil = soil_mod.profile(s)
            base = dict(variety=v, kw=v["kw"], layers=soil, irrigation=irr)
            # this season: every member from the farm's sowing, no re-sowing
            members = ro.run_tasks([dict(base, dates=dates.values, rain=ds.precip_mm.values[:, k], tmax=ds.tmax_c.values[:, k],
                                         tmin=ds.tmin_c.values[:, k], et0=ds.et0_mm.values[:, k], source=ds.precip_source.values,
                                         planting=[sow] * M, resow=[[] for _ in range(M)], initial_frac=float(frac[k]))], workers)[0]
            members = [{kk: vv for kk, vv in m.items() if not kk.startswith("_")} for m in members]
            # the normal: the same crop, sowing day and irrigation in each observed season (cached)
            nkey = _normal_key(s.cell, f["crop"], sow, irr)
            if nkey not in cache:
                tasks, keys = [], []
                for y in years:
                    if y not in observed:
                        observed[y] = (inp.observed(y), inp.initial_water(y))
                    dy, fy = observed[y]
                    sy = _season_day(sow, y)
                    tasks.append(dict(base, dates=dy.time.values, rain=dy.precip_mm.values[:, k], tmax=dy.tmax_c.values[:, k],
                                      tmin=dy.tmin_c.values[:, k], et0=dy.et0_mm.values[:, k], source=dy.precip_source.values,
                                      planting=[sy], resow=[[]], initial_frac=float(fy[k])))
                    keys.append((s.id, f["crop"], "farm", y))
                res = ro.run_tasks(tasks, workers)
                bench = ro.bench_stats(res, keys, {f["crop"]: v}, years)[s.id][f["crop"]]["farm"]
                bench.pop("canopy", None)
                cache[nkey] = bench
                CACHE.write_text(json.dumps(cache), encoding="utf-8")
            normal = cache[nkey]
            summ = ro.summarize(members, v, normal)
            out[f["id"]] = {
                "summary": summ, "variety": f["crop"], "variety_label": v.get("label", f["crop"]),
                "sowing_date": f"{sow}", "irrigation_mm": round(sum(mm for _, mm in (irr or {}).get("schedule_das", [])), 1),
                "nitrogen_kg_ha": round(sum(float(x["kg_ha"]) for x in f.get("nitrogen") or []), 1),
                "members": [{kk: m.get(kk) for kk in ("member", "status", "yield_t_ha", "harvest", "stress_days", "rain_mm")} for m in members],
                "normal_years": {y: {kk: r.get(kk) for kk in ("status", "yield_t_ha")} for y, r in normal["years"].items()},
                "meta": {"run": f"{b.lead0}", "obs_end": f"{b.obs_end}", "model_label": attrs["model_label"], "members": M,
                         "engine": f"AquaCrop-OSPy {version('aquacrop')}", "cell": [s.cell_lat, s.cell_lon],
                         "weather": "the 0.25-degree cell: CHIRPS rain, then ECMWF SEAS5 (bias-corrected); ERA5-Land temperature and ET0",
                         "soil": "SoilGrids 2.0, the cell's mean profile", "failure_t_ha": v["failure_t_ha"],
                         "normal": f"the same crop, sowing day and irrigation in the observed seasons {years[0]}-{years[-1]}",
                         "nitrogen": "recorded, not modelled (AquaCrop is water-limited here)",
                         "march_rain": ds.attrs.get("march_rain"), "temperature": ds.attrs.get("temperature"),
                         "created": dt.datetime.now().astimezone().isoformat(timespec="minutes")}}
        except Exception as exc:                                       # one farm must not stop the others
            out[f["id"]] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    log(f"{sum('summary' in r for r in out.values())} of {len(queue)} farms simulated in {time.time() - t0:.0f} s")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queue", type=Path, help="a queue file (JSON list) instead of the backend's")
    ap.add_argument("--out", type=Path, help="write the results here instead of posting them")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.queue:
        queue = json.loads(a.queue.read_text(encoding="utf-8"))
    else:
        if not token():
            log(f"no batch token (FARM_BATCH_TOKEN or {TOKEN_FILE}); skipped")
            return 0
        queue = _api("/farms/batch/queue")
    if not queue:
        log("no farms to simulate")
        return 0
    queue = sorted(queue, key=lambda f: f.get("updated_at") or "")[-MAX_FARMS:]
    res = run(queue, a.workers)
    if a.out:
        a.out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        log(f"results -> {a.out}")
        return 0
    failed = 0
    for f in queue:
        try:
            _api(f"/farms/batch/{f['id']}/simulation", {"result": res.get(f["id"], {"error": "not run"}), "inputs": f})
        except Exception as exc:
            failed += 1
            log(f"posting farm {f['id'][:8]}: {type(exc).__name__}: {str(exc)[:120]}")
    log(f"{len(queue) - failed} results posted")
    return 1 if failed == len(queue) else 0


if __name__ == "__main__":
    sys.exit(main())
