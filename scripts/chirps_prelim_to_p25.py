#!/usr/bin/env python3
"""
chirps_prelim_to_p25.py
───────────────────────
Convert CHIRPS-2.0 preliminary daily GeoTIFFs (0.05°) into a 0.25° NetCDF on the Kenya
target grid (lat -4.875..5.375, lon 33.625..41.875), by 5x5 block means — the same
aggregation CHIRPS uses for its p25 product. Output variable: precip (mm/day), dims time/lat/lon.

Usage:
  python scripts/chirps_prelim_to_p25.py data/chirps_prelim_2026 data/chirps_prelim_2026/chirps_prelim_2026_p25_kenya.nc
"""
import glob
import os
import re
import sys

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds
import xarray as xr

# Cell edges of the 0.25° target grid
S, N, W, E = -5.0, 5.5, 33.5, 42.0
FACTOR = 5


def main(tif_dir, out_path):
    # Files are kept gzipped (~2.4 MB vs ~69 MB unpacked) and read in place through GDAL's /vsigzip/
    files = sorted(glob.glob(os.path.join(tif_dir, "chirps-v2.0.*.tif.gz")))
    if not files:
        sys.exit(f"no .tif.gz files in {tif_dir}")
    days, grids = [], []
    for fp in files:
        m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\.tif\.gz$", fp)
        with rasterio.open(f"/vsigzip/{os.path.abspath(fp)}") as src:
            win = from_bounds(W, S, E, N, src.transform).round_offsets().round_lengths()
            a = src.read(1, window=win).astype(np.float32)
            if src.nodata is not None:
                a[a == src.nodata] = np.nan
        a[a < 0] = np.nan
        ny, nx = a.shape[0] // FACTOR, a.shape[1] // FACTOR
        blocks = a[: ny * FACTOR, : nx * FACTOR].reshape(ny, FACTOR, nx, FACTOR)
        with np.errstate(invalid="ignore"):
            g = np.nanmean(blocks, axis=(1, 3))[::-1]  # rows north->south -> south->north
        days.append(pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
        grids.append(g)
    lat = np.round(np.arange(S + 0.125, N, 0.25), 3)
    lon = np.round(np.arange(W + 0.125, E, 0.25), 3)
    ds = xr.Dataset({"precip": (("time", "lat", "lon"), np.stack(grids))},
                    coords={"time": days, "lat": lat, "lon": lon},
                    attrs={"source": "CHIRPS-2.0 preliminary daily p05, 5x5 block mean to 0.25 deg"})
    ds["precip"].attrs["units"] = "mm/day"
    ds.to_netcdf(out_path)
    print(f"wrote {out_path}: {len(days)} days {days[0].date()} -> {days[-1].date()}, grid {len(lat)}x{len(lon)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
