#!/usr/bin/env python3
"""
fao_era5land_gee.py
───────────────────
ERA5-Land forcing for the FAO water-balance module from Google Earth Engine (faster than the Copernicus CDS queue):
daily FAO-56 Penman-Monteith ET0 and root-zone soil moisture on the platform's 0.25° Kenya grid.

  ECMWF/ERA5_LAND/DAILY_AGGR (UTC days):
    temperature_2m_max / _min            → Tmax, Tmin  (FAO-56: T = (Tmax + Tmin) / 2)
    dewpoint_temperature_2m              → actual vapour pressure ea
    surface_solar_radiation_downwards_sum → Rs (J m-2 day-1)
    surface_pressure                     → γ and the elevation used for Rso
    volumetric_soil_water_layer_1..3     → θ 0–100 cm (7 / 21 / 72 cm weights): initial storage and validation
  ECMWF/ERA5_LAND/HOURLY:
    10 m u, v at 00, 06, 12, 18 UTC      → daily mean wind speed (speed at each time, then the mean; the daily mean
                                           of the components underestimates it, ~8 % over Kenya)

Months Jan–Mar and Aug–Dec of each year (OND season from 15 Aug, cessation to 28 Feb). Pixels are sampled on a
0.05° grid nested in the 0.25° cells (nearest ERA5-Land 0.1° value), ET0 is computed there and averaged 5 × 5 over
land pixels. Same output as fao_water_balance.build_et0 (the CDS route):

  outputs/fao_wb/et0/et0_<year>.nc   ET0 (mm/day), theta_rootzone (m3 m-3)

Existing years are skipped; the current year is rebuilt (ERA5-Land runs about 5 days behind real time).
Earth Engine project: EE_PROJECT, else ~/.config/earthengine/project.txt.

Usage:
  python scripts/fao_era5land_gee.py                 # 1993 – this year
  python scripts/fao_era5land_gee.py --years 2026
"""
import argparse
import datetime as dt
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
import fao_water_balance as fw  # noqa: E402

MONTHS = (1, 2, 3, 8, 9, 10, 11, 12)
GRID = {"dimensions": {"width": 170, "height": 210}, "crsCode": "EPSG:4326",
        "affineTransform": {"scaleX": 0.05, "shearX": 0, "translateX": 33.5, "shearY": 0, "scaleY": -0.05, "translateY": 5.5}}
DAILY = ["temperature_2m_max", "temperature_2m_min", "dewpoint_temperature_2m", "surface_solar_radiation_downwards_sum",
         "surface_pressure", "volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2", "volumetric_soil_water_layer_3"]
NODATA = -9999.0
SYNOPTIC = None        # set in init_ee: hours 00, 06, 12, 18 UTC (as the CDS route; 6× less compute than 24 hours)


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def init_ee():
    import ee
    project = os.environ.get("EE_PROJECT") or (Path.home() / ".config" / "earthengine" / "project.txt").read_text().strip()
    ee.Initialize(project=project, opt_url="https://earthengine-highvolume.googleapis.com")
    global SYNOPTIC
    SYNOPTIC = ee.Filter.Or(*[ee.Filter.calendarRange(h, h, "hour") for h in (0, 6, 12, 18)])
    return ee


def pixels(ee, img, tries=8):
    """(bands, 210, 170) float32 on the 0.05° grid, north-up; NaN where masked (sea, lakes). Fetched as a GeoTIFF
    (a NUMPY_NDARRAY reply lists every band in its header, which NumPy refuses beyond ~10 kB). Network drops and
    Earth Engine rate limits are retried with growing pauses."""
    from rasterio.io import MemoryFile
    for i in range(tries):
        try:
            b = ee.data.computePixels({"expression": img.unmask(NODATA).toFloat(), "fileFormat": "GEO_TIFF", "grid": GRID})
            break
        except Exception as exc:
            if i == tries - 1 or "must be less than" in str(exc):
                raise
            log(f"  retry {i + 1}: {str(exc)[:120]}")
            __import__("time").sleep(30 * (i + 1))
    with MemoryFile(b) as m, m.open() as src:
        out = src.read().astype(np.float32)
    out[out <= NODATA + 1] = np.nan
    return out


def month(ee, y, m):
    """One month: (days, 8 daily variables + wind, 210, 170) and the dates; None when ERA5-Land has no days yet."""
    start = ee.Date.fromYMD(y, m, 1)
    end = start.advance(1, "month")
    daily = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(start, end).select(DAILY)
    n = daily.size().getInfo()
    if n == 0:
        return None
    dates = pd.to_datetime(daily.aggregate_array("system:time_start").getInfo(), unit="ms")
    d = pixels(ee, daily.toBands()).reshape(n, len(DAILY), 210, 170)
    hourly = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").select(["u_component_of_wind_10m", "v_component_of_wind_10m"])

    def speed(t):
        t = ee.Date(t)
        h = hourly.filterDate(t, t.advance(1, "day")).filter(SYNOPTIC)
        return h.map(lambda im: im.expression("sqrt(u*u + v*v)", {"u": im.select(0), "v": im.select(1)})).mean().rename("wind")

    w = pixels(ee, ee.ImageCollection.fromImages(ee.List([int(x.value // 10**6) for x in dates]).map(speed)).toBands())
    return np.concatenate([d, w[:, None]], axis=1), dates


def _retry(fn, *args, tries=5):
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as exc:
            if i == tries - 1:
                raise
            log(f"  {fn.__name__}{args[1:]} retry {i + 1}: {str(exc)[:120]}")
            __import__("time").sleep(60 * (i + 1))


def build_year(ee, y, lat, lon, workers):
    dest = fw.ET0_DIR / f"et0_{y}.nc"
    today = dt.date.today()
    if dest.exists() and y < today.year - (1 if today.month <= 3 else 0):
        return
    months = [m for m in MONTHS if dt.date(y, m, 1) <= today]
    with ThreadPoolExecutor(workers) as ex:
        parts = [r for r in ex.map(lambda m: _retry(month, ee, y, m), months) if r is not None]
    if not parts:
        log(f"  {y}: no ERA5-Land days")
        return
    v = np.concatenate([p[0] for p in parts])                           # (days, 9, 210, 170)
    dates = pd.DatetimeIndex(np.concatenate([p[1] for p in parts]))
    v = v[:, :, ::-1]                                                    # north-up → ascending latitude
    tmax, tmin, tdew = v[:, 0] - 273.15, v[:, 1] - 273.15, v[:, 2] - 273.15
    rs, p_kpa = v[:, 3] / 1e6, v[:, 4] / 1000.0
    sub_lat = np.repeat(lat, 5) + np.tile((np.arange(5) - 2) * 0.05, len(lat))
    with np.errstate(invalid="ignore"):
        elev = fw.elevation_from_pressure(np.nanmean(p_kpa, axis=0))
        f32 = np.float32                                                 # keep the arithmetic in float32 (memory)
        et0 = fw.et0_fao56(tmax, tmin, tdew, fw.u2_from_u10(v[:, 8]), rs, p_kpa, sub_lat.astype(f32)[None, :, None],
                           dates.dayofyear.values.astype(f32)[:, None, None], elev.astype(f32)[None]).astype(f32)
        del tmax, tmin, tdew, rs, p_kpa
        rz = 0.07 * v[:, 5] + 0.21 * v[:, 6] + 0.72 * v[:, 7]
        cell = lambda a: np.nanmean(a.reshape(a.shape[0], len(lat), 5, len(lon), 5), axis=(2, 4)).astype(np.float32)
        ds = xr.Dataset({"ET0": (("time", "lat", "lon"), cell(et0)), "theta_rootzone": (("time", "lat", "lon"), cell(rz))},
                        coords={"time": dates, "lat": lat, "lon": lon})
    ds["ET0"].attrs.update(units="mm/day", long_name="FAO-56 Penman-Monteith reference evapotranspiration (ERA5-Land via Earth Engine)")
    ds["theta_rootzone"].attrs.update(units="m3 m-3", long_name="ERA5-Land volumetric soil water 0–100 cm (layers 1–3)")
    ds.attrs.update(source="ECMWF/ERA5_LAND/DAILY_AGGR and /HOURLY (wind speed) via Google Earth Engine; UTC days")
    fw.ET0_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    ds.to_netcdf(tmp, encoding={k: {"zlib": True, "complevel": 4} for k in ds.data_vars})
    tmp.replace(dest)
    log(f"  {y}: {len(dates)} days to {dates[-1].date()}, ET0 mean {np.nanmean(ds['ET0'].values):.2f} mm/day → {dest.name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="*", default=list(range(1993, dt.date.today().year + 1)))
    ap.add_argument("--workers", type=int, default=8, help="months fetched in parallel (high-volume endpoint)")
    ap.add_argument("--year-workers", type=int, default=2)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ee = init_ee()
    lat, lon, _ = fw.grid()
    log(f"ERA5-Land via Earth Engine → {fw.ET0_DIR}")
    with ThreadPoolExecutor(a.year_workers) as ex:
        list(ex.map(lambda y: build_year(ee, y, lat, lon, a.workers), a.years))
    log("done")


if __name__ == "__main__":
    main()
