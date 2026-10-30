#!/usr/bin/env python3
"""
fetch_ecmwf_extended.py
───────────────────────
ECMWF IFS extended-range (sub-seasonal) ensemble precipitation for Kenya: 46 days, 101 members, 00 UTC runs,
1.5°, from the dynamical.org archive of ECMWF's real-time product (CC-BY-4.0 + ECMWF terms of use; ECMWF releases
sub-seasonal data 48 h after the run, so the newest run is about two days old).
  https://dynamical.org/catalog/ecmwf-ifs-ens-forecast-46-day-daily-1-5-degree/

Each run is saved as daily rainfall by valid date (mm/day; the archive's lead L is the mean rate over the previous
24 h, i.e. the UTC day run date + L - 1), kept on its native 1.5° grid; blend_subseasonal.py maps it to 0.25°.
  → data/ecmwf_ext/ext_tp_<YYYYMMDD>_kenya.nc   (precip: member, time, lat, lon)

The latest run is always fetched; --days-back also fetches the runs of the previous days, which fill the days
between the last observation and the newest forecasts. Runs already on disk are skipped.
Needs: pip install icechunk pystac (zarr, xarray).

Usage:
  python scripts/fetch_ecmwf_extended.py                  # latest run + the 6 before it
  python scripts/fetch_ecmwf_extended.py --days-back 0    # latest run only
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "ecmwf_ext"
COLLECTION = "ecmwf-ifs-ens-forecast-46-day-daily-1-5-degree"
BOX = dict(s=-7.5, n=7.5, w=31.5, e=43.5)        # Kenya target grid plus one 1.5° cell of margin


def open_archive():
    import icechunk
    import pystac
    col = pystac.Catalog.from_file("https://stac.dynamical.org/catalog.json").get_child(COLLECTION)
    repo = icechunk.Repository.open(icechunk.http_storage(col.assets["icechunk-https"].href))
    return xr.open_zarr(repo.readonly_session("main").store, chunks=None)


def fetch(ds, init):
    out = OUT_DIR / f"ext_tp_{init:%Y%m%d}_kenya.nc"
    if out.exists():
        print(f"  {out.name}: on disk")
        return out
    lat = ds.latitude.values
    lat_sl = slice(BOX["n"], BOX["s"]) if lat[0] > lat[-1] else slice(BOX["s"], BOX["n"])
    pr = ds["precipitation_surface"].sel(init_time=init, latitude=lat_sl, longitude=slice(BOX["w"], BOX["e"]))
    leads = pd.to_timedelta(pr.lead_time.values)
    keep = leads >= pd.Timedelta(days=1)                       # lead 0 has no accumulation
    vals = pr.isel(lead_time=np.where(keep)[0]).transpose("ensemble_member", "lead_time", "latitude", "longitude").values
    vals = np.clip(vals.astype(np.float32) * 86400.0, 0, None)  # kg m-2 s-1 → mm/day
    if np.isnan(vals).all():
        raise RuntimeError(f"run {init:%Y-%m-%d} has no data yet")
    times = pd.Timestamp(init).normalize() + leads[keep] - pd.Timedelta(days=1)   # valid UTC day
    da = xr.DataArray(vals, dims=("member", "time", "lat", "lon"),
                      coords={"member": pr.ensemble_member.values, "time": times,
                              "lat": pr.latitude.values, "lon": pr.longitude.values}, name="precip",
                      attrs={"units": "mm/day", "long_name": "daily precipitation (UTC day)"})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    da.to_dataset().assign_attrs(
        source="ECMWF IFS extended-range ensemble via dynamical.org (CC-BY-4.0, ECMWF terms of use)",
        init=f"{init:%Y%m%d}00", grid="1.5 deg native", bias_correction="none").to_netcdf(out)
    print(f"  {out.name}: {vals.shape[0]} members, {str(times[0])[:10]} – {str(times[-1])[:10]}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days-back", type=int, default=6, help="also fetch this many earlier daily runs (gap filling)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ds = open_archive()
    inits = pd.DatetimeIndex(ds.init_time.values)
    print(f"[ext] archive runs {inits[0]:%Y-%m-%d} – {inits[-1]:%Y-%m-%d}")
    for init in inits[-(a.days_back + 1):]:
        try:
            fetch(ds, init)
        except Exception as exc:                                   # a run still being ingested: skip it
            print(f"  {init:%Y-%m-%d}: skipped ({type(exc).__name__}: {str(exc)[:120]})")


if __name__ == "__main__":
    main()
