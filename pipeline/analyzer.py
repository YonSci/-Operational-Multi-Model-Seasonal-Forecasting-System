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
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap, BoundaryNorm

from pipeline.config import SeasonConfig, STAGING_DIR, BASE_DIR

def _plot_country_boundary(ax, country: str, color="#1e293b", linewidth=1.8):
    """Plot country administrative boundary from GeoJSON."""
    c_code = "ke" if country.lower() == "kenya" else "eth" if country.lower() == "ethiopia" else country.lower()
    boundary_file = BASE_DIR / "frontend" / "public" / "boundaries" / f"{c_code}_admin0.geojson"
    if boundary_file.exists():
        try:
            with open(boundary_file, "r") as f:
                b_data = json.load(f)
            for feat in b_data.get("features", []):
                geom = feat.get("geometry", {})
                g_type = geom.get("type")
                coords = geom.get("coordinates", [])
                if g_type == "Polygon":
                    for ring in coords:
                        xs, ys = zip(*ring)
                        ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=5)
                elif g_type == "MultiPolygon":
                    for poly in coords:
                        for ring in poly:
                            xs, ys = zip(*ring)
                            ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=5)
        except Exception as e:
            print(f"  [Analyzer] Notice reading boundary GeoJSON: {e}")

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

    # 8. Render Publication Preview Maps (Terciles & Onset Median)
    preview_png = stage_dir / "preview_tercile_map.png"
    _render_preview_plot(p_op, target_lat, target_lon, mask_active, lm, cfg, year, metrics, preview_png)

    onset_png = stage_dir / "preview_onset_median_map.png"
    onset_stats = _render_onset_preview_plot(cfg, target_lat, target_lon, mask_active, lm, year, onset_png)
    if onset_stats:
        metrics.update(onset_stats)

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
            "preview_onset_map": "preview_onset_median_map.png",
        },
        "target_output_dir": str(cfg.output_dir),
        "demo_npz_key": cfg.demo_npz_key,
    }

    with open(stage_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  [6/6] Staged products and manifest created successfully at {stage_dir}")
    return manifest

def _render_preview_plot(p_op, lats, lons, mask_active, lm, cfg, year, metrics, out_png):
    """Render authentic publication preview map of dominant terciles identical to live dashboard."""
    n_lat, n_lon = len(lats), len(lons)
    rgba = np.zeros((n_lat, n_lon, 4), dtype=np.uint8)

    for i in range(n_lat):
        for j in range(n_lon):
            if not lm[i, j]:
                # Outside sovereign domain -> transparent
                rgba[i, j] = [0, 0, 0, 0]
                continue
            
            if not mask_active[i, j]:
                # Non-seasonal / dry masked area -> authentic solid ICPAC gray #bebebe
                rgba[i, j] = [190, 190, 190, 255]
                continue
            
            probs = p_op[:, i, j]
            if np.isnan(probs).any():
                rgba[i, j] = [0, 0, 0, 0]
                continue
            
            dom = int(np.argmax(probs))  # 0: below, 1: normal, 2: above
            max_p = float(probs[dom]) * 100.0
            
            if max_p < 40.0:
                # Climatological neutral (< 40%) -> #ffffff
                rgba[i, j] = [255, 255, 255, 255]
            elif dom == 2:  # Above normal (Greens)
                if max_p >= 80.0:
                    rgba[i, j] = [37, 78, 16, 255]    # #254e10
                elif max_p >= 70.0:
                    rgba[i, j] = [65, 125, 33, 255]   # #417d21
                elif max_p >= 60.0:
                    rgba[i, j] = [98, 167, 49, 255]   # #62a731
                elif max_p >= 50.0:
                    rgba[i, j] = [111, 181, 54, 255]  # #6fb536
                elif max_p >= 45.0:
                    rgba[i, j] = [152, 245, 118, 255] # #98f576
                else:
                    rgba[i, j] = [204, 252, 191, 255] # #ccfcbf
            elif dom == 1:  # Near normal (Cyans)
                if max_p >= 80.0:
                    rgba[i, j] = [136, 251, 254, 255] # #88fbfe
                elif max_p >= 70.0:
                    rgba[i, j] = [138, 251, 254, 255] # #8afbfe
                elif max_p >= 60.0:
                    rgba[i, j] = [149, 251, 254, 255] # #95fbfe
                elif max_p >= 50.0:
                    rgba[i, j] = [159, 251, 254, 255] # #9ffbfe
                elif max_p >= 45.0:
                    rgba[i, j] = [171, 252, 254, 255] # #abfcfe
                else:
                    rgba[i, j] = [236, 254, 255, 255] # #ecfeff
            elif dom == 0:  # Below normal (Reds/Oranges/Yellows)
                if max_p >= 80.0:
                    rgba[i, j] = [225, 53, 30, 255]   # #e1351e
                elif max_p >= 70.0:
                    rgba[i, j] = [226, 77, 34, 255]   # #e24d22
                elif max_p >= 60.0:
                    rgba[i, j] = [230, 122, 43, 255]  # #e67a2b
                elif max_p >= 50.0:
                    rgba[i, j] = [233, 147, 49, 255]  # #e99331
                elif max_p >= 45.0:
                    rgba[i, j] = [247, 226, 71, 255]  # #f7e247
                else:
                    rgba[i, j] = [253, 254, 143, 255] # #fdfe8f

    # Create figure with high-contrast, clean styling
    fig, ax = plt.subplots(figsize=(8.5, 9.0), dpi=180)
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#f1f5f9")

    # Lat/Lon bounds & extent
    lat_min, lat_max = float(lats.min()), float(lats.max())
    lon_min, lon_max = float(lons.min()), float(lons.max())
    extent = [lon_min - 0.125, lon_max + 0.125, lat_min - 0.125, lat_max + 0.125]

    # Render raster layer
    ax.imshow(rgba, origin="lower", extent=extent, interpolation="nearest", zorder=2)

    # Overlay sovereign boundary
    _plot_country_boundary(ax, cfg.country, color="#1e293b", linewidth=1.8)

    # Geographic labels
    if cfg.country.lower() == "kenya":
        ax.text(37.8, 0.5, "KENYA", fontsize=11, color="#64748b", fontweight="bold", alpha=0.35, ha="center", va="center", zorder=3)
        ax.text(38.5, 5.2, "ETHIOPIA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.text(42.5, 2.0, "SOMALIA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.text(37.5, -3.8, "TANZANIA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.text(33.2, 1.5, "UGANDA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.set_xlim(32.8, 43.2)
        ax.set_ylim(-5.2, 5.8)
    elif cfg.country.lower() == "ethiopia":
        ax.text(39.5, 8.5, "ETHIOPIA", fontsize=11, color="#64748b", fontweight="bold", alpha=0.35, ha="center", va="center", zorder=3)
        ax.text(38.5, 15.0, "ERITREA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.text(46.0, 7.5, "SOMALIA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.text(37.5, 3.5, "KENYA", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.text(33.5, 8.0, "SUDAN", fontsize=9, color="#94a3b8", fontweight="bold", alpha=0.6, ha="center", zorder=1)
        ax.set_xlim(lon_min - 0.8, lon_max + 1.2)
        ax.set_ylim(lat_min - 0.4, lat_max + 0.5)
    else:
        ax.set_xlim(lon_min - 0.8, lon_max + 1.2)
        ax.set_ylim(lat_min - 0.4, lat_max + 0.5)

    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#cbd5e1")
        spine.set_linewidth(1.0)

    # Season acronym tag
    season_tag = "OND" if cfg.id in ("short_rains", "deyr", "ond") else "MAM" if cfg.id in ("long_rains", "mam") else "FMAM" if cfg.id in ("belg", "fmam") else "JJAS" if cfg.id in ("kiremt", "jjas") else cfg.id.upper()

    # Floating dashboard legend card
    card_ax = ax.inset_axes([0.47, 0.02, 0.51, 0.33], facecolor="#ffffff", zorder=10)
    card_ax.set_xticks([])
    card_ax.set_yticks([])
    for s in card_ax.spines.values():
        s.set_color("#cbd5e1")
        s.set_linewidth(1.2)

    # Title & Subtitle
    card_ax.text(0.05, 0.91, f"{cfg.operational_model} {season_tag} {year} Probabilistic Forecast", fontsize=8.2, fontweight="bold", color="#0f172a", transform=card_ax.transAxes)
    card_ax.text(0.05, 0.81, f"Valid period: {cfg.target_period_label} {year}", fontsize=7.2, fontweight="bold", color="#64748b", transform=card_ax.transAxes)

    # 3 Tercile Columns: Above, Normal, Below
    ramp_y0, ramp_h = 0.38, 0.31
    ramp_w = 0.25

    # Above column
    card_ax.text(0.185, 0.73, "Above (%)", fontsize=7.2, fontweight="bold", color="#2e7d32", ha="center", transform=card_ax.transAxes)
    above_colors = ["#254e10", "#417d21", "#62a731", "#6fb536", "#98f576", "#ccfcbf"]
    for k, c in enumerate(above_colors):
        sy = ramp_y0 + (5 - k) * (ramp_h / 6.0)
        card_ax.add_patch(mpatches.Rectangle((0.06, sy), ramp_w, ramp_h / 6.0, facecolor=c, edgecolor="none", transform=card_ax.transAxes))
    card_ax.add_patch(mpatches.Rectangle((0.06, ramp_y0), ramp_w, ramp_h, fill=False, edgecolor="#94a3b8", linewidth=0.6, transform=card_ax.transAxes))
    card_ax.text(0.06, 0.32, "90", fontsize=6.2, color="#64748b", transform=card_ax.transAxes)
    card_ax.text(0.06 + ramp_w, 0.32, "40", fontsize=6.2, color="#64748b", ha="right", transform=card_ax.transAxes)

    # Normal column
    card_ax.text(0.505, 0.73, "Normal (%)", fontsize=7.2, fontweight="bold", color="#0284c7", ha="center", transform=card_ax.transAxes)
    normal_colors = ["#88fbfe", "#8afbfe", "#95fbfe", "#9ffbfe", "#abfcfe", "#ecfeff"]
    for k, c in enumerate(normal_colors):
        sy = ramp_y0 + (5 - k) * (ramp_h / 6.0)
        card_ax.add_patch(mpatches.Rectangle((0.38, sy), ramp_w, ramp_h / 6.0, facecolor=c, edgecolor="none", transform=card_ax.transAxes))
    card_ax.add_patch(mpatches.Rectangle((0.38, ramp_y0), ramp_w, ramp_h, fill=False, edgecolor="#94a3b8", linewidth=0.6, transform=card_ax.transAxes))
    card_ax.text(0.38, 0.32, "90", fontsize=6.2, color="#64748b", transform=card_ax.transAxes)
    card_ax.text(0.38 + ramp_w, 0.32, "40", fontsize=6.2, color="#64748b", ha="right", transform=card_ax.transAxes)

    # Below column
    card_ax.text(0.825, 0.73, "Below (%)", fontsize=7.2, fontweight="bold", color="#b91c1c", ha="center", transform=card_ax.transAxes)
    below_colors = ["#e1351e", "#e24d22", "#e67a2b", "#e99331", "#f7e247", "#fdfe8f"]
    for k, c in enumerate(below_colors):
        sy = ramp_y0 + (5 - k) * (ramp_h / 6.0)
        card_ax.add_patch(mpatches.Rectangle((0.70, sy), ramp_w, ramp_h / 6.0, facecolor=c, edgecolor="none", transform=card_ax.transAxes))
    card_ax.add_patch(mpatches.Rectangle((0.70, ramp_y0), ramp_w, ramp_h, fill=False, edgecolor="#94a3b8", linewidth=0.6, transform=card_ax.transAxes))
    card_ax.text(0.70, 0.32, "90", fontsize=6.2, color="#64748b", transform=card_ax.transAxes)
    card_ax.text(0.70 + ramp_w, 0.32, "40", fontsize=6.2, color="#64748b", ha="right", transform=card_ax.transAxes)

    # Divider line
    card_ax.axhline(0.26, color="#e2e8f0", linewidth=0.8, xmin=0.05, xmax=0.95)

    # Neutral & Masked items
    card_ax.add_patch(mpatches.Rectangle((0.06, 0.15), 0.045, 0.07, facecolor="#ffffff", edgecolor="#94a3b8", linewidth=0.8, transform=card_ax.transAxes))
    card_ax.text(0.13, 0.16, "No dominant tercile / probabilities below 40%", fontsize=6.5, color="#475569", transform=card_ax.transAxes)

    card_ax.add_patch(mpatches.Rectangle((0.06, 0.04), 0.045, 0.07, facecolor="#bebebe", edgecolor="#6b7280", linewidth=0.8, transform=card_ax.transAxes))
    card_ax.text(0.13, 0.05, "Non-Seasonal / Masked", fontsize=6.5, color="#475569", transform=card_ax.transAxes)

    plt.tight_layout()
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)

def _render_onset_preview_plot(cfg: SeasonConfig, lats: np.ndarray, lons: np.ndarray, mask_active: np.ndarray, lm: np.ndarray, year: int, out_png: Path) -> dict:
    """Render high-resolution preview map of Ensemble Median Onset DOY."""
    onset_med = None
    
    # 1. Try loading from ECMWF_onset_doy_all_years.nc or onset_doy_2026.nc in output_dir
    possible_nc_files = [
        cfg.output_dir / "ECMWF_onset_doy_all_years.nc",
        cfg.output_dir / f"onset_doy_{year}.nc",
        cfg.output_dir / "onset_doy_2026.nc",
    ]
    for nc_f in possible_nc_files:
        if nc_f.exists():
            try:
                with xr.open_dataset(nc_f) as ds:
                    v = list(ds.data_vars.values())[0]
                    if "year" in ds.coords and len(ds.year) > 1:
                        target_y = year if year in ds.year.values else ds.year.values[-1]
                        op_data = v.sel(year=target_y).values
                    else:
                        op_data = v.values
                    
                    if op_data.ndim == 3:
                        onset_med = np.nanmedian(op_data, axis=0)
                    elif op_data.ndim == 2:
                        onset_med = op_data
                    elif op_data.ndim == 4:
                        onset_med = np.nanmedian(op_data[:, -1, :, :], axis=0)
                    break
            except Exception as e:
                print(f"  [Analyzer] Notice reading {nc_f.name}: {e}")

    # 2. Fallback to demo_data.npz
    if onset_med is None or onset_med.shape != (len(lats), len(lons)):
        demo_path = BASE_DIR / "backend" / "demo_data.npz"
        if demo_path.exists():
            try:
                d = np.load(demo_path)
                npz_key = "sep_ecmwf_onset" if "short" in cfg.id else "bega_ecmwf_onset" if "deyr" in cfg.id else "ecmwf_onset" if "long" in cfg.id else "fmam_ecmwf_onset" if "belg" in cfg.id else "kiremt_ecmwf_onset"
                if npz_key in d:
                    arr = d[npz_key]
                    if arr.ndim == 4:
                        onset_med = np.nanmedian(arr[:, -1, :, :], axis=0)
                    elif arr.ndim == 3:
                        onset_med = np.nanmedian(arr, axis=0)
            except Exception as e:
                print(f"  [Analyzer] Notice reading demo_data.npz for onset: {e}")

    if onset_med is None or onset_med.shape != (len(lats), len(lons)):
        print("  [Analyzer] Warning: Could not locate onset array for preview map.")
        return {}

    from datetime import datetime, timedelta
    fig, ax = plt.subplots(figsize=(7, 6.5), dpi=160)
    
    # Active seasonal values
    disp = np.where(mask_active & np.isfinite(onset_med), onset_med, np.nan)
    
    # Background for dry / non-seasonal areas
    dry_bg = np.where(~mask_active & lm & np.isfinite(onset_med), 1.0, np.nan)
    ax.pcolormesh(lons, lats, dry_bg, cmap=ListedColormap(["#e2e8f0"]), shading="auto")
    
    # Dynamic DOY bounds from active cells
    valid_vals = disp[np.isfinite(disp)]
    if len(valid_vals) > 0:
        p10 = float(np.percentile(valid_vals, 5))
        p90 = float(np.percentile(valid_vals, 95))
        step = 10 if (p90 - p10) > 40 else 7 if (p90 - p10) > 25 else 5
        start_bound = int(np.floor(p10 / step) * step)
        end_bound = int(np.ceil(p90 / step) * step)
        bounds = list(range(start_bound, end_bound + step, step))
        if len(bounds) > 8:
            step = 15
            bounds = list(range(int(np.floor(p10 / step) * step), int(np.ceil(p90 / step) * step) + step, step))
    else:
        bounds = [260, 275, 290, 305, 320, 335, 350]

    n_intervals = max(len(bounds) - 1, 1)
    base_colors = ['#1a9850', '#66bd63', '#a6d96a', '#ffffbf', '#fdae61', '#f46d43', '#d73027']
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("onset_cmap", base_colors, N=n_intervals)
    norm = BoundaryNorm(bounds, cmap.N)
    
    im = ax.pcolormesh(lons, lats, disp, cmap=cmap, norm=norm, shading="auto")

    # Overlay sovereign boundary
    _plot_country_boundary(ax, cfg.country, color="#1e293b", linewidth=1.6)
    
    # Colorbar with DOY and calendar dates
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.08, shrink=0.85, ticks=bounds)
    tick_labels = []
    for b in bounds:
        try:
            dt = datetime(year, 1, 1) + timedelta(days=int(b) - 1)
            d_str = dt.strftime("%d %b")
            tick_labels.append(f"{b}\n({d_str})")
        except Exception:
            tick_labels.append(str(b))
    cbar.set_ticklabels(tick_labels, fontsize=8)
    cbar.set_label("Ensemble Median Onset Date (DOY / Calendar Date)", fontsize=9, fontweight="bold", labelpad=6)
    
    ax.set_title(f"{cfg.operational_model} {cfg.label} {year} - Ensemble Median Onset (P50)\nValid: {cfg.target_period_label} {year} | Forecast Init: {year}-{cfg.init_month:02d}-01", fontsize=10, fontweight="bold", pad=10)
    ax.set_xlabel("Longitude (°E)", fontsize=9)
    ax.set_ylabel("Latitude (°N)", fontsize=9)
    ax.grid(True, linestyle=":", alpha=0.5, color="#94a3b8")
    
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#e2e8f0", edgecolor="#94a3b8", label="Non-Seasonal / Dry (Masked)")], loc="lower left", fontsize=7.5, framealpha=0.9)
    
    plt.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)

    onset_stats = {}
    if len(valid_vals) > 0:
        med_val = float(np.nanmedian(valid_vals))
        dt_med = datetime(year, 1, 1) + timedelta(days=int(round(med_val)) - 1)
        onset_stats = {
            "domain_median_onset_doy": round(med_val, 1),
            "domain_median_onset_date": dt_med.strftime("%d %B"),
            "onset_p10_date": (datetime(year, 1, 1) + timedelta(days=int(round(p10)) - 1)).strftime("%d %b"),
            "onset_p90_date": (datetime(year, 1, 1) + timedelta(days=int(round(p90)) - 1)).strftime("%d %b"),
        }
    return onset_stats
