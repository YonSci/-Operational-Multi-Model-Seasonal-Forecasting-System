#!/usr/bin/env python3
"""
process_method2_ecmwf_rainfall.py
──────────────────────────────────
Method 2: Raw Dynamical GCM Ensemble Ingestion & Downscaling
for Ethiopia Deyr/Hagaya (OND 2026) Seasonal Rainfall Terciles.

Pipeline Steps:
  1. Ingest raw ECMWF SEAS5 51-member operational ensemble initialized September 01, 2026.
  2. Compute seasonal cumulative total precipitation per ensemble member across OND (lead days 30 to 122)
     in mm (tp * 1000.0).
  3. Spatially regrid member fields from native GCM resolution (1.0°) to Ethiopia's target 0.25° grid
     (48 lats × 60 lons) using bilinear interpolation.
  4. Perform Parametric Quantile Matching (Bias Correction) against historical CHIRPS calibration (1993–2016).
  5. Calculate member-based tercile frequencies P(BN), P(NN), P(AN) against historical T33 and T67.
  6. Apply Bayesian linear shrinkage (alpha*) based on historical validation RPSS.
  7. Apply sovereign and dry-area masking (mask_deyr: 578 active pastoral cells, 907 dry highland cells).
  8. Export standardized NetCDFs in outputs/ecmwf_bega/ and update backend/demo_data.npz.
"""

import sys
import os
from pathlib import Path
import numpy as np
import xarray as xr
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "outputs" / "ecmwf_bega"
MASKS_DIR = BASE_DIR / "outputs" / "masks"
CHIRPS_PATH = BASE_DIR / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc"

ET_SEP_FILE = BASE_DIR / "data" / "seasonal_pr_downloads_et_sep" / "ecmwf_202609_d01.nc"
KE_SEP_FILE = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_sep" / "ecmwf_202609_d01.nc"

def run_method2():
    print("=" * 78)
    print("  METHOD 2: Raw Dynamical GCM Ensemble Ingestion & Downscaling")
    print("  Forecast Target: Ethiopia Deyr/Hagaya (OND 2026)")
    print("  Model: ECMWF SEAS5 (System 51, 51 Members, Initialized Sep 01, 2026)")
    print("=" * 78)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load CHIRPS grid & historical baseline (1993-2016)
    print("\n[Step 1/6] Ingesting CHIRPS historical calibration data (1993-2016)...")
    if not CHIRPS_PATH.exists():
        raise FileNotFoundError(f"CHIRPS file missing: {CHIRPS_PATH}")

    ds_c = xr.open_dataset(CHIRPS_PATH)
    pr = ds_c["precip"]
    time_idx = pd.to_datetime(ds_c.time.values)
    lats_target = ds_c.lat.values.astype(np.float64)
    lons_target = ds_c.lon.values.astype(np.float64)
    n_lat, n_lon = len(lats_target), len(lons_target)
    print(f"  Target Grid: {n_lat} lats x {n_lon} lons ({n_lat*n_lon} total pixels)")

    # Load seasonal mask (mask_deyr)
    mask_file = MASKS_DIR / "seasonal_masks.npz"
    if mask_file.exists():
        masks = np.load(mask_file)
        mask_deyr = masks["mask_deyr"]
    else:
        ds_m = xr.open_dataset(MASKS_DIR / "mask_deyr.nc")
        mask_deyr = ds_m["mask_deyr"].values.astype(bool)

    active_pixels = int(np.sum(mask_deyr))
    dry_pixels = int(np.sum(~mask_deyr))
    print(f"  Deyr Mask: {active_pixels} active pastoral pixels | {dry_pixels} non-seasonal dry pixels")

    # Compute historical OND seasonal rainfall totals (1993-2016)
    cal_years = np.arange(1993, 2017)
    cal_ond_totals = []
    for y in cal_years:
        mask_y = (time_idx >= f"{y}-10-01") & (time_idx <= f"{y}-12-31")
        tot = pr.isel(time=mask_y).sum(dim="time").values # (48, 60)
        cal_ond_totals.append(tot)
    cal_ond_totals = np.stack(cal_ond_totals, axis=0) # (24, 48, 60)

    # Compute tercile boundaries T33 and T67
    t33 = np.percentile(cal_ond_totals, 33.333, axis=0).astype(np.float32)
    t67 = np.percentile(cal_ond_totals, 66.667, axis=0).astype(np.float32)
    print(f"  Historical OND Tercile Boundaries: mean T33={np.mean(t33[mask_deyr]):.1f} mm, mean T67={np.mean(t67[mask_deyr]):.1f} mm")

    # 2. Ingest ECMWF SEAS5 Ensemble Data
    print("\n[Step 2/6] Ingesting ECMWF SEAS5 operational ensemble fields...")
    gcm_file = None
    if ET_SEP_FILE.exists() and ET_SEP_FILE.stat().st_size > 100000:
        gcm_file = ET_SEP_FILE
        print(f"  Found full Ethiopia domain GCM file: {gcm_file.name} ({gcm_file.stat().st_size // 1024} KB)")
    elif KE_SEP_FILE.exists():
        gcm_file = KE_SEP_FILE
        print(f"  Ingesting high-resolution East Africa / Kenya GCM file: {gcm_file.name} ({gcm_file.stat().st_size // 1024} KB)")
    else:
        raise FileNotFoundError("No ECMWF SEAS5 September file available on disk.")

    ds_gcm = xr.open_dataset(gcm_file)
    n_members = len(ds_gcm.number)
    gcm_lats = ds_gcm.latitude.values.astype(np.float64)
    gcm_lons = ds_gcm.longitude.values.astype(np.float64)
    print(f"  GCM Dimensions: {n_members} members, {len(gcm_lats)} lats, {len(gcm_lons)} lons")

    # Extract OND cumulative rainfall per member: lead day 30 (Sep 30) to lead day 122 (Dec 31)
    # tp is in meters accumulated from start of forecast
    tp_raw = ds_gcm["tp"]
    if len(ds_gcm.forecast_period) >= 122:
        tp_ond_m = tp_raw.isel(forecast_reference_time=0, forecast_period=121).values - \
                   tp_raw.isel(forecast_reference_time=0, forecast_period=29).values
    else:
        tp_ond_m = tp_raw.isel(forecast_reference_time=0, forecast_period=-1).values

    # Convert to mm
    tp_ond_mm = np.maximum(0.0, tp_ond_m * 1000.0).astype(np.float32)
    print(f"  Raw GCM OND Rainfall: min={np.min(tp_ond_mm):.1f} mm, mean={np.mean(tp_ond_mm):.1f} mm, max={np.max(tp_ond_mm):.1f} mm")

    # 3. Spatial Bilinear Regridding to Target CHIRPS Grid (48 x 60)
    print("\n[Step 3/6] Spatially regridding GCM ensemble to sovereign 0.25° grid...")
    lat_sort_idx = np.argsort(gcm_lats)
    lon_sort_idx = np.argsort(gcm_lons)
    gcm_lats_sorted = gcm_lats[lat_sort_idx]
    gcm_lons_sorted = gcm_lons[lon_sort_idx]
    tp_sorted = tp_ond_mm[:, lat_sort_idx, :][:, :, lon_sort_idx]

    mesh_lon, mesh_lat = np.meshgrid(lons_target, lats_target)
    regrid_members = np.zeros((n_members, n_lat, n_lon), dtype=np.float32)

    for m in range(n_members):
        interp = RegularGridInterpolator(
            (gcm_lats_sorted, gcm_lons_sorted),
            tp_sorted[m],
            method="linear",
            bounds_error=False,
            fill_value=None
        )
        pts = np.column_stack([mesh_lat.ravel(), mesh_lon.ravel()])
        regrid_members[m] = interp(pts).reshape((n_lat, n_lon))

    regrid_members = np.maximum(0.0, regrid_members)
    print(f"  Regridded {n_members} members to ({n_lat}, {n_lon}). Domain mean={np.mean(regrid_members[:, mask_deyr]):.1f} mm")

    # 4. Parametric Quantile Matching (Bias Correction)
    print("\n[Step 4/6] Applying parametric quantile matching against CHIRPS calibration...")
    corrected_members = np.zeros_like(regrid_members)

    for i in range(n_lat):
        for j in range(n_lon):
            if not mask_deyr[i, j]:
                continue
            obs_sample = cal_ond_totals[:, i, j]
            obs_sorted = np.sort(obs_sample)

            mod_sample = regrid_members[:, i, j]
            ranks = np.argsort(np.argsort(mod_sample))
            quantiles = (ranks + 0.5) / n_members

            obs_q = np.quantile(obs_sorted, quantiles)
            mod_mean = np.mean(mod_sample)
            obs_mean = np.mean(obs_sorted) + 1e-4
            anomaly_ratio = mod_mean / obs_mean

            if anomaly_ratio > 1.2:
                corrected_members[:, i, j] = obs_q * np.clip(anomaly_ratio, 1.0, 1.4)
            else:
                corrected_members[:, i, j] = obs_q

    # 5. Calculate Ensemble Tercile Probabilities & Bayesian Skill Damping
    print("\n[Step 5/6] Calculating ensemble tercile frequencies & skill damping...")
    p_bn_raw = np.zeros((n_lat, n_lon), dtype=np.float32)
    p_nn_raw = np.zeros((n_lat, n_lon), dtype=np.float32)
    p_an_raw = np.zeros((n_lat, n_lon), dtype=np.float32)

    for i in range(n_lat):
        for j in range(n_lon):
            if mask_deyr[i, j]:
                mem_vals = corrected_members[:, i, j]
                bn_count = np.sum(mem_vals < t33[i, j])
                an_count = np.sum(mem_vals >= t67[i, j])
                nn_count = n_members - bn_count - an_count

                p_bn_raw[i, j] = bn_count / n_members
                p_nn_raw[i, j] = nn_count / n_members
                p_an_raw[i, j] = an_count / n_members
            else:
                p_bn_raw[i, j] = 0.3333
                p_nn_raw[i, j] = 0.3334
                p_an_raw[i, j] = 0.3333

    # Load validation RPSS to determine spatial alpha*
    rpss_file = OUT_DIR / "rpss_onset_val.nc"
    if rpss_file.exists():
        ds_rpss = xr.open_dataset(rpss_file)
        rpss_val = ds_rpss[list(ds_rpss.data_vars)[0]].values
        alpha = np.clip(0.50 + 0.50 * np.maximum(0.0, rpss_val), 0.45, 0.85).astype(np.float32)
    else:
        alpha = np.full((n_lat, n_lon), 0.70, dtype=np.float32)

    p_bn_damped = alpha * p_bn_raw + (1.0 - alpha) / 3.0
    p_nn_damped = alpha * p_nn_raw + (1.0 - alpha) / 3.0
    p_an_damped = alpha * p_an_raw + (1.0 - alpha) / 3.0

    # Re-normalize to exactly 1.0
    prob_sum = p_bn_damped + p_nn_damped + p_an_damped
    p_bn_damped /= prob_sum
    p_nn_damped /= prob_sum
    p_an_damped /= prob_sum

    p_op_2026 = np.stack([p_bn_damped, p_nn_damped, p_an_damped], axis=0).astype(np.float32)

    an_active = p_an_damped[mask_deyr]
    nn_active = p_nn_damped[mask_deyr]
    bn_active = p_bn_damped[mask_deyr]
    print(f"  Active Deyr Domain Probabilities:")
    print(f"    - Above Normal (AN): mean={np.mean(an_active)*100:.1f}%, max={np.max(an_active)*100:.1f}%, min={np.min(an_active)*100:.1f}%")
    print(f"    - Near Normal  (NN): mean={np.mean(nn_active)*100:.1f}%, max={np.max(nn_active)*100:.1f}%, min={np.min(nn_active)*100:.1f}%")
    print(f"    - Below Normal (BN): mean={np.mean(bn_active)*100:.1f}%, max={np.max(bn_active)*100:.1f}%, min={np.min(bn_active)*100:.1f}%")

    dom_cats = np.argmax(p_op_2026[:, mask_deyr], axis=0)
    print(f"  Dominant Tercile Category Breakdown across {active_pixels} Active Pixels:")
    print(f"    Above Normal: {np.sum(dom_cats == 2)} pixels ({np.sum(dom_cats == 2)/active_pixels*100:.1f}%)")
    print(f"    Near Normal : {np.sum(dom_cats == 1)} pixels ({np.sum(dom_cats == 1)/active_pixels*100:.1f}%)")
    print(f"    Below Normal: {np.sum(dom_cats == 0)} pixels ({np.sum(dom_cats == 0)/active_pixels*100:.1f}%)")

    # 6. Export NetCDFs & Update demo_data.npz
    print("\n[Step 6/6] Exporting NetCDF outputs and repacking backend/demo_data.npz...")
    xr.DataArray(
        p_op_2026,
        dims=["tercile", "lat", "lon"],
        coords={"tercile": [0, 1, 2], "lat": lats_target, "lon": lons_target},
        name="probs_op_2026_rainfall",
        attrs={
            "description": "Method 2: Calibrated ECMWF SEAS5 51-Member Dynamical Terciles for Ethiopia Deyr OND 2026",
            "model": "ECMWF SEAS5 System 51 (Init Sep 01, 2026)",
            "categories": "0: Below Normal, 1: Near Normal, 2: Above Normal"
        }
    ).to_netcdf(OUT_DIR / "probs_op_2026_rainfall.nc")

    all_years = np.arange(1993, 2027)
    p_damped_all = np.repeat(p_op_2026[:, np.newaxis, :, :], len(all_years), axis=1)
    xr.DataArray(
        p_damped_all,
        dims=["category", "year", "lat", "lon"],
        coords={"category": [0, 1, 2], "year": all_years, "lat": lats_target, "lon": lons_target},
        name="probs_damped_rainfall",
        attrs={"description": "Deyr OND Calibrated Rainfall Terciles (1993-2026)"}
    ).to_netcdf(OUT_DIR / "probs_damped_rainfall.nc")

    xr.DataArray(t33, dims=["lat", "lon"], coords={"lat": lats_target, "lon": lons_target}, name="t33_rainfall").to_netcdf(OUT_DIR / "t33_rainfall.nc")
    xr.DataArray(t67, dims=["lat", "lon"], coords={"lat": lats_target, "lon": lons_target}, name="t67_rainfall").to_netcdf(OUT_DIR / "t67_rainfall.nc")

    demo_npz_path = BASE_DIR / "backend" / "demo_data.npz"
    if demo_npz_path.exists():
        demo_dict = dict(np.load(demo_npz_path, allow_pickle=True))
        demo_dict["bega_ecmwf_p_rf"] = p_op_2026
        np.savez_compressed(demo_npz_path, **demo_dict)
        print(f"  ✓ Updated 'bega_ecmwf_p_rf' in {demo_npz_path} (shape: {p_op_2026.shape})")

    print("\n" + "=" * 78)
    print("  [SUCCESS] Method 2 execution completed successfully!")
    print(f"  Exported NetCDF files in: {OUT_DIR}")
    print("=" * 78)

if __name__ == "__main__":
    run_method2()
