"""
pipeline/downloader.py
──────────────────────
Automated Copernicus CDS seasonal forecast downloader.
Fetches ECMWF SEAS5 51-member operational ensemble for the configured
country bounding box, initialization date, and lead-time window.
"""

import os
import sys
import glob
from pathlib import Path
from typing import Optional
import xarray as xr

from pipeline.config import SeasonConfig

def download_forecast(
    cfg: SeasonConfig,
    year: int,
    force: bool = False,
    dry_run: bool = False,
) -> Path:
    """
    Download ECMWF SEAS5 operational ensemble forecast from Copernicus CDS.
    Returns path to the downloaded/verified NetCDF file.
    """
    cfg.raw_download_dir.mkdir(parents=True, exist_ok=True)
    target_filename = f"ecmwf_{year}{cfg.init_month:02d}_d01.nc"
    target_path = cfg.raw_download_dir / target_filename

    if target_path.exists() and not force:
        print(f"  [Downloader] File already exists: {target_path} ({target_path.stat().st_size / 1e6:.1f} MB)")
        # Verify NetCDF integrity
        try:
            with xr.open_dataset(target_path) as ds:
                n_mem = len(ds.number)
                n_fp = len(ds.forecast_period)
                print(f"  [Downloader] Verified existing file: {n_mem} members, {n_fp} lead steps.")
                return target_path
        except Exception as e:
            print(f"  [Downloader] Existing file is corrupted ({e}). Re-downloading...")

    if dry_run:
        print(f"  [Downloader] [DRY RUN] Would request CDS for {cfg.operational_model} {year}-{cfg.init_month:02d}-01")
        print(f"               BBox: {cfg.bbox} -> {target_path}")
        return target_path

    # Formulate CDS request
    import cdsapi
    c = cdsapi.Client()

    north, west, south, east = cfg.bbox
    # Lead time in hours (24h daily steps up to lead_end_day + 10 days)
    max_days = max(cfg.lead_end_day + 15, 125)
    leadtime_hours = [str(h) for h in range(24, max_days * 24 + 1, 24)]

    request_params = {
        "originating_centre": "ecmwf",
        "system": cfg.operational_system,
        "variable": ["total_precipitation"],
        "year": str(year),
        "month": f"{cfg.init_month:02d}",
        "day": f"{cfg.init_day:02d}",
        "leadtime_hour": leadtime_hours,
        "area": [north, west, south, east],
        "format": "netcdf",
    }

    print(f"  [Downloader] Submitting Copernicus CDS request for {cfg.operational_model} (System {cfg.operational_system})...")
    print(f"               Year: {year}, Month: {cfg.init_month:02d}, Area: {cfg.bbox}")
    print(f"               Destination: {target_path}")

    c.retrieve("seasonal-original-single-levels", request_params, str(target_path))

    if not target_path.exists() or target_path.stat().st_size == 0:
        raise RuntimeError(f"CDS download failed or resulted in empty file: {target_path}")

    with xr.open_dataset(target_path) as ds:
        print(f"  [Downloader] Successfully downloaded and verified: {len(ds.number)} members, {len(ds.forecast_period)} lead days.")

    return target_path

def check_hindcasts_availability(cfg: SeasonConfig, cal_years: range = range(1993, 2017)) -> list[int]:
    """Check which historical hindcast years (1993-2016) exist locally."""
    available = []
    missing = []
    for y in cal_years:
        f = cfg.raw_download_dir / f"ecmwf_{y}{cfg.init_month:02d}_d01.nc"
        if f.exists() and f.stat().st_size > 10000:
            available.append(y)
        else:
            missing.append(y)
    return missing
