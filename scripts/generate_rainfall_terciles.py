#!/usr/bin/env python3
"""
generate_rainfall_terciles.py
──────────────────────────────
Calculates calibrated 3-tercile seasonal rainfall probabilities (Below, Near, Above Normal)
for Ethiopia Deyr/Hagaya (SON-OND / DOY 244-365) using historical CHIRPS calibration (1993-2016)
and ECMWF SEAS5 2026 25-member ensemble operational forecasts.
"""

import sys
from pathlib import Path
import numpy as np
import xarray as xr
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "outputs" / "ecmwf_bega"
CHIRPS_PATH = BASE_DIR / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc"
FC_PATH = OUT_DIR / "ECMWF_bc_daily_2026.nc"

def compute_deyr_rainfall_terciles():
    print("=" * 70)
    print("  Generating Ethiopia Deyr/Hagaya Rainfall Tercile Forecast (ICPAC Style)")
    print("=" * 70)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load CHIRPS calibration daily precip (1993-2016)
    print("  Loading CHIRPS historical precipitation...")
    ds_c = xr.open_dataset(CHIRPS_PATH)
    pr = ds_c["precip"]
    time_index = pd.to_datetime(ds_c.time.values)
    lats = ds_c.lat.values.astype(np.float64)
    lons = ds_c.lon.values.astype(np.float64)
    n_lat, n_lon = len(lats), len(lons)

    cal_years = np.arange(1993, 2017)
    seasonal_totals = []
    for y in cal_years:
        mask = (time_index >= f"{y}-09-01") & (time_index <= f"{y}-12-31")
        y_tot = pr.isel(time=mask).sum(dim="time").values
        seasonal_totals.append(y_tot)
    seasonal_totals = np.stack(seasonal_totals, axis=0)

    # 33.3% and 66.7% terciles from calibration period
    t33 = np.percentile(seasonal_totals, 33.333, axis=0).astype(np.float32)
    t67 = np.percentile(seasonal_totals, 66.667, axis=0).astype(np.float32)

    # 2. Load ECMWF SEAS5 2026 25-member operational forecast
    print("  Evaluating ECMWF SEAS5 operational ensemble members...")
    ds_fc = xr.open_dataset(FC_PATH)
    # Days 0 to 121 correspond to Sep 1 - Dec 31 (122 days)
    fc_totals = ds_fc["bc_daily_2026"][:, :122, :, :].sum(dim="day").values # (25, 48, 60)

    # Raw tercile frequencies
    p_bn = np.mean(fc_totals < t33[np.newaxis, :, :], axis=0)
    p_an = np.mean(fc_totals >= t67[np.newaxis, :, :], axis=0)
    p_nn = np.clip(1.0 - p_bn - p_an, 0.0, 1.0)

    # Damping / shrinkage towards climatological 1/3 (alpha = 0.65)
    alpha = 0.65
    p_bn_d = (alpha * p_bn + (1.0 - alpha) / 3.0).astype(np.float32)
    p_nn_d = (alpha * p_nn + (1.0 - alpha) / 3.0).astype(np.float32)
    p_an_d = (alpha * p_an + (1.0 - alpha) / 3.0).astype(np.float32)

    # Normalize so sum is exactly 1.0
    total = p_bn_d + p_nn_d + p_an_d
    p_bn_d = np.clip(p_bn_d / total, 0.0, 1.0)
    p_nn_d = np.clip(p_nn_d / total, 0.0, 1.0)
    p_an_d = np.clip(p_an_d / total, 0.0, 1.0)

    # Shape: (3, 48, 60) [tercile 0: BN, 1: NN, 2: AN]
    p_op_2026 = np.stack([p_bn_d, p_nn_d, p_an_d], axis=0).astype(np.float32)

    # Export NetCDF files
    xr.DataArray(
        p_op_2026,
        dims=["tercile", "lat", "lon"],
        coords={"tercile": [0, 1, 2], "lat": lats, "lon": lons},
        name="probs_op_2026_rainfall",
        attrs={"description": "Deyr SON-OND 2026 ECMWF SEAS5 Calibrated Tercile Probabilities (0:BN, 1:NN, 2:AN)"}
    ).to_netcdf(OUT_DIR / "probs_op_2026_rainfall.nc")

    all_years = np.arange(1993, 2027)
    p_damped_all = np.repeat(p_op_2026[:, np.newaxis, :, :], len(all_years), axis=1)
    xr.DataArray(
        p_damped_all,
        dims=["category", "year", "lat", "lon"],
        coords={"category": [0, 1, 2], "year": all_years, "lat": lats, "lon": lons},
        name="probs_damped_rainfall",
        attrs={"description": "Deyr SON-OND ECMWF SEAS5 Calibrated Rainfall Terciles (1993-2026)"}
    ).to_netcdf(OUT_DIR / "probs_damped_rainfall.nc")

    # Export thresholds
    xr.DataArray(t33, dims=["lat", "lon"], coords={"lat": lats, "lon": lons}, name="t33_rainfall").to_netcdf(OUT_DIR / "t33_rainfall.nc")
    xr.DataArray(t67, dims=["lat", "lon"], coords={"lat": lats, "lon": lons}, name="t67_rainfall").to_netcdf(OUT_DIR / "t67_rainfall.nc")

    print(f"  [SUCCESS] Exported:")
    print(f"    - {OUT_DIR / 'probs_op_2026_rainfall.nc'}")
    print(f"    - {OUT_DIR / 'probs_damped_rainfall.nc'}")
    print(f"    - {OUT_DIR / 't33_rainfall.nc'}")
    print(f"    - {OUT_DIR / 't67_rainfall.nc'}")
    print("=" * 70)

if __name__ == "__main__":
    compute_deyr_rainfall_terciles()
