#!/usr/bin/env python3
"""
process_ecmwf_september.py
──────────────────────────
Operational Processing Pipeline for ECMWF SEAS5 Initialized in September.
Steps:
  1. Ingest CHIRPS daily (1993–2025) and establish 42 × 34 target grid & land mask
  2. Ingest 33 downloaded ECMWF SEAS5 September forecasts (1993–2025) & reindex
  3. Member-wise Empirical Quantile Mapping Daily Bias Correction (EQM-BC)
  4. Dunning et al. (2016) Season Climatology & Event Detection (Onset, Cessation, LGP)
  5. Probabilistic Terciles, Skill Scoring (RPSS, HR), and Damping Optimization (alpha*)
  6. Standard NetCDF Export to outputs/ecmwf_sep/
"""

import os
import sys
import glob
import warnings
from pathlib import Path
import numpy as np
import xarray as xr
import pandas as pd

warnings.filterwarnings("ignore")

# Add notebook/ to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "notebook"))
try:
    import dunning_lib as dl
except ImportError:
    dl = None

# Pipeline Configuration (Short Rains OND)
WIN_DOY_START       = 244   # Sept 1 (DOY 244)
WIN_DOY_END         = 365   # Dec 31 (DOY 365)
WIN_N_DAYS          = WIN_DOY_END - WIN_DOY_START + 1  # 122 days

DUNNING_BUFFER_DAYS = 30
MIN_LGP_DAYS        = 20

QM_DOY_WINDOW       = 15
WET_DAY_THRESH      = 0.1   # mm/day
BC_TRANSFORM_POWER  = 1/3   # cube-root power transform

CAL_YEARS           = np.arange(1993, 2017)   # 1993–2016 (24 years calibration)
VAL_YEARS           = np.arange(2017, 2025)   # 2017–2024 (8 years validation)
N_MEMBERS_COMMON    = 25                      # 25 ensemble members

MIN_TERCILE_YEARS   = 12
ALPHA_GRID          = np.round(np.arange(0.0, 1.01, 0.02), 2)

ECMWF_DIR           = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_sep"
CHIRPS_PATH         = BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
OUT_DIR             = BASE_DIR / "outputs" / "ecmwf_sep"


def _build_qm_transfer(c_pool, s_pool):
    """Build empirical quantile mapping transfer function."""
    c_wet = c_pool[c_pool > WET_DAY_THRESH]
    s_wet = s_pool[s_pool > WET_DAY_THRESH]

    if len(c_wet) < 5 or len(s_wet) < 5:
        return lambda x: x

    f_c = len(c_wet) / max(len(c_pool), 1)
    f_s = len(s_wet) / max(len(s_pool), 1)
    if f_s > f_c and len(s_wet) > 1:
        n_clip = int(round((f_s - f_c) * len(s_pool)))
        if n_clip > 0:
            cutoff = np.sort(s_wet)[min(n_clip, len(s_wet) - 1)]
            s_wet = s_wet[s_wet >= cutoff]
    if len(s_wet) < 3:
        return lambda x: x

    power = BC_TRANSFORM_POWER
    c_tr  = np.sort(c_wet ** power)
    s_tr  = np.sort(s_wet ** power)
    n_c, n_s = len(c_tr), len(s_wet)
    p_s  = (np.arange(1, n_s + 1) - 0.5) / n_s
    p_c  = (np.arange(1, n_c + 1) - 0.5) / n_c

    def transfer(x_raw):
        x_arr = np.asarray(x_raw, dtype=np.float32)
        out = np.zeros_like(x_arr)
        wet_mask = (x_arr > WET_DAY_THRESH) & (~np.isnan(x_arr))
        if not np.any(wet_mask):
            return out
        x_t = x_arr[wet_mask] ** power
        p_hat = np.interp(x_t, s_tr, p_s, left=p_s[0], right=p_s[-1])
        x_c_t = np.interp(p_hat, p_c, c_tr, left=c_tr[0], right=c_tr[-1])
        out[wet_mask] = np.maximum(x_c_t, 0.0) ** (1.0 / power)
        return out if isinstance(x_raw, np.ndarray) else float(out)

    return transfer


def run_pipeline():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n" + "=" * 70)
    print("  ECMWF SEAS5 (September Initialization) Operational Pipeline")
    print("=" * 70)
    print(f"  Forecast window : DOY {WIN_DOY_START}–{WIN_DOY_END} ({WIN_N_DAYS} days)")
    print(f"  Calibration yrs : {CAL_YEARS[0]}–{CAL_YEARS[-1]} ({len(CAL_YEARS)} yrs)")
    print(f"  Validation yrs  : {VAL_YEARS[0]}–{VAL_YEARS[-1]} ({len(VAL_YEARS)} yrs)")
    print(f"  Inputs dir      : {ECMWF_DIR}")
    print(f"  Output folder   : {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Target Grid & Land Mask Definition (exact 42 × 34 layout)
    target_lat = np.round(np.arange(-4.875, 5.375 + 0.001, 0.25), 3).astype(np.float32)
    target_lon = np.round(np.arange(33.625, 41.875 + 0.001, 0.25), 3).astype(np.float32)
    n_lat, n_lon = len(target_lat), len(target_lon)

    ref_qbar = BASE_DIR / "outputs" / "ecmwf_v3" / "chirps_Q_bar.nc"
    if ref_qbar.exists():
        with xr.open_dataset(ref_qbar) as ds_qb:
            q_arr = list(ds_qb.data_vars.values())[0].values
            lm = ~np.isnan(q_arr)
    else:
        lm = np.ones((n_lat, n_lon), dtype=bool)

    print(f"\n[Step 1/5] Target grid established: {n_lat} lat × {n_lon} lon ({int(lm.sum())} land pixels)")

    # 2. Ingest CHIRPS Observations (1993–2025)
    print("\n[Step 2/5] Ingesting and aligning CHIRPS daily observations ...")
    with xr.open_dataset(CHIRPS_PATH) as ds_c:
        # Reindex lat/lon to target grid
        ds_c_rg = ds_c.reindex(lat=target_lat, lon=target_lon, method="nearest")
        c_time = pd.DatetimeIndex(ds_c_rg.time.values)
        chirps_years = np.unique(c_time.year)
        n_cy = len(chirps_years)

        chirps_daily = np.full((n_cy, 366, n_lat, n_lon), np.nan, dtype=np.float32)
        pr_vals = ds_c_rg["precip"].values

        for yi, yr in enumerate(chirps_years):
            m_yr = (c_time.year == yr)
            sub_t = c_time[m_yr]
            sub_v = pr_vals[m_yr]
            doys = sub_t.dayofyear.values - 1
            chirps_daily[yi, doys] = sub_v

    print(f"  CHIRPS loaded: {chirps_years[0]}–{chirps_years[-1]} ({n_cy} years)")

    # 3. Ingest ECMWF SEAS5 Downloads
    print("\n[Step 3/5] Ingesting 33 ECMWF SEAS5 September forecast files ...")
    pattern = str(ECMWF_DIR / "ecmwf_*09_d01.nc")
    ecmwf_files = sorted(glob.glob(pattern))
    if not ecmwf_files:
        raise FileNotFoundError(f"No ECMWF September files found matching {pattern}")

    file_years = []
    for fp in ecmwf_files:
        yr = int(Path(fp).stem.split("_")[1][:4])
        file_years.append(yr)

    file_years = np.array(file_years)
    n_ey = len(file_years)
    print(f"  Available forecast years: {file_years[0]}–{file_years[-1]} ({n_ey} files)")

    ecmwf_raw = np.full((N_MEMBERS_COMMON, n_ey, WIN_N_DAYS, n_lat, n_lon), np.nan, dtype=np.float32)

    for yi, yr in enumerate(file_years):
        fp = ECMWF_DIR / f"ecmwf_{yr}09_d01.nc"
        with xr.open_dataset(fp) as ds_e:
            tp = ds_e["tp"]
            if "forecast_reference_time" in tp.dims:
                tp = tp.squeeze("forecast_reference_time")
            # Reindex latitude and longitude
            tp_rg = tp.reindex(latitude=target_lat, longitude=target_lon, method="nearest")
            vals = tp_rg.values  # shape: (number, forecast_period, lat, lon)
            
            # Subsample members to N_MEMBERS_COMMON (25)
            n_m = min(vals.shape[0], N_MEMBERS_COMMON)
            
            # Slice forecast period: Day 0 (Sept 1) to Day WIN_N_DAYS-1 (Dec 31)
            vals_win = vals[:n_m, :WIN_N_DAYS, :, :]

            # In ECMWF SEAS5 C3S, 'tp' is cumulative total precipitation in metres.
            # Differentiate along the forecast_period axis (axis=1) to obtain daily precipitation rate in mm/day.
            daily_diff = np.diff(vals_win, axis=1, prepend=0.0)
            daily_diff[daily_diff < 0] = 0.0  # guard against reset/monotonicity artifacts
            daily_mm = daily_diff * 1000.0   # convert m to mm

            ecmwf_raw[:n_m, yi, :, :, :] = daily_mm

    # 4. Member-Wise Empirical Quantile Mapping Bias Correction (EQM-BC)
    print("\n[Step 4/5] Running member-wise Empirical Quantile Mapping daily bias correction ...")
    ecmwf_bc = ecmwf_raw.copy()

    cal_mask_c = np.isin(chirps_years, CAL_YEARS)
    cal_mask_e = np.isin(file_years, CAL_YEARS)
    cal_idx_c  = np.where(cal_mask_c)[0]

    land_pixels = np.argwhere(lm)
    n_land = len(land_pixels)

    for pix_num, (pi, pj) in enumerate(land_pixels):
        if (pix_num + 1) % 150 == 0 or pix_num == n_land - 1:
            print(f"  Calibrating pixel {pix_num+1:4d} / {n_land} ({100*(pix_num+1)/n_land:.0f}%)", flush=True)

        for d in range(WIN_N_DAYS):
            doy_d = WIN_DOY_START + d

            # CHIRPS pool: CAL years ±QM_DOY_WINDOW around doy_d
            idx_start = max(0, doy_d - 1 - QM_DOY_WINDOW)
            idx_end   = min(366, doy_d + QM_DOY_WINDOW)
            c_sub = chirps_daily[cal_idx_c, idx_start:idx_end, pi, pj].ravel()
            c_pool = c_sub[~np.isnan(c_sub)]

            # ECMWF pool: CAL years, day d, all members
            s_pool = ecmwf_raw[:, cal_mask_e, d, pi, pj].ravel()
            s_pool = s_pool[~np.isnan(s_pool)]

            transfer_fn = _build_qm_transfer(c_pool, s_pool)
            ecmwf_bc[:, :, d, pi, pj] = transfer_fn(ecmwf_raw[:, :, d, pi, pj])

    # Save bias-corrected daily NetCDF
    bc_da = xr.DataArray(
        ecmwf_bc,
        dims=["member", "year", "day", "lat", "lon"],
        coords={
            "member": np.arange(1, N_MEMBERS_COMMON + 1),
            "year":   file_years,
            "day":    np.arange(WIN_N_DAYS),
            "lat":    target_lat,
            "lon":    target_lon,
        },
        attrs={"units": "mm/day", "long_name": "Bias-corrected daily precipitation (EQM)"}
    )
    bc_da.to_netcdf(OUT_DIR / "ECMWF_bc_daily_all_years.nc")
    print("  ✓ Saved ECMWF_bc_daily_all_years.nc")

    # 5. Dunning Season Detection & Probabilistic Calibration
    print("\n[Step 5/5] Computing Dunning climatology, season detection & skill calibration ...")
    clim = dl.compute_climatology(
        daily=chirps_daily,
        years=chirps_years,
        cal_years=CAL_YEARS,
        win_doy_start=WIN_DOY_START,
        win_doy_end=WIN_DOY_END,
        land_mask=lm
    )

    # Save baseline climatology
    for k in ["Q_bar", "C_clim", "d_s", "d_e"]:
        val = clim[k]
        dims = ["doy", "lat", "lon"] if val.ndim == 3 else ["lat", "lon"]
        coords = {"doy": np.arange(val.shape[0]), "lat": target_lat, "lon": target_lon} if val.ndim == 3 else {"lat": target_lat, "lon": target_lon}
        xr.DataArray(val, dims=dims, coords=coords).to_netcdf(OUT_DIR / f"chirps_{k}.nc")

    # Detect CHIRPS historical onset/cessation/LGP
    c_onset = np.full((n_cy, n_lat, n_lon), np.nan, dtype=np.float32)
    c_cess  = np.full((n_cy, n_lat, n_lon), np.nan, dtype=np.float32)
    c_lgp   = np.full((n_cy, n_lat, n_lon), np.nan, dtype=np.float32)

    doy_axis = np.arange(WIN_DOY_START, WIN_DOY_END + 1)
    for yi in range(n_cy):
        p_win = chirps_daily[yi, WIN_DOY_START - 1 : WIN_DOY_END, :, :]
        flat_p = p_win[:, lm].T
        res_c = dl.detect_season_batch(
            precip=flat_p,
            Q_bar=clim["Q_bar"][lm],
            d_s=clim["d_s"][lm],
            d_e=clim["d_e"][lm],
            doy_axis=doy_axis,
            win_doy_start=WIN_DOY_START,
            win_doy_end=WIN_DOY_END,
            buffer_days=DUNNING_BUFFER_DAYS,
            min_lgp_days=MIN_LGP_DAYS
        )
        c_onset[yi, lm] = res_c["onset_doy"]
        c_cess[yi, lm]  = res_c["cess_doy"]
        c_lgp[yi, lm]   = res_c["lgp_days"]

    for name, arr in [("onset_doy", c_onset), ("cessation_doy", c_cess), ("lgp_days", c_lgp)]:
        xr.DataArray(arr, dims=["year", "lat", "lon"], coords={"year": chirps_years, "lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"CHIRPS_{name}_1981_2025.nc")

    # Detect ECMWF SEAS5 detections
    e_onset = np.full((N_MEMBERS_COMMON, n_ey, n_lat, n_lon), np.nan, dtype=np.float32)
    e_cess  = np.full((N_MEMBERS_COMMON, n_ey, n_lat, n_lon), np.nan, dtype=np.float32)
    e_lgp   = np.full((N_MEMBERS_COMMON, n_ey, n_lat, n_lon), np.nan, dtype=np.float32)

    for m in range(N_MEMBERS_COMMON):
        for yi in range(n_ey):
            p_mem = ecmwf_bc[m, yi, :, :, :]
            flat_mem = p_mem[:, lm].T
            res_e = dl.detect_season_batch(
                precip=flat_mem,
                Q_bar=clim["Q_bar"][lm],
                d_s=clim["d_s"][lm],
                d_e=clim["d_e"][lm],
                doy_axis=doy_axis,
                win_doy_start=WIN_DOY_START,
                win_doy_end=WIN_DOY_END,
                buffer_days=DUNNING_BUFFER_DAYS,
                min_lgp_days=MIN_LGP_DAYS
            )
            e_onset[m, yi, lm] = res_e["onset_doy"]
            e_cess[m, yi, lm]  = res_e["cess_doy"]
            e_lgp[m, yi, lm]   = res_e["lgp_days"]

    for name, arr in [("onset_doy", e_onset), ("cessation_doy", e_cess), ("lgp_days", e_lgp)]:
        xr.DataArray(arr, dims=["member", "year", "lat", "lon"], coords={"member": np.arange(1, N_MEMBERS_COMMON + 1), "year": file_years, "lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"ECMWF_{name}_all_years.nc")
    print("  ✓ Saved ECMWF & CHIRPS event detection files.")

    # Tercile probabilities & skill damping
    for var_name, e_arr, c_arr in [("onset", e_onset, c_onset), ("cessation", e_cess, c_cess), ("lgp", e_lgp, c_lgp)]:
        t33, t67, _ = dl.estimate_terciles(c_arr[cal_mask_c], lm, min_tercile_years=MIN_TERCILE_YEARS)
        p_raw = dl.estimate_probs(e_arr, t33, t67)  # (3, n_ey, lat, lon)

        overlap_years = np.intersect1d(file_years, chirps_years)
        e_idx = np.where(np.isin(file_years, overlap_years))[0]
        c_idx = np.where(np.isin(chirps_years, overlap_years))[0]

        obs_cat = np.full((len(overlap_years), n_lat, n_lon), -1, dtype=np.int8)
        for i_ov in range(len(overlap_years)):
            v = c_arr[c_idx[i_ov]]
            cat = np.where(v < t33, 0, np.where(v < t67, 1, 2))
            cat[np.isnan(v)] = -1
            obs_cat[i_ov] = cat

        cal_mask_ov = np.isin(overlap_years, CAL_YEARS)
        alpha_star = dl.optimise_alpha(p_raw[:, e_idx[cal_mask_ov]], obs_cat[cal_mask_ov], ALPHA_GRID)
        p_damped = dl.apply_pooling(p_raw, alpha_star)

        # Save calibration tercile boundaries
        cal_dir = OUT_DIR / "calibration_params"
        cal_dir.mkdir(parents=True, exist_ok=True)
        suffix = "doy" if var_name != "lgp" else "days"
        xr.DataArray(t33, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(cal_dir / f"t33_{var_name}_{suffix}.nc")
        xr.DataArray(t67, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(cal_dir / f"t67_{var_name}_{suffix}.nc")

        xr.DataArray(p_damped, dims=["category", "year", "lat", "lon"], coords={"year": file_years, "lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"probs_damped_{var_name}.nc")
        xr.DataArray(alpha_star, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"alpha_{var_name}.nc")

        op_idx = len(file_years) - 1
        xr.DataArray(p_damped[:, op_idx, :, :], dims=["category", "lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"probs_op_{file_years[op_idx]}_{var_name}.nc")

        cal_mask_ov = np.isin(overlap_years, CAL_YEARS)
        if np.sum(cal_mask_ov) > 0:
            rps_cal = dl.rps_batch(p_damped[:, e_idx[cal_mask_ov]], obs_cat[cal_mask_ov])
            rps_clim_c = dl.rps_clim_batch(obs_cat[cal_mask_ov])
            rpss_cal = dl.compute_rpss(np.nanmean(rps_cal, axis=0), np.nanmean(rps_clim_c, axis=0))
            hr_cal = dl.compute_hitrate(p_damped[:, e_idx[cal_mask_ov]], obs_cat[cal_mask_ov])
            xr.DataArray(rpss_cal, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"rpss_{var_name}_cal.nc")
            xr.DataArray(hr_cal, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"hitrate_{var_name}_cal.nc")

        val_mask_ov = np.isin(overlap_years, VAL_YEARS)
        if np.sum(val_mask_ov) > 0:
            rps_val = dl.rps_batch(p_damped[:, e_idx[val_mask_ov]], obs_cat[val_mask_ov])
            rps_clim = dl.rps_clim_batch(obs_cat[val_mask_ov])
            rpss_val = dl.compute_rpss(np.nanmean(rps_val, axis=0), np.nanmean(rps_clim, axis=0))
            hr_val = dl.compute_hitrate(p_damped[:, e_idx[val_mask_ov]], obs_cat[val_mask_ov])
            xr.DataArray(rpss_val, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"rpss_{var_name}_val.nc")
            xr.DataArray(hr_val, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}).to_netcdf(OUT_DIR / f"hitrate_{var_name}_val.nc")

    xr.Dataset({"year": ("year", file_years)}).to_netcdf(OUT_DIR / "model_years.nc")
    print(f"\n  ✓ All NetCDF files written successfully to {OUT_DIR}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_pipeline()
