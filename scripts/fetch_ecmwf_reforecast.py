#!/usr/bin/env python3
"""
fetch_ecmwf_reforecast.py
─────────────────────────
ECMWF extended-range reforecasts (hindcasts) of daily rainfall for Kenya, from the ECMWF Data Store (ECDS, dataset
"s2s-reforecasts"), for the bias correction of the extended-range forecasts in blend_subseasonal.py.

ECMWF runs the reforecasts with the current model version on fixed model-version dates (odd days in 2026), each one
started on the same day and month of the 20 previous years (2006-2025), with 1 control and 10 perturbed members to
day 46, on the same 1.5° grid as the real-time extended range. One request per model-version date fetches the
perturbed members of all hindcast years; ECDS queues requests, so each can take an hour or more.
  → data/ecmwf_s2s_reforecast/refc_tp_<YYYYMMDD>_kenya.nc   (precip: hyear, member, lead, lat, lon; mm/day;
                                                              lead L is the UTC day start date + L - 1)
Dates already on disk are skipped.

Needs: pip install cdsapi cfgrib, and an ECDS token in ~/.ecdsapirc ("url: https://ecds.ecmwf.int/api" and
"key: <token>"); the s2s-reforecasts licence must be accepted on the dataset page.

Usage:
  python scripts/fetch_ecmwf_reforecast.py                                 # the OND model-version dates
  python scripts/fetch_ecmwf_reforecast.py --dates 2026-10-29 2026-11-05
"""
import argparse
import datetime as dt
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import xarray as xr

BASE_DIR = Path(os.environ.get("PIPELINE_BASE") or Path(__file__).resolve().parent.parent)
OUT_DIR = BASE_DIR / "data" / "ecmwf_s2s_reforecast"
AREA = [7.5, 31.5, -7.5, 43.5]                     # N, W, S, E: Kenya plus one 1.5° cell, as fetch_ecmwf_extended.py
HYEARS = range(2006, 2026)
N_LEAD = 46
# about weekly through the Short Rains starts (model-version dates are odd days)
OND_DATES = ["2026-10-01", "2026-10-09", "2026-10-17", "2026-10-25", "2026-11-01", "2026-11-09",
             "2026-11-17", "2026-11-25", "2026-12-01"]


def read_ecdsapirc():
    cfg = dict(line.split(":", 1) for line in (Path.home() / ".ecdsapirc").read_text().splitlines() if ":" in line)
    return cfg["url"].strip(), cfg["key"].strip()


def fetch(client, date):
    out = OUT_DIR / f"refc_tp_{date:%Y%m%d}_kenya.nc"
    if out.exists():
        print(f"  {out.name}: on disk", flush=True)
        return out
    grib = out.with_suffix(".grib")
    d = f"{date:%d}"
    client.retrieve("s2s-reforecasts", {
        "origin": "ecmwf", "forecast_type": "perturbed_forecast", "level_type": "single_level",
        "variable": ["total_precipitation"], "year": [f"{date:%Y}"], "month": [f"{date:%m}"], "day": [d],
        "time": ["00:00"], "hyear": [str(y) for y in HYEARS], "hmonth": [f"{date:%m}"], "hday": [d],
        "leadtime_hour": [str(24 * i) for i in range(N_LEAD + 1)], "area": AREA, "data_format": "grib",
    }, str(grib))
    return grib_to_nc(grib, out, date)


def grib_to_nc(grib, out, date):
    """Accumulated rainfall (GRIB) → daily rainfall by lead (NetCDF); the GRIB is removed."""
    with xr.open_dataset(grib, engine="cfgrib", backend_kwargs={"indexpath": ""}) as ds:
        tp = ds["tp"]
        if "time" not in tp.dims:                    # a single hindcast year comes back without a time dimension
            tp = tp.expand_dims("time")
        tp = tp.transpose("time", "number", "step", "latitude", "longitude")
        acc = tp.values.astype(np.float32)           # kg m-2 accumulated from the start = mm
        hyear = tp.time.dt.year.values
        lat, lon, member = tp.latitude.values, tp.longitude.values, tp.number.values
    daily = np.clip(np.diff(acc, axis=2), 0, None)   # mm/day; lead L = UTC day start + L - 1
    da = xr.DataArray(daily, dims=("hyear", "member", "lead", "lat", "lon"),
                      coords={"hyear": hyear, "member": member, "lead": np.arange(1, daily.shape[2] + 1),
                              "lat": lat, "lon": lon}, name="precip",
                      attrs={"units": "mm/day", "model_version_date": f"{date}",
                             "source": "ECMWF extended-range reforecasts, ECMWF Data Store (s2s-reforecasts)"})
    da.to_netcdf(out, encoding={"precip": {"zlib": True, "complevel": 1}})
    grib.unlink()
    print(f"  {out.name}: {len(hyear)} years × {len(member)} members × {daily.shape[2]} days", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dates", nargs="+", default=OND_DATES, help="model-version dates (YYYY-MM-DD, odd days)")
    ap.add_argument("--parallel", type=int, default=3, help="requests queued at ECDS at once")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import cdsapi
    url, key = read_ecdsapirc()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dates = [dt.date.fromisoformat(d) for d in a.dates]
    print(f"[reforecast] {len(dates)} model-version dates, hindcast years {HYEARS.start}-{HYEARS.stop - 1}", flush=True)
    failed = []

    def one(d):
        try:
            fetch(cdsapi.Client(url=url, key=key, quiet=True), d)    # one client per thread
        except Exception as exc:                     # keep the other dates going
            failed.append(d)
            print(f"  {d}: failed ({str(exc)[:200]})", flush=True)

    with ThreadPoolExecutor(a.parallel) as pool:
        list(pool.map(one, dates))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
