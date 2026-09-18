"""
compute_seasonal_masks.py
-------------------------
Scientifically computes seasonal rainfall masks for Ethiopia and Kenya using:
  Method 1: Climatological Precipitation Depth (P_season >= threshold)
            AND Seasonal Contribution Ratio (R_season = P_season / P_annual >= ratio_thresh).
  Method 2: Physical Water-Balance Detectability Rate (DR_season >= dr_thresh).

Outputs:
  outputs/masks/mask_kiremt.nc     (48, 60) boolean
  outputs/masks/mask_fmam.nc       (48, 60) boolean
  outputs/masks/mask_bega.nc       (48, 60) boolean
  outputs/masks/mask_kenya_mam.nc  (42, 34) boolean
  outputs/masks/mask_kenya_ond.nc  (42, 34) boolean
  outputs/masks/seasonal_masks.npz Combined masks for packaging
"""

import os
import sys
import json
import numpy as np
import xarray as xr
from shapely.geometry import shape, Point

sys.path.insert(0, os.path.abspath("backend"))
import mam_loader as dl

def compute_ethiopia_masks():
    print("=== Computing Ethiopia Seasonal Rainfall Masks (Methods 1 & 2) ===")
    chirps_path = "data/chirps_pr_et/et_chirps_pr_r25_1993_2025.nc"
    ds = xr.open_dataset(chirps_path)
    p = ds["precip"]  # (time, lat, lon)
    lats = ds["lat"].values
    lons = ds["lon"].values
    n_lat, n_lon = len(lats), len(lons)

    # 1. Sovereign Ethiopia Land Mask
    with open("frontend/public/boundaries/eth_admin0.geojson", "r", encoding="utf-8") as f:
        b_data = json.load(f)
    poly = shape(b_data["features"][0]["geometry"])
    lm = np.zeros((n_lat, n_lon), dtype=bool)
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            lm[i, j] = poly.contains(Point(lon, lat))
    n_land = int(np.sum(lm))
    print(f"Total sovereign Ethiopia land pixels: {n_land}")

    # 2. Annual & Seasonal Precipitation Totals (1993-2025 mean)
    p_ann = p.groupby("time.year").sum(dim="time").mean(dim="year").values
    p_jjas = p.sel(time=p.time.dt.month.isin([6, 7, 8, 9])).groupby("time.year").sum(dim="time").mean(dim="year").values
    p_fmam = p.sel(time=p.time.dt.month.isin([2, 3, 4, 5])).groupby("time.year").sum(dim="time").mean(dim="year").values
    p_ond  = p.sel(time=p.time.dt.month.isin([10, 11, 12])).groupby("time.year").sum(dim="time").mean(dim="year").values

    with np.errstate(divide="ignore", invalid="ignore"):
        r_jjas = np.where(p_ann > 10, p_jjas / p_ann, 0.0)
        r_fmam = np.where(p_ann > 10, p_fmam / p_ann, 0.0)
        r_ond  = np.where(p_ann > 10, p_ond  / p_ann, 0.0)

    # 3. Detection rates from calibrated CHIRPS detections
    dl.configure()
    dl.load(force=True)
    state = dl.get_state()

    c_kiremt = state.get("chirps_kiremt")
    c_fmam   = state.get("chirps_fmam")
    c_bega   = state.get("chirps_bega")

    dr_kiremt = np.sum(~np.isnan(c_kiremt["onset_doy"]), axis=0) / c_kiremt["onset_doy"].shape[0] if c_kiremt else np.ones((n_lat, n_lon))
    dr_fmam   = np.sum(~np.isnan(c_fmam["onset_doy"]),   axis=0) / c_fmam["onset_doy"].shape[0]   if c_fmam   else np.ones((n_lat, n_lon))
    dr_bega   = np.sum(~np.isnan(c_bega["onset_doy"]),   axis=0) / c_bega["onset_doy"].shape[0]   if c_bega   else np.ones((n_lat, n_lon))

    # 4. Method 1 + 2 Composite Masks
    # Kiremt (JJAS): P >= 150mm AND R >= 30% AND DR >= 70%
    mask_kiremt = (p_jjas >= 150.0) & (r_jjas >= 0.30) & (dr_kiremt >= 0.70) & lm
    # Belg (FMAM): P >= 80mm AND R >= 15% AND DR >= 65%
    mask_belg   = (p_fmam >= 80.0)  & (r_fmam >= 0.15) & (dr_fmam >= 0.65)   & lm
    # Bega (ONDJ / Deyr): P >= 50mm AND R >= 15% AND DR >= 65%
    mask_bega   = (p_ond >= 50.0)   & (r_ond >= 0.15)  & (dr_bega >= 0.65)   & lm

    print(f"Kiremt Seasonal Mask: {np.sum(mask_kiremt)}/{n_land} ({np.sum(mask_kiremt)/n_land*100:.1f}%)")
    print(f"Belg Seasonal Mask:   {np.sum(mask_belg)}/{n_land} ({np.sum(mask_belg)/n_land*100:.1f}%)")
    print(f"Bega Seasonal Mask:   {np.sum(mask_bega)}/{n_land} ({np.sum(mask_bega)/n_land*100:.1f}%)")

    return {
        "lats": lats,
        "lons": lons,
        "mask_kiremt": mask_kiremt,
        "mask_belg": mask_belg,
        "mask_bega": mask_bega,
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
    p = ds["precip"]  # (time, lat, lon)

    # Align onto exact (42, 34) grid
    p_interp = p.interp(lat=t_lat, lon=t_lon, method="nearest")

    p_ann = p_interp.groupby("time.year").sum(dim="time").mean(dim="year").values
    p_mam = p_interp.sel(time=p_interp.time.dt.month.isin([3, 4, 5])).groupby("time.year").sum(dim="time").mean(dim="year").values
    p_ond = p_interp.sel(time=p_interp.time.dt.month.isin([10, 11, 12])).groupby("time.year").sum(dim="time").mean(dim="year").values

    with np.errstate(divide="ignore", invalid="ignore"):
        r_mam = np.where(p_ann > 10, p_mam / p_ann, 0.0)
        r_ond = np.where(p_ann > 10, p_ond / p_ann, 0.0)

    # Detection rate
    on_mam = state["onset_doy"]  # (n_years, 42, 34)
    dr_mam = np.sum(~np.isnan(on_mam), axis=0) / on_mam.shape[0]

    c_sep = state.get("chirps_sep")
    if c_sep:
        on_ond = c_sep["onset_doy"]
        dr_ond = np.sum(~np.isnan(on_ond), axis=0) / on_ond.shape[0]
    else:
        dr_ond = np.ones((n_lat, n_lon))

    # Kenya Long Rains (MAM): P >= 80mm AND R >= 18% AND DR >= 60%
    mask_mam = (p_mam >= 80.0) & (r_mam >= 0.18) & (dr_mam >= 0.60) & lm
    # Kenya Short Rains (OND): P >= 60mm AND R >= 15% AND DR >= 60%
    mask_ond = (p_ond >= 60.0) & (r_ond >= 0.15) & (dr_ond >= 0.60) & lm

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
    ds_kiremt = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_kiremt"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_kiremt.to_netcdf("outputs/masks/mask_kiremt.nc")

    ds_belg = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_belg"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_belg.to_netcdf("outputs/masks/mask_fmam.nc")

    ds_bega = xr.Dataset({"mask": (["lat", "lon"], et_res["mask_bega"].astype(np.int8))}, coords={"lat": et_res["lats"], "lon": et_res["lons"]})
    ds_bega.to_netcdf("outputs/masks/mask_bega.nc")

    ds_mam = xr.Dataset({"mask": (["lat", "lon"], ke_res["mask_kenya_mam"].astype(np.int8))}, coords={"lat": ke_res["lats"], "lon": ke_res["lons"]})
    ds_mam.to_netcdf("outputs/masks/mask_kenya_mam.nc")

    ds_ond = xr.Dataset({"mask": (["lat", "lon"], ke_res["mask_kenya_ond"].astype(np.int8))}, coords={"lat": ke_res["lats"], "lon": ke_res["lons"]})
    ds_ond.to_netcdf("outputs/masks/mask_kenya_ond.nc")

    # Save combined NPZ
    npz_path = "outputs/masks/seasonal_masks.npz"
    np.savez_compressed(
        npz_path,
        mask_kiremt=et_res["mask_kiremt"],
        mask_belg=et_res["mask_belg"],
        mask_bega=et_res["mask_bega"],
        mask_kenya_mam=ke_res["mask_kenya_mam"],
        mask_kenya_ond=ke_res["mask_kenya_ond"],
    )
    print(f"\n[SUCCESS] Exported all NetCDF and NPZ masks to outputs/masks/ (Size: {os.path.getsize(npz_path)/1024:.2f} KB)")

if __name__ == "__main__":
    main()
