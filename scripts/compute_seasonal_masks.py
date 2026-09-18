"""
compute_seasonal_masks.py
-------------------------
Scientifically computes seasonal rainfall masks and rainfall regime classifications
for Ethiopia and Kenya based on:
  1. Two-Stage Harmonic & Climatological Regime Classification (Dunning et al. 2016 & EMI):
     - Stage 1: Fourier Harmonic Decomposition (rH = C_2 / C_1).
     - Stage 2: Climatological Peak Timing & Water-Season Detection.
     - Regime 0 (Arid / Marginal): Pre-filter for hyper-arid Afar/Danakil (P_ann < 200mm or dry autumn).
     - Regime 1 (Western Unimodal): Single prolonged wet season (Mar/Apr to Oct/Nov).
     - Regime 2 (Bimodal Type 1 Highlands): Belg early rains + dry pause + Kiremt main rains.
     - Regime 3 (Bimodal Type 2 Pastoral Lowlands): Gu MAM + dry summer (JJA) + Deyr SON/OND.
  2. Regime-Aware Seasonal Masks:
     - Belg (FMAM): Confined strictly to Regime 2 Highlands.
     - Gu (MAM): Confined strictly to Regime 3 Pastoral Lowlands.
     - Kiremt (JJAS): Regime 2 (bimodal onset) + Regime 1 (national JJAS rainfall).
     - Deyr (SON-OND): Confined strictly to Regime 3 Pastoral Lowlands.
     - Annual Wet Season: Confined strictly to Regime 1 Western Unimodal.
  3. Morphological connected-component cleanup (removing isolated single/double pixels < 3 px).
  4. Unified sovereign land mask (1,485 pixels).

Outputs:
  outputs/masks/mask_kiremt.nc     (48, 60) boolean
  outputs/masks/mask_belg.nc       (48, 60) boolean (also mask_fmam.nc)
  outputs/masks/mask_gu.nc         (48, 60) boolean (Gu spring pastoral rains)
  outputs/masks/mask_deyr.nc       (48, 60) boolean (also mask_bega.nc)
  outputs/masks/mask_annual.nc     (48, 60) boolean (Western Unimodal long season)
  outputs/masks/regime_map.nc      (48, 60) int8 (0: Arid, 1: Unimodal, 2: Bimodal Highlands, 3: Bimodal Lowlands)
  outputs/masks/mask_kenya_mam.nc  (42, 34) boolean
  outputs/masks/mask_kenya_ond.nc  (42, 34) boolean
  outputs/masks/seasonal_masks.npz Combined masks and regime map for packaging
"""

import os
import sys
import json
import numpy as np
import xarray as xr
import scipy.ndimage as ndi
from shapely.geometry import shape, Point

sys.path.insert(0, os.path.abspath("backend"))
import mam_loader as dl

def remove_small_objects(mask, min_size=3):
    """Purges isolated noise clusters while preserving narrow ecological corridors."""
    labeled, num_features = ndi.label(mask)
    if num_features == 0:
        return mask.copy()
    sizes = ndi.sum(mask, labeled, range(num_features + 1))
    small = sizes < min_size
    mask_clean = mask.copy()
    mask_clean[small[labeled]] = False
    return mask_clean

def compute_ethiopia_masks():
    print("=== Computing Ethiopia Seasonal Regimes and Masks (Dunning et al. 2016 & EMI) ===")
    chirps_path = "data/chirps_pr_et/et_chirps_pr_r25_1993_2025.nc"
    ds = xr.open_dataset(chirps_path)
    p = ds["precip"]  # (time, lat, lon)
    lats = ds["lat"].values
    lons = ds["lon"].values
    n_lat, n_lon = len(lats), len(lons)

    # 1. Sovereign Ethiopia Land Mask (Unified 1,485 pixels)
    with open("frontend/public/boundaries/eth_admin0.geojson", "r", encoding="utf-8") as f:
        b_data = json.load(f)
    poly = shape(b_data["features"][0]["geometry"])
    lm = np.zeros((n_lat, n_lon), dtype=bool)
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            lm[i, j] = poly.contains(Point(lon, lat))
    n_land = int(np.sum(lm))
    print(f"Total sovereign Ethiopia land pixels: {n_land}")

    # 2. Daily Climatology Q(d) across 365 calendar days
    doy = p.time.dt.dayofyear.values
    mask_365 = doy <= 365
    doy_clean = doy[mask_365]
    p_clean = p.values[mask_365]

    q_clim = np.zeros((365, n_lat, n_lon), dtype=np.float32)
    for d in range(1, 366):
        q_clim[d-1] = np.mean(p_clean[doy_clean == d], axis=0)

    # Monthly Climatology (mm/month)
    month_starts = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]
    q_month = np.zeros((12, n_lat, n_lon), dtype=np.float32)
    for m in range(12):
        q_month[m] = np.sum(q_clim[month_starts[m]:month_starts[m+1]], axis=0)

    # 3. Fourier Harmonic Decomposition (Dunning et al. 2016)
    theta = 2.0 * np.pi * (np.arange(1, 366) - 0.5) / 365.0
    cos1 = np.cos(theta)[:, None, None]
    sin1 = np.sin(theta)[:, None, None]
    cos2 = np.cos(2 * theta)[:, None, None]
    sin2 = np.sin(2 * theta)[:, None, None]

    A1 = (2.0 / 365.0) * np.sum(q_clim * cos1, axis=0)
    B1 = (2.0 / 365.0) * np.sum(q_clim * sin1, axis=0)
    C1 = np.sqrt(A1**2 + B1**2)

    A2 = (2.0 / 365.0) * np.sum(q_clim * cos2, axis=0)
    B2 = (2.0 / 365.0) * np.sum(q_clim * sin2, axis=0)
    C2 = np.sqrt(A2**2 + B2**2)
    rH = np.where(C1 > 1e-4, C2 / C1, 0.0)

    # 4. Climatological seasonal totals
    p_ann  = np.sum(q_clim, axis=0)
    p_fmam = np.sum(q_clim[31:151], axis=0)   # Feb-May (Belg / Gu)
    p_jjas = np.sum(q_clim[151:273], axis=0)  # Jun-Sep (Kiremt)
    p_ond  = np.sum(q_clim[273:365], axis=0)  # Oct-Dec (Deyr)
    p_jja  = np.sum(q_clim[151:243], axis=0)  # Jun-Aug (Summer)

    with np.errstate(divide="ignore", invalid="ignore"):
        r_jjas = np.where(p_ann > 10, p_jjas / p_ann, 0.0)
        r_fmam = np.where(p_ann > 10, p_fmam / p_ann, 0.0)
        r_ond  = np.where(p_ann > 10, p_ond  / p_ann, 0.0)

    # Peak timing detection
    q_smooth = np.zeros_like(q_month)
    for m in range(12):
        prev_m = (m - 1) % 12
        next_m = (m + 1) % 12
        q_smooth[m] = 0.25 * q_month[prev_m] + 0.5 * q_month[m] + 0.25 * q_month[next_m]

    peak1_month = np.argmax(q_smooth, axis=0) + 1  # 1-indexed (Jan=1..Dec=12)

    peak2_month = np.zeros((n_lat, n_lon), dtype=int)
    for i in range(n_lat):
        for j in range(n_lon):
            local_max = []
            for m in range(12):
                prev_m = (m - 1) % 12
                next_m = (m + 1) % 12
                if q_smooth[m, i, j] > q_smooth[prev_m, i, j] and q_smooth[m, i, j] > q_smooth[next_m, i, j]:
                    local_max.append((m + 1, q_smooth[m, i, j]))
            local_max.sort(key=lambda x: x[1], reverse=True)
            if len(local_max) > 1:
                peak2_month[i, j] = local_max[1][0]
            elif len(local_max) == 1:
                peak2_month[i, j] = local_max[0][0]

    LON, LAT = np.meshgrid(lons, lats)

    # 5. TWO-STAGE REGIME CLASSIFICATION
    # Step 1: Pre-filter Regime 0: Arid / Marginal (Hyper-arid Danakil Depression / Afar)
    reg_0 = ((p_ann < 200.0) | ((p_ann < 300.0) & (p_ond < 30.0))) & lm

    # Step 2: Regime 3: Bimodal Type 2 - Southern / SE Pastoral Lowlands (Gu + Deyr)
    reg_3 = (
        (p_ond >= 30.0) & (r_ond >= 0.08) &
        (p_jja < 1.3 * p_ond) &
        ((rH >= 0.70) | np.isin(peak1_month, [10, 11]) | np.isin(peak2_month, [10, 11])) &
        (~reg_0) & lm
    )

    # Step 3: Regime 2: Bimodal Type 1 - Central/Eastern Highlands (Belg + Kiremt)
    has_belg_peak = (p_fmam >= 50.0) & (r_fmam >= 0.10)
    has_kiremt_peak = (p_jjas >= 120.0) & (r_jjas >= 0.25)
    highland_lon = (LON >= 38.0) | ((LON >= 37.5) & (LAT >= 10.0))

    reg_2 = (
        has_belg_peak & has_kiremt_peak &
        highland_lon &
        ((rH >= 0.38) | np.isin(peak2_month, [3, 4, 5])) &
        (~reg_0) & (~reg_3) & lm
    )

    # Step 4: Regime 1: Western Unimodal (Single Prolonged Wet Season)
    reg_1 = lm & (~reg_0) & (~reg_2) & (~reg_3)

    # Morphological cleanup (remove isolated clusters < 3 pixels)
    reg_0 = remove_small_objects(reg_0, min_size=2)
    reg_2 = remove_small_objects(reg_2, min_size=3)
    reg_3 = remove_small_objects(reg_3, min_size=3)
    reg_1 = lm & (~reg_0) & (~reg_2) & (~reg_3)

    regime_map = np.zeros((n_lat, n_lon), dtype=np.int8)
    regime_map[reg_1] = 1
    regime_map[reg_2] = 2
    regime_map[reg_3] = 3
    regime_map[reg_0] = 0

    print(f"Regime 1 (Western Unimodal):           {np.sum(reg_1)} / {n_land} ({np.sum(reg_1)/n_land*100:.1f}%)")
    print(f"Regime 2 (Bimodal Highlands):          {np.sum(reg_2)} / {n_land} ({np.sum(reg_2)/n_land*100:.1f}%)")
    print(f"Regime 3 (Bimodal Pastoral Lowlands):  {np.sum(reg_3)} / {n_land} ({np.sum(reg_3)/n_land*100:.1f}%)")
    print(f"Regime 0 (Arid / Marginal):            {np.sum(reg_0)} / {n_land} ({np.sum(reg_0)/n_land*100:.1f}%)")

    # 6. Detection rates from calibrated CHIRPS detections
    dl.configure()
    dl.load(force=True)
    state = dl.get_state()

    c_kiremt = state.get("chirps_kiremt")
    c_fmam   = state.get("chirps_fmam")
    c_bega   = state.get("chirps_bega")

    dr_kiremt = np.sum(~np.isnan(c_kiremt["onset_doy"]), axis=0) / c_kiremt["onset_doy"].shape[0] if c_kiremt else np.ones((n_lat, n_lon))
    dr_fmam   = np.sum(~np.isnan(c_fmam["onset_doy"]),   axis=0) / c_fmam["onset_doy"].shape[0]   if c_fmam   else np.ones((n_lat, n_lon))
    dr_bega   = np.sum(~np.isnan(c_bega["onset_doy"]),   axis=0) / c_bega["onset_doy"].shape[0]   if c_bega   else np.ones((n_lat, n_lon))

    # 7. Regime-Aware Composite Seasonal Masks
    # Belg (FMAM): Confined strictly to Regime 2 Highlands
    mask_belg   = remove_small_objects(reg_2 & (p_fmam >= 50.0) & (r_fmam >= 0.10) & (dr_fmam >= 0.55) & lm, min_size=3)
    # Gu (MAM): Confined strictly to Regime 3 Pastoral Lowlands
    mask_gu     = remove_small_objects(reg_3 & (p_fmam >= 40.0) & (r_fmam >= 0.10) & (dr_fmam >= 0.50) & lm, min_size=3)
    # Deyr (SON-OND): Confined strictly to Regime 3 Pastoral Lowlands
    mask_deyr   = remove_small_objects(reg_3 & (p_ond >= 30.0) & (r_ond >= 0.08) & (dr_bega >= 0.50) & lm, min_size=3)
    # Kiremt Onset (JJAS): Confined strictly to Regime 2 Highlands bimodal onset domain
    mask_kiremt = remove_small_objects(reg_2 & (p_jjas >= 120.0) & (r_jjas >= 0.20) & (dr_kiremt >= 0.60) & lm, min_size=3)
    # National JJAS Rainfall Domain: Regime 1 + Regime 2
    mask_kiremt_jjas = remove_small_objects((reg_1 | reg_2) & (p_jjas >= 120.0) & (r_jjas >= 0.20) & (dr_kiremt >= 0.60) & lm, min_size=3)
    # Annual Wet Season: Confined strictly to Regime 1 Western Unimodal
    mask_annual = remove_small_objects(reg_1 & lm, min_size=3)

    print(f"\nFinal Kiremt Onset Mask (Regime 2): {np.sum(mask_kiremt)}/{n_land} ({np.sum(mask_kiremt)/n_land*100:.1f}%)")
    print(f"Final JJAS Rainfall Mask (R1+R2):  {np.sum(mask_kiremt_jjas)}/{n_land} ({np.sum(mask_kiremt_jjas)/n_land*100:.1f}%)")
    print(f"Final Belg Mask (Regime 2):        {np.sum(mask_belg)}/{n_land} ({np.sum(mask_belg)/n_land*100:.1f}%)")
    print(f"Final Gu Mask (Regime 3):          {np.sum(mask_gu)}/{n_land} ({np.sum(mask_gu)/n_land*100:.1f}%)")
    print(f"Final Deyr Mask (Regime 3):        {np.sum(mask_deyr)}/{n_land} ({np.sum(mask_deyr)/n_land*100:.1f}%)")
    print(f"Final Annual Mask (Regime 1):      {np.sum(mask_annual)}/{n_land} ({np.sum(mask_annual)/n_land*100:.1f}%)")

    return {
        "lats": lats,
        "lons": lons,
        "regime_map": regime_map,
        "mask_kiremt": mask_kiremt,
        "mask_kiremt_jjas": mask_kiremt_jjas,
        "mask_belg": mask_belg,
        "mask_gu": mask_gu,
        "mask_deyr": mask_deyr,
        "mask_bega": mask_deyr,    # backward-compatible alias
        "mask_annual": mask_annual,
    }

def compute_kenya_masks():
    print("\n=== Computing Kenya Seasonal Rainfall Masks (Methods 1 & 2) ===")
    dl.configure()
    state = dl.get_state()
    t_lat = state["target_lat"]  # (42,)
    t_lon = state["target_lon"]  # (34,)
    lm    = state["lm"]          # (42, 34)
    n_land = int(np.sum(lm))
    n_lat, n_lon = len(t_lat), len(t_lon)
    print(f"Total Kenya land pixels: {n_land} (Grid: {n_lat}x{n_lon})")

    chirps_path = "data/chirps_pr_ke/ke_chirps_pr_r25_1993_2025.nc"
    ds = xr.open_dataset(chirps_path)
    p = ds["precip"]

    p_interp = p.interp(lat=t_lat, lon=t_lon, method="nearest")

    p_ann = p_interp.groupby("time.year").sum(dim="time").mean(dim="year").values
    p_mam = p_interp.sel(time=p_interp.time.dt.month.isin([3, 4, 5])).groupby("time.year").sum(dim="time").mean(dim="year").values
    p_ond = p_interp.sel(time=p_interp.time.dt.month.isin([10, 11, 12])).groupby("time.year").sum(dim="time").mean(dim="year").values

    with np.errstate(divide="ignore", invalid="ignore"):
        r_mam = np.where(p_ann > 10, p_mam / p_ann, 0.0)
        r_ond = np.where(p_ann > 10, p_ond / p_ann, 0.0)

    on_mam = state["onset_doy"]
    dr_mam = np.sum(~np.isnan(on_mam), axis=0) / on_mam.shape[0]

    c_sep = state.get("chirps_sep")
    if c_sep:
        on_ond = c_sep["onset_doy"]
        dr_ond = np.sum(~np.isnan(on_ond), axis=0) / on_ond.shape[0]
    else:
        dr_ond = np.ones((n_lat, n_lon))

    # Kenya Long Rains (MAM): P >= 80mm AND R >= 18% AND DR >= 60%
    mask_mam_raw = (p_mam >= 80.0) & (r_mam >= 0.18) & (dr_mam >= 0.60) & lm
    # Kenya Short Rains (OND): P >= 60mm AND R >= 15% AND DR >= 60%
    mask_ond_raw = (p_ond >= 60.0) & (r_ond >= 0.15) & (dr_ond >= 0.60) & lm

    mask_mam = remove_small_objects(mask_mam_raw, min_size=3)
    mask_ond = remove_small_objects(mask_ond_raw, min_size=3)

    print(f"Kenya Long Rains (MAM) Mask:  {np.sum(mask_mam)}/{n_land} ({np.sum(mask_mam)/n_land*100:.1f}%)")
    print(f"Kenya Short Rains (OND) Mask: {np.sum(mask_ond)}/{n_land} ({np.sum(mask_ond)/n_land*100:.1f}%)")

    return {
        "lats": t_lat,
        "lons": t_lon,
        "mask_kenya_mam": mask_mam,
        "mask_kenya_ond": mask_ond,
    }

def main():
    os.makedirs("outputs/masks", exist_ok=True)
    et_res = compute_ethiopia_masks()
    ke_res = compute_kenya_masks()

    # Save to individual NetCDFs
    ds_regime = xr.Dataset({"regime": (["lat", "lon"], et_res["regime_map"])}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_regime.to_netcdf("outputs/masks/regime_map.nc")

    ds_kiremt = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_kiremt"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_kiremt.to_netcdf("outputs/masks/mask_kiremt.nc")

    ds_belg = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_belg"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_belg.to_netcdf("outputs/masks/mask_belg.nc")
    ds_belg.to_netcdf("outputs/masks/mask_fmam.nc")

    ds_gu = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_gu"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_gu.to_netcdf("outputs/masks/mask_gu.nc")

    ds_deyr = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_deyr"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_deyr.to_netcdf("outputs/masks/mask_deyr.nc")
    ds_deyr.to_netcdf("outputs/masks/mask_bega.nc")

    ds_annual = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_annual"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_annual.to_netcdf("outputs/masks/mask_annual.nc")

    ds_mam = xr.Dataset({"mask": (["lat", "lon"], ke_res["mask_kenya_mam"].astype(np.int8))}, coords={"lat": ke_res["lats"], "lon": ke_res["lons"]})
    ds_mam.to_netcdf("outputs/masks/mask_kenya_mam.nc")

    ds_ond = xr.Dataset({"mask": (["lat", "lon"], ke_res["mask_kenya_ond"].astype(np.int8))}, coords={"lat": ke_res["lats"], "lon": ke_res["lons"]})
    ds_ond.to_netcdf("outputs/masks/mask_kenya_ond.nc")

    # Save combined NPZ
    npz_path = "outputs/masks/seasonal_masks.npz"
    np.savez_compressed(
        npz_path,
        regime_map=et_res["regime_map"],
        mask_kiremt=et_res["mask_kiremt"],
        mask_belg=et_res["mask_belg"],
        mask_gu=et_res["mask_gu"],
        mask_deyr=et_res["mask_deyr"],
        mask_bega=et_res["mask_bega"],
        mask_annual=et_res["mask_annual"],
        mask_kenya_mam=ke_res["mask_kenya_mam"],
        mask_kenya_ond=ke_res["mask_kenya_ond"],
    )
    print(f"\n[SUCCESS] Exported all NetCDF and NPZ masks to outputs/masks/ (Size: {os.path.getsize(npz_path)/1024:.2f} KB)")

if __name__ == "__main__":
    main()
