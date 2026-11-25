#!/usr/bin/env python3
"""
fao_download_chirps_v3.py
─────────────────────────
CHIRPS v3 daily rainfall on a region's 0.25° grid (regions.py; --region, default Kenya): the platform's observed
record (CHIRPS_VERSION=v3, the default) or, with CHIRPS_VERSION=v2, the FAO water balance's own v3 files as before.

  final   CHIRPS v3 "sat" (IMERG used to split each CHIRPS3 pentad into days), 1998 – about a month ago, and "rnl"
          (ERA5 timing) before 1998, which "sat" does not cover; with CHIRPS_VERSION=v2, "rnl" for Jan–Mar and Aug–Dec
          only (OND season searched from 15 Aug, cessation to 28 Feb), as the FAO module used before the switch.
          Default source: Google Earth Engine UCSB-CHC/CHIRPS/V3/DAILY_SAT (DAILY_RNL) at 0.05°, averaged over each
          0.25° cell's land pixels (fast); --source chc reads the CHC daily/final GeoTIFFs instead (the CHC server is
          slow and blocks bursts)
  prelim  daily/prelim/sat      0.05° GeoTIFFs (IMERG timing) for the days after the final record; only the region's
          window is read over HTTP and averaged over each cell's land pixels (a coastal cell keeps its land pixels)

CHIRPS v3 daily is the pentadal CHIRPS3 total split into days with IMERG or ERA5 timing; it is not an independent
daily product. "sat" (IMERG) gives about a quarter fewer light-rain days than "rnl" (ERA5) and has the timing of the
preliminary days.

Output: v3  data/chirps_v3_daily/chirps_v3_p25_<region>_<year>.nc, every day of the year (variable "precip", mm/day;
            "source" per day); --history then writes the 1993–2025 file the scripts read (regions.Region.chirps_hist)
        v2  data/chirps_v3/chirps_v3_p25_<region>_<year>.nc (Jan–Mar, Aug–Dec)
Existing complete years are skipped; the current year is rebuilt on every run.

Usage:
  python scripts/fao_download_chirps_v3.py                # 1993 – this year
  python scripts/fao_download_chirps_v3.py --years 2026
  python scripts/fao_download_chirps_v3.py --region ethiopia_deyr
  python scripts/fao_download_chirps_v3.py --history     # 1993 – this year, then the 1993–2025 history file
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
import rasterio.errors
import xarray as xr
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
import regions  # noqa: E402

CHC = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily"
REGION = LAT = LON = BOUNDS = None                   # set by use_region: cell centres and W, S, E, N edges


def use_region(key=None):
    global REGION, LAT, LON, BOUNDS
    REGION = regions.get(key)
    LAT, LON, BOUNDS = REGION.lat, REGION.lon, REGION.bounds
    return REGION


use_region()
MONTHS_V2 = (1, 2, 3, 8, 9, 10, 11, 12)             # the FAO module's months (CHIRPS_VERSION=v2)
SOURCE = "gee"
GEE = {"sat": "UCSB-CHC/CHIRPS/V3/DAILY_SAT", "rnl": "UCSB-CHC/CHIRPS/V3/DAILY_RNL"}


def product(year):
    """The CHIRPS v3 daily final product of a year: "sat" (IMERG timing) from 1998 with CHIRPS_VERSION=v3, else "rnl"."""
    return "sat" if regions.chirps_version() == "v3" and year >= regions.V3_SAT_FROM else "rnl"


def months():
    return tuple(range(1, 13)) if regions.chirps_version() == "v3" else MONTHS_V2


def block_mean(a):
    """0.05° rows (north-up, the region's window) → (lat, lon) mean over each 0.25° cell's land pixels."""
    a = a[::-1].reshape(len(LAT), 5, len(LON), 5)
    with np.errstate(invalid="ignore"), __import__("warnings").catch_warnings():
        __import__("warnings").simplefilter("ignore", RuntimeWarning)       # all-sea cells stay NaN
        return np.nanmean(a, axis=(1, 3)).astype(np.float32)
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


def final_url(day):
    """CHC's final file of a day: "rnl" at 0.25° (p25), "sat" at 0.05° only."""
    if product(day.year) == "sat":
        return f"{CHC}/final/sat/{day.year}/chirps-v3.0.sat.{day:%Y.%m.%d}.tif"
    return f"{CHC}/final/rnl/p25/{day.year}/chirps-v3.0.rnl.{day:%Y.%m.%d}.tif"


def read_final(day):
    """The region's window of one final file → (lat, lon) mm/day ("sat": 0.05° averaged onto the cells). Only the region's
    rows are read over HTTP (the CHC server is slow, ~0.2 MB/s, but answers many small range requests in parallel);
    whole-file download as fallback."""
    url = final_url(day)
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
    a[a < 0] = np.nan
    if product(day.year) == "sat":
        return block_mean(a)
    return a[::-1]                                    # north-up rows → ascending latitude


PRELIM_WORKERS = 2                                   # the CHC server answers bursts with HTTP 429


def read_prelim(day, tries=5):
    """The region's window of one preliminary 0.05° file over HTTP, averaged 5 × 5 → (lat, lon) mm/day, or None when the
    server still refuses it after the retries. A rate-limited request (HTTP 429) comes back as an HTML page that GDAL
    cannot open, so GDAL retries it itself (GDAL_HTTP_MAX_RETRY) and the whole read is retried after a pause."""
    url = f"/vsicurl/{CHC}/prelim/sat/{day.year}/chirps-v3.0.prelim.{day:%Y.%m.%d}.tif"
    for i in range(tries):
        try:
            with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                              GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="20"):
                with rasterio.open(url) as src:
                    a = src.read(1, window=from_bounds(*BOUNDS, src.transform)).astype(np.float32)
            break
        except (rasterio.errors.RasterioIOError, rasterio.errors.WindowError) as exc:   # WindowError: not a raster (a
            if i == tries - 1:                                # proxy's or rate-limit page)
                log(f"  {day}: preliminary file not read after {tries} tries ({str(exc)[:80]})")
                return None
            __import__("time").sleep(60 * (i + 1))
    a[a < 0] = np.nan
    return block_mean(a)


def gee_final(year, want):
    """{day: (lat, lon) mm/day} for the wanted days of year from Earth Engine (the year's product, 0.05° → 0.25° mean)."""
    import fao_era5land_gee as g
    ee = g._retry(lambda _: g.init_ee(), None)          # sign-in can hit a dropped connection too
    g.set_grid(REGION.key)
    def one(_, m):                                   # (_ = placeholder: _retry logs args[1:])
        ic = ee.ImageCollection(GEE[product(year)]).filterDate(f"{year}-{m:02d}-01", ee.Date.fromYMD(year, m, 1).advance(1, "month"))
        dates = [pd.Timestamp(t, unit="ms").date() for t in ic.aggregate_array("system:time_start").getInfo()]
        if not dates:
            return {}
        a = g.pixels(ee, ic.select("precipitation").toBands())[:, ::-1]           # (days, rows, columns) ascending lat
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
    return [x.date() for x in d if x.month in months()]


def build_year(year, workers):
    dest = REGION.chirps_v3(year)
    today = dt.date.today()
    current = year >= today.year - (1 if today.month <= 3 else 0)
    if dest.exists() and not current:
        return
    want = days_of(year, today)
    prod = product(year)
    if SOURCE == "gee":
        arrs = gee_final(year, set(want))
        fin = sorted(arrs)
        src = {d: f"final {prod} (Earth Engine, 0.05° → 0.25°)" for d in fin}
    else:
        final_days = set(listing(final_url(dt.date(year, 1, 1)).rsplit("/", 1)[0] + "/"))     # file names
        fin = [d for d in want if final_url(d).rsplit("/", 1)[1] in final_days]
        with ThreadPoolExecutor(workers) as ex:
            arrs = dict(zip(fin, ex.map(read_final, fin)))
        src = {d: f"final {prod} ({'p25' if prod == 'rnl' else 'p05 → 0.25°'})" for d in fin if arrs.get(d) is not None}
    rest = [d for d in want if d not in src and (not fin or d > max(fin))]
    if rest:
        pre = set(listing(f"{CHC}/prelim/sat/{year}/"))
        rest = [d for d in rest if f"chirps-v3.0.prelim.{d:%Y.%m.%d}.tif" in pre]
        if rest:
            log(f"  {year}: {len(rest)} preliminary day(s) {rest[0]} – {rest[-1]} (0.05° window over HTTP)")
            with ThreadPoolExecutor(min(workers, PRELIM_WORKERS)) as ex:
                for d, a in zip(rest, ex.map(read_prelim, rest)):
                    if a is None:                        # keep the record contiguous: stop at the first day missed
                        log(f"  {year}: preliminary days from {d} left for the next run")
                        break
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
    ds.attrs.update(source=f"CHIRPS v3.0 daily (final {prod}; prelim sat; 0.05° averaged over each 0.25° cell's land "
                           f"pixels)", url=CHC)
    dest.parent.mkdir(parents=True, exist_ok=True)
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
    ap.add_argument("--history", action="store_true",
                    help="then write the history file (regions.HIST_YEARS) from the year files (CHIRPS_VERSION=v3)")
    regions.add_argument(ap)
    a = ap.parse_args()
    use_region(regions.activate(a.region).key)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    global SOURCE
    SOURCE = a.source
    log(f"CHIRPS v3 ({a.source}, {REGION.key}, CHIRPS_VERSION={regions.chirps_version()}) → {REGION.chirps_v3(a.years[0]).parent}")
    for y in a.years:
        try:
            build_year(y, a.workers)
        except Refused:
            log(f"CHC server refused access (HTTP 403) at {y}; stopping — re-run later (existing years are kept)")
            sys.exit(2)
    if a.history:
        write_history()
    log("CHIRPS v3 done")


def write_history():
    """The 1993–2025 file (regions.Region.chirps_hist) from the year files: one (time, lat, lon) record, as the v2 one."""
    if regions.chirps_version() != "v3":
        raise SystemExit("--history writes the CHIRPS v3 history; CHIRPS_VERSION is v2")
    y0, y1 = regions.HIST_YEARS
    files = [REGION.chirps_daily(y) for y in range(y0, y1 + 1)]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"history: year files missing: {', '.join(missing)}")
    parts = []
    for f in files:
        with xr.open_dataset(f) as ds:
            n = pd.Timestamp(f"{ds.time.dt.year.values[0]}-12-31").dayofyear
            if ds.sizes["time"] != n:
                raise SystemExit(f"history: {f.name} has {ds.sizes['time']} of {n} days")
            parts.append(ds[["precip", "source"]].load())
    h = xr.concat(parts, "time")
    h.attrs.update(source=f"CHIRPS v3.0 daily: final rnl {y0}–{regions.V3_SAT_FROM - 1}, final sat {regions.V3_SAT_FROM}–{y1} "
                          f"(fao_download_chirps_v3.py --history)", url=CHC)
    dest = REGION.chirps_hist
    tmp = dest.with_suffix(".part")
    h.to_netcdf(tmp, encoding={"precip": {"zlib": True, "complevel": 4}})
    os.replace(tmp, dest)
    log(f"history: {h.sizes['time']} days {y0}–{y1} → {dest.name}")


if __name__ == "__main__":
    main()
