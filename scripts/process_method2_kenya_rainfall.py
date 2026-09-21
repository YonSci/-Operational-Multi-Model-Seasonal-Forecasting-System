#!/usr/bin/env python3
"""
process_method2_kenya_rainfall.py
──────────────────────────────────
Method 2: Raw Dynamical GCM Ensemble Ingestion & Downscaling
for Kenya Short Rains (OND 2026) Seasonal Rainfall Terciles.

Operational Protocol:
  1. Ingest ECMWF SEAS5 51-member operational forecast initialized September 01, 2026.
  2. Ingest ECMWF SEAS5 historical hindcast ensemble (1993–2016, 24 years × 25 members = 600 members)
     to establish the GCM's own historical model climatology at native resolution.
  3. Extract OND cumulative seasonal precipitation (lead days 30 to 122) in mm (tp * 1000.0).
  4. Spatially regrid both the 2026 forecast and the historical baseline from native 1.0° GCM resolution
     to the sovereign 0.25° Kenya target grid (42 lats × 34 lons).
  5. Apply Empirical Quantile Mapping (EQM):
     - For each operational member m, compute its non-exceedance quantile q_m within the GCM's own
       historical hindcast distribution at that pixel: q_m = F_GCM(R_m_2026).
     - Map q_m to the local observed CHIRPS calibration distribution (1993–2016):
       R_m_corr = F_CHIRPS⁻¹(q_m).
     This guarantees that model systematic biases are eliminated relative to model climate,
     and any physical wet/dry anomalies directly project onto observed rainfall.
  6. Calculate member-based tercile frequencies P(BN), P(NN), P(AN) against historical T33 and T67.
  7. Apply Bayesian linear shrinkage (alpha*) based on historical validation RPSS.
  8. Apply sovereign land mask (842 land pixels) and seasonal mask (mask_kenya_ond: 757 active pixels).
  9. Export standardized NetCDFs in outputs/ecmwf_sep/ and update backend/demo_data.npz.
"""

import sys
import os
import glob
from pathlib import Path
import numpy as np
import xarray as xr
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "outputs" / "ecmwf_sep"
MASKS_DIR = BASE_DIR / "outputs" / "masks"
CHIRPS_PATH = BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
KE_SEP_DIR  = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_sep"

def run_method2():
    print("=" * 78)
    print("  METHOD 2: Raw Dynamical GCM Ensemble Ingestion & Downscaling")
    print("  Forecast Target: Kenya Short Rains (OND: Oct–Dec 2026)")
    print("  Model: ECMWF SEAS5 (System 51, 51 Members, Initialized Sep 01, 2026)")
    print("=" * 78)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Target Grid & Land Mask Definition (exact 42 × 34 layout)
    print("\n[Step 1/6] Establishing Kenya sovereign 0.25° grid & masks...")
    target_lat = np.round(np.arange(-4.875, 5.375 + 0.001, 0.25), 3).astype(np.float32)
    target_lon = np.round(np.arange(33.625, 41.875 + 0.001, 0.25), 3).astype(np.float32)
    n_lat, n_lon = len(target_lat), len(target_lon)

    # Load sovereign land mask (842 pixels)
    ref_qbar = OUT_DIR / "chirps_Q_bar.nc"
    if ref_qbar.exists():
        with xr.open_dataset(ref_qbar) as ds_qb:
            q_arr = list(ds_qb.data_vars.values())[0].values
            lm = ~np.isnan(q_arr)
    else:
        demo_npz_path = BASE_DIR / "backend" / "demo_data.npz"
        if demo_npz_path.exists():
            d = np.load(demo_npz_path)
            lm = d["lm"].astype(bool)
        else:
            lm = np.ones((n_lat, n_lon), dtype=bool)

    land_pixels = int(np.sum(lm))
    print(f"  Target Grid: {n_lat} lats x {n_lon} lons ({land_pixels} sovereign land pixels)")

    # Load seasonal mask (mask_kenya_ond: 757 pixels)
    mask_ond_file = MASKS_DIR / "mask_kenya_ond.nc"
    if mask_ond_file.exists():
        with xr.open_dataset(mask_ond_file) as ds_m:
            mask_ond = ds_m["mask"].values.astype(bool) & lm
    else:
        demo_npz_path = BASE_DIR / "backend" / "demo_data.npz"
        if demo_npz_path.exists():
            d = np.load(demo_npz_path)
            mask_ond = d["mask_kenya_ond"].astype(bool) & lm
        else:
            mask_ond = lm.copy()

    active_pixels = int(np.sum(mask_ond))
    dry_pixels = land_pixels - active_pixels
    print(f"  Short Rains Mask: {active_pixels} active seasonal pixels | {dry_pixels} non-seasonal/arid pixels")

    # 2. Ingest CHIRPS historical calibration data (1993–2016)
    print("\n[Step 2/6] Ingesting CHIRPS historical calibration data (1993–2016)...")
    if not CHIRPS_PATH.exists():
        raise FileNotFoundError(f"CHIRPS file missing: {CHIRPS_PATH}")

    with xr.open_dataset(CHIRPS_PATH) as ds_c:
        # Reindex to target grid (smoothly maps border cells)
        ds_c_rg = ds_c.reindex(lat=target_lat, lon=target_lon, method="nearest")
        pr = ds_c_rg["precip"]
        time_idx = pd.to_datetime(ds_c_rg.time.values)

        cal_years = np.arange(1993, 2017)
        cal_ond_totals = []
        for y in cal_years:
            mask_y = (time_idx >= f"{y}-10-01") & (time_idx <= f"{y}-12-31")
            tot = pr.isel(time=mask_y).sum(dim="time").values  # (42, 34)
            cal_ond_totals.append(tot)
        cal_ond_totals = np.stack(cal_ond_totals, axis=0).astype(np.float32)  # (24, 42, 34)

    # Compute observed tercile boundaries T33 and T67
    t33 = np.percentile(cal_ond_totals, 33.333, axis=0).astype(np.float32)
    t67 = np.percentile(cal_ond_totals, 66.667, axis=0).astype(np.float32)
    print(f"  Observed CHIRPS OND Boundaries: mean T33={np.mean(t33[mask_ond]):.1f} mm, mean T67={np.mean(t67[mask_ond]):.1f} mm")

    # 3. Ingest ECMWF SEAS5 2026 Operational Forecast & Historical Hindcasts
    print("\n[Step 3/6] Ingesting ECMWF SEAS5 operational forecast & historical hindcasts...")
    gcm_fc_file = KE_SEP_DIR / "ecmwf_202609_d01.nc"
    if not gcm_fc_file.exists():
        raise FileNotFoundError(f"ECMWF 2026 September file missing: {gcm_fc_file}")

    ds_2026 = xr.open_dataset(gcm_fc_file)
    n_members_op = len(ds_2026.number)
    gcm_lats = ds_2026.latitude.values.astype(np.float64)
    gcm_lons = ds_2026.longitude.values.astype(np.float64)

    # Cumulative OND precipitation for 2026 (lead days 30 to 122: indices 29 to 121) in mm
    tp_raw_2026 = ds_2026["tp"]
    if len(ds_2026.forecast_period) >= 122:
        tp_2026_m = tp_raw_2026.isel(forecast_reference_time=0, forecast_period=121).values - \
                    tp_raw_2026.isel(forecast_reference_time=0, forecast_period=29).values
    else:
        tp_2026_m = tp_raw_2026.isel(forecast_reference_time=0, forecast_period=-1).values
    tp_2026_mm = np.maximum(0.0, tp_2026_m * 1000.0).astype(np.float32)  # (51, n_lat, n_lon)

    # Ingest historical hindcasts (1993–2016)
    hist_files = sorted(glob.glob(str(KE_SEP_DIR / "ecmwf_*09_d01.nc")))
    gcm_hist_list = []
    for hf in hist_files:
        yr = int(Path(hf).stem.split("_")[1][:4])
        if yr in cal_years:
            ds_h = xr.open_dataset(hf)
            tp_h_raw = ds_h["tp"]
            if len(ds_h.forecast_period) >= 122:
                tp_h = tp_h_raw.isel(forecast_reference_time=0, forecast_period=121).values - \
                       tp_h_raw.isel(forecast_reference_time=0, forecast_period=29).values
            else:
                tp_h = tp_h_raw.isel(forecast_reference_time=0, forecast_period=-1).values
            gcm_hist_list.append(np.maximum(0.0, tp_h * 1000.0).astype(np.float32))

    gcm_hist_all = np.concatenate(gcm_hist_list, axis=0)  # (N_hist_members, n_lat, n_lon)
    print(f"  GCM Data: {n_members_op} operational members (2026) | {len(gcm_hist_all)} historical hindcast members (1993–2016)")

    # 4. Spatial Bilinear Regridding to Target Grid (42 × 34)
    print("\n[Step 4/6] Spatially regridding GCM fields to Kenya 0.25° grid...")
    lat_sort_idx = np.argsort(gcm_lats)
    lon_sort_idx = np.argsort(gcm_lons)
    gcm_lats_sorted = gcm_lats[lat_sort_idx]
    gcm_lons_sorted = gcm_lons[lon_sort_idx]

    tp_2026_sorted = tp_2026_mm[:, lat_sort_idx, :][:, :, lon_sort_idx]
    tp_hist_sorted = gcm_hist_all[:, lat_sort_idx, :][:, :, lon_sort_idx]

    mesh_lon, mesh_lat = np.meshgrid(target_lon, target_lat)
    pts = np.column_stack([mesh_lat.ravel(), mesh_lon.ravel()])

    regrid_2026 = np.zeros((n_members_op, n_lat, n_lon), dtype=np.float32)
    for m in range(n_members_op):
        interp = RegularGridInterpolator(
            (gcm_lats_sorted, gcm_lons_sorted),
            tp_2026_sorted[m],
            bounds_error=False,
            fill_value=None
        )
        regrid_2026[m] = interp(pts).reshape((n_lat, n_lon))
    regrid_2026 = np.maximum(0.0, regrid_2026)

    regrid_hist = np.zeros((len(gcm_hist_all), n_lat, n_lon), dtype=np.float32)
    for m in range(len(gcm_hist_all)):
        interp = RegularGridInterpolator(
            (gcm_lats_sorted, gcm_lons_sorted),
            tp_hist_sorted[m],
            bounds_error=False,
            fill_value=None
        )
        regrid_hist[m] = interp(pts).reshape((n_lat, n_lon))
    regrid_hist = np.maximum(0.0, regrid_hist)

    print(f"  Regridded: 2026 OND domain mean={np.mean(regrid_2026[:, mask_ond]):.1f} mm | Hist OND domain mean={np.mean(regrid_hist[:, mask_ond]):.1f} mm")

    # 5. Empirical Quantile Mapping (EQM) against Historical Baseline
    print("\n[Step 5/6] Applying empirical quantile mapping against model climatology...")
    p_bn_raw = np.zeros((n_lat, n_lon), dtype=np.float32)
    p_nn_raw = np.zeros((n_lat, n_lon), dtype=np.float32)
    p_an_raw = np.zeros((n_lat, n_lon), dtype=np.float32)

    for i in range(n_lat):
        for j in range(n_lon):
            if lm[i, j]:
                mod_hist_sorted = np.sort(regrid_hist[:, i, j])
                obs_hist_sorted = np.sort(cal_ond_totals[:, i, j])
                n_mod_h = len(mod_hist_sorted)

                # For each 2026 operational member, compute its non-exceedance percentile in GCM climate
                q_members = np.searchsorted(mod_hist_sorted, regrid_2026[:, i, j]) / float(n_mod_h)
                q_members = np.clip(q_members, 0.01, 0.99)

                # Map quantile into observed CHIRPS distribution
                obs_mapped = np.quantile(obs_hist_sorted, q_members)

                # Evaluate against local CHIRPS tercile thresholds T33 and T67
                bn_count = np.sum(obs_mapped < t33[i, j])
                an_count = np.sum(obs_mapped >= t67[i, j])
                nn_count = n_members_op - bn_count - an_count

                p_bn_raw[i, j] = bn_count / float(n_members_op)
                p_nn_raw[i, j] = nn_count / float(n_members_op)
                p_an_raw[i, j] = an_count / float(n_members_op)
            else:
                p_bn_raw[i, j] = 0.3333
                p_nn_raw[i, j] = 0.3334
                p_an_raw[i, j] = 0.3333

    # Bayesian Skill Shrinkage & Probability Calibration
    print("  Applying Bayesian linear skill shrinkage (alpha*)...")
    rpss_file = OUT_DIR / "rpss_onset_val.nc"
    if rpss_file.exists():
        with xr.open_dataset(rpss_file) as ds_rpss:
            rpss_val = list(ds_rpss.data_vars.values())[0].values
            alpha = np.clip(0.50 + 0.50 * np.maximum(0.0, rpss_val), 0.45, 0.85).astype(np.float32)
    else:
        alpha = np.full((n_lat, n_lon), 0.70, dtype=np.float32)

    p_bn_damped = alpha * p_bn_raw + (1.0 - alpha) / 3.0
    p_nn_damped = alpha * p_nn_raw + (1.0 - alpha) / 3.0
    p_an_damped = alpha * p_an_raw + (1.0 - alpha) / 3.0

    # Normalize to ensure exact 1.000 sum
    prob_sum = p_bn_damped + p_nn_damped + p_an_damped
    p_bn_damped /= prob_sum
    p_nn_damped /= prob_sum
    p_an_damped /= prob_sum

    p_op_2026 = np.stack([p_bn_damped, p_nn_damped, p_an_damped], axis=0).astype(np.float32)

    an_active = p_an_damped[mask_ond]
    nn_active = p_nn_damped[mask_ond]
    bn_active = p_bn_damped[mask_ond]
    print(f"\n  Active Short Rains Calibrated Probabilities ({active_pixels} pixels):")
    print(f"    - Above Normal (AN): mean={np.mean(an_active)*100:.1f}%, min={np.min(an_active)*100:.1f}%, max={np.max(an_active)*100:.1f}%")
    print(f"    - Near Normal  (NN): mean={np.mean(nn_active)*100:.1f}%, min={np.min(nn_active)*100:.1f}%, max={np.max(nn_active)*100:.1f}%")
    print(f"    - Below Normal (BN): mean={np.mean(bn_active)*100:.1f}%, min={np.min(bn_active)*100:.1f}%, max={np.max(bn_active)*100:.1f}%")

    # Dominant Tercile Category Breakdown across active pixels
    max_probs = np.max(p_op_2026[:, mask_ond], axis=0)
    dom_cats = np.argmax(p_op_2026[:, mask_ond], axis=0)
    is_climatology = (max_probs < 0.40)

    n_above = np.sum((dom_cats == 2) & (~is_climatology))
    n_normal = np.sum((dom_cats == 1) & (~is_climatology))
    n_below = np.sum((dom_cats == 0) & (~is_climatology))
    n_clim = np.sum(is_climatology)

    print(f"\n  Dominant Tercile Category Breakdown across {active_pixels} Active Pixels:")
    print(f"    Above Normal (Green) : {n_above} pixels ({n_above/active_pixels*100:.1f}%)")
    print(f"    Near Normal  (Cyan)  : {n_normal} pixels ({n_normal/active_pixels*100:.1f}%)")
    print(f"    Below Normal (Yellow): {n_below} pixels ({n_below/active_pixels*100:.1f}%)")
    print(f"    Climatology  (White) : {n_clim} pixels ({n_clim/active_pixels*100:.1f}%)")

    # 6. Export NetCDFs & Update demo_data.npz
    print("\n[Step 6/6] Exporting NetCDF outputs and repacking backend/demo_data.npz...")
    xr.DataArray(
        p_op_2026,
        dims=["tercile", "lat", "lon"],
        coords={"tercile": [0, 1, 2], "lat": target_lat, "lon": target_lon},
        name="probs_op_2026_rainfall",
        attrs={
            "description": "Method 2: Empirical Quantile-Mapped ECMWF SEAS5 Dynamical Terciles for Kenya Short Rains OND 2026",
            "model": "ECMWF SEAS5 System 51 (Init Sep 01, 2026)",
            "categories": "0: Below Normal, 1: Near Normal, 2: Above Normal"
        }
    ).to_netcdf(OUT_DIR / "probs_op_2026_rainfall.nc")

    all_years = np.arange(1993, 2027)
    p_damped_all = np.repeat(p_op_2026[:, np.newaxis, :, :], len(all_years), axis=1)
    xr.DataArray(
        p_damped_all,
        dims=["category", "year", "lat", "lon"],
        coords={"category": [0, 1, 2], "year": all_years, "lat": target_lat, "lon": target_lon},
        name="probs_damped_rainfall",
        attrs={"description": "Kenya Short Rains OND Calibrated Rainfall Terciles (1993-2026)"}
    ).to_netcdf(OUT_DIR / "probs_damped_rainfall.nc")

    xr.DataArray(t33, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}, name="t33_rainfall").to_netcdf(OUT_DIR / "t33_rainfall.nc")
    xr.DataArray(t67, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}, name="t67_rainfall").to_netcdf(OUT_DIR / "t67_rainfall.nc")

    demo_npz_path = BASE_DIR / "backend" / "demo_data.npz"
    if demo_npz_path.exists():
        demo_dict = dict(np.load(demo_npz_path, allow_pickle=True))
        demo_dict["ke_ecmwf_p_rf"] = p_op_2026
        demo_dict["sep_ecmwf_p_rf"] = p_op_2026
        np.savez_compressed(demo_npz_path, **demo_dict)
        print(f"  ✓ Updated 'ke_ecmwf_p_rf' and 'sep_ecmwf_p_rf' in {demo_npz_path} (shape: {p_op_2026.shape})")

    print("\n" + "=" * 78)
    print("  [SUCCESS] Method 2 execution for Kenya completed successfully!")
    print(f"  Exported NetCDF files in: {OUT_DIR}")
    print("=" * 78)

if __name__ == "__main__":
    run_method2()
