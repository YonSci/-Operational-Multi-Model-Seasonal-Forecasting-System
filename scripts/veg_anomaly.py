"""Cropland vegetation anomaly per 0.25-degree cell, for My farms' status and the crop map.

Sentinel-2 L2A NDVI (COPERNICUS/S2_SR_HARMONIZED; clouds and shadows masked with Cloud Score+, cs_cdf >= 0.6),
median of the last 16 days, over ESA WorldCover 2021 cropland (class 40), averaged per 0.25-degree cell of the tracker grid
at 100 m on Earth Engine. Compared with the same 16 days of each past year with a clear view (2019-2025; Sentinel-2
L2A covers Kenya from December 2018): the mean and spread of those years, the standardised anomaly and in how many
of them the cropland was less green.

    python scripts/veg_anomaly.py [--end 2026-11-24]      -> frontend/public/tracker/data/veg.csv

The past years of a window are kept in data/veg/baseline.json (by window end, MM-DD) and reused while today's window
ends within BASE_REUSE days of a kept one: Earth Engine then computes the current window only (about a minute), and the
seven past years (about 10 minutes) about once a week. Cells with under 1% cropland, or under 50 clear 100 m cropland pixels
in the window, have no value. Needs the Earth Engine project of realtime_rain.py (EE_PROJECT or
~/.config/earthengine/project.txt)."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
GRID = BASE / "frontend" / "public" / "tracker" / "data" / "grid.csv"
OUT = BASE / "frontend" / "public" / "tracker" / "data" / "veg.csv"
CACHE = BASE / "data" / "veg" / "baseline.json"
WINDOW = 16                      # days
YEARS = range(2019, 2026)        # past years compared (Sentinel-2 L2A over Kenya from Dec 2018)
SCALE = 100                      # m
CS_MIN = 0.6                     # Cloud Score+ cs_cdf: clear above
MIN_CROP = 0.01                  # cropland share of a cell to report it
MIN_PIX = 50                     # clear cropland pixels (at SCALE) in a window to count it
MIN_YEARS = 4                    # past years with a value for an anomaly
BASE_REUSE = 4                   # days: past years of a window ending this close to today's are reused
SD_FLOOR = 0.03                  # NDVI: the spread of the past years is at least this (a few similar years are not 0)
CELL = 0.25


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] veg: {msg}", flush=True)


def ee_init():
    import ee
    import realtime_rain as rr
    proj = rr.ee_project()
    ee.Initialize(project=proj) if proj else ee.Initialize()
    return ee


def cells():
    g = pd.read_csv(GRID, usecols=["lat", "lon"])
    return g.sort_values(["lat", "lon"]).reset_index(drop=True)


def reduce(ee, fc, start, end):
    """{id: (ndvi mean, clear cropland pixels, cropland share)} for the window [start, end)"""
    crop = ee.Image("ESA/WorldCover/v200/2021").select("Map").eq(40)
    cs = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterDate(start, end).filterBounds(fc.geometry())
          .linkCollection(cs, ["cs_cdf"])
          .map(lambda im: im.normalizedDifference(["B8", "B4"]).rename("ndvi").updateMask(im.select("cs_cdf").gte(CS_MIN))))
    img = s2.median().updateMask(crop).addBands(crop.rename("crop"))
    red = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    out = img.reduceRegions(collection=fc, reducer=red, scale=SCALE, tileScale=4).getInfo()
    res = {}
    for f in out["features"]:
        p = f["properties"]
        res[p["id"]] = (p.get("ndvi_mean"), p.get("ndvi_count", 0), p.get("crop_mean"))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", help="last day of the window (default: yesterday)")
    ap.add_argument("--out", type=Path, default=OUT, help=f"output CSV (default {OUT.relative_to(BASE)})")
    a = ap.parse_args()
    end = dt.date.fromisoformat(a.end) if a.end else dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=WINDOW - 1)
    ee = ee_init()
    cl = cells()
    ids = [f"{la:.3f},{lo:.3f}" for la, lo in zip(cl.lat, cl.lon)]
    h = CELL / 2
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Rectangle([lo - h, la - h, lo + h, la + h]), {"id": i})
                               for i, la, lo in zip(ids, cl.lat, cl.lon)])
    day = lambda d: d.isoformat()
    cur = reduce(ee, fc, day(start), day(end + dt.timedelta(days=1)))
    log(f"{start} to {end}: {sum(1 for v in cur.values() if v[0] is not None and v[1] >= MIN_PIX)} cells with a clear view")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    doy = lambda md: dt.date(2001, int(md[:2]), int(md[3:])).timetuple().tm_yday
    near = [k for k in cache if min(abs(doy(k) - doy(f"{end:%m-%d}")), 365 - abs(doy(k) - doy(f"{end:%m-%d}"))) <= BASE_REUSE
            and all(str(y) in cache[k] for y in YEARS if y < end.year)]
    key = min(near, key=lambda k: abs(doy(k) - doy(f"{end:%m-%d}"))) if near else f"{end:%m-%d}"
    base = cache.get(key, {})
    if near:
        log(f"past years: reusing the windows ending {key}")
    end_b = dt.date(end.year, int(key[:2]), int(key[3:]))
    for y in YEARS:
        if str(y) in base or y >= end.year:
            continue
        try:
            e = end_b.replace(year=y)
        except ValueError:                                   # 29 Feb
            e = end_b.replace(year=y, day=28)
        s = e - dt.timedelta(days=WINDOW - 1)
        r = reduce(ee, fc, day(s), day(e + dt.timedelta(days=1)))
        base[str(y)] = {i: (round(v[0], 4) if v[0] is not None and v[1] >= MIN_PIX else None) for i, v in r.items()}
        log(f"past year {y} ({s} to {e}): {sum(v is not None for v in base[str(y)].values())} cells")
        cache[key] = base
        CACHE.write_text(json.dumps(cache))

    rows = []
    for i, la, lo in zip(ids, cl.lat, cl.lon):
        nd, n, cf = cur.get(i, (None, 0, None))
        if cf is None or cf < MIN_CROP:
            continue
        past = np.array([base[str(y)].get(i) for y in YEARS if str(y) in base and base[str(y)].get(i) is not None], dtype=float)
        row = {"lat": la, "lon": lo, "crop_frac": round(cf, 3), "ndvi": None, "clear_px": int(n), "base_mean": None, "base_sd": None,
               "years": len(past), "z": None, "lower_years": None}
        if len(past):
            row["base_mean"] = round(float(past.mean()), 3)
            row["base_sd"] = round(float(past.std(ddof=1)), 3) if len(past) > 1 else None
        if nd is not None and n >= MIN_PIX:
            row["ndvi"] = round(nd, 3)
            if len(past) >= MIN_YEARS:
                row["z"] = round((nd - past.mean()) / max(past.std(ddof=1), SD_FLOOR), 2)
                row["lower_years"] = int((past < nd).sum())
        rows.append(row)
    df = pd.DataFrame(rows)
    df.insert(0, "past_window_end", key)
    df.insert(0, "window_end", day(end))
    df.insert(0, "window_start", day(start))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    ok = df.z.notna()
    log(f"{len(df)} cropland cells, {int(ok.sum())} with an anomaly; z below -1: {int((df.z < -1).sum())}, above +1: {int((df.z > 1).sum())} -> {a.out}")


if __name__ == "__main__":
    main()
