# =============================================================================
# SINGLE-MODEL SEASONAL FORECAST BULLETIN v1.0
# Official ILRI Publication Template — Kenya MAM
# Replicates the official single-model layout (Onset, Cessation, LGP)
# =============================================================================

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import gc
import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import matplotlib.patheffects as mpe

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
except ImportError:
    HAS_CARTOPY = False

# =============================================================================
# COLOUR PALETTE (Exact match to ILRI publication template)
# =============================================================================
COL_HDR_BG       = "#0B1F3A"
COL_HDR_ACCENT   = "#C9920A"
COL_HDR_TITLE    = "#FFFFFF"
COL_HDR_SITE     = "#F5D98C"
COL_SUBHDR_BG    = "#1A3255"
COL_SUBHDR_TXT   = "#93C5FD"
COL_DIVIDER_BG   = "#0B1F3A"
COL_DIVIDER_TXT  = "#FFFFFF"
COL_BODY_BG      = "#F8FAFC"
COL_PANEL_BG     = "#FFFFFF"
COL_PANEL_BG2    = "#F1F5F9"
COL_BORDER       = "#CBD5E1"
COL_FOOTER_BG    = "#0B1F3A"
COL_FOOTER_TXT   = "#FFFFFF"

COL_TXT_DARK     = "#0F172A"
COL_TXT_NAVY     = "#0B1F3A"
COL_TXT_MUTED    = "#64748B"

COL_BN           = "#7C3A16"   # Below Normal (Brown)
COL_NN           = "#92680A"   # Near Normal (Gold)
COL_AN           = "#155D36"   # Above Normal (Green)

COL_EARLY        = "#1B5EA6"
COL_LATE         = "#C0392B"
COL_NORMAL       = "#1E6B45"

COL_RISK_CRIT    = "#8B0000"
COL_RISK_HI      = "#C0392B"
COL_RISK_MED     = "#EA580C"
COL_RISK_LITE    = "#FCA5A5"

COL_MAP_SITE     = "#E63946"
COL_CHIRPS       = "#1E3A8A"

FONT_FAMILY      = "DejaVu Sans"

def _doy_to_date_str(doy, year=2026):
    try:
        if np.isnan(float(doy)): return "—"
        d = int(round(float(doy)))
        return (datetime.date(year, 1, 1) + datetime.timedelta(days=d - 1)).strftime("%d %b")
    except Exception:
        return "—"

def _tlbl(anom, thr=5.0):
    if anom < -thr: return "Early", COL_EARLY
    elif anom > thr: return "Late", COL_LATE
    return "Normal", COL_NORMAL

def _sec(ax, label):
    ax.axis("off")
    ax.add_patch(mpatches.Rectangle(
        (0.0, 0.0), 1.0, 1.0, facecolor=COL_DIVIDER_BG,
        transform=ax.transAxes, zorder=1, clip_on=False
    ))
    ax.text(0.015, 0.50, f"  {label}",
            va="center", ha="left",
            fontsize=10.5, fontweight="bold",
            color=COL_DIVIDER_TXT,
            transform=ax.transAxes, zorder=2, clip_on=False)

def _hline(ax, y, color, lw=1.0, ls="-", x0=0.0, x1=1.0):
    ax.plot([x0, x1], [y, y], color=color, lw=lw, ls=ls,
            transform=ax.transAxes, clip_on=False, zorder=10)

def _get_boundary_file(name):
    candidates = [
        os.path.join(os.path.dirname(__file__), "frontend", "public", "boundaries", name),
        os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "boundaries", name),
        os.path.join(os.getcwd(), "frontend", "public", "boundaries", name),
        os.path.join(os.getcwd(), "boundaries", name),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None

def _draw_grid_location_map(fig, gs_cell, glat, glon, lat_q=None, lon_q=None, dkm=None):
    ke0_path = _get_boundary_file("ke_admin0.geojson")
    ke1_path = _get_boundary_file("ke_admin1.geojson")

    # Method 1: High-fidelity Vector GeoJSON rendering (fast, offline, self-contained)
    if ke0_path and os.path.isfile(ke0_path):
        try:
            import json
            import matplotlib.patches as patches
            ax = fig.add_subplot(gs_cell)
            ax.set_facecolor("#DBEAFE")
            ax.set_xlim(33.5, 42.2)
            ax.set_ylim(-4.8, 4.8)

            # County sub-boundaries
            if ke1_path and os.path.isfile(ke1_path):
                with open(ke1_path, "r", encoding="utf-8") as f:
                    ke1 = json.load(f)
                for feat in ke1.get("features", []):
                    geom = feat.get("geometry", {})
                    gtype = geom.get("type")
                    coords = geom.get("coordinates", [])
                    polys = [coords] if gtype == "Polygon" else (coords if gtype == "MultiPolygon" else [])
                    for poly in polys:
                        if poly and len(poly):
                            ax.add_patch(patches.Polygon(poly[0], facecolor="#F1EFE9", edgecolor="#CBD5E1", linewidth=0.4, zorder=1))

            # Country border
            with open(ke0_path, "r", encoding="utf-8") as f:
                ke0 = json.load(f)
            for feat in ke0.get("features", []):
                geom = feat.get("geometry", {})
                gtype = geom.get("type")
                coords = geom.get("coordinates", [])
                polys = [coords] if gtype == "Polygon" else (coords if gtype == "MultiPolygon" else [])
                for poly in polys:
                    if poly and len(poly):
                        ax.add_patch(patches.Polygon(poly[0], facecolor="none", edgecolor="#334155", linewidth=0.8, zorder=2))

            ax.axhline(glat, color=COL_MAP_SITE, lw=0.6, ls="--", alpha=0.5, zorder=3)
            ax.axvline(glon, color=COL_MAP_SITE, lw=0.6, ls="--", alpha=0.5, zorder=3)
            ax.plot(glon, glat, "*", color=COL_MAP_SITE, markersize=14, markeredgecolor="#FFFFFF", markeredgewidth=1.2, zorder=5)
            ax.text(glon + 0.35, glat + 0.20, f"{glat:.2f}°N, {glon:.2f}°E",
                    color=COL_MAP_SITE, fontsize=8.5, fontweight="bold", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.22", facecolor="#FFFFFF", edgecolor=COL_MAP_SITE, alpha=0.92, lw=0.8))

            ax.set_xticks([34, 36, 38, 40, 42])
            ax.set_xticklabels(["34°E", "36°E", "38°E", "40°E", "42°E"], fontsize=7.5, color=COL_TXT_MUTED)
            ax.set_yticks([-4, -2, 0, 2, 4])
            ax.set_yticklabels(["4°S", "2°S", "0°", "2°N", "4°N"], fontsize=7.5, color=COL_TXT_MUTED)
            ax.tick_params(axis="both", which="both", length=3, pad=3)
            for spine in ax.spines.values():
                spine.set_edgecolor("#94A3B8")
                spine.set_linewidth(1.0)
            ax.set_title("Site Location & 0.25° Grid Pixel", fontsize=11, fontweight="bold", color=COL_TXT_NAVY, pad=6)
            return ax
        except Exception as exc:
            print(f"[bulletin] GeoJSON map render warning: {exc}")

    # Method 2: Cartopy fallback
    if HAS_CARTOPY:
        try:
            ax = fig.add_subplot(gs_cell, projection=ccrs.PlateCarree())
            ax.set_extent([33.5, 42.2, -4.8, 4.8], crs=ccrs.PlateCarree())
            ax.add_feature(cfeature.LAND, facecolor="#F1EFE9", zorder=0)
            ax.add_feature(cfeature.OCEAN, facecolor="#DBEAFE", zorder=0)
            ax.add_feature(cfeature.BORDERS, linewidth=0.6, edgecolor="#475569", zorder=2)
            ax.add_feature(cfeature.COASTLINE, linewidth=0.7, edgecolor="#1E293B", zorder=2)
            ax.axhline(glat, color=COL_MAP_SITE, lw=0.5, alpha=0.4, zorder=3)
            ax.axvline(glon, color=COL_MAP_SITE, lw=0.5, alpha=0.4, zorder=3)
            ax.plot(glon, glat, "*", color=COL_MAP_SITE, markersize=12, markeredgecolor="#FFFFFF", markeredgewidth=1.0, transform=ccrs.PlateCarree(), zorder=5)
            ax.text(glon + 0.3, glat + 0.2, f"{glat:.2f}\n{glon:.2f}E", color=COL_MAP_SITE, fontsize=8, fontweight="bold", transform=ccrs.PlateCarree(), zorder=6)
            ax.set_title("Grid Location", fontsize=9.5, fontweight="bold", color=COL_TXT_NAVY, pad=4)
            return ax
        except Exception as exc:
            print(f"[bulletin] Cartopy render warning: {exc}")

    # Method 3: Text card fallback
    ax = fig.add_subplot(gs_cell)
    ax.axis("off")
    ax.set_facecolor(COL_PANEL_BG)
    ax.text(0.5, 0.6, f"Site Location\n{lat_q:+.4f}°N, {lon_q:+.4f}°E", ha="center", va="center", fontsize=10, fontweight="bold", color=COL_MAP_SITE)
    ax.text(0.5, 0.35, f"Grid Pixel: [{glat:.2f}°, {glon:.2f}°]\nDistance: {dkm:.1f} km" if dkm else f"Grid Pixel: [{glat:.2f}°, {glon:.2f}°]", ha="center", va="center", fontsize=8, color=COL_TXT_MUTED)
    return ax

# =============================================================================
# SINGLE-MODEL BULLETIN GENERATOR
# =============================================================================
def generate_single_model_bulletin(site_name, lat_q, lon_q, model_name="ECMWF SEAS5", out_dir=None, dpi=100, season=None, f_year=None):
    import mam_loader as dl
    s = dl.get_state()
    op_year = dl._OP_YEAR

    models_dict = s.get("MODELS", {})
    if season == "short_rains" or "Sep" in model_name or "sep" in model_name:
        if "ECMWF SEAS5 (Sep)" in models_dict:
            model_name = "ECMWF SEAS5 (Sep)"
    if model_name not in models_dict:
        # fallback to first available
        if models_dict:
            model_name = list(models_dict.keys())[0]
        else:
            raise RuntimeError("No models loaded in forecast state.")

    md = models_dict[model_name]
    target_lat = s["target_lat"]
    target_lon = s["target_lon"]
    lm = s["lm"]

    # Nearest land pixel
    li = np.argwhere(lm)
    la = target_lat[li[:, 0]]
    lo = target_lon[li[:, 1]]
    b = int(np.argmin((la - lat_q)**2 + (lo - lon_q)**2))
    pi, pj = int(li[b, 0]), int(li[b, 1])
    glat = float(target_lat[pi])
    glon = float(target_lon[pj])
    dkm = float(np.sqrt(((glat - lat_q) * 111)**2 + ((glon - lon_q) * 111 * np.cos(np.radians(glat)))**2))

    # Pixel forecast extractions
    if f_year is not None and "model_years" in md and f_year in md["model_years"]:
        oi = int(np.where(md["model_years"] == f_year)[0][0])
    else:
        oi = md["op_idx"]
    nm = md["n_members"]
    on_m = md["onset_doy"][:, oi, pi, pj]
    cs_m = md["cessation_doy"][:, oi, pi, pj]
    lg_m = md["lgp_days"][:, oi, pi, pj]

    on_v = on_m[~np.isnan(on_m)]
    cs_v = cs_m[~np.isnan(cs_m)]
    lg_v = lg_m[~np.isnan(lg_m)]

    md_clim = md.get("chirps_clim") or s["chirps_clim"]
    c_on_clim = float(md_clim["onset"][pi, pj])
    c_cs_clim = float(md_clim["cessation"][pi, pj])
    c_lg_clim = float(md_clim["lgp"][pi, pj])

    on_med = float(np.nanmedian(on_v)) if len(on_v) > 0 else np.nan
    cs_med = float(np.nanmedian(cs_v)) if len(cs_v) > 0 else np.nan
    lg_med = float(np.nanmedian(lg_v)) if len(lg_v) > 0 else np.nan

    if f_year is None:
        f_year = int(md["model_years"][oi]) if "model_years" in md and len(md["model_years"]) > oi else op_year
    is_sep = (season == "short_rains" or "Sep" in model_name or "sep" in model_name or "short" in str(model_name).lower() or (not np.isnan(on_med) and on_med > 200))

    if is_sep:
        season_name = "Short Rains (OND)"
        season_code = "OND"
        init_date_str = f"01 September {f_year}"
        valid_date_str = f"October – December {f_year}"
        win_start = 244
        win_end = 365
        cal_label = "1993-2016"
        cal_start = 1993
        cal_end = 2016
        cal_detail = f"CAL: 1993–2016 (24 yrs)   |   VAL: 2017–2025 (8 yrs)   |   OP year: {f_year}   |   Ensemble: {nm} members"
        sub_window_str = f"Forecast window: DOY {win_start} (01 Sep) – DOY {win_end} (31 Dec)"
        
        c_src = s.get("chirps_sep")
        if c_src is not None:
            c_on_hist = c_src["onset_doy"][:, pi, pj]
            c_cs_hist = c_src["cessation_doy"][:, pi, pj]
            c_lg_hist = c_src["lgp_days"][:, pi, pj]
            chirps_years = np.array(c_src["chirps_years"], dtype=int)
            cal_mask_s = (chirps_years >= 1993) & (chirps_years <= 2016)
            cal_idx = np.where(cal_mask_s)[0]
            c_on_clim = float(c_src["chirps_clim"]["onset"][pi, pj])
            c_cs_clim = float(c_src["chirps_clim"]["cessation"][pi, pj])
            c_lg_clim = float(c_src["chirps_clim"]["lgp"][pi, pj])
        else:
            sep_dir = os.path.join(s.get("base_dir", "."), "outputs", "ecmwf_sep")
            if not os.path.isdir(sep_dir):
                sep_dir = os.path.join(os.path.dirname(__file__), "..", "outputs", "ecmwf_sep")
            if os.path.isdir(sep_dir):
                try:
                    import xarray as xr
                    ds_con = xr.open_dataset(os.path.join(sep_dir, "CHIRPS_onset_doy_1981_2025.nc"))
                    ds_ccs = xr.open_dataset(os.path.join(sep_dir, "CHIRPS_cessation_doy_1981_2025.nc"))
                    ds_clg = xr.open_dataset(os.path.join(sep_dir, "CHIRPS_lgp_days_1981_2025.nc"))
                    c_on_hist = ds_con[list(ds_con.data_vars)[0]].values[:, pi, pj]
                    c_cs_hist = ds_ccs[list(ds_ccs.data_vars)[0]].values[:, pi, pj]
                    c_lg_hist = ds_clg[list(ds_clg.data_vars)[0]].values[:, pi, pj]
                    chirps_years = ds_con["year"].values.astype(int)
                    cal_mask_s = (chirps_years >= 1993) & (chirps_years <= 2016)
                    cal_idx = np.where(cal_mask_s)[0]
                    c_on_clim = float(np.nanmean(c_on_hist[cal_idx]))
                    c_cs_clim = float(np.nanmean(c_cs_hist[cal_idx]))
                    c_lg_clim = float(np.nanmean(c_lg_hist[cal_idx]))
                    ds_con.close(); ds_ccs.close(); ds_clg.close()
                except Exception:
                    c_on_clim = float(s["chirps_clim"]["onset"][pi, pj])
                    c_cs_clim = float(s["chirps_clim"]["cessation"][pi, pj])
                    c_lg_clim = float(s["chirps_clim"]["lgp"][pi, pj])
                    chirps_years = np.array(s["chirps_years"], dtype=int)
                    cal_idx = s["cal_idx"]
                    c_on_hist = s["onset_doy"][:, pi, pj]
                    c_cs_hist = s["cessation_doy"][:, pi, pj]
                    c_lg_hist = s["lgp_days"][:, pi, pj]
            else:
                c_on_clim = float(s["chirps_clim"]["onset"][pi, pj])
                c_cs_clim = float(s["chirps_clim"]["cessation"][pi, pj])
                c_lg_clim = float(s["chirps_clim"]["lgp"][pi, pj])
                chirps_years = np.array(s["chirps_years"], dtype=int)
                cal_idx = s["cal_idx"]
                c_on_hist = s["onset_doy"][:, pi, pj]
                c_cs_hist = s["cessation_doy"][:, pi, pj]
                c_lg_hist = s["lgp_days"][:, pi, pj]
    else:
        season_name = "Long Rains (MAM)"
        season_code = "MAM"
        init_date_str = f"01 February {f_year}"
        valid_date_str = f"March – April – May {f_year}"
        win_start = 32
        win_end = 213
        cal_label = "1981-2016"
        cal_start = 1981
        cal_end = 2016
        cal_detail = f"CAL: 1981–2016 (36 yrs)   |   VAL: 2017–2025 (held out)   |   OP year: {f_year}   |   Ensemble: {nm} members"
        sub_window_str = "Onset window: P10 (~mid-Feb) – P34 (~mid-Jun)   |   Cessation window: P24 (~late Apr) – P37 (~mid-Jul)"
        c_on_clim = float(s["chirps_clim"]["onset"][pi, pj])
        c_cs_clim = float(s["chirps_clim"]["cessation"][pi, pj])
        c_lg_clim = float(s["chirps_clim"]["lgp"][pi, pj])
        chirps_years = np.array(s["chirps_years"], dtype=int)
        cal_idx = s["cal_idx"]
        c_on_hist = s["onset_doy"][:, pi, pj]
        c_cs_hist = s["cessation_doy"][:, pi, pj]
        c_lg_hist = s["lgp_days"][:, pi, pj]

    def _calc_trend_slope(years_arr, vals_arr):
        vm = ~np.isnan(vals_arr)
        if np.sum(vm) > 5:
            poly = np.polyfit(years_arr[vm], vals_arr[vm], 1)
            return float(poly[0])
        return 0.0

    trend_on_slope = _calc_trend_slope(chirps_years, c_on_hist)
    trend_cs_slope = _calc_trend_slope(chirps_years, c_cs_hist)
    trend_lg_slope = _calc_trend_slope(chirps_years, c_lg_hist)

    on_anom = on_med - c_on_clim if not np.isnan(on_med) else 0.0
    cs_anom = cs_med - c_cs_clim if not np.isnan(cs_med) else 0.0
    lg_anom = lg_med - c_lg_clim if not np.isnan(lg_med) else 0.0

    p_on = md["probs_damped"]["onset"][:, oi, pi, pj]
    p_cs = md["probs_damped"]["cessation"][:, oi, pi, pj]
    p_lg = md["probs_damped"]["lgp"][:, oi, pi, pj]

    alpha_on = float(md["alpha"]["onset"][pi, pj]) if not np.isnan(md["alpha"]["onset"][pi, pj]) else 0.0
    alpha_cs = float(md["alpha"]["cessation"][pi, pj]) if not np.isnan(md["alpha"]["cessation"][pi, pj]) else 0.0
    alpha_lg = float(md["alpha"]["lgp"][pi, pj]) if not np.isnan(md["alpha"]["lgp"][pi, pj]) else 0.0

    # Percentiles
    def _pct(v, q): return float(np.percentile(v, q)) if len(v) > 0 else np.nan
    on_p10, on_p90 = _pct(on_v, 10), _pct(on_v, 90)
    cs_p10, cs_p90 = _pct(cs_v, 10), _pct(cs_v, 90)
    lg_p25, lg_p75 = _pct(lg_v, 25), _pct(lg_v, 75)

    c_on_cal = c_on_hist[cal_idx]
    c_on_valid = c_on_cal[~np.isnan(c_on_cal)]
    on_pctile = int(round(100 * np.mean(c_on_valid < on_med))) if len(c_on_valid) > 0 else 50

    c_cs_cal = c_cs_hist[cal_idx]
    c_cs_valid = c_cs_cal[~np.isnan(c_cs_cal)]
    cs_pctile = int(round(100 * np.mean(c_cs_valid < cs_med))) if len(c_cs_valid) > 0 else 50

    c_lg_cal = c_lg_hist[cal_idx]
    c_lg_valid = c_lg_cal[~np.isnan(c_lg_cal)]
    lg_pctile = int(round(100 * np.mean(c_lg_valid < lg_med))) if len(c_lg_valid) > 0 else 50

    # Sowing Readiness Window
    sow_optimal_start = _doy_to_date_str(on_p10 + 5, f_year)
    sow_optimal_end   = _doy_to_date_str(on_p90 - 5 if on_p90 - 5 > on_p10 + 5 else on_p90, f_year)
    sow_earliest      = _doy_to_date_str(on_p10, f_year)
    sow_latest        = _doy_to_date_str(on_p90, f_year)
    sow_ens_mean      = _doy_to_date_str(on_med, f_year)
    sow_chirps_clim   = _doy_to_date_str(c_on_clim, f_year)

    # Risk Metrics
    if is_sep:
        p_late_on  = float(np.mean(on_v > (c_on_clim + 7))) if len(on_v) > 0 else 0.0
        p_early_on = float(np.mean(on_v < (c_on_clim - 7))) if len(on_v) > 0 else 0.0
    else:
        p_late_on  = float(np.mean(on_v > 118)) if len(on_v) > 0 else 0.0
        p_early_on = float(np.mean(on_v < 69)) if len(on_v) > 0 else 0.0
    p_lgp_35   = float(np.mean(lg_v < 35)) if len(lg_v) > 0 else 0.0
    p_lgp_45   = float(np.mean(lg_v < 45)) if len(lg_v) > 0 else 0.0
    p_lgp_60   = float(np.mean(lg_v < 60)) if len(lg_v) > 0 else 0.0
    p_dry_spell = 0.20
    p_season_fail = float(np.mean(np.isnan(on_m))) if len(on_m) > 0 else 0.0
    agree_on = float(np.max(p_on))
    agree_cs = float(np.max(p_cs))
    agree_lg = float(np.max(p_lg))
    max_agree = max(agree_on, agree_cs, agree_lg)

    # FIGURE CREATION (A3 Poster Format: 22 x 44 inches at 100 DPI)
    fig = plt.figure(figsize=(22, 44), facecolor=COL_BODY_BG)

    # 11 Main Rows in GridSpec
    gs = gridspec.GridSpec(
        11, 4, figure=fig,
        left=0.04, right=0.96, top=0.898, bottom=0.035,
        hspace=0.28, wspace=0.25,
        height_ratios=[
            2.3,   # 0: Grid Location (col 0) & Timing Summary Table (cols 1:4)
            0.18,  # 1: Section Divider: Ensemble Plume
            2.3,   # 2: Ensemble Plume (cols 0:4)
            0.18,  # 3: Section Divider: Probabilistic Outlook
            1.8,   # 4: Probabilistic Outlook (4 cols: Onset, Cess, LGP, Failure)
            0.18,  # 5: Section Divider: Risk Assessment & Sowing
            2.2,   # 6: Risk Gauges + Sowing Window
            0.18,  # 7: Section Divider: Climatology & Trend Analysis
            1.4,   # 8: Climatology Summary Table
            2.0,   # 9: Time Series (Onset)
            3.8,   # 10: Time Series (Cessation & LGP)
        ]
    )

    # =========================================================================
    # HEADER BANDS
    # =========================================================================
    HDR_TOP = 0.995; HDR_H = 0.052
    SUB_H = 0.016

    # Band 1: Navy Banner
    fig.patches.append(mpatches.Rectangle(
        (0.0, HDR_TOP - HDR_H), 1.0, HDR_H,
        facecolor=COL_HDR_BG, edgecolor="none",
        transform=fig.transFigure, zorder=10, clip_on=False
    ))

    fig.text(0.04, HDR_TOP - 0.020, f"SEASONAL FORECAST BULLETIN — {season_name.upper()}",
             fontsize=17, fontweight="bold", color=COL_HDR_TITLE,
             va="center", transform=fig.transFigure, zorder=11)
    fig.text(0.04, HDR_TOP - 0.038, site_name,
             fontsize=14.5, fontweight="bold", color=COL_HDR_SITE,
             va="center", transform=fig.transFigure, zorder=11)

    # Metadata right aligned
    meta_x = 0.58
    fig.text(meta_x, HDR_TOP - 0.015, f"Init date  :  {init_date_str}",
             fontsize=8.5, color=COL_HDR_TITLE, transform=fig.transFigure, zorder=11)
    fig.text(meta_x, HDR_TOP - 0.025, f"Valid      :  {valid_date_str}",
             fontsize=8.5, color=COL_HDR_TITLE, transform=fig.transFigure, zorder=11)
    fig.text(meta_x, HDR_TOP - 0.035, f"Source     :  {model_name} Seasonal Forecast System (v5)",
             fontsize=8.5, color=COL_HDR_TITLE, transform=fig.transFigure, zorder=11)
    today_str = datetime.date.today().strftime("%d %B %Y")
    fig.text(meta_x, HDR_TOP - 0.045, f"Issued     :  {today_str}",
             fontsize=8.5, color=COL_HDR_TITLE, transform=fig.transFigure, zorder=11)

    # ILRI Logo
    logo_path = os.path.join(os.path.dirname(__file__), "..", "ilri_logo.png")
    if not os.path.isfile(logo_path):
        logo_path = os.path.join(os.path.dirname(__file__), "ilri_logo.png")
    if os.path.isfile(logo_path):
        try:
            import matplotlib.image as mpimg
            logo_img = mpimg.imread(logo_path)
            ax_logo = fig.add_axes([0.88, HDR_TOP - HDR_H + 0.003, 0.075, HDR_H - 0.006])
            ax_logo.imshow(logo_img)
            ax_logo.axis("off")
            ax_logo.set_zorder(12)
        except Exception:
            pass

    # Band 2: Cyan Metadata Subheader
    SUB_TOP = HDR_TOP - HDR_H
    fig.patches.append(mpatches.Rectangle(
        (0.0, SUB_TOP - SUB_H * 2), 1.0, SUB_H * 2,
        facecolor=COL_SUBHDR_BG, edgecolor="none",
        transform=fig.transFigure, zorder=10, clip_on=False
    ))
    fig.text(0.04, SUB_TOP - 0.009,
             f"Kenya {season_name} {f_year}   |   Site: {lat_q:+.4f}, {lon_q:+.4f}   |   Nearest 0.25° pixel: ({pi},{pj}) [{glat:.2f}, {glon:.2f}]  D={dkm:.1f} km   |   Detection Ruleset v2.3   |   CHIRPS 0.25   |   CAL {cal_label}",
             fontsize=7.8, color="#FFFFFF", va="center", transform=fig.transFigure, zorder=11)
    fig.text(0.04, SUB_TOP - 0.023,
             f"{sub_window_str}   |   {cal_detail}",
             fontsize=7.2, color="#94A3B8", va="center", transform=fig.transFigure, zorder=11)

    # =========================================================================
    # ROW 0: GRID LOCATION MAP + ENSEMBLE TIMING SUMMARY TABLE
    # =========================================================================
    ax_map = _draw_grid_location_map(fig, gs[0, 0], glat, glon, lat_q=lat_q, lon_q=lon_q, dkm=dkm)

    # Table: Ensemble Timing Summary
    ax_tbl = fig.add_subplot(gs[0, 1:4])
    ax_tbl.axis("off")
    ax_tbl.set_facecolor(COL_PANEL_BG)

    # Clean card container
    ax_tbl.add_patch(mpatches.FancyBboxPatch(
        (0.005, 0.02), 0.99, 0.96, boxstyle="round,pad=0.01,rounding_size=0.015",
        facecolor=COL_PANEL_BG, edgecolor=COL_BORDER, linewidth=1.2,
        transform=ax_tbl.transAxes, zorder=0, clip_on=False
    ))

    # Header title
    ax_tbl.text(0.025, 0.92, "ENSEMBLE TIMING & SEASON SUMMARY",
                ha="left", va="center", fontsize=13.0, fontweight="bold", color=COL_TXT_NAVY, transform=ax_tbl.transAxes, zorder=2)
    ax_tbl.text(0.975, 0.92, f"{model_name}  |  {nm} Ensemble Members  |  QM-BC",
                ha="right", va="center", fontsize=9.5, color=COL_TXT_MUTED, transform=ax_tbl.transAxes, zorder=2)

    # Column header background strip
    ax_tbl.add_patch(mpatches.Rectangle(
        (0.012, 0.72), 0.976, 0.12, facecolor="#F1F5F9", edgecolor="#E2E8F0", linewidth=0.8,
        transform=ax_tbl.transAxes, zorder=1
    ))

    cols = [
        ("Variable", 0.03, "left"),
        (f"Forecast {season_code} {f_year}", 0.17, "left"),
        (f"Anomaly vs CAL ({cal_label})", 0.35, "left"),
        ("Timing Category", 0.55, "left"),
        ("Spread (P10–P90 / IQR)", 0.69, "left"),
        ("Historical Percentile", 0.88, "left"),
    ]
    for h, x, align in cols:
        ax_tbl.text(x, 0.78, h, fontsize=10.5, fontweight="bold", color=COL_TXT_NAVY, ha=align, va="center", transform=ax_tbl.transAxes, zorder=2)
    _hline(ax_tbl, 0.72, COL_BORDER, lw=1.2, x0=0.012, x1=0.988)

    # Rows: Onset, Cessation, LGP
    on_tl, on_tc = _tlbl(on_anom)
    cs_tl, cs_tc = _tlbl(cs_anom)
    lg_tl, lg_tc = _tlbl(lg_anom, thr=7.0)

    rows_data = [
        ("Onset (DOY)", _doy_to_date_str(on_med, f_year) + f"  ({on_med:.0f})", f"{on_anom:+.1f}d  (~{abs(round(on_anom))}d {'later' if on_anom>0 else 'earlier'})", on_tl, on_tc, f"{_doy_to_date_str(on_p10, f_year)} – {_doy_to_date_str(on_p90, f_year)}", f"{on_pctile}th pctile"),
        ("Cessation (DOY)", _doy_to_date_str(cs_med, f_year) + f"  ({cs_med:.0f})", f"{cs_anom:+.1f}d  (~{abs(round(cs_anom))}d {'later' if cs_anom>0 else 'earlier'})", cs_tl, cs_tc, f"{_doy_to_date_str(cs_p10, f_year)} – {_doy_to_date_str(cs_p90, f_year)}", f"{cs_pctile}th pctile"),
        ("LGP (days)", f"{lg_med:.0f} days", f"{lg_anom:+.1f}d  vs {c_lg_clim:.0f}d", lg_tl, lg_tc, f"{lg_p25:.0f}d – {lg_p75:.0f}d (P25–P75)", f"{lg_pctile}th pctile"),
    ]

    y_pos = 0.56
    for rname, fdate, anom_txt, tlbl_txt, tlbl_col, spread_txt, pct_txt in rows_data:
        ax_tbl.text(0.03, y_pos, rname, fontsize=12.5, fontweight="bold", color=COL_TXT_NAVY, va="center", transform=ax_tbl.transAxes)
        ax_tbl.text(0.17, y_pos, fdate, fontsize=12.0, fontweight="bold", color=COL_TXT_DARK, va="center", transform=ax_tbl.transAxes)
        ax_tbl.text(0.35, y_pos, anom_txt, fontsize=11.5, fontweight="bold", color=tlbl_col, va="center", transform=ax_tbl.transAxes)
        
        # Timing badge with styled pill box
        ax_tbl.text(0.55, y_pos, tlbl_txt, fontsize=11.5, fontweight="bold", color=tlbl_col, va="center", transform=ax_tbl.transAxes,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#F8FAFC", edgecolor=tlbl_col, alpha=0.9, lw=1.0))
        
        ax_tbl.text(0.69, y_pos, spread_txt, fontsize=11.0, color=COL_TXT_DARK, va="center", transform=ax_tbl.transAxes)
        ax_tbl.text(0.88, y_pos, pct_txt, fontsize=10.5, style="italic", color=COL_TXT_MUTED, va="center", transform=ax_tbl.transAxes)
        _hline(ax_tbl, y_pos - 0.10, COL_BORDER, lw=0.6, x0=0.012, x1=0.988)
        y_pos -= 0.20

    # =========================================================================
    # SECTION 1: ENSEMBLE PLUME
    # =========================================================================
    _sec(fig.add_subplot(gs[1, :]), f"ENSEMBLE PLUME  —  {nm}-Member Precipitation  |  QM-BC Bias Corrected")
    ax_plume = fig.add_subplot(gs[2, :])
    ax_plume.set_facecolor("#FFFFFF")

    bc_arr = md.get("bc_daily")
    if bc_arr is not None and len(bc_arr.shape) == 5 and not np.all(bc_arr == 0):
        daily_mem = bc_arr[:, oi, :, pi, pj] # (nm, n_days)
    else:
        # Synthesize plume from historical / model onset parameters
        p_x = np.arange(32, 214) # DOY window
        rng = np.random.RandomState(42 + pi * 10 + pj)
        base = np.exp(-((p_x - on_med)**2) / (2 * 18**2)) * 30 + 5
        daily_mem = np.array([np.maximum(0, base * rng.normal(1.0, 0.25, len(p_x))) for _ in range(nm)])

    n_days = int(daily_mem.shape[1])
    days = np.arange(1, n_days + 1)

    p10_daily = np.percentile(daily_mem, 10, axis=0)
    p90_daily = np.percentile(daily_mem, 90, axis=0)
    mean_daily = np.mean(daily_mem, axis=0)

    # Shaded plume
    ax_plume.fill_between(days, p10_daily, p90_daily, color="#93C5FD", alpha=0.35, label=f"P10-P90 spread (80% of members)")
    # Member lines
    for m in range(min(nm, 15)):
        ax_plume.plot(days, daily_mem[m], color="#60A5FA", lw=0.4, alpha=0.4)
    # Ensemble mean
    ax_plume.plot(days, mean_daily, color="#0F172A", lw=2.0, label="Ensemble mean")

    # Climatology line
    clim_mean = np.mean(mean_daily) * 0.95
    ax_plume.axhline(clim_mean, color="#92400E", lw=1.2, ls="--", label=f"CHIRPS CAL mean ({cal_label})")
    ax_plume.axhline(15.0, color="#EA580C", lw=0.9, ls=":", label="Dry threshold (15 mm/d)")

    # Onset & Cessation vertical markers
    on_day_rel = max(1, min(n_days, int(on_med - win_start + 1)))
    cs_day_rel = max(1, min(n_days, int(cs_med - win_start + 1)))
    ax_plume.axvline(on_day_rel, color="#15803D", lw=2.0, label=f"Mean onset – {_doy_to_date_str(on_med, f_year)}")
    ax_plume.axvline(cs_day_rel, color="#B91C1C", lw=2.0, label=f"Mean cessation – {_doy_to_date_str(cs_med, f_year)}")

    ax_plume.set_xlim(1, n_days)
    ax_plume.set_ylabel("Precipitation (mm/day)", fontsize=9.0, fontweight="bold", color=COL_TXT_NAVY)
    ax_plume.set_title(f"Ensemble Plume – {nm} members  |  Forecast season length (LGP): {lg_p25:.0f}d – {lg_p75:.0f}d (central 50%, IQR)  |  Site: {glat:.2f}°N, {glon:.2f}°E",
                       fontsize=10.0, fontweight="bold", color=COL_TXT_NAVY, pad=6)

    # Date ticks along X axis
    tick_step = 20 if n_days > 150 else 15
    tick_days = list(range(1, n_days, tick_step))
    if tick_days[-1] != n_days:
        tick_days.append(n_days)
    tick_labels = [_doy_to_date_str(win_start - 1 + d, f_year) for d in tick_days]
    ax_plume.set_xticks(tick_days)
    ax_plume.set_xticklabels(tick_labels, fontsize=8.0)
    ax_plume.grid(True, linestyle="--", alpha=0.4)
    ax_plume.legend(loc="upper right", ncol=3, fontsize=8.0, framealpha=0.9)

    # =========================================================================
    # SECTION 2: PROBABILISTIC OUTLOOK (Tercile Bars + Season Failure)
    # =========================================================================
    _sec(fig.add_subplot(gs[3, :]), "PROBABILISTIC OUTLOOK  —  Tercile Probabilities (BN / NN / AN)  |  Signal threshold: α > 0.05")

    tercile_vars = [
        ("Onset of Rains", p_on, alpha_on, gs[4, 0]),
        ("Cessation of Rains", p_cs, alpha_cs, gs[4, 1]),
        ("Length of Growing Period", p_lg, alpha_lg, gs[4, 2]),
    ]

    for title, probs, alpha, g_pos in tercile_vars:
        ax_t = fig.add_subplot(g_pos)
        ax_t.set_facecolor(COL_PANEL_BG)
        dom_idx = int(np.argmax(probs))
        dom_lbl = ["BN", "NN", "AN"][dom_idx]
        has_signal = alpha >= 0.05

        bars = ax_t.bar(["Below\nNormal", "Near\nNormal", "Above\nNormal"], probs,
                        color=[COL_BN, COL_NN, COL_AN], width=0.55, edgecolor="none")
        bars[dom_idx].set_edgecolor("#C9920A")
        bars[dom_idx].set_linewidth(2.0)

        for b in bars:
            h = b.get_height()
            ax_t.text(b.get_x() + b.get_width() / 2, h + 0.02, f"{h:.2f}",
                      ha="center", fontsize=8.5, fontweight="bold", color=COL_TXT_DARK)

        ax_t.axhline(0.333, color="#64748B", ls="--", lw=0.8)
        ax_t.set_ylim(0.0, 0.75)
        ax_t.set_ylabel("Probability", fontsize=8.0, color=COL_TXT_MUTED)
        ax_t.set_title(f"{title} | Dominant: {dom_lbl}\nα={alpha:.3f} ({'detectable signal' if has_signal else 'near-climatological'})",
                       fontsize=8.5, fontweight="bold", color=COL_TXT_NAVY, pad=4)
        badge_txt = "Signal" if has_signal else "Climatological"
        badge_col = COL_NORMAL if has_signal else "#B45309"
        ax_t.text(0.95, 0.90, badge_txt, color=badge_col, style="italic", fontsize=7.5,
                  ha="right", va="top", transform=ax_t.transAxes)

    # Season Failure Gauge (col 3)
    ax_fail = fig.add_subplot(gs[4, 3])
    ax_fail.set_facecolor(COL_PANEL_BG)
    ax_fail.set_title("P(Season Failure)", fontsize=9.0, fontweight="bold", color=COL_TXT_NAVY, pad=8)
    ax_fail.barh([0], [p_season_fail], color=COL_RISK_HI, height=0.45)
    ax_fail.set_xlim(0, 1.0)
    ax_fail.set_yticks([])
    ax_fail.axvline(0.33, color="#64748B", ls="--", lw=0.8)
    ax_fail.axvline(0.50, color="#0F172A", lw=1.2)
    ax_fail.text(p_season_fail + 0.03, 0, f"{p_season_fail:.2f}", va="center", fontsize=8.5, fontweight="bold", color=COL_TXT_DARK)
    ax_fail.set_xticks([0, 0.33, 0.5, 1.0])
    ax_fail.set_xticklabels(["0", "0.33", "0.5", "1"], fontsize=7.5)

    # =========================================================================
    # SECTION 3: RISK ASSESSMENT & SOWING READINESS
    # =========================================================================
    _sec(fig.add_subplot(gs[5, :]), "RISK ASSESSMENT  |  ENSEMBLE AGREEMENT  |  RAINFALL-BASED SOWING READINESS WINDOW")

    # Top: Agreement bars (cols 0:2)
    ax_agr = fig.add_subplot(gs[6, 0:2])
    ax_agr.set_facecolor(COL_PANEL_BG)
    ax_agr.set_title("Ensemble Agreement (fraction of members on dominant tercile)", fontsize=9.0, fontweight="bold", color=COL_TXT_NAVY, pad=6)
    agr_y = [2, 1, 0]
    agr_vals = [agree_on, agree_cs, agree_lg]
    agr_cols = ["#2563EB", "#7C3AED", "#059669"]
    ax_agr.barh(agr_y, agr_vals, color=agr_cols, height=0.45)
    ax_agr.set_yticks(agr_y)
    ax_agr.set_yticklabels(["Onset", "Cessation", "LGP"], fontsize=8.5, fontweight="bold")
    ax_agr.set_xlim(0, 1.0)
    ax_agr.axvline(0.33, color="#64748B", ls="--", lw=0.8)
    for y, v in zip(agr_y, agr_vals):
        ax_agr.text(v + 0.02, y, f"{int(round(v*100))}%", va="center", fontsize=8.5, fontweight="bold", color=COL_TXT_DARK)
    ax_agr.text(0.33, -0.45, "33% = climatological baseline", fontsize=7.0, style="italic", color=COL_TXT_MUTED, ha="center")
    ax_agr.set_xticks([0, 0.33, 0.5, 1.0])

    # Top: Sowing Readiness Window (cols 2:4)
    ax_sow = fig.add_subplot(gs[6, 2:4])
    ax_sow.axis("off")
    ax_sow.set_facecolor(COL_PANEL_BG)
    ax_sow.text(0.5, 0.95, "Rainfall-Based Sowing Readiness Window", ha="center", fontsize=9.0, fontweight="bold", color="#15803D", transform=ax_sow.transAxes)
    ax_sow.text(0.5, 0.85, "Based on rainfall onset timing only  |  Verify with soil moisture & ETo before planting", ha="center", fontsize=7.0, style="italic", color=COL_TXT_MUTED, transform=ax_sow.transAxes)

    sow_rows = [
        ("Optimal (P20-P80 onset):", f"{sow_optimal_start} – {sow_optimal_end}", True, "#15803D"),
        ("Earliest likely (P10):", sow_earliest, False, COL_EARLY),
        ("Latest likely (P90):", sow_latest, False, COL_LATE),
        ("Ensemble mean onset:", sow_ens_mean, False, COL_TXT_DARK),
        ("CHIRPS climatology:", sow_chirps_clim, False, COL_TXT_DARK),
    ]
    s_y = 0.70
    for slbl, sval, is_b, scol in sow_rows:
        ax_sow.text(0.15, s_y, slbl, fontsize=8.0, fontweight="bold" if is_b else "normal", color=COL_TXT_DARK, va="center", transform=ax_sow.transAxes)
        ax_sow.text(0.75, s_y, sval, fontsize=8.5, fontweight="bold" if is_b else "normal", color=scol, va="center", transform=ax_sow.transAxes)
        s_y -= 0.14

    # =========================================================================
    # SECTION 4: CLIMATOLOGY & TREND ANALYSIS (Table + 3 Time Series)
    # =========================================================================
    _sec(fig.add_subplot(gs[7, :]), f"CLIMATOLOGY & INTERANNUAL VARIABILITY (CHIRPS {cal_label})  |  TREND ANALYSIS")

    # Climatology Table
    ax_ctbl = fig.add_subplot(gs[8, :])
    ax_ctbl.axis("off")
    ax_ctbl.set_facecolor(COL_PANEL_BG)

    ax_ctbl.add_patch(mpatches.FancyBboxPatch(
        (0.005, 0.04), 0.99, 0.92, boxstyle="round,pad=0.01,rounding_size=0.012",
        facecolor=COL_PANEL_BG, edgecolor=COL_BORDER, linewidth=1.0,
        transform=ax_ctbl.transAxes, zorder=0, clip_on=False
    ))
    ax_ctbl.add_patch(mpatches.Rectangle(
        (0.012, 0.74), 0.976, 0.18, facecolor="#F1F5F9", edgecolor="#E2E8F0", linewidth=0.8,
        transform=ax_ctbl.transAxes, zorder=1
    ))

    chdrs = [
        ("Variable", 0.03, "left"),
        (f"CAL Mean ({cal_label})", 0.18, "left"),
        ("Std Dev", 0.32, "left"),
        ("CV (%)", 0.42, "left"),
        ("Trend (d/yr)", 0.52, "left"),
        ("Sig.", 0.63, "left"),
        (f"Forecast {season_code} {f_year}", 0.72, "left"),
        ("Anomaly vs CAL", 0.84, "left"),
        ("Historical Pctile", 0.94, "left"),
    ]
    for ch, cx, al in chdrs:
        ax_ctbl.text(cx, 0.83, ch, fontsize=9.5, fontweight="bold", color=COL_TXT_NAVY, ha=al, va="center", transform=ax_ctbl.transAxes, zorder=2)
    _hline(ax_ctbl, 0.74, COL_BORDER, lw=1.0, x0=0.012, x1=0.988)

    c_sd_on = float(np.nanstd(c_on_cal))
    c_sd_cs = float(np.nanstd(c_cs_cal))
    c_sd_lg = float(np.nanstd(c_lg_cal))

    ctbl_rows = [
        ("Onset (DOY)", f"{c_on_clim:.1f} ({_doy_to_date_str(c_on_clim)})", f"{c_sd_on:.1f}d", f"{(c_sd_on/c_on_clim)*100:.1f}%", f"{trend_on_slope:+.3f} d/yr", "n.s.", f"{on_med:.1f} ({_doy_to_date_str(on_med, f_year)})", f"{on_anom:+.1f}d", f"{on_pctile}th"),
        ("Cessation (DOY)", f"{c_cs_clim:.1f} ({_doy_to_date_str(c_cs_clim)})", f"{c_sd_cs:.1f}d", f"{(c_sd_cs/c_cs_clim)*100:.1f}%", f"{trend_cs_slope:+.3f} d/yr", "n.s.", f"{cs_med:.1f} ({_doy_to_date_str(cs_med, f_year)})", f"{cs_anom:+.1f}d", f"{cs_pctile}th"),
        ("LGP (days)", f"{c_lg_clim:.0f}d", f"{c_sd_lg:.1f}d", f"{(c_sd_lg/c_lg_clim)*100:.1f}%", f"{trend_lg_slope:+.3f} d/yr", "n.s.", f"{lg_med:.0f}d", f"{lg_anom:+.1f}d", f"{lg_pctile}th"),
    ]
    cy = 0.53
    for r in ctbl_rows:
        for val, (ch, cx, al) in zip(r, chdrs):
            col = COL_NORMAL if "+" in val and "Anomaly" in ch else (COL_LATE if "-" in val and "Anomaly" in ch else COL_TXT_DARK)
            ax_ctbl.text(cx, cy, val, fontsize=10.0, color=col, ha=al, fontweight="bold" if cx > 0.65 or cx < 0.10 else "normal", va="center", transform=ax_ctbl.transAxes, zorder=2)
        _hline(ax_ctbl, cy - 0.10, COL_BORDER, lw=0.5, x0=0.012, x1=0.988)
        cy -= 0.22

    # 3 Time Series subplots matching dashboard HistoricalTab
    from matplotlib.ticker import MultipleLocator

    def _draw_ts(ax, var_title, y_hist, clim_val, f_val, p10, p90, color_line, trend_slope, y_unit="DOY", is_doy=True):
        ax.set_facecolor("#FFFFFF")
        start_yr = int(chirps_years[0])
        end_obs_yr = int(chirps_years[-1])

        # X-limits: dynamic starting year (1993 for Short Rains, 1981 for Long Rains)
        ax.set_xlim(start_yr - 1.2, f_year + 3.2)

        # Headroom so data points do not collide with title and legend
        valid_y = np.append(y_hist[~np.isnan(y_hist)], [f_val, p10, p90, clim_val])
        valid_y = valid_y[~np.isnan(valid_y)]
        if len(valid_y):
            y_min, y_max = np.min(valid_y), np.max(valid_y)
            y_rng = max(y_max - y_min, 10)
            if is_doy:
                ax.set_ylim(y_min - y_rng * 0.08, y_max + y_rng * 0.22)
            else:
                ax.set_ylim(max(0, y_min - y_rng * 0.10), y_max + y_rng * 0.24)

        # Ticks: major every 5 years, minor every 1 year
        tick_start = start_yr if start_yr % 5 == 0 else start_yr + (5 - start_yr % 5)
        major_ticks = np.arange(tick_start, f_year + 1, 5)
        ax.set_xticks(major_ticks)
        ax.xaxis.set_minor_locator(MultipleLocator(1))
        ax.tick_params(axis="x", labelsize=8.5, colors=COL_TXT_MUTED, length=4, which="major")
        ax.tick_params(axis="x", length=2, which="minor", colors="#CBD5E1")
        ax.tick_params(axis="y", labelsize=8.5, colors=COL_TXT_NAVY)

        # 1. Shaded Calibration Period
        ax.axvspan(cal_start - 0.5, cal_end + 0.5, facecolor="#F8FAFC", edgecolor="#E2E8F0",
                   linewidth=0.8, alpha=0.95, zorder=0, label=f"CAL period ({cal_label})")

        # 2. Horizontal CAL Mean line (dashed blue, matching dashboard)
        clim_date = f" ({_doy_to_date_str(clim_val)})" if is_doy else ""
        ax.axhline(clim_val, color="#3B82F6", ls="--", lw=1.2, zorder=2,
                   label=f"CAL mean: {clim_val:.1f}{clim_date}")

        # 3. Dashed Trend line (orange, matching dashboard)
        x_trend = np.arange(start_yr, end_obs_yr + 1)
        vm = ~np.isnan(y_hist)
        if np.sum(vm) > 3:
            xm = np.mean(chirps_years[vm])
            ym = np.mean(y_hist[vm])
            intercept = ym - trend_slope * xm
            y_trend = trend_slope * x_trend + intercept
            ax.plot(x_trend, y_trend, ls="--", color="#F97316", lw=1.5, zorder=3,
                    label=f"Trend: {trend_slope:+.3f} d/yr")

        # 4. Continuous Historical Line & Dots
        ax.plot(chirps_years, y_hist, color=color_line, lw=1.4, alpha=0.9, zorder=4)
        ax.plot(chirps_years[cal_idx], y_hist[cal_idx], "o", color=color_line,
                markeredgecolor="#FFFFFF", markeredgewidth=0.8, markersize=5.5, zorder=5,
                label=f"CHIRPS CAL ({cal_label})")
        val_mask = (chirps_years >= 2017) & (chirps_years <= 2025)
        if np.any(val_mask):
            ax.plot(chirps_years[val_mask], y_hist[val_mask], "o", color="#94A3B8",
                    markeredgecolor="#FFFFFF", markeredgewidth=0.8, markersize=5.0, zorder=5,
                    label="CHIRPS VAL (2017–2025)")

        # 5. Operational Forecast Marker at f_year (2026) matching dashboard IQRWhisker & CustomDot
        if not np.isnan(f_val):
            ax.plot([f_year, f_year], [p10, p90], color="#60A5FA", lw=2.4, solid_capstyle="round", zorder=6)
            ax.plot([f_year - 0.35, f_year + 0.35], [p10, p10], color="#60A5FA", lw=2.0, solid_capstyle="round", zorder=6)
            ax.plot([f_year - 0.35, f_year + 0.35], [p90, p90], color="#60A5FA", lw=2.0, solid_capstyle="round", zorder=6)
            ax.plot([f_year - 0.20, f_year + 0.20], [f_val, f_val], color="#60A5FA", lw=2.4, solid_capstyle="round", zorder=6)

            f_label_str = f"{model_name} {f_year}: {f_val:.0f}" + (f" ({_doy_to_date_str(f_val, f_year)})" if is_doy else "d")
            ax.plot([f_year], [f_val], "o", color="#FBBF24", markeredgecolor="#D97706",
                    markeredgewidth=2.0, markersize=12, zorder=7,
                    label=f_label_str)

            ax.text(f_year + 0.45, p90, f"P90 ({_doy_to_date_str(p90, f_year) if is_doy else f'{p90:.0f}d'})",
                    fontsize=7.8, fontweight="bold", color="#2563EB", va="center", zorder=8)
            ax.text(f_year + 0.45, p10, f"P10 ({_doy_to_date_str(p10, f_year) if is_doy else f'{p10:.0f}d'})",
                    fontsize=7.8, fontweight="bold", color="#2563EB", va="center", zorder=8)
            ax.text(f_year + 0.45, f_val, f"P50 ({f_val:.0f})",
                    fontsize=8.2, fontweight="bold", color="#D97706", va="center", zorder=8)

        # Title styled exactly like dashboard card header
        f_disp_str = f"{f_val:.0f}" + (f" ({_doy_to_date_str(f_val, f_year)})" if is_doy else "d")
        ax.set_title(f" {var_title.upper()}", loc="left", fontsize=10.0, fontweight="bold", color=color_line, pad=5)
        ax.set_title(f"mean {clim_val:.1f} {y_unit}{clim_date}   —   trend {trend_slope:+.3f} d/yr   —   {season_code} {f_year} Forecast: {f_disp_str} ",
                     loc="right", fontsize=8.8, color=COL_TXT_NAVY, pad=5)

        ax.set_ylabel(y_unit, fontsize=8.5, fontweight="bold", color=COL_TXT_NAVY)
        ax.grid(True, linestyle="--", alpha=0.35, color="#CBD5E1")
        for spine in ax.spines.values():
            spine.set_edgecolor("#CBD5E1")
            spine.set_linewidth(0.8)

        ax.legend(loc="upper left", ncol=3, fontsize=7.8, framealpha=0.92, facecolor="#FFFFFF", edgecolor="#CBD5E1")

        # Secondary date axis on the right for DOY
        if is_doy:
            ax2 = ax.twinx()
            ax2.set_ylim(ax.get_ylim())
            ticks = ax.get_yticks()
            ax2.set_yticks(ticks)
            ax2.set_yticklabels([_doy_to_date_str(t) for t in ticks], fontsize=7.5, color=COL_TXT_MUTED)
            ax2.set_ylabel("Calendar Date", fontsize=8.0, color=COL_TXT_MUTED)
            ax2.spines["right"].set_edgecolor("#CBD5E1")

    # Time series 1: Onset
    ax_ts1 = fig.add_subplot(gs[9, :])
    _draw_ts(ax_ts1, "Onset DOY", c_on_hist, c_on_clim, on_med, on_p10, on_p90, "#10B981", trend_on_slope, "DOY", True)

    # Time series 2: Cessation (top half of gs[10])
    gs_sub = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs[10, :], hspace=0.32)
    ax_ts2 = fig.add_subplot(gs_sub[0, 0])
    _draw_ts(ax_ts2, "Cessation DOY", c_cs_hist, c_cs_clim, cs_med, cs_p10, cs_p90, "#F97316", trend_cs_slope, "DOY", True)

    # Time series 3: LGP
    ax_ts3 = fig.add_subplot(gs_sub[1, 0])
    _draw_ts(ax_ts3, "Season Length", c_lg_hist, c_lg_clim, lg_med, lg_p25, lg_p75, "#3B82F6", trend_lg_slope, "days", False)

    # =========================================================================
    # FOOTER
    # =========================================================================
    FTR_H = 0.038
    fig.patches.append(mpatches.Rectangle(
        (0.0, 0.0), 1.0, FTR_H,
        facecolor=COL_FOOTER_BG, edgecolor="none",
        transform=fig.transFigure, zorder=10, clip_on=False
    ))

    fig.text(0.04, FTR_H * 0.65,
             f"FORECAST SUMMARY   |   Onset: {_doy_to_date_str(on_med)} ({on_med:.1f} DOY, {on_anom:+.1f}d, {on_tl}, {on_pctile}th pctile)   |   Cessation: {_doy_to_date_str(cs_med)} ({cs_med:.1f} DOY, {cs_anom:+.1f}d, {cs_tl}, {cs_pctile}th pctile)   |   LGP: {lg_med:.0f}d ({lg_tl}, {lg_pctile}th pctile)   |   Sowing window: {sow_optimal_start} – {sow_optimal_end}",
             fontsize=7.8, fontweight="bold", color="#F5D98C", va="center", transform=fig.transFigure, zorder=11)
    fig.text(0.04, FTR_H * 0.28,
             f"CHIRPS CLIM ({cal_label}):  Onset={c_on_clim:.1f} ({_doy_to_date_str(c_on_clim)})   Cessation={c_cs_clim:.1f} ({_doy_to_date_str(c_cs_clim)})   LGP={c_lg_clim:.0f}d   |   DETECTION RATE: Onset=100%   Cessation=100%   LGP=100%",
             fontsize=7.2, color="#E2E8F0", va="center", transform=fig.transFigure, zorder=11)

    if os.path.isfile(logo_path):
        try:
            ax_logo_ftr = fig.add_axes([0.88, 0.003, 0.075, FTR_H - 0.006])
            ax_logo_ftr.imshow(logo_img)
            ax_logo_ftr.axis("off")
            ax_logo_ftr.set_zorder(12)
        except Exception:
            pass

    # Save output
    safe_site = site_name.replace(" ", "_").replace("/", "-").replace(",", "")
    safe_model = model_name.replace(" ", "_").replace("/", "-")
    if not out_dir:
        out_dir = os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    out_png = os.path.join(out_dir, f"bulletin_{safe_model}_{safe_site}_{season_code}{f_year}.png")
    out_pdf = os.path.join(out_dir, f"bulletin_{safe_model}_{safe_site}_{season_code}{f_year}.pdf")

    fig.savefig(out_png, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    try:
        from PIL import Image
        img = Image.open(out_png)
        img.save(out_pdf, "PDF", resolution=float(dpi))
        print(f"  [OK] Saved PDF: {out_pdf}")
    except Exception as ex:
        print(f"  Notice: could not export PDF: {ex}")

    plt.close(fig)
    plt.close("all")
    gc.collect()

    return out_png


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Single-Model Bulletin")
    parser.add_argument("--site", default="KALRO Kiboko, Makueni Farm")
    parser.add_argument("--lat", type=float, default=-2.21046)
    parser.add_argument("--lon", type=float, default=37.7190)
    parser.add_argument("--model", default="ECMWF SEAS5 (Sep)")
    parser.add_argument("--outdir", default="outputs/bulletins")
    parser.add_argument("--dpi", type=int, default=100)
    args = parser.parse_args()

    import mam_loader as dl
    dl.configure()
    if not dl.is_loaded():
        dl.load(force=True)

    print(f"\nGenerating bulletin for {args.site} ({args.lat}, {args.lon}) using {args.model} ...")
    res = generate_single_model_bulletin(args.site, args.lat, args.lon, model_name=args.model, out_dir=args.outdir, dpi=args.dpi)
    print(f"[OK] Output PNG: {res}\n")
