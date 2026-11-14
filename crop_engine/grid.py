#!/usr/bin/env python3
"""
Gridded regional crop outlook (pilot): AquaCrop on every 0.25° cell of the analysis grid that grows rainfed maize in
the eastern Kenya Short Rains counties, driven by the seasonal forecast's members, and summed to counties.

Each cell is grown as the monitored sites are (run_outlook.py): the cell's forecast rain members and its own forecast
onset as the sowing date, the SoilGrids profile of the cell, the ERA5-Land root-zone water on 1 Aug, and ERA5-Land
temperature averaged over the cell (data/grid_temperature.py; the sites take theirs at the point), then SEAS5
member k, bias-corrected to it. Its normal is the same crop grown in the observed weather of 1993–2025.

DSSAT (where the variety has a DSSAT cultivar, unless --no-dssat) grows the same cells and members beside AquaCrop,
with the cells' ERA5-Land solar radiation, humidity and wind (era5land.site_met at the cell centres, cached per
cell), against its own normal (benchmark_dssat.json); published as cells_dssat and counties_dssat.

Cells: MapSPAM 2020 rainfed maize harvested area (5 arc-min pixels) summed to the 0.25° cells, each pixel given to its
HarvestStat county; a cell is kept when it holds at least MIN_HA in the counties. A county's yield is the mean of its
cells' yields weighted by its maize area in each, member by member (a forecast) or year by year (its normal): the
members keep the spatial pattern of their rain.

Published per cell and county: the expected (mean) yield as a percent of its 1993–2025 average, the chances of a
below / above normal yield (the benchmark's terciles of 1993–2016) and the chance of crop failure; per county also
the share of its maize area that fails. Yields are water-limited (no nutrients, pests or losses): the anomalies are
what is meant, not the levels. The county normal series is checked against HarvestStat's Short Rains maize yields of
the county (verify()).

Outputs:
  outputs/crop_engine/grid/benchmark.json        the cells' observed-weather seasons (rebuilt when the
                                                 configuration or the cells change)
  outputs/crop_engine/grid/benchmark_dssat.json  the same seasons grown by DSSAT
  outputs/crop_engine/grid/<run id>.json         the forecast's members and summaries per cell (meta.dssat: DSSAT's)
  frontend/public/tracker/data/crop/grid.json    the Crop outlook tab's map and county table (published)

Usage:
  python -m crop_engine.grid                           # temperature top-up, benchmark if needed, the seasonal run
  python -m crop_engine.grid --verify                  # also print the county check
  python -m crop_engine.grid --counties Machakos Makueni --workers 4 --force
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.data import grid_temperature as gt
from crop_engine.data import sites as sites_mod
from crop_engine.data import soil as soil_mod
from crop_engine.scenarios import planting as pl
from crop_engine.yields import YIELD_DATA
from crop_engine.yields import statistics as ys

GRID_OUT = C.OUT / "grid"
PUBLISHED = C.DASHBOARD_OUT / "grid.json"
# The Short Rains maize counties of eastern Kenya: the season that matters there, with the longest HarvestStat
# Short Rains records (14–19 seasons since 1990)
COUNTIES = ["Machakos", "Makueni", "Kitui", "Kajiado", "Embu", "Tharaka Nithi", "Meru", "Taita Taveta"]
MIN_HA = 300.0                       # rainfed maize harvested area of a cell in the counties (MapSPAM 2020)
VARIETIES = ["maize_early"]
RULES = ["fao-agricultural"]
MIN_COUNTY_YEARS = 8
CAVEATS = [
    "Pilot: the eastern Kenya Short Rains maize counties, early-maturing maize sown at the FAO agricultural onset "
    "of each cell's forecast.",
    "Each 0.25° cell (about 28 km) is one field, grown by AquaCrop and by DSSAT, with the cell's average soil "
    "(SoilGrids), rain (CHIRPS and the bias-corrected forecast) and temperature (ERA5-Land; DSSAT also its radiation, "
    "humidity and wind): not any farmer's field.",
    "Yields are water-limited, without nutrient stress, pests or management losses: read the percent of normal and "
    "the chances, not the tonnes per hectare.",
    "A county is the mean of its cells, weighted by their rainfed maize area (MapSPAM 2020).",
    "The normal is the same crop grown in the observed weather of 1993–2025; the terciles are those of 1993–2016.",
    "The forecasts have not been verified against observed yields; the county normals are compared with HarvestStat's "
    "Short Rains maize yields (see the county table).",
    "A crop sown into dry soil waits for rain to germinate, and its season counts from germination (a correction "
    "of AquaCrop-OSPy's end of season, November 2026).",
]


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] grid: {m}", flush=True)


def cell_id(lat, lon):
    return f"g{lat:+.3f}_{lon:.3f}"


# ── the cells ───────────────────────────────────────────────────────────────
def crop_cells(counties=COUNTIES, min_ha=MIN_HA, crop="maiz", root=YIELD_DATA):
    """DataFrame of the 0.25° cells with at least min_ha of the crop's rainfed harvested area in the counties:
    id, cell_lat, cell_lon, area_ha (in the counties) and weights {county: ha}."""
    import geopandas as gpd                                       # here: only the cell selection needs it
    k = ys.mapspam_kenya(root, log)
    b = gpd.read_file(root / "HarvestStat_Africa" / "hvstat_africa_boundary_v1.2.gpkg")
    b = b[(b.country_code == "KE") & b.admin_1.isin(counties)]
    missing = sorted(set(counties) - set(b.admin_1))
    if missing:
        raise ValueError(f"not HarvestStat counties of Kenya: {', '.join(missing)}")
    pts = gpd.GeoDataFrame(k[["x", "y", f"{crop}_H_TR"]], geometry=gpd.points_from_xy(k.x, k.y), crs="EPSG:4326")
    j = gpd.sjoin(pts, b[["admin_1", "geometry"]], how="inner", predicate="within")
    j["cell_lat"], j["cell_lon"] = ys.cell_of(j.y.values, j.x.values)
    w = j.groupby(["cell_lat", "cell_lon", "admin_1"])[f"{crop}_H_TR"].sum().rename("ha").reset_index()
    rows = []
    for (la, lo), g in w.groupby(["cell_lat", "cell_lon"]):
        g = g[g.ha > 0]
        if g.ha.sum() >= min_ha:
            rows.append(dict(id=cell_id(la, lo), cell_lat=round(float(la), 3), cell_lon=round(float(lo), 3),
                             area_ha=round(float(g.ha.sum()), 1),
                             weights={c: round(float(h), 1) for c, h in zip(g.admin_1, g.ha)}))
    return pd.DataFrame(rows)


def county_outlines(counties=COUNTIES, root=YIELD_DATA, tolerance=0.01):
    """{county: GeoJSON geometry} simplified for the tab's map (coordinates to 3 decimals)."""
    import geopandas as gpd
    from shapely.geometry import mapping
    b = gpd.read_file(root / "HarvestStat_Africa" / "hvstat_africa_boundary_v1.2.gpkg")
    b = b[(b.country_code == "KE") & b.admin_1.isin(counties)].dissolve("admin_1")

    def rnd(x):
        return [rnd(v) for v in x] if isinstance(x, (list, tuple)) and not isinstance(x[0], float) else \
            [round(x[0], 3), round(x[1], 3)]
    out = {}
    for name, geom in b.geometry.items():
        g = mapping(geom.simplify(tolerance, preserve_topology=True))
        out[name] = {"type": g["type"], "coordinates": rnd(g["coordinates"])}
    return out


def as_sites(cells):
    return [sites_mod.Site(r.id, f"Cell {r.cell_lat:.3f}, {r.cell_lon:.3f}", float(r.cell_lat), float(r.cell_lon),
                           "kenya") for r in cells.itertuples()]


def inputs(cells, refresh=True, with_met=False):
    """weather.Inputs at the cells: their gridded ERA5-Land temperature, and with_met (DSSAT) their ERA5-Land solar
    radiation, humidity and wind (era5land.site_met at the cells, fetched once from Earth Engine and cached per cell).
    Cells off the forecast's land mask or without soil data are dropped (logged): returns (inputs, soils, the cells
    kept)."""
    from crop_engine.data import weather as W
    if refresh:
        failed = gt.update()
        if failed:
            log(f"temperature of {failed} not updated; the files on disk are used")
    b = W.bs.Blender(C.BASE)
    lat, lon = b.lat, b.lon
    keep = []
    for r in cells.itertuples():
        i, j = int(np.abs(lat - r.cell_lat).argmin()), int(np.abs(lon - r.cell_lon).argmin())
        if abs(lat[i] - r.cell_lat) > 0.01 or abs(lon[j] - r.cell_lon) > 0.01 or not b.lm[i, j]:
            log(f"{r.id}: not on the forecast's land grid; left out")
            continue
        keep.append(r.Index)
    cells = cells.loc[keep]
    soils, ok = {}, []
    for s, r in zip(as_sites(cells), cells.itertuples()):
        try:
            soils[s.id] = soil_mod.profile(sites_mod.Site(s.id, s.name, s.lat, s.lon, s.country, cell_lat=s.lat,
                                                          cell_lon=s.lon))
            ok.append(r.Index)
        except ValueError as exc:
            log(f"{s.id}: {exc}; left out")
    cells = cells.loc[ok].reset_index(drop=True)
    inp = W.Inputs(sites=as_sites(cells), refresh=False, blender=b, temps=gt.cell_series, with_met=with_met)
    moved = [s.id for s in inp.sites if cell_id(s.cell_lat, s.cell_lon) != s.id]
    if moved:
        raise RuntimeError(f"cells moved to another grid cell: {moved[:5]}")
    return inp, soils, cells


def grid_hash(rules, varieties, sites, season_year):
    """The benchmark's configuration: run_outlook.config_hash of the cells, the varieties grown, and the temperature
    (its module and the past years on disk: a benchmark made before the download finished is rebuilt)."""
    h = hashlib.sha1(ro.config_hash(rules, sites).encode())
    h.update(json.dumps(sorted(varieties)).encode())
    h.update(Path(gt.__file__).read_bytes())
    h.update(json.dumps([y for y in range(gt.FIRST_YEAR, season_year) if gt.path(y).exists()]).encode())
    return h.hexdigest()[:12]


# ── area sums ───────────────────────────────────────────────────────────────
def _eff(m):
    return np.nan if m is None or m.get("status") == "error" else ro.effective_yield(m)


def area_mean(values, weights):
    """Area-weighted mean over cells of (cell, n) values; NaN values (model errors) leave their cell out."""
    v = np.asarray(values, float)
    w = np.broadcast_to(np.asarray(weights, float)[:, None], v.shape)
    ok = np.isfinite(v)
    with np.errstate(invalid="ignore"):
        return np.where(ok.any(axis=0), np.nansum(np.where(ok, v * w, 0), axis=0) / np.where(ok, w, 0).sum(axis=0), np.nan)


def terciles(cal):
    cal = np.asarray(cal, float)
    cal = cal[np.isfinite(cal)]
    return (float(np.quantile(cal, 1 / 3)), float(np.quantile(cal, 2 / 3))) if len(cal) >= 10 else (None, None)


def chances(y, t33, t67, failure):
    """p below / above normal of yields y against the terciles; None when the terciles do not separate yields (a
    third or more of the normal seasons failed), as run_outlook.summarize."""
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    if t33 is None or not len(y) or t33 < failure or t67 <= t33:
        return None, None
    return round(float((y < t33).mean()), 3), round(float((y > t67).mean()), 3)


def pct(a, b):
    return round(100 * a / b) if b and np.isfinite(a) and np.isfinite(b) and b > 0.05 else None


def county_series(bench, cells, vk, rk, years):
    """{county: ((years,) area-mean normal yields, (cell, years) its cells' yields, the cells' weights)}, from the
    cells' benchmark."""
    out = {}
    for county in sorted({c for w in cells.weights for c in w}):
        rows = [(r.id, r.weights[county]) for r in cells.itertuples() if county in r.weights]
        v = np.array([[_eff(bench[cid][vk][rk]["years"].get(str(y))) for y in years] for cid, _ in rows])
        w = [h for _, h in rows]
        out[county] = (area_mean(v, w), v, w)
    return out


def summarize_counties(fc, bench, cells, varieties, vk, rk, years):
    """Per county: the forecast's area-mean yield per member against the county's normal of the same cells."""
    f = varieties[vk]["failure_t_ha"]
    cal = [k for k, y in enumerate(years) if C.CAL_YEARS[0] <= y <= C.CAL_YEARS[1]]
    out = {}
    series = county_series(bench, cells, vk, rk, years)
    for county, (normal, per_cell_b, w) in series.items():
        ids = [r.id for r in cells.itertuples() if county in r.weights]
        m = np.array([[_eff(x) for x in fc[cid][vk][rk]] for cid in ids])          # (cell, member)
        y = area_mean(m, w)
        failed = area_mean((m < f).astype(float) + np.where(np.isfinite(m), 0, np.nan), w)
        failed_b = area_mean((per_cell_b < f).astype(float) + np.where(np.isfinite(per_cell_b), 0, np.nan), w)
        t33, t67 = terciles(normal[cal])
        pb, pa = chances(y, t33, t67, f)
        out[county] = {
            "n_cells": len(ids), "area_ha": round(float(sum(w))),
            "mean_t_ha": round(float(np.nanmean(y)), 3), "median_t_ha": round(float(np.nanmedian(y)), 3),
            "p10_t_ha": round(float(np.nanquantile(y, 0.1)), 3), "p90_t_ha": round(float(np.nanquantile(y, 0.9)), 3),
            "normal_mean_t_ha": round(float(np.nanmean(normal)), 3),
            "normal_median_t_ha": round(float(np.nanmedian(normal)), 3),
            "pct_normal": pct(np.nanmean(y), np.nanmean(normal)),
            "t33": None if t33 is None else round(t33, 3), "t67": None if t67 is None else round(t67, 3),
            "p_below_normal": pb, "p_above_normal": pa,
            "failed_area_share_median": round(float(np.nanmedian(failed)), 3),
            "normal_failed_area_share_median": round(float(np.nanmedian(failed_b)), 3),
        }
    return out


# ── verification: the county normals against HarvestStat ──────────────────
def harveststat_sr(crop="maize"):
    """{county: {year: Short Rains dry yield, t/ha}} (HarvestStat Africa, QC-flagged seasons left out)."""
    h = ys.harveststat()
    h = h[(h.season == "SR") & (h.crop == crop) & h.qc_flag.isna() & np.isfinite(h.yield_dry_kg_ha)]
    return {c: {int(y): float(v) / 1000 for y, v in zip(g.year, g.yield_dry_kg_ha)} for c, g in h.groupby("admin_1")}


def _detrend(x, t):
    x, t = np.asarray(x, float), np.asarray(t, float)
    return x - np.polyval(np.polyfit(t, x, 1), t)


def verify(bench, cells, vk, rk, years, site_bench=None, min_years=MIN_COUNTY_YEARS):
    """Per county: rank correlation of the area-mean normal yields with HarvestStat's Short Rains maize yields over
    the shared years, and the Pearson correlation of both detrended; with the monitored site's single cell beside it
    (site_bench: run_outlook's climatology.json sites) where the county has one."""
    from scipy.stats import pearsonr, spearmanr
    obs = harveststat_sr()
    series = county_series(bench, cells, vk, rk, years)
    site_county = {}
    if site_bench:
        sc = pd.read_csv(C.OUT / "yields" / "sites.csv") if (C.OUT / "yields" / "sites.csv").exists() else None
        if sc is not None:
            site_county = {r.county: r.site_id for r in sc.itertuples() if r.site_id in site_bench}
    out = {}
    for county, (normal, _, _) in series.items():
        cy = obs.get(county, {})
        k = [i for i, y in enumerate(years) if y in cy and np.isfinite(normal[i])]
        if len(k) < min_years:
            out[county] = {"n_years": len(k)}
            continue
        yy = [years[i] for i in k]
        a, o = normal[k], np.array([cy[y] for y in yy])
        row = {"n_years": len(k), "years": yy, "r_rank": round(float(spearmanr(a, o).correlation), 2),
               "r_detrended": round(float(pearsonr(_detrend(a, yy), _detrend(o, yy))[0]), 2)}
        sid = site_county.get(county)
        if sid:
            sb = site_bench[sid].get(vk, {}).get(rk, {}).get("years", {})
            s = np.array([_eff(sb.get(str(y))) for y in yy])
            if np.isfinite(s).all():
                row.update(site=sid, site_r_rank=round(float(spearmanr(s, o).correlation), 2),
                           site_r_detrended=round(float(pearsonr(_detrend(s, yy), _detrend(o, yy))[0]), 2))
        out[county] = row
    return out


def verify_table(v):
    log(f"{'county':14s} years | r with HarvestStat SR maize: grid (rank, detrended) | the site's cell alone")
    for c, r in v.items():
        if "r_rank" not in r:
            log(f"  {c:14s} {r['n_years']:3d}   too few years")
            continue
        site = f"{r['site_r_rank']:+.2f}, {r['site_r_detrended']:+.2f} ({r['site'][:20]})" if "site" in r else "—"
        log(f"  {c:14s} {r['n_years']:3d}   {r['r_rank']:+.2f}, {r['r_detrended']:+.2f}  | {site}")


# ── benchmark and forecast ──────────────────────────────────────────────────
def benchmark(inp, soils, varieties, rules, workers, force=False):
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    h = grid_hash(rules, varieties, inp.sites, inp.year)
    path = GRID_OUT / "benchmark.json"
    if path.exists() and not force:
        b = json.loads(path.read_text(encoding="utf-8"))
        if b.get("config_hash") == h:
            return b
    rep = [(s, [s.id]) for s in inp.sites]
    t0 = time.time()
    cells = ro.benchmark(inp, rep, varieties, rules, soils, workers)
    for vs in cells.values():                                         # the tab needs no canopy bands of every cell
        for rs in vs.values():
            for r in rs.values():
                r.pop("canopy", None)
    b = {"config_hash": h, "years": years, "cal_years": list(C.CAL_YEARS), "created": _now(), "cells": cells}
    GRID_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(b), encoding="utf-8")
    log(f"benchmark: {len(inp.sites)} cells in {time.time() - t0:.0f} s → {path}")
    return b


def dssat_benchmark(inp, soils, varieties, rules, workers, force=False):
    """DSSAT's observed-weather benchmark of the cells (the same seasons and sowings as benchmark()), or None without
    DSSAT or the cells' radiation, humidity and wind."""
    from crop_engine import compare_engines as ce
    use = {vk: varieties[vk] for vk in ro.dssat_varieties(varieties)}
    if not use or inp.met2 is None:
        return None
    years = list(range(C.HIST_YEARS[0], C.HIST_YEARS[1] + 1))
    h = hashlib.sha1((grid_hash(rules, use, inp.sites, inp.year) + ro.dssat_hash(rules, inp.sites)).encode()).hexdigest()[:12]
    path = GRID_OUT / "benchmark_dssat.json"
    if path.exists() and not force:
        b = json.loads(path.read_text(encoding="utf-8"))
        if b.get("config_hash") == h:
            return b
    rep = [(s, [s.id]) for s in inp.sites]
    tasks, keys = ce.tasks_for(inp, years, rep, use, rules, soils)
    tasks = [dict(t, potential=False) for t in tasks]
    t0 = time.time()
    cells = ro.bench_stats(ro.run_tasks(tasks, workers, engine="dssat"), keys, use, years)
    for vs in cells.values():
        for rs in vs.values():
            for r in rs.values():
                r.pop("canopy", None)
    b = {"config_hash": h, "years": years, "cal_years": list(C.CAL_YEARS), "created": _now(), "engine": ro.THIRD_ENGINE,
         "cells": cells}
    GRID_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(b), encoding="utf-8")
    log(f"DSSAT benchmark: {len(inp.sites)} cells in {time.time() - t0:.0f} s → {path}")
    return b


def _now():
    return dt.datetime.now().astimezone().isoformat(timespec="minutes")


def seasonal_run(inp, soils, varieties, rules, bench, workers, dbench=None):
    """The seasonal forecast (SEAS5 1 Oct + the latest observations) at the cells → {cell: {variety: {rule: members}}},
    the summaries per cell and the run's description; with DSSAT's benchmark (dbench), DSSAT grows the same members
    too (meta "dssat": its members and summaries)."""
    import forecast_runs as fr  # noqa: E402  (scripts/, on sys.path via config)
    b = inp.b
    P = b.seas
    segs = [{"kind": "obs", "label": "Observed rainfall (CHIRPS)", "start": f"{b.win0}", "end": f"{b.obs_end}"},
            {"kind": "seas", "label": "ECMWF SEAS5 seasonal forecast", "start": f"{b.obs_end + dt.timedelta(days=1)}",
             "end": f"{b.last}"}]
    rid = f"seasonal_{b.lead0:%Y%m%d}"
    meth_res = fr.Methods(inp.year).run(P, np.zeros(P.shape[1], bool))
    attrs = {"forecast_source": "seasonal", "model_label": "ECMWF SEAS5 (Oct 01 + latest obs)", "run_date": f"{b.lead0}",
             "obs_end": f"{b.obs_end}", "members_kind": "ensemble (SEAS5)", "segments": segs}
    ds = inp.forecast(P, segs, attrs)
    from crop_engine.data import weather as W
    problems = W.validate(ds)
    if problems:
        raise ValueError(f"{rid}: weather inputs invalid: {'; '.join(problems)}")
    frac = inp.initial_water(inp.year)
    dates = ds.time.to_index()
    plant = {rk: pl.forecast_dates(meth_res, inp.sites, inp.year, rk) for rk in rules}
    tasks, keys = [], []
    for k, s in enumerate(inp.sites):
        resow = pl.sowing_opportunities(ds.precip_mm.values[:, k], dates)
        for rk in rules:
            for vk, v in varieties.items():
                tasks.append(dict(dates=dates.values, rain=ds.precip_mm.values[:, k], tmax=ds.tmax_c.values[:, k],
                                  tmin=ds.tmin_c.values[:, k], et0=ds.et0_mm.values[:, k], source=ds.precip_source.values,
                                  planting=plant[rk][s.id], resow=resow, variety=v, kw=v["kw"], layers=soils[s.id],
                                  initial_frac=float(frac[k])))
                keys.append((s.id, vk, rk))
    t0 = time.time()
    res = ro.run_tasks(tasks, workers)
    log(f"{rid}: {len(tasks) * P.shape[0]} member seasons at {len(inp.sites)} cells in {time.time() - t0:.0f} s")
    dssat = None
    if dbench is not None and "rad_mj_m2" in ds:
        ids = [x.id for x in inp.sites]
        dt_, dk = [], []
        for t, key in zip(tasks, keys):
            k = ids.index(key[0])
            s = inp.sites[k]
            dt_.append(dict(t, rad=ds.rad_mj_m2.values[:, k], vap=ds.vap_hpa.values[:, k], wind2=ds.wind2_ms.values[:, k],
                            lat=s.lat, lon=s.lon, elev=float(ds.elev_m.values[k]), potential=False))
            dk.append(key)
        t1 = time.time()
        dres = ro.run_tasks(dt_, workers, engine="dssat")
        dssat = {"members": {}, "summaries": {}}
        for (cid, vk, rk), outcomes in zip(dk, dres):
            for m in outcomes:
                m.pop("_canopy", None)
            dssat["members"].setdefault(cid, {}).setdefault(vk, {})[rk] = outcomes
            dssat["summaries"].setdefault(cid, {}).setdefault(vk, {})[rk] = ro.summarize(
                outcomes, varieties[vk], dbench["cells"][cid][vk][rk])
        log(f"{rid}: DSSAT {len(dt_) * P.shape[0]} member seasons in {time.time() - t1:.0f} s")
    members, summ = {}, {}
    for (cid, vk, rk), outcomes in zip(keys, res):
        for m in outcomes:
            m.pop("_canopy", None)
        members.setdefault(cid, {}).setdefault(vk, {})[rk] = outcomes
        summ.setdefault(cid, {}).setdefault(vk, {})[rk] = ro.summarize(outcomes, varieties[vk],
                                                                       bench["cells"][cid][vk][rk])
    every = [m for outcomes in res for m in outcomes]
    low = ro.low_harvest_index(every)
    if low is not None:
        log(f"{rid}: {low:g} % of the matured member seasons have a harvest index below {ro.LOW_HI:g} "
            f"(should stay near 0: the delayed-germination check)")
    meta = {"id": rid, "source": "seasonal", "model_label": attrs["model_label"], "run": f"{b.lead0}",
            "low_harvest_index_pct": low,
            "obs_end": f"{b.obs_end}", "members": int(P.shape[0]), "engine": ro.ENGINE, "config_hash": bench["config_hash"],
            "created": _now(), "march_rain": ds.attrs.get("march_rain"), "temperature": ds.attrs.get("temperature_forecast"),
            "dssat_config_hash": (dbench or {}).get("config_hash")}
    if dssat:
        meta["dssat"] = dssat
    return members, summ, meta


def cell_rows(cells, summ, bench, vk, rk):
    rows = []
    for r in cells.itertuples():
        s = summ[r.id][vk][rk]
        b = bench["cells"][r.id][vk][rk]
        vb = s.get("vs_benchmark", {})
        normal = [_eff(x) for x in b["years"].values()]
        rows.append({"id": r.id, "lat": r.cell_lat, "lon": r.cell_lon, "area_ha": r.area_ha,
                     "county": max(r.weights, key=r.weights.get), "weights": r.weights,
                     "mean_t_ha": s["yield_t_ha"]["mean"], "median_t_ha": s["yield_t_ha"]["median"],
                     "p10_t_ha": s["yield_t_ha"]["p10"], "p90_t_ha": s["yield_t_ha"]["p90"],
                     "normal_mean_t_ha": round(float(np.nanmean(normal)), 3), "normal_median_t_ha": b["median"],
                     "pct_normal": pct(np.nan if s["yield_t_ha"]["mean"] is None else s["yield_t_ha"]["mean"],
                                       float(np.nanmean(normal))),
                     "p_below_normal": vb.get("p_below_normal"), "p_above_normal": vb.get("p_above_normal"),
                     "p_failure": s["p_failure"], "normal_p_failure": b["p_failure"],
                     "sowing_median": s["planting"]["median"], "not_sown": s["share"]["not_sown"],
                     "too_late": s["share"]["too_late"]})
    return rows


def publish(cells, summ, members, bench, meta, varieties, rules, counties, verification, outlines, dest=PUBLISHED,
            dbench=None):
    vk, rk = next(iter(varieties)), rules[0]
    years = bench["years"]
    member_map = {cid: {vk: {rk: members[cid][vk][rk]}} for cid in members}
    dss = meta.get("dssat")
    meta = {k: v for k, v in meta.items() if k != "dssat"}
    out = {"meta": {**meta, "variety": vk, "models": ["aquacrop"] + (["dssat"] if dss and dbench else []), "variety_label": varieties[vk]["label"], "rule": rk,
                    "rule_label": C.PLANTING_RULES[rk]["label"], "failure_t_ha": varieties[vk]["failure_t_ha"],
                    "cell_deg": 0.25, "counties": counties, "min_ha": MIN_HA,
                    "area_source": "MapSPAM 2020 V2r2 rainfed maize harvested area", "years": [years[0], years[-1]],
                    "cal_years": bench["cal_years"], "caveats": CAVEATS},
           "cells": cell_rows(cells, summ, bench, vk, rk),
           "counties": [{"name": c, **v, "verification": verification.get(c, {})}
                        for c, v in summarize_counties(member_map, bench["cells"], cells, varieties, vk, rk,
                                                       years).items()],
           "outlines": outlines}
    if dss and dbench:                                                   # DSSAT's cells and counties, against its own normal
        dmap = {cid: {vk: {rk: dss["members"][cid][vk][rk]}} for cid in dss["members"]}
        out["cells_dssat"] = cell_rows(cells, dss["summaries"], dbench, vk, rk)
        dv = verify(dbench["cells"], cells, vk, rk, dbench["years"])
        out["counties_dssat"] = [{"name": c, **v, "verification": dv.get(c, {})}
                                 for c, v in summarize_counties(dmap, dbench["cells"], cells, varieties, vk, rk,
                                                                years).items()]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dest)
    log(f"published {len(out['cells'])} cells, {len(out['counties'])} counties → {dest}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counties", nargs="+", default=COUNTIES)
    ap.add_argument("--min-ha", type=float, default=MIN_HA)
    ap.add_argument("--varieties", nargs="+", default=VARIETIES)
    ap.add_argument("--rules", nargs="+", choices=list(C.PLANTING_RULES), default=RULES)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--benchmark", action="store_true", help="rebuild the cells' observed-weather benchmark")
    ap.add_argument("--force", action="store_true", help="rerun a forecast already made from the same observations")
    ap.add_argument("--no-refresh", action="store_true", help="do not top up the gridded ERA5-Land temperature")
    ap.add_argument("--verify", action="store_true", help="print the county check against HarvestStat")
    ap.add_argument("--no-dashboard", action="store_true", help="do not write the tab's grid.json")
    ap.add_argument("--dashboard-file", default=str(PUBLISHED), help="where to write it (default: the tab's data)")
    ap.add_argument("--no-dssat", action="store_true", help="AquaCrop only")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):        # the worker processes
        os.environ.setdefault(k, "1")
    _, varieties = ro.load_varieties(a.varieties)
    cells = crop_cells(a.counties, a.min_ha)
    log(f"{len(cells)} cells with at least {a.min_ha:.0f} ha of rainfed maize in {', '.join(a.counties)} "
        f"({cells.area_ha.sum():.0f} ha)")
    use_dssat = not a.no_dssat and bool(ro.dssat_varieties(dict(varieties)))
    inp, soils, cells = inputs(cells, refresh=not a.no_refresh, with_met=use_dssat)
    log(f"{len(inp.sites)} cells with weather and soil; observations to {inp.b.obs_end}")
    bench = benchmark(inp, soils, varieties, a.rules, a.workers, a.benchmark)
    dbench = dssat_benchmark(inp, soils, varieties, a.rules, a.workers, a.benchmark) if use_dssat else None
    if use_dssat and dbench is None:
        log(f"DSSAT left out: {inp.met2_note or 'no DSSAT variety'}")
    vk, rk = a.varieties[0], a.rules[0]
    site_b = C.OUT / "climatology.json"
    v = verify(bench["cells"], cells, vk, rk, bench["years"],
               json.loads(site_b.read_text(encoding="utf-8"))["sites"] if site_b.exists() else None)
    if a.verify:
        verify_table(v)
    rid = f"seasonal_{inp.b.lead0:%Y%m%d}"
    path = GRID_OUT / f"{rid}.json"
    if path.exists() and not a.force:
        old = json.loads(path.read_text(encoding="utf-8"))
        if (old["meta"].get("obs_end") == f"{inp.b.obs_end}" and old["meta"].get("config_hash") == bench["config_hash"]
                and old["meta"].get("dssat_config_hash") == (dbench or {}).get("config_hash")):
            log(f"{rid}: already made from these observations")
            if not a.no_dashboard:
                publish(cells, old["summaries"], old["members"], bench, old["meta"], varieties, a.rules, a.counties, v,
                        county_outlines(a.counties), a.dashboard_file, dbench)
            return 0
    members, summ, meta = seasonal_run(inp, soils, varieties, a.rules, bench, a.workers, dbench)
    GRID_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "summaries": summ, "members": members}), encoding="utf-8")
    if not a.no_dashboard:
        out = publish(cells, summ, members, bench, meta, varieties, a.rules, a.counties, v, county_outlines(a.counties),
                      a.dashboard_file, dbench)
        for c in out["counties"]:
            log(f"  {c['name']:14s} {c['pct_normal']}% of normal, below {c['p_below_normal']}, above "
                f"{c['p_above_normal']}, failed area {c['failed_area_share_median']} "
                f"(normal {c['normal_failed_area_share_median']})")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
