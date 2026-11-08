#!/usr/bin/env python3
"""
Download the 182-day SEAS5 1 Oct runs the crop weather uses (crop_engine.data.seas5), one year per Copernicus CDS
request and one request at a time (CDS asks for sequential requests; a rejected request is retried after a pause).

  --kind temperature   daily max / min temperature and rain → seas5.DIR (data/seasonal_downloads_ke/ecmwf_oct_182d)
  --kind met           solar radiation, dewpoint, 10 m wind → seas5.MET_DIR (…/ecmwf_oct_182d_met)

The season year comes first (the outlook needs it), then the calibration years 1993–2016 farthest-first, so any first
few years spread over the period. Years already on disk are skipped. The CDS key is read from ~/.cdsapirc.
--after-pid waits for another process (e.g. a download already running) to end first.

Usage:
  python -m crop_engine.data.seas5_download --kind met
  python -m crop_engine.data.seas5_download --kind met --after-pid 12345
"""
import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

import xarray as xr

from crop_engine import config as C
from crop_engine.data import seas5 as s5

import download_seasonal_forecasts_daily_c3s as dl  # noqa: E402  (scripts/, on sys.path via config)

AREA = [5.5, 33.0, -5.5, 42.5]                    # N, W, S, E
POLL = 120                                         # s between status checks
BACKOFF = 1200                                     # s after a rejection


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] seas5 download: {m}", flush=True)


def client():
    from ecmwf.datastores import Client
    cfg = dict(line.split(":", 1) for line in (Path.home() / ".cdsapirc").read_text().splitlines() if ":" in line)
    return Client(url=cfg["url"].strip(), key=cfg["key"].strip(), timeout=60, maximum_tries=10, retry_after=60)


def order(years, have):
    """Farthest-first: each next year as far as possible from those on disk or already chosen."""
    left, out = [y for y in years if y not in have], []
    while left:
        y = max(left, key=lambda v: min([abs(v - h) for h in list(have) + out] or [99]))
        out.append(y)
        left.remove(y)
    return out


def request(year, kind):
    return dl.build_request(dl.MODEL_REGISTRY["ecmwf"], year, 10, 1, AREA, s5.VARIABLES[kind], s5.LEAD_DAYS)


def _alive(pid):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)    # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                       # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def fetch(c, year, kind):
    """One year: submit, wait, download to a .part file, check it opens, then move it into place."""
    dest = s5.path(year, kind)
    while True:
        try:
            job = c.submit("seasonal-original-single-levels", request(year, kind))
        except Exception as exc:
            log(f"{year}: submit failed ({type(exc).__name__}: {str(exc)[:100]}); retrying in {POLL} s")
            time.sleep(POLL)
            continue
        log(f"{year}: submitted {job.request_id[:8]}")
        while True:
            time.sleep(POLL)
            try:
                st = c.get_remote(job.request_id).status
            except Exception as exc:
                log(f"{year}: status unavailable ({type(exc).__name__}); retrying")
                continue
            if st == "successful":
                part = dest.with_suffix(".nc.part")
                c.get_remote(job.request_id).download(str(part))
                with xr.open_dataset(part) as ds:
                    if "forecast_reference_time" in ds.dims and ds.sizes["forecast_reference_time"] != 1:
                        raise ValueError(f"{part.name}: {ds.sizes['forecast_reference_time']} runs")
                part.replace(dest)
                log(f"{year}: saved ({dest.stat().st_size / 1e6:.1f} MB)")
                return
            if st in ("failed", "rejected", "dismissed", "deleted"):
                log(f"{year}: job {st}; resubmitting in {BACKOFF // 60} min")
                time.sleep(BACKOFF)
                break


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=list(s5.VARIABLES), default="met")
    ap.add_argument("--season-year", type=int, default=dt.date.today().year)
    ap.add_argument("--after-pid", type=int, help="wait for this process to end first")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.after_pid:
        log(f"waiting for process {a.after_pid} to end (one CDS request at a time)")
        while _alive(a.after_pid):
            time.sleep(300)
    s5.path(a.season_year, a.kind).parent.mkdir(parents=True, exist_ok=True)
    cal = list(range(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1))
    have = {y for y in cal + [a.season_year] if s5.path(y, a.kind).exists()}
    todo = ([a.season_year] if a.season_year not in have else []) + order(cal, have)
    log(f"{a.kind}: {len(have)} years on disk; to fetch in this order: {todo}")
    c = client()
    for y in todo:
        fetch(c, y, a.kind)
    log(f"{a.kind}: done; {len(s5.calibration_years(a.kind))} calibration years on disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
