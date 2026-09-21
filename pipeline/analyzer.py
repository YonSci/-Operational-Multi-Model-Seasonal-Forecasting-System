"""
pipeline/analyzer.py
────────────────────
Method 2 Analysis Engine: Raw Dynamical GCM Ensemble Ingestion,
Empirical Quantile Mapping against GCM Model Climate, and
Bayesian Skill Shrinkage for any Country and Season.
"""

import os
import sys
import glob
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple

import numpy as np
import xarray as xr
import pandas as pd
from scipy.interpolate import RegularGridInterpolator
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

from pipeline.config import SeasonConfig, STAGING_DIR, BASE_DIR

def run_analysis(
    cfg: SeasonConfig,
    year: int,
    gcm_file: Path,
    run_id: str | None = None,
) -> Dict[str, Any]:
    """
    Execute Method 2 dynamical post-processing for the given season configuration.
    Stages output files in outputs/staging/<run_id> and returns an execution digest.
    """
    if run_id is None:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_id = f"RUN-{cfg.country.upper()}-{cfg.id.upper()}{year}-{timestamp}"

    stage_dir = STAGING_DIR / run_id
    stage_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*78}")
    print(f"  ANALYZER: Executing Method 2 Dynamical Post-Processing")
    print(f"  Target: {cfg.country.title()} {cfg.label} ({year})")
    print(f"  Staging Directory: {stage_dir}")
    print(f"{'='*78}")

    # 1. Target Grid & Mask Setup
    lat_s, lat_e, lat_step = cfg.target_lats
    lon_s, lon_e, lon_step = cfg.target_lons
    target_lat = np.round(np.arange(lat_s, lat_e + 0.001, lat_step), 3).astype(np.float32)
    target_lon = np.round(np.arange(lon_s, lon_e + 0.001, lon_step), 3).astype(np.float32)
    n_lat, n_lon = len(target_lat), len(target_lon)

    # Load sovereign land mask
    lm = np.ones((n_lat, n_lon), dtype=bool)
    qbar_file = cfg.output_dir / "chirps_Q_bar.nc"
    if qbar_file.exists():
        with xr.open_dataset(qbar_file) as ds_qb:
            q_arr = list(ds_qb.data_vars.values())[0].values
            if q_arr.shape == (n_lat, n_lon):
                lm = ~np.isnan(q_arr)
    else:
        demo_npz_path = BASE_DIR / "backend" / "demo_data.npz"
        if demo_npz_path.exists():
            d = np.load(demo_npz_path)
            lm_key = "bega_lm" if cfg.country == "ethiopia" else "lm"
            if lm_key in d and d[lm_key].shape == (n_lat, n_lon):
                lm = d[lm_key].astype(bool)

    # Load seasonal mask
    mask_active = lm.copy()
    if cfg.mask_file.exists():
        with xr.open_dataset(cfg.mask_file) as ds_m:
            vname = cfg.mask_var if cfg.mask_var in ds_m else list(ds_m.data_vars.keys())[0]
            m_arr = ds_m[vname].values.astype(bool)
            if m_arr.shape == (n_lat, n_lon):
                mask_active = m_arr & lm

    n_land = int(np.sum(lm))
    n_active = int(np.sum(mask_active))
    print(f"  [1/6] Grid established: {n_lat}x{n_lon} ({n_land} land px | {n_active} active seasonal px)")

    # 2. CHIRPS Historical Calibration Baseline (1993–2016)
    if not cfg.chirps_path.exists():
        raise FileNotFoundError(f"CHIRPS file missing: {cfg.chirps_path}")

    with xr.open_dataset(cfg.chirps_path) as ds_c:
        # Reindex if lat/lon differs slightly
        if len(ds_c.lat) != n_lat or len(ds_c.lon) != n_lon or not np.allclose(ds_c.lat.values[:n_lat], target_lat):
            ds_c_rg = ds_c.reindex(lat=target_lat, lon=target_lon, method="nearest")
        else:
            ds_c_rg = ds_c
        pr = ds_c_rg["precip"]
        time_idx = pd.to_datetime(ds_c_rg.time.values)

        cal_years = np.arange(1993, 2017)
        cal_totals = []
        for y in cal_years:
            if cfg.id in ("short_rains", "deyr", "ond"):
                mask_y = (time_idx >= f"{y}-10-01") & (time_idx <= f"{y}-12-31")
            elif cfg.id in ("long_rains", "mam"):
                mask_y = (time_idx >= f"{y}-03-01") & (time_idx <= f"{y}-05-31")
            elif cfg.id in ("belg", "fmam"):
                mask_y = (time_idx >= f"{y}-02-01") & (time_idx <= f"{y}-05-31")
            elif cfg.id in ("kiremt", "jjas"):
                mask_y = (time_idx >= f"{y}-06-01") & (time_idx <= f"{y}-09-30")
            else:
                mask_y = (time_idx >= f"{y}-10-01") & (time_idx <= f"{y}-12-31")

            tot = pr.isel(time=mask_y).sum(dim="time").values
            cal_totals.append(tot)
        cal_totals = np.stack(cal_totals, axis=0).astype(np.float32)

    t33 = np.percentile(cal_totals, 33.333, axis=0).astype(np.float32)
    t67 = np.percentile(cal_totals, 66.667, axis=0).astype(np.float32)
    print(f"  [2/6] CHIRPS baseline (1993-2016): mean T33={np.mean(t33[mask_active]):.1f} mm, mean T67={np.mean(t67[mask_active]):.1f} mm")

    # 3. Ingest GCM Forecast & Hindcasts
    if not Path(gcm_file).exists():
        month_tag = "sep" if cfg.init_month == 9 else "feb" if cfg.init_month == 2 else "may"
        fallback_gcm = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / f"ecmwf_{month_tag}" / f"ecmwf_{year}{cfg.init_month:02d}_d01.nc"
        if fallback_gcm.exists():
            gcm_file = fallback_gcm

    ds_op = xr.open_dataset(gcm_file)
    n_members_op = len(ds_op.number)
    gcm_lats = ds_op.latitude.values.astype(np.float64)
    gcm_lons = ds_op.longitude.values.astype(np.float64)

    # Extract cumulative seasonal precipitation
    tp_raw = ds_op["tp"]
    p_start_idx = cfg.lead_start_day - 1
    p_end_idx = cfg.lead_end_day - 1
    if len(ds_op.forecast_period) >= cfg.lead_end_day:
        tp_op = tp_raw.isel(forecast_reference_time=0, forecast_period=p_end_idx).values - \
                tp_raw.isel(forecast_reference_time=0, forecast_period=p_start_idx).values
    else:
        tp_op = tp_raw.isel(forecast_reference_time=0, forecast_period=-1).values
    tp_op_mm = np.maximum(0.0, tp_op * 1000.0).astype(np.float32)

    # Ingest historical hindcasts (1993-2016)
    hist_files = sorted(glob.glob(str(cfg.raw_download_dir / f"ecmwf_*0{cfg.init_month}_d01.nc")))
    if not hist_files:
        hist_files = sorted(glob.glob(str(cfg.raw_download_dir / f"ecmwf_*{cfg.init_month:02d}_d01.nc")))
    if not hist_files:
        month_tag = "sep" if cfg.init_month == 9 else "feb" if cfg.init_month == 2 else "may"
        fallback_dir = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / f"ecmwf_{month_tag}"
        hist_files = sorted(glob.glob(str(fallback_dir / f"ecmwf_*{cfg.init_month:02d}_d01.nc")))
    gcm_hist_list = []
    for hf in hist_files:
        try:
            yr = int(Path(hf).stem.split("_")[1][:4])
        except Exception:
            continue
        if yr in cal_years:
            ds_h = xr.open_dataset(hf)
            tp_h_raw = ds_h["tp"]
            if len(ds_h.forecast_period) >= cfg.lead_end_day:
                tp_h = tp_h_raw.isel(forecast_reference_time=0, forecast_period=p_end_idx).values - \
                       tp_h_raw.isel(forecast_reference_time=0, forecast_period=p_start_idx).values
            else:
                tp_h = tp_h_raw.isel(forecast_reference_time=0, forecast_period=-1).values
            gcm_hist_list.append(np.maximum(0.0, tp_h * 1000.0).astype(np.float32))

    if not gcm_hist_list:
        raise FileNotFoundError(f"No GCM historical hindcasts found in {cfg.raw_download_dir}")
    gcm_hist_all = np.concatenate(gcm_hist_list, axis=0)
    print(f"  [3/6] Ingested GCM data: {n_members_op} operational members (2026) | {len(gcm_hist_all)} hindcast members (1993-2016)")

    # 4. Bilinear Spatial Regridding
    lat_sort_idx = np.argsort(gcm_lats)
    lon_sort_idx = np.argsort(gcm_lons)
    gcm_lats_sorted = gcm_lats[lat_sort_idx]
    gcm_lons_sorted = gcm_lons[lon_sort_idx]

    tp_op_sorted = tp_op_mm[:, lat_sort_idx, :][:, :, lon_sort_idx]
    tp_hist_sorted = gcm_hist_all[:, lat_sort_idx, :][:, :, lon_sort_idx]

    mesh_lon, mesh_lat = np.meshgrid(target_lon, target_lat)
    pts = np.column_stack([mesh_lat.ravel(), mesh_lon.ravel()])

    regrid_op = np.zeros((n_members_op, n_lat, n_lon), dtype=np.float32)
    for m in range(n_members_op):
        interp = RegularGridInterpolator((gcm_lats_sorted, gcm_lons_sorted), tp_op_sorted[m], bounds_error=False, fill_value=None)
        regrid_op[m] = interp(pts).reshape((n_lat, n_lon))
    regrid_op = np.maximum(0.0, regrid_op)

    regrid_hist = np.zeros((len(gcm_hist_all), n_lat, n_lon), dtype=np.float32)
    for m in range(len(gcm_hist_all)):
        interp = RegularGridInterpolator((gcm_lats_sorted, gcm_lons_sorted), tp_hist_sorted[m], bounds_error=False, fill_value=None)
        regrid_hist[m] = interp(pts).reshape((n_lat, n_lon))
    regrid_hist = np.maximum(0.0, regrid_hist)

    domain_mean_op = float(np.mean(regrid_op[:, mask_active]))
    domain_mean_hist = float(np.mean(regrid_hist[:, mask_active]))
    anomaly_pct = ((domain_mean_op - domain_mean_hist) / domain_mean_hist) * 100.0 if domain_mean_hist > 0 else 0.0
    print(f"  [4/6] Regridded: Forecast mean={domain_mean_op:.1f} mm | Model climate={domain_mean_hist:.1f} mm (Anomaly: {anomaly_pct:+.1f}%)")

    # 5. Method 2 Empirical Quantile Mapping & Skill Shrinkage
    p_bn_raw = np.zeros((n_lat, n_lon), dtype=np.float32)
    p_nn_raw = np.zeros((n_lat, n_lon), dtype=np.float32)
    p_an_raw = np.zeros((n_lat, n_lon), dtype=np.float32)

    for i in range(n_lat):
        for j in range(n_lon):
            if lm[i, j]:
                mod_h_sorted = np.sort(regrid_hist[:, i, j])
                obs_h_sorted = np.sort(cal_totals[:, i, j])
                n_mod_h = len(mod_h_sorted)

                q_members = np.searchsorted(mod_h_sorted, regrid_op[:, i, j]) / float(n_mod_h)
                q_members = np.clip(q_members, 0.01, 0.99)

                obs_mapped = np.quantile(obs_h_sorted, q_members)

                bn_cnt = np.sum(obs_mapped < t33[i, j])
                an_cnt = np.sum(obs_mapped >= t67[i, j])
                nn_cnt = n_members_op - bn_cnt - an_cnt

                p_bn_raw[i, j] = bn_cnt / float(n_members_op)
                p_nn_raw[i, j] = nn_cnt / float(n_members_op)
                p_an_raw[i, j] = an_cnt / float(n_members_op)
            else:
                p_bn_raw[i, j] = 0.3333
                p_nn_raw[i, j] = 0.3334
                p_an_raw[i, j] = 0.3333

    # Bayesian skill shrinkage
    alpha = np.full((n_lat, n_lon), 0.70, dtype=np.float32)
    rpss_file = cfg.output_dir / "rpss_onset_val.nc"
    if rpss_file.exists():
        try:
            with xr.open_dataset(rpss_file) as ds_rpss:
                r_val = list(ds_rpss.data_vars.values())[0].values
                if r_val.shape == (n_lat, n_lon):
                    alpha = np.clip(0.50 + 0.50 * np.maximum(0.0, r_val), 0.45, 0.85).astype(np.float32)
        except Exception:
            pass

    p_bn_damped = alpha * p_bn_raw + (1.0 - alpha) / 3.0
    p_nn_damped = alpha * p_nn_raw + (1.0 - alpha) / 3.0
    p_an_damped = alpha * p_an_raw + (1.0 - alpha) / 3.0

    prob_sum = p_bn_damped + p_nn_damped + p_an_damped
    p_bn_damped /= prob_sum
    p_nn_damped /= prob_sum
    p_an_damped /= prob_sum

    p_op = np.stack([p_bn_damped, p_nn_damped, p_an_damped], axis=0).astype(np.float32)

    # 6. Compute Category Statistics
    an_active = p_an_damped[mask_active]
    nn_active = p_nn_damped[mask_active]
    bn_active = p_bn_damped[mask_active]

    max_p = np.max(p_op[:, mask_active], axis=0)
    dom_cat = np.argmax(p_op[:, mask_active], axis=0)
    is_neutral = (max_p < 0.40)

    n_an = int(np.sum((dom_cat == 2) & (~is_neutral)))
    n_nn = int(np.sum((dom_cat == 1) & (~is_neutral)))
    n_bn = int(np.sum((dom_cat == 0) & (~is_neutral)))
    n_neu = int(np.sum(is_neutral))

    metrics = {
        "mean_an": round(float(np.mean(an_active) * 100), 1),
        "min_an": round(float(np.min(an_active) * 100), 1),
        "max_an": round(float(np.max(an_active) * 100), 1),
        "mean_nn": round(float(np.mean(nn_active) * 100), 1),
        "mean_bn": round(float(np.mean(bn_active) * 100), 1),
        "above_cells": n_an,
        "above_pct": round(n_an / n_active * 100, 1),
        "normal_cells": n_nn,
        "normal_pct": round(n_nn / n_active * 100, 1),
        "below_cells": n_bn,
        "below_pct": round(n_bn / n_active * 100, 1),
        "neutral_cells": n_neu,
        "neutral_pct": round(n_neu / n_active * 100, 1),
        "active_cells": n_active,
        "land_cells": n_land,
        "domain_mean_op_mm": round(domain_mean_op, 1),
        "domain_mean_hist_mm": round(domain_mean_hist, 1),
        "anomaly_pct": round(anomaly_pct, 1),
    }

    # 7. Export Staged NetCDFs
    xr.DataArray(
        p_op, dims=["tercile", "lat", "lon"], coords={"tercile": [0, 1, 2], "lat": target_lat, "lon": target_lon},
        name="probs_op_2026_rainfall",
        attrs={"model": cfg.operational_model, "season": cfg.id, "year": year}
    ).to_netcdf(stage_dir / "probs_op_2026_rainfall.nc")

    all_years = np.arange(1993, year + 1)
    p_damped_all = np.repeat(p_op[:, np.newaxis, :, :], len(all_years), axis=1)
    xr.DataArray(
        p_damped_all, dims=["category", "year", "lat", "lon"],
        coords={"category": [0, 1, 2], "year": all_years, "lat": target_lat, "lon": target_lon},
        name="probs_damped_rainfall"
    ).to_netcdf(stage_dir / "probs_damped_rainfall.nc")

    xr.DataArray(t33, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}, name="t33_rainfall").to_netcdf(stage_dir / "t33_rainfall.nc")
    xr.DataArray(t67, dims=["lat", "lon"], coords={"lat": target_lat, "lon": target_lon}, name="t67_rainfall").to_netcdf(stage_dir / "t67_rainfall.nc")

    # 8. Render Publication Preview Map (PNG)
    preview_png = stage_dir / "preview_tercile_map.png"
    _render_preview_plot(p_op, target_lat, target_lon, mask_active, lm, cfg, year, metrics, preview_png)

    # 9. Create Staging Manifest
    approval_token = secrets.token_urlsafe(16)
    manifest = {
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "STAGED_PENDING_APPROVAL",
        "country": cfg.country,
        "season_id": cfg.id,
        "season_label": cfg.label,
        "forecast_year": year,
        "init_date": f"{year}-{cfg.init_month:02d}-01",
        "target_period": cfg.target_period_label,
        "model": cfg.operational_model,
        "approval_token": approval_token,
        "metrics": metrics,
        "files": {
            "probs_op": "probs_op_2026_rainfall.nc",
            "probs_damped": "probs_damped_rainfall.nc",
            "t33": "t33_rainfall.nc",
            "t67": "t67_rainfall.nc",
            "preview_map": "preview_tercile_map.png",
        },
        "target_output_dir": str(cfg.output_dir),
        "demo_npz_key": cfg.demo_npz_key,
    }

    with open(stage_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  [6/6] Staged products and manifest created successfully at {stage_dir}")
    return manifest

def _render_preview_plot(p_op, lats, lons, mask_active, lm, cfg, year, metrics, out_png):
    """Render high-resolution preview map of dominant terciles."""
    fig, ax = plt.subplots(figsize=(7, 6.5), dpi=160)
    
    # Calculate dominant category and display value
    # Categories: 0: Below (Red/Yellow), 1: Normal (Cyan), 2: Above (Green), 3: Neutral (White), 4: Dry (Gray)
    grid_display = np.full((len(lats), len(lons)), np.nan)
    max_p = np.max(p_op, axis=0)
    dom_cat = np.argmax(p_op, axis=0)

    for i in range(len(lats)):
        for j in range(len(lons)):
            if not lm[i, j]:
                continue
            if not mask_active[i, j]:
                grid_display[i, j] = 4  # Dry/Non-seasonal
            elif max_p[i, j] < 0.40:
                grid_display[i, j] = 3  # Neutral / Climatology
            else:
                grid_display[i, j] = dom_cat[i, j]

    cmap = ListedColormap(["#e1351e", "#88fbfe", "#417d21", "#ffffff", "#bebebe"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap.N)

    im = ax.pcolormesh(lons, lats, grid_display, cmap=cmap, norm=norm, shading="auto")
    ax.set_title(f"{cfg.operational_model} {cfg.label} {year} Probabilistic Forecast\nValid: {cfg.target_period_label} {year} | Init: {year}-{cfg.init_month:02d}-01", fontsize=10, fontweight="bold", pad=10)
    ax.set_xlabel("Longitude (°E)", fontsize=9)
    ax.set_ylabel("Latitude (°N)", fontsize=9)
    ax.grid(True, linestyle=":", alpha=0.5, color="#64748b")

    # Add custom legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#417d21", edgecolor="#14532d", label=f"Above Normal: {metrics['above_cells']} px ({metrics['above_pct']}%)"),
        Patch(facecolor="#88fbfe", edgecolor="#0284c7", label=f"Near Normal: {metrics['normal_cells']} px ({metrics['normal_pct']}%)"),
        Patch(facecolor="#e1351e", edgecolor="#991b1b", label=f"Below Normal: {metrics['below_cells']} px ({metrics['below_pct']}%)"),
        Patch(facecolor="#ffffff", edgecolor="#94a3b8", label=f"No Dominant Tercile (<40%): {metrics['neutral_cells']} px ({metrics['neutral_pct']}%)"),
        Patch(facecolor="#bebebe", edgecolor="#6b7280", label=f"Non-Seasonal / Dry (Masked)"),
    ]
    ax.legend(handles=legend_elements, loc="lower left", fontsize=7.5, framealpha=0.9)

    plt.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)
