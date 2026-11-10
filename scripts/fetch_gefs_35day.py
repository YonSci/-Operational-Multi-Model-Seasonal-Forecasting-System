#!/usr/bin/env python3
"""
fetch_gefs_35day.py
───────────────────
NOAA GEFS 35-day ensemble precipitation for Kenya: 31 members (control + 30), 00 UTC runs, 0.25° (the archive keeps
the 0.5° days 11–35 on the same 0.25° grid), from the dynamical.org archive of NOAA's real-time GEFS (CC-BY-4.0).
  https://dynamical.org/catalog/noaa-gefs-forecast-35-day/

The archive's precipitation is the mean rate since the previous step (3-hourly to 240 h, 6-hourly after); each step's
rain is put on the UTC day its period starts, giving daily rain by valid date (mm/day) for days 1–35.
  → data/gefs/gefs_tp_<YYYYMMDD>_kenya.nc   (precip: member, time, lat, lon)
and the run's daily maximum and minimum temperature at the crop engine's sites (its weather for the s2s-gefs runs):
  → data/gefs/gefs_met_<YYYYMMDD>_sites.nc  (rad, vap, wind2: radiation, humidity, wind; crop_engine/data/s2s_met.py)
  → data/gefs/gefs_t2m_<YYYYMMDD>_sites.nc  (tmax, tmin: member, time, site; crop_engine/data/s2s_temperature.py)

The latest run is always fetched; --days-back also fetches the runs of the previous days. Runs already on disk are
skipped, and runs older than --keep days are deleted (the forecast-run results keep what the platform needs).
Needs: pip install icechunk pystac (zarr, xarray).

Usage:
  python scripts/fetch_gefs_35day.py                  # latest run + the 2 before it
  python scripts/fetch_gefs_35day.py --days-back 0    # latest run only
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "gefs"
COLLECTION = "noaa-gefs-forecast-35-day"
BOX = dict(s=-5.5, n=6.0, w=33.25, e=42.25)        # the Kenya 0.25° target grid plus one cell of margin


def open_archive():
    import icechunk
    import pystac
    col = pystac.Catalog.from_file("https://stac.dynamical.org/catalog.json").get_child(COLLECTION)
    repo = icechunk.Repository.open(icechunk.http_storage(col.assets["icechunk-https"].href))
    return xr.open_zarr(repo.readonly_session("main").store, chunks=None)


def fetch(ds, init):
    out = OUT_DIR / f"gefs_tp_{init:%Y%m%d}_kenya.nc"
    if out.exists():
        print(f"  {out.name}: on disk")
        return out
    lat = ds.latitude.values
    lat_sl = slice(BOX["n"], BOX["s"]) if lat[0] > lat[-1] else slice(BOX["s"], BOX["n"])
    pr = ds["precipitation_surface"].sel(init_time=init, latitude=lat_sl, longitude=slice(BOX["w"], BOX["e"]))
    rate = pr.transpose("ensemble_member", "lead_time", "latitude", "longitude").values.astype(np.float32)
    leads = pd.to_timedelta(pr.lead_time.values)
    hours = (leads / pd.Timedelta(hours=1)).astype(int).values
    n_day = int(hours[-1] // 24)
    daily = np.zeros((rate.shape[0], n_day, rate.shape[2], rate.shape[3]), np.float32)
    seen = np.zeros(n_day, int)
    for k in range(1, len(hours)):                                  # step k: mean rate over (hours[k-1], hours[k]]
        d = hours[k - 1] // 24
        if d < n_day:
            daily[:, d] += np.nan_to_num(rate[:, k]) * (hours[k] - hours[k - 1]) * 3600.0
            seen[d] += np.isfinite(rate[:, k]).all()
    # a day counts only when every step of it arrived (members still being ingested leave NaN)
    full = np.array([seen[d] == ((hours > d * 24) & (hours <= (d + 1) * 24)).sum() for d in range(n_day)])
    n_ok = int(np.argmin(full)) if not full.all() else n_day
    want = int(pd.Timedelta(pr.expected_forecast_length.values) // pd.Timedelta(days=1))
    if n_ok < want:                                             # still being ingested: fetched again on a later run
        raise RuntimeError(f"run {init:%Y-%m-%d} has {n_ok} of {want} days so far")
    daily = np.clip(daily[:, :n_ok], 0, None)
    times = pd.date_range(pd.Timestamp(init).normalize(), periods=n_ok, freq="D")
    da = xr.DataArray(daily, dims=("member", "time", "lat", "lon"),
                      coords={"member": pr.ensemble_member.values.astype(int), "time": times,
                              "lat": pr.latitude.values, "lon": pr.longitude.values}, name="precip",
                      attrs={"units": "mm/day", "long_name": "daily precipitation (UTC day)"})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    da.to_dataset().assign_attrs(
        source="NOAA GEFS 35-day ensemble via dynamical.org (CC-BY-4.0)", init=f"{init:%Y%m%d}00",
        grid="0.25 deg (days 11-35 0.5 deg native)", bias_correction="none").to_netcdf(
        out, encoding={"precip": {"zlib": True, "complevel": 4}})
    print(f"  {out.name}: {daily.shape[0]} members, {times[0]:%Y-%m-%d} – {times[-1]:%Y-%m-%d} ({n_ok} days)")
    return out


def site_temperature(source, ds, inits):
    """The runs' daily maximum and minimum temperature at the crop sites, for the crop engine's weather
    (crop_engine/data/s2s_temperature.py); a failure is printed and never stops the rain."""
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from crop_engine.data import s2s_met as s2m
        from crop_engine.data import s2s_temperature as s2t
    except Exception as exc:
        print(f"  temperature at the crop sites: skipped ({type(exc).__name__}: {str(exc)[:160]})")
        return
    s2t.fetch_runs(source, ds, inits)
    s2m.fetch_runs(source, ds, inits)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days-back", type=int, default=2, help="also fetch this many earlier daily runs")
    ap.add_argument("--keep", type=int, default=10, help="delete runs older than this many days")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ds = open_archive()
    inits = pd.DatetimeIndex(ds.init_time.values)
    print(f"[gefs] archive runs {inits[0]:%Y-%m-%d} – {inits[-1]:%Y-%m-%d}")
    for init in inits[-(a.days_back + 1):]:
        try:
            fetch(ds, init)
        except Exception as exc:                                   # a run still being ingested: skip it
            print(f"  {init:%Y-%m-%d}: skipped ({type(exc).__name__}: {str(exc)[:120]})")
    site_temperature("gefs", ds, inits[-(a.days_back + 1):])
    cut = dt.date.today() - dt.timedelta(days=a.keep)
    for p in [*OUT_DIR.glob("gefs_tp_*_kenya.nc"), *OUT_DIR.glob("gefs_t2m_*_sites.nc"), *OUT_DIR.glob("gefs_met_*_sites.nc")]:
        if dt.datetime.strptime(p.stem.split("_")[2], "%Y%m%d").date() < cut:
            p.unlink()


if __name__ == "__main__":
    main()
