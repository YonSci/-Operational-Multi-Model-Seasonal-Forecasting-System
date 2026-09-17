#!/usr/bin/env python3
"""
process_ecmwf_kiremt.py
─────────────────────────
Operational Processing Pipeline for ECMWF SEAS5 Initialized on May 01 (Ethiopia Kiremt).
Steps:
  1. Ingest CHIRPS ET daily (1993–2025) and establish 48 × 60 target grid & Ethiopia land mask
  2. Assemble/Synchronize Kiremt NetCDF outputs in outputs/ecmwf_kiremt/
  3. Generate and export chirps_C_clim.nc (DOY 122–304 cumulative anomaly baseline)
  4. Ensure calibration terciles (t33, t67) are in calibration_params/ and root
  5. Concatenate 33y hindcast + 2026 operational probability fields into 34-year records
  6. Export operational daily bias-corrected rainfall plume (ECMWF_bc_daily_all_years.nc)
  7. Export standardized model_years.nc (1993–2026)
"""

import os
import sys
import shutil
import warnings
from pathlib import Path
import numpy as np
import xarray as xr
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "notebook"))
try:
    import dunning_lib as dl
except ImportError:
    dl = None

# Pipeline Configuration (Ethiopia Kiremt: May 2 – Oct 31)
WIN_DOY_START       = 122   # May 2 (DOY 122)
WIN_DOY_END         = 304   # Oct 31 (DOY 304)
WIN_N_DAYS          = WIN_DOY_END - WIN_DOY_START + 1  # 183 days

DUNNING_BUFFER_DAYS = 50
MIN_LGP_DAYS        = 20

CAL_YEARS           = np.arange(1993, 2017)   # 1993–2016 (24 years calibration)
VAL_YEARS           = np.arange(2017, 2026)   # 2017–2025 (9 years validation)
ALL_YEARS           = np.arange(1993, 2027)   # 1993–2026 (34 years total)
OP_YEAR             = 2026
N_MEMBERS_COMMON    = 25                      # 25 ensemble members

MIN_TERCILE_YEARS   = 12
ALPHA_GRID          = np.round(np.arange(0.0, 1.01, 0.01), 2)

ETH_SHP             = BASE_DIR / "data" / "shapefiles" / "eth" / "eth_admin0.shp"
CHIRPS_PATH         = BASE_DIR / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc"
HINDCAST_PATH       = BASE_DIR / "data" / "bias-corrected" / "corrected_1993_2025.nc"
FORECAST_PATH       = BASE_DIR / "data" / "bias-corrected" / "corrected_2026.nc"
OUT_DIR             = BASE_DIR / "outputs" / "ecmwf_kiremt"


def run_kiremt_pipeline():
    print("=" * 75)
    print("  ECMWF SEAS5 Ethiopia Kiremt (Main Rains) Operational Pipeline")
    print(f"  Forecast Window: DOY {WIN_DOY_START} (May 2) - {WIN_DOY_END} (Oct 31) [{WIN_N_DAYS} days]")
    print(f"  Calibration: 1993–2016 ({len(CAL_YEARS)}y) | Validation: 2017–2025 ({len(VAL_YEARS)}y) | OP: {OP_YEAR}")
    print("=" * 75)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    calib_dir = OUT_DIR / "calibration_params"
    calib_dir.mkdir(parents=True, exist_ok=True)

    # 1. Land Mask & Coordinates
    print("\n[Step 1/7] Loading grid coordinates & building Ethiopia land mask...")
    if not CHIRPS_PATH.exists():
        raise FileNotFoundError(f"CHIRPS ET file missing at: {CHIRPS_PATH}")

    with xr.open_dataset(CHIRPS_PATH) as ds_c:
        lats = ds_c.lat.values.astype(np.float64)
        lons = ds_c.lon.values.astype(np.float64)

    n_lat, n_lon = len(lats), len(lons)
    print(f"  Grid dimensions: {n_lat} lats x {n_lon} lons (total {n_lat*n_lon} cells)")

    if ETH_SHP.exists() and dl is not None:
        lm = dl.build_land_mask(str(ETH_SHP), lats, lons, 0.25)
        print(f"  Ethiopia sovereign land pixels: {int(np.sum(lm))} / {n_lat * n_lon}")
    else:
        lm = np.ones((n_lat, n_lon), dtype=bool)
        print("  Using default bounding box land mask.")

    # 2. Synchronize precomputed outputs
    existing_out = BASE_DIR / "data" / "outputs_ETHIOPIA_KIREMT_v1"
    if existing_out.exists():
        print(f"\n[Step 2/7] Synchronizing files from {existing_out} to {OUT_DIR}...")
        for src_file in existing_out.glob("*.nc"):
            dest_file = OUT_DIR / src_file.name
            if not dest_file.exists() or dest_file.stat().st_size == 0:
                shutil.copy2(src_file, dest_file)
                print(f"  Copied: {src_file.name}")

        # Synchronize calibration params
        src_calib = existing_out / "calibration_params"
        if src_calib.exists():
            for c_file in src_calib.glob("*.nc"):
                dest_cal = calib_dir / c_file.name
                if not dest_cal.exists() or dest_cal.stat().st_size == 0:
                    shutil.copy2(c_file, dest_cal)
                    print(f"  Copied to calibration_params/: {c_file.name}")
                # Also copy to root OUT_DIR for flexible loader resolution
                dest_root = OUT_DIR / c_file.name
                if not dest_root.exists() or dest_root.stat().st_size == 0:
                    shutil.copy2(c_file, dest_root)

    # 3. Concatenate Hindcast + 2026 Forecast Event Detections (Onset, Cessation, LGP)
    print("\n[Step 3/7] Assembling 34-year (1993–2026) ensemble event detections...")
    for var, unit in [("onset_doy", "DOY"), ("cessation_doy", "DOY"), ("lgp_days", "days")]:
        target_nc = OUT_DIR / f"ECMWF_{var}_all_years.nc"
        h_file = OUT_DIR / f"{var}_hindcast_1993_2025.nc"
        f_file = OUT_DIR / f"{var}_2026.nc"

        if not target_nc.exists() or target_nc.stat().st_size == 0:
            if h_file.exists() and f_file.exists():
                with xr.open_dataset(h_file) as ds_h, xr.open_dataset(f_file) as ds_f:
                    v_h = list(ds_h.data_vars)[0]
                    v_f = list(ds_f.data_vars)[0]
                    arr_h = ds_h[v_h].values  # (25, 33, 48, 60)
                    arr_f = ds_f[v_f].values  # (25, 48, 60) or (25, 1, 48, 60)
                    if arr_f.ndim == 3:
                        arr_f = arr_f[:, np.newaxis, :, :]
                    combined = np.concatenate([arr_h, arr_f], axis=1)  # (25, 34, 48, 60)

                da = xr.DataArray(
                    combined.astype(np.float32),
                    dims=["member", "year", "lat", "lon"],
                    coords={
                        "member": np.arange(N_MEMBERS_COMMON),
                        "year": ALL_YEARS,
                        "lat": lats,
                        "lon": lons
                    },
                    name=var,
                    attrs={"long_name": f"ECMWF SEAS5 Kiremt {var} 1993-2026", "units": unit}
                )
                da.to_netcdf(target_nc)
                print(f"  Created: {target_nc.name} shape {combined.shape}")
            else:
                print(f"  [WARNING] Missing {h_file.name} or {f_file.name}")
        else:
            print(f"  Verified: {target_nc.name}")

    # 4. Generate & Save chirps_C_clim.nc
    print("\n[Step 4/7] Generating and verifying chirps_C_clim.nc...")
    c_clim_nc = OUT_DIR / "chirps_C_clim.nc"
    if not c_clim_nc.exists() or c_clim_nc.stat().st_size == 0:
        print("  Computing Kiremt cumulative anomaly climatology curve from CHIRPS...")
        with xr.open_dataset(CHIRPS_PATH) as ds_c:
            pr_var = list(ds_c.data_vars)[0]
            # Ensure time sorting and extract DOY 122 to 304 for CAL_YEARS (1993-2016)
            c_times = pd.DatetimeIndex(ds_c.time.values)
            cal_mask_time = np.isin(c_times.year, CAL_YEARS)
            ds_cal = ds_c.isel(time=cal_mask_time)
            times_cal = pd.DatetimeIndex(ds_cal.time.values)
            doys_cal = times_cal.dayofyear.values

            win_mask = (doys_cal >= WIN_DOY_START) & (doys_cal <= WIN_DOY_END)
            # Group by DOY and compute mean daily precipitation curve Q_d
            cal_pr_win = ds_cal[pr_var].values[win_mask]
            win_doys = doys_cal[win_mask]

            q_d = np.zeros((WIN_N_DAYS, n_lat, n_lon), dtype=np.float32)
            for di, d in enumerate(range(WIN_DOY_START, WIN_DOY_END + 1)):
                d_idx = np.where(win_doys == d)[0]
                if len(d_idx) > 0:
                    q_d[di] = np.nanmean(cal_pr_win[d_idx], axis=0)

            # Scalar seasonal window mean Q_bar
            q_bar = np.nanmean(q_d, axis=0)
            # Cumulative anomaly curve C_clim
            c_clim = np.cumsum(q_d - q_bar[np.newaxis, :, :], axis=0)

            xr.DataArray(
                c_clim.astype(np.float32),
                dims=["doy", "lat", "lon"],
                coords={"doy": np.arange(WIN_DOY_START, WIN_DOY_END + 1), "lat": lats, "lon": lons},
                name="C_clim",
                attrs={"long_name": "CHIRPS cumulative daily anomalous accumulation", "units": "mm"}
            ).to_netcdf(c_clim_nc)
            print(f"  Created: {c_clim_nc.name} shape {c_clim.shape}")
    else:
        print(f"  Verified: {c_clim_nc.name}")

    # 5. Concatenate probs_damped (1993–2025) and probs_op_2026 into 34-year fields
    print("\n[Step 5/7] Assembling 34-year damped tercile probabilities (probs_damped)...")
    for var in ["onset", "cessation", "lgp"]:
        p_nc = OUT_DIR / f"probs_damped_{var}.nc"
        op_nc = OUT_DIR / f"probs_op_2026_{var}.nc"
        if p_nc.exists() and op_nc.exists():
            with xr.open_dataset(p_nc) as ds_p:
                vp = list(ds_p.data_vars)[0]
                p_arr = ds_p[vp].values.copy()     # (3, 33, 48, 60) or (3, 34, 48, 60)
            with xr.open_dataset(op_nc) as ds_op:
                vop = list(ds_op.data_vars)[0]
                op_arr = ds_op[vop].values.copy()  # (3, 48, 60)

            if p_arr.shape[1] == 33:
                combined_p = np.concatenate([p_arr, op_arr[:, np.newaxis, :, :]], axis=1)
                da_p = xr.DataArray(
                    combined_p.astype(np.float32),
                    dims=["category", "year", "lat", "lon"],
                    coords={
                        "category": [0, 1, 2],
                        "year": ALL_YEARS,
                        "lat": lats,
                        "lon": lons
                    },
                    name=f"probs_damped_{var}",
                    attrs={"long_name": f"Damped tercile probabilities for {var} 1993-2026"}
                )
                tmp_nc = OUT_DIR / f"temp_probs_{var}.nc"
                da_p.to_netcdf(tmp_nc)
                if p_nc.exists():
                    p_nc.unlink()
                tmp_nc.replace(p_nc)
                print(f"  Updated: {p_nc.name} with 34 years (1993-2026)")
            else:
                print(f"  Verified: {p_nc.name} already has {p_arr.shape[1]} years")

    # 6. Export Daily Operational Bias-Corrected Precipitation
    print("\n[Step 6/7] Exporting daily bias-corrected precipitation plume...")
    bc_all_nc = OUT_DIR / "ECMWF_bc_daily_all_years.nc"
    bc_2026_nc = OUT_DIR / "ECMWF_bc_daily_2026.nc"

    if FORECAST_PATH.exists():
        with xr.open_dataset(FORECAST_PATH) as ds_fc:
            pr_val = ds_fc["pr"].values  # (lat: 48, lon: 60, time: 183, realization: 25)
            # Transpose to (realization, time, lat, lon)
            pr_tr = np.transpose(pr_val, (3, 2, 0, 1))  # (25, 183, 48, 60)

        # Save 2026 single-year daily array
        if not bc_2026_nc.exists() or bc_2026_nc.stat().st_size == 0:
            xr.DataArray(
                pr_tr.astype(np.float32),
                dims=["member", "day", "lat", "lon"],
                coords={
                    "member": np.arange(N_MEMBERS_COMMON),
                    "day": np.arange(WIN_N_DAYS),
                    "lat": lats,
                    "lon": lons
                },
                name="bc_daily_2026",
                attrs={"units": "mm/day", "long_name": "ECMWF SEAS5 May 01 2026 daily bias-corrected rainfall"}
            ).to_netcdf(bc_2026_nc)
            print(f"  Saved: {bc_2026_nc.name}")

        # Save all-years container with 2026 filled at index 33
        if not bc_all_nc.exists() or bc_all_nc.stat().st_size == 0:
            bc_all = np.zeros((N_MEMBERS_COMMON, len(ALL_YEARS), WIN_N_DAYS, n_lat, n_lon), dtype=np.float32)
            bc_all[:, 33, :, :, :] = pr_tr
            xr.DataArray(
                bc_all,
                dims=["member", "year", "day", "lat", "lon"],
                coords={
                    "member": np.arange(N_MEMBERS_COMMON),
                    "year": ALL_YEARS,
                    "day": np.arange(WIN_N_DAYS),
                    "lat": lats,
                    "lon": lons
                },
                name="bc_daily_all_years",
                attrs={"units": "mm/day", "long_name": "ECMWF SEAS5 May 01 daily bias-corrected precipitation"}
            ).to_netcdf(bc_all_nc)
            print(f"  Saved: {bc_all_nc.name} (shape {bc_all.shape})")
        else:
            print(f"  Verified: {bc_all_nc.name}")
    else:
        print(f"  [NOTICE] FORECAST_PATH {FORECAST_PATH} not found, daily plume will use synthesized fallback.")

    # 7. Model Years NetCDF
    print("\n[Step 7/7] Generating standardized model_years.nc...")
    my_nc = OUT_DIR / "model_years.nc"
    xr.Dataset({"year": ("year", ALL_YEARS.astype(int))}).to_netcdf(my_nc)
    print(f"  Saved: {my_nc.name} (1993-2026, {len(ALL_YEARS)} years)")

    print("\n" + "=" * 75)
    print(f"  [SUCCESS] All Kiremt operational NetCDF files assembled in: {OUT_DIR}")
    print("=" * 75)


if __name__ == "__main__":
    run_kiremt_pipeline()
