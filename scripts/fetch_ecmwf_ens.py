#!/usr/bin/env python3
"""
fetch_ecmwf_ens.py
──────────────────
Download the latest ECMWF IFS ensemble (ENS, 50 perturbed members, 0.25°) total precipitation
from ECMWF Open Data (https://data.ecmwf.int/forecasts, CC-BY-4.0) for the Kenya box and save
daily accumulations (mm/day) for days 1–15 on the project's 0.25° Kenya target grid.

Only the tp messages at 24-h steps are fetched (HTTP range requests via the .index files),
so a run is ~0.5 GB instead of the full ensemble.

Output: data/ecmwf_ens/ens_tp_<YYYYMMDD><HH>_kenya.nc  (precip: member, time, lat, lon)
        time = valid date of each 24-h accumulation (00–24 UTC on that date)

Usage:
  python scripts/fetch_ecmwf_ens.py                 # latest available 00z run
  python scripts/fetch_ecmwf_ens.py --date 20261025 --run 00
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "ecmwf_ens"
ROOT = "https://data.ecmwf.int/forecasts"
STEPS = list(range(24, 361, 24))                        # 15 daily accumulations
TARGET_LAT = np.round(np.arange(-4.875, 5.375 + 0.001, 0.25), 3)
TARGET_LON = np.round(np.arange(33.625, 41.875 + 0.001, 0.25), 3)


def _get(url, headers=None, tries=10):
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code in (200, 206):
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"failed to fetch {url}")


def _run_base(date, run):
    return f"{ROOT}/{date}/{run}z/ifs/0p25/enfo/{date}{run}0000"


def latest_run(run="00"):
    """Most recent date whose 360h ENS index exists."""
    today = dt.datetime.utcnow().date()
    for back in range(0, 4):
        d = (today - dt.timedelta(days=back)).strftime("%Y%m%d")
        r = _get(f"{_run_base(d, run)}-360h-enfo-ef.index", tries=2)
        if r is not None:
            return d
    sys.exit("no complete ENS run found in the last 4 days")


def _decode_crop(msg):
    import eccodes
    h = eccodes.codes_new_from_message(msg)
    try:
        ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
        lat0, lat1 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
        lon0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
        dlon = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
        vals = eccodes.codes_get_values(h).reshape(nj, ni)
    finally:
        eccodes.codes_release(h)
    lats = np.linspace(lat0, lat1, nj)
    lons = (lon0 + dlon * np.arange(ni) + 180.0) % 360.0 - 180.0
    da = xr.DataArray(vals, dims=("lat", "lon"), coords={"lat": lats, "lon": lons}).sortby("lat").sortby("lon")
    da = da.sel(lat=slice(-6, 6.5), lon=slice(32.5, 43))
    # 0.25° source points sit on x.00/x.25; target centres on x.125/x.375 → bilinear
    return da.interp(lat=TARGET_LAT, lon=TARGET_LON).values.astype(np.float32)


def fetch(date, run="00", workers=4):
    out = OUT_DIR / f"ens_tp_{date}{run}_kenya.nc"
    if out.exists():
        print(f"ENS {date} {run}z already downloaded: {out}")
        return out
    base = _run_base(date, run)
    jobs = []
    for step in STEPS:
        idx = _get(f"{base}-{step}h-enfo-ef.index")
        if idx is None:
            sys.exit(f"index missing for step {step}h")
        for line in idx.text.splitlines():
            e = json.loads(line)
            if e.get("param") == "tp":
                jobs.append((step, int(e["number"]), f"{base}-{step}h-enfo-ef.grib2", int(e["_offset"]), int(e["_length"])))
    members = sorted({j[1] for j in jobs})
    cum = np.full((len(members), len(STEPS), len(TARGET_LAT), len(TARGET_LON)), np.nan, np.float32)
    m_ix = {m: i for i, m in enumerate(members)}
    s_ix = {s: i for i, s in enumerate(STEPS)}

    def work(j):
        step, num, url, off, ln = j
        r = _get(url, headers={"Range": f"bytes={off}-{off + ln - 1}"})
        if r is None or len(r.content) != ln:
            raise RuntimeError(f"bad range response {url} {off}")
        return step, num, r.content

    print(f"ENS {date} {run}z: {len(jobs)} tp messages ({sum(j[4] for j in jobs) / 1e6:.0f} MB), {len(members)} members")
    done = 0
    # downloads run in threads; ecCodes is not thread-safe, so decoding stays on this thread
    with cf.ThreadPoolExecutor(workers) as ex:
        for step, num, msg in ex.map(work, jobs):
            cum[m_ix[num], s_ix[step]] = _decode_crop(msg)
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)

    daily = np.diff(cum, axis=1, prepend=0.0) * 1000.0      # m accumulated → mm/day
    daily[daily < 0] = 0.0
    init = pd.Timestamp(f"{date} {run}:00")
    times = pd.date_range(init.normalize(), periods=len(STEPS), freq="D")
    ds = xr.Dataset({"precip": (("member", "time", "lat", "lon"), daily)},
                    coords={"member": members, "time": times, "lat": TARGET_LAT, "lon": TARGET_LON},
                    attrs={"source": "ECMWF IFS ENS open data (CC-BY-4.0), tp 24-h accumulations, bilinear to 0.25 deg Kenya grid",
                           "init": f"{date}{run}", "bias_correction": "none"})
    ds["precip"].attrs["units"] = "mm/day"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out)
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYYMMDD (default: latest complete run)")
    ap.add_argument("--run", default="00", choices=["00", "12"])
    a = ap.parse_args()
    fetch(a.date or latest_run(a.run), a.run)
