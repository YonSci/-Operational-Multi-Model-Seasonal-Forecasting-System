#!/usr/bin/env python3
"""
fao_download_chirps_v3.py
─────────────────────────
CHIRPS v3 daily rainfall over Kenya on the platform's 0.25° grid, for the FAO water-balance module.

  final   CHIRPS v3 "rnl" (ERA5 used to split each CHIRPS3 pentad into days), 1981 – about a month ago; Jan–Mar and
          Aug–Dec of every year are kept (OND season searched from 15 Aug, cessation to 28 Feb). Default source:
          Google Earth Engine UCSB-CHC/CHIRPS/V3/DAILY_RNL at 0.05°, averaged 5 × 5 onto the 0.25° cells (fast);
          --source chc reads the CHC daily/final/rnl/p25 GeoTIFFs instead (the CHC server is slow and blocks bursts)
  prelim  daily/prelim/sat      0.05° GeoTIFFs (IMERG timing) for the days after the final record; only the Kenya
          window is read over HTTP and averaged 5 × 5 onto the 0.25° grid

CHIRPS v3 daily is the pentadal CHIRPS3 total split into days with ERA5 (final) or IMERG (prelim) timing; it is not
an independent daily product, which suits the module's 5–10 day windows.

Output: data/chirps_v3/chirps_v3_p25_kenya_<year>.nc   (variable "precip", mm/day; attribute "source" per day)
Existing complete years are skipped; the current year is rebuilt on every run.

Usage:
  python scripts/fao_download_chirps_v3.py                # 1993 – this year
  python scripts/fao_download_chirps_v3.py --years 2026
"""
import argparse
import datetime as dt
import io
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
OUT = BASE / "data" / "chirps_v3"
CHC = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily"
LAT = np.arange(-4.875, 5.4, 0.25)                   # platform grid (cell centres), 42 × 34
LON = np.arange(33.625, 41.9, 0.25)
BOUNDS = (33.5, -5.0, 42.0, 5.5)                     # W, S, E, N edges
MONTHS = (1, 2, 3, 8, 9, 10, 11, 12)
SOURCE = "gee"
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


class Refused(RuntimeError):
    """The CHC server refused access (HTTP 403), e.g. after too many requests: stop and try again later."""


def get(url, tries=8):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "fao-wb"}), timeout=300).read()
        except Exception as exc:
            if "404" in str(exc):
                return None
            if "403" in str(exc):
                raise Refused(url) from exc
            if i == tries - 1:
                raise
            __import__("time").sleep(30 * (i + 1))          # network drop (DNS, timeouts): wait and retry
    return None


def listing(url):
    b = get(url)
    return re.findall(r'href="([^"?/]+\.tif)"', b.decode("utf-8", "replace")) if b else []


def read_final(day):
    """Kenya window of one final 0.25° file → (42, 34) mm/day. Only the 42 Kenya rows are read over HTTP (the CHC
    server is slow, ~0.2 MB/s, but answers many small range requests in parallel); whole-file download as fallback."""
    url = f"{CHC}/final/rnl/p25/{day.year}/chirps-v3.0.rnl.{day:%Y.%m.%d}.tif"
    a = None
    for _ in range(3):
        try:
            with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", CPL_VSIL_CURL_CHUNK_SIZE="65536"):
                with rasterio.open("/vsicurl/" + url) as src:
                    a = src.read(1, window=from_bounds(*BOUNDS, src.transform)).astype(np.float32)
            break
        except Exception:
            continue
    if a is None:
        b = get(url)
        if b is None:
            return None
        with MemoryFile(b) as m, m.open() as src:
            a = src.read(1, window=from_bounds(*BOUNDS, src.transform)).astype(np.float32)
    a = a[::-1]                                       # north-up rows → ascending latitude
    a[a < 0] = np.nan
    return a


def read_prelim(day):
    """Kenya window of one preliminary 0.05° file over HTTP, averaged 5 × 5 → (42, 34) mm/day."""
    url = f"/vsicurl/{CHC}/prelim/sat/{day.year}/chirps-v3.0.prelim.{day:%Y.%m.%d}.tif"
    with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES"):
        with rasterio.open(url) as src:
            a = src.read(1, window=from_bounds(*BOUNDS, src.transform)).astype(np.float32)
    a[a < 0] = np.nan
    a = a[::-1].reshape(len(LAT), 5, len(LON), 5).mean(axis=(1, 3))
    return a


def gee_final(year, want):
    """{day: (42, 34) mm/day} for the wanted days of year from Earth Engine (CHIRPS v3 rnl, 0.05° → 0.25° mean)."""
    import fao_era5land_gee as g
    ee = g._retry(lambda _: g.init_ee(), None)          # sign-in can hit a dropped connection too
    def one(_, m):                                   # (_ = placeholder: _retry logs args[1:])
        ic = ee.ImageCollection("UCSB-CHC/CHIRPS/V3/DAILY_RNL").filterDate(f"{year}-{m:02d}-01", ee.Date.fromYMD(year, m, 1).advance(1, "month"))
        dates = [pd.Timestamp(t, unit="ms").date() for t in ic.aggregate_array("system:time_start").getInfo()]
        if not dates:
            return {}
        a = g.pixels(ee, ic.select("precipitation").toBands())[:, ::-1]           # (days, 210, 170) ascending lat
        with np.errstate(invalid="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)       # all-sea cells
            a = np.nanmean(a.reshape(len(dates), len(LAT), 5, len(LON), 5), axis=(2, 4)).astype(np.float32)
        return {d: a[i] for i, d in enumerate(dates) if d in want}

    out = {}
    with ThreadPoolExecutor(4) as ex:
        for part in ex.map(lambda m: g._retry(one, None, m), sorted({d.month for d in want})):
            out.update(part)
    return out


def days_of(year, last):
    d = pd.date_range(f"{year}-01-01", min(pd.Timestamp(f"{year}-12-31"), pd.Timestamp(last)))
    return [x.date() for x in d if x.month in MONTHS]


def build_year(year, workers):
    dest = OUT / f"chirps_v3_p25_kenya_{year}.nc"
    today = dt.date.today()
    current = year >= today.year - (1 if today.month <= 3 else 0)
    if dest.exists() and not current:
        return
    want = days_of(year, today)
    if SOURCE == "gee":
        arrs = gee_final(year, set(want))
        fin = sorted(arrs)
        src = {d: "final rnl (Earth Engine, 0.05° → 0.25°)" for d in fin}
    else:
        final_days = set(listing(f"{CHC}/final/rnl/p25/{year}/"))
        fin = [d for d in want if f"chirps-v3.0.rnl.{d:%Y.%m.%d}.tif" in final_days]
        with ThreadPoolExecutor(workers) as ex:
            arrs = dict(zip(fin, ex.map(read_final, fin)))
        src = {d: "final rnl p25" for d in fin if arrs.get(d) is not None}
    rest = [d for d in want if d not in src and (not fin or d > max(fin))]
    if rest:
        pre = set(listing(f"{CHC}/prelim/sat/{year}/"))
        rest = [d for d in rest if f"chirps-v3.0.prelim.{d:%Y.%m.%d}.tif" in pre]
        if rest:
            log(f"  {year}: {len(rest)} preliminary day(s) {rest[0]} – {rest[-1]} (0.05° window over HTTP)")
            with ThreadPoolExecutor(workers) as ex:
                for d, a in zip(rest, ex.map(read_prelim, rest)):
                    arrs[d] = a; src[d] = "prelim sat p05→p25"
    days = sorted(d for d in src)
    if not days:
        log(f"  {year}: no data")
        return
    da = xr.DataArray(np.stack([arrs[d] for d in days]), dims=("time", "lat", "lon"),
                      coords={"time": pd.to_datetime(days), "lat": LAT, "lon": LON}, name="precip",
                      attrs={"units": "mm/day", "long_name": "CHIRPS v3 daily precipitation"})
    ds = da.to_dataset()
    ds["source"] = ("time", [src[d] for d in days])
    ds.attrs.update(source="CHIRPS v3.0 daily (final rnl p25; prelim sat p05 averaged to 0.25°)", url=CHC)
    tmp = dest.with_suffix(".part")
    ds.to_netcdf(tmp, encoding={"precip": {"zlib": True, "complevel": 4}})
    os.replace(tmp, dest)
    n_pre = sum(1 for d in days if src[d].startswith("prelim"))
    log(f"  {year}: {len(days)} days to {days[-1]} ({n_pre} preliminary) → {dest.name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="*", default=list(range(1993, dt.date.today().year + 1)))
    ap.add_argument("--workers", type=int, default=4, help="parallel requests (keep low: the CHC server blocks bursts)")
    ap.add_argument("--source", choices=("gee", "chc"), default="gee", help="final record from Earth Engine or the CHC server")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    global SOURCE
    SOURCE = a.source
    log(f"CHIRPS v3 ({a.source}) → {OUT}")
    for y in a.years:
        try:
            build_year(y, a.workers)
        except Refused:
            log(f"CHC server refused access (HTTP 403) at {y}; stopping — re-run later (existing years are kept)")
            sys.exit(2)
    log("CHIRPS v3 done")


if __name__ == "__main__":
    main()
