#!/usr/bin/env python3
"""
fao_download_era5land.py
────────────────────────
Download the ERA5-Land meteorological forcing for the FAO water-balance module (fao_water_balance.py) over Kenya:

  derived-era5-land-daily-statistics (local day, UTC+3):
    2m_temperature            daily maximum / minimum           → Tmax, Tmin (FAO-56: T = (Tmax + Tmin) / 2)
    surface_pressure          daily mean, one year (2010)       → psychrometric constant γ (pressure climatology;
                                                                   its year-to-year change is negligible for γ)
  reanalysis-era5-land (hourly), "met":
    10m_u/v_component_of_wind at 00, 06, 12, 18 UTC             → daily mean wind speed (speed per time, then mean;
                                                                   averaging the components first underestimates it)
    2m_dewpoint_temperature   at 00, 06, 12, 18 UTC             → daily mean dewpoint → actual vapour pressure ea
    surface_solar_radiation_downwards (00 UTC value used)       → daily total Rs (ERA5-Land accumulates from 00 UTC,
                                                                   so the 00 UTC value is the previous day's total)
  reanalysis-era5-land (hourly), "swvl":
    volumetric_soil_water_layer_1..3 at 00 UTC                  → soil-water initialisation and validation

Months Jan–Mar and Aug–Dec (the OND season searched from 15 Aug, cessation to 28 Feb), one year per request (the
CDS cost limits: 400 days for daily statistics, 12 000 fields for hourly). The CDS queues only a couple of
requests per dataset and user, so at most PER_DATASET requests per dataset are in flight and a "queue full"
rejection is retried after a pause. Existing files are skipped: re-run to resume, or with
--refresh-current to add the latest days (ERA5-Land runs about 5 days behind real time).

Output: data/era5land/<name>_<year>.nc   (0.1°, area 5.6N 33.4E – 5.1S 42.1E)

Usage:
  python scripts/fao_download_era5land.py                          # 1993 – this year
  python scripts/fao_download_era5land.py --years 2026 --refresh-current
"""
import argparse
import datetime as dt
import os
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cdsapi

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "era5land"
AREA = [5.6, 33.4, -5.1, 42.1]                       # N, W, S, E: the platform's Kenya grid plus one 0.1° cell
MONTHS = ["01", "02", "03", "08", "09", "10", "11", "12"]
LAG_DAYS = 6                                         # ERA5-Land availability behind today
PER_DATASET = 2                                      # requests in flight per CDS dataset
DAILY = [  # (file name, variable, statistic)
    ("t2m_max", "2m_temperature", "daily_maximum"),
    ("t2m_min", "2m_temperature", "daily_minimum"),
]
HOURLY = [  # (file name, variables, times)
    ("met", ["10m_u_component_of_wind", "10m_v_component_of_wind", "2m_dewpoint_temperature",
             "surface_solar_radiation_downwards"], ["00:00", "06:00", "12:00", "18:00"]),
    ("swvl", ["volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2", "volumetric_soil_water_layer_3"], ["00:00"]),
]
SP_YEAR = 2010
lock = threading.Lock()
slots = {"derived-era5-land-daily-statistics": threading.Semaphore(PER_DATASET),
         "reanalysis-era5-land": threading.Semaphore(PER_DATASET)}


def log(msg):
    with lock:
        print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch(dataset, request, dest):
    """Retrieve one request to dest (.nc); unpack a zip if the CDS returns one. Queue-full rejections wait and retry."""
    tmp = dest.with_suffix(".part")
    for attempt in range(300):                                    # the CDS can refuse new requests for hours when busy
        with slots[dataset]:
            try:
                cdsapi.Client(quiet=True, progress=False).retrieve(dataset, request, str(tmp))
                if zipfile.is_zipfile(tmp):
                    with zipfile.ZipFile(tmp) as z:
                        names = [n for n in z.namelist() if n.endswith(".nc")]
                        for n in names:
                            target = dest if len(names) == 1 else dest.with_name(dest.stem + "__" + Path(n).name)
                            with z.open(n) as src, open(target, "wb") as f:
                                f.write(src.read())
                        if len(names) > 1:
                            dest.write_bytes(b"")             # marker: request done, parts beside it
                    tmp.unlink()
                else:
                    os.replace(tmp, dest)
                return dest
            except Exception as exc:
                msg = str(exc)
        wait = 300 if ("queued" in msg or "400" in msg) else 60 * min(attempt + 1, 5)
        log(f"  retry {attempt + 1} {dest.name} in {wait // 60} min: {msg[:120]}")
        time.sleep(wait)
    raise RuntimeError(f"failed: {dest.name}")


def jobs(years, batch, refresh_current):
    last = dt.date.today() - dt.timedelta(days=LAG_DAYS)
    days = [f"{d:02d}" for d in range(1, 32)]
    sp = OUT / f"sp_mean_{SP_YEAR}.nc"
    if not sp.exists():
        yield ("derived-era5-land-daily-statistics",
               dict(variable="surface_pressure", year=[str(SP_YEAR)], month=MONTHS, day=days, daily_statistic="daily_mean",
                    time_zone="utc+03:00", frequency="6_hourly", area=AREA), sp)
    past = [y for y in years if y < last.year]
    groups = [past[i:i + batch] for i in range(0, len(past), batch)] + [[y] for y in years if y >= last.year]
    for g in groups:
        current = g[-1] >= last.year
        months = [m for m in MONTHS if dt.date(g[-1], int(m), 1) <= last] if current else MONTHS
        tag = f"{g[0]}" if len(g) == 1 else f"{g[0]}-{g[-1]}"
        for name, var, stat in DAILY:
            dest = OUT / f"{name}_{tag}.nc"
            if dest.exists() and not (current and refresh_current):
                continue
            yield ("derived-era5-land-daily-statistics",
                   dict(variable=var, year=[str(y) for y in g], month=months, day=days, daily_statistic=stat,
                        time_zone="utc+03:00", frequency="1_hourly", area=AREA), dest)
        for name, var, times in HOURLY:
            dest = OUT / f"{name}_{tag}.nc"
            if dest.exists() and not (current and refresh_current):
                continue
            yield ("reanalysis-era5-land",
                   dict(variable=var, year=[str(y) for y in g], month=months, day=days, time=times,
                        data_format="netcdf", download_format="unarchived", area=AREA), dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="*", default=list(range(1993, dt.date.today().year + 1)))
    ap.add_argument("--batch-years", type=int, default=1, help="years per request (CDS cost limits allow 1)")
    ap.add_argument("--refresh-current", action="store_true", help="re-download the current year's files")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    todo = list(jobs(a.years, a.batch_years, a.refresh_current))
    log(f"ERA5-Land: {len(todo)} request(s) to {OUT} (≤ {PER_DATASET} in flight per dataset)")
    done = 0
    with ThreadPoolExecutor(2 * PER_DATASET + 2) as ex:
        futs = {ex.submit(fetch, ds, req, dest): dest for ds, req, dest in todo}
        for f in as_completed(futs):
            try:
                f.result(); done += 1
                log(f"  {done}/{len(todo)} {futs[f].name} ({futs[f].stat().st_size / 1e6:.1f} MB)")
            except Exception as exc:
                log(f"  FAILED {futs[f].name}: {exc}")
    log("ERA5-Land download finished")


if __name__ == "__main__":
    main()
