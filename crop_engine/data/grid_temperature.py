"""
Daily ERA5-Land 2 m maximum and minimum temperature on the platform's 0.25° Kenya grid, for the gridded crop outlook
(crop_engine/grid.py): ECMWF/ERA5_LAND/DAILY_AGGR from Google Earth Engine, sampled on the 0.05° grid nested in the
0.25° cells and averaged 5 × 5 over land, as scripts/fao_era5land_gee.py builds the platform's ET0. The sites take
the same temperature from Open-Meteo at their point (data/era5land.py); a cell takes its area average.

Months of the crop season and of the SEAS5 corrections (Jan–Mar, Aug–Dec), UTC days:

  data/crop_engine/grid/era5land_t2m_<year>.nc   tmax, tmin (°C; time, lat, lon)

Past years are fetched once. The current year, and the previous one until April, are rebuilt when their file is more
than REFRESH_HOURS old (ERA5-Land runs about 5 days behind real time).

Usage:
  python -m crop_engine.data.grid_temperature                  # 1993 – this year
  python -m crop_engine.data.grid_temperature --years 2026
"""
import argparse
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C

import fao_water_balance as fw  # noqa: E402  (scripts/, on sys.path via config)

DIR = C.CACHE / "grid"
MONTHS = (1, 2, 3, 8, 9, 10, 11, 12)
BANDS = ["temperature_2m_max", "temperature_2m_min"]
FIRST_YEAR = 1993
REFRESH_HOURS = 20


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] grid temperature: {m}", flush=True)


def path(year):
    return DIR / f"era5land_t2m_{year}.nc"


def stale(year, today=None):
    """Whether the year's file must be (re)built: missing, or still growing and older than REFRESH_HOURS."""
    today = today or dt.date.today()
    f = path(year)
    if not f.exists():
        return True
    growing = year >= today.year - (1 if today.month <= 3 else 0)
    return growing and time.time() - f.stat().st_mtime > REFRESH_HOURS * 3600


def _month(ee, gee, y, m):
    """(days, 2, 210, 170) tmax, tmin (K) of one month on the 0.05° grid, north-up, and the dates; None if no days."""
    start = ee.Date.fromYMD(y, m, 1)
    daily = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(start, start.advance(1, "month")).select(BANDS)
    n = daily.size().getInfo()
    if n == 0:
        return None
    dates = pd.to_datetime(daily.aggregate_array("system:time_start").getInfo(), unit="ms")
    return gee.pixels(ee, daily.toBands()).reshape(n, len(BANDS), 210, 170), dates


def _retry(fn, *args, tries=5):
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as exc:
            if i == tries - 1:
                raise
            log(f"{args[2:]} retry {i + 1}: {str(exc)[:120]}")
            time.sleep(60 * (i + 1))


def build_year(ee, gee, y, lat, lon, workers=4, today=None):
    today = today or dt.date.today()
    months = [m for m in MONTHS if dt.date(y, m, 1) <= today]
    with ThreadPoolExecutor(workers) as ex:
        parts = [r for r in ex.map(lambda m: _retry(_month, ee, gee, y, m), months) if r is not None]
    if not parts:
        log(f"{y}: no ERA5-Land days")
        return None
    v = np.concatenate([p[0] for p in parts])[:, :, ::-1] - 273.15                 # ascending latitude, °C
    dates = pd.DatetimeIndex(np.concatenate([p[1] for p in parts]))
    with np.errstate(invalid="ignore"):
        cell = np.nanmean(v.reshape(len(dates), 2, len(lat), 5, len(lon), 5), axis=(3, 5)).astype(np.float32)
    ds = xr.Dataset({"tmax": (("time", "lat", "lon"), cell[:, 0]), "tmin": (("time", "lat", "lon"), cell[:, 1])},
                    coords={"time": dates, "lat": lat, "lon": lon})
    for k, name in (("tmax", "maximum"), ("tmin", "minimum")):
        ds[k].attrs.update(units="degC", long_name=f"ERA5-Land daily {name} 2 m temperature, 0.25° cell mean of 0.05° samples")
    ds.attrs.update(source="ECMWF/ERA5_LAND/DAILY_AGGR via Google Earth Engine; UTC days",
                    created=dt.datetime.now().astimezone().isoformat(timespec="minutes"))
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = path(y).with_suffix(".part")
    ds.to_netcdf(tmp, encoding={k: {"zlib": True, "complevel": 4} for k in ds.data_vars})
    tmp.replace(path(y))
    log(f"{y}: {len(dates)} days to {dates[-1].date()}, tmax mean {np.nanmean(ds.tmax.values):.1f} °C → {path(y).name}")
    return path(y)


def update(years=None, workers=4, year_workers=2):
    """Fetch the missing and stale years; returns the years that could not be fetched."""
    import fao_era5land_gee as gee  # noqa: E402  (Earth Engine: imported only when fetching)
    today = dt.date.today()
    years = [y for y in (years or range(FIRST_YEAR, today.year + 1)) if stale(y, today)]
    if not years:
        return []
    ee = gee.init_ee()
    lat, lon, _ = fw.grid()
    failed = []

    def one(y):
        try:
            build_year(ee, gee, y, lat, lon, workers, today)
        except Exception as exc:                                         # the year's old file (if any) stays
            log(f"{y}: failed ({type(exc).__name__}: {str(exc)[:200]})")
            failed.append(y)
    with ThreadPoolExecutor(year_workers) as ex:
        list(ex.map(one, years))
    return failed


def cell_series(cells, years=None):
    """{cell id: DataFrame indexed by date, tmax, tmin (°C)} at the cells (objects with id, cell_lat, cell_lon) from
    the yearly files on disk (as era5land.site_temperature returns a site's series)."""
    files = [path(y) for y in (years or range(FIRST_YEAR, dt.date.today().year + 1)) if path(y).exists()]
    if not files:
        raise FileNotFoundError(f"no gridded ERA5-Land temperature in {DIR} (python -m crop_engine.data.grid_temperature)")
    la = xr.DataArray([c.cell_lat for c in cells], dims="cell")
    lo = xr.DataArray([c.cell_lon for c in cells], dims="cell")
    tx, tn, t = [], [], []
    for f in files:
        with xr.open_dataset(f) as ds:
            s = ds.sel(lat=la, lon=lo, method="nearest")
            tx.append(s.tmax.values)
            tn.append(s.tmin.values)
            t.append(pd.DatetimeIndex(ds.time.values))
    tx, tn, t = np.concatenate(tx), np.concatenate(tn), t[0].append(t[1:])
    return {c.id: pd.DataFrame({"tmax": tx[:, k], "tmin": tn[:, k]}, index=t).dropna().sort_index()
            for k, c in enumerate(cells)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="*")
    ap.add_argument("--workers", type=int, default=4, help="months fetched in parallel")
    ap.add_argument("--year-workers", type=int, default=2)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failed = update(a.years, a.workers, a.year_workers)
    log("done" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
