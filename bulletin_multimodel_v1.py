# VERSION: 2026-04-03-fixed  (shape mismatch + RPSS NaN guard)
# =============================================================================
# MULTI-MODEL SEASONAL FORECAST BULLETIN  v1.0
# Kenya MAM — Onset / Cessation / LGP
# Combines C3S multi-model ensemble products into a single site bulletin.
#
# USAGE
# -----
# Called from a multi-model Stage 8 notebook after all individual pipelines
# have been run. Requires a MODELS dict and shared CHIRPS reference arrays.
#
# The following metadata can be overridden by the calling notebook:
if "MM_INIT_DATE" not in globals():
    MM_INIT_DATE = "01 February 2026"
if "MM_VALID_STR" not in globals():
    MM_VALID_STR = "March – April – May 2026"
if "MM_ISSUED_STR" not in globals():
    import datetime as _dt_mm
    MM_ISSUED_STR = _dt_mm.date.today().strftime("%d %B %Y")
if "MM_RULESET" not in globals():
    MM_RULESET = "Dunning et al. (2016) daily  |  CHIRPS 0.25 deg  |  CAL 1981-2016"

# =============================================================================
# EXPECTED NAMESPACE  (must be set by calling notebook before exec)
# =============================================================================
# MODELS : dict  — see structure below
# CHIRPS reference arrays (shared across all models):
#   chirps_onset_doy      (n_chirps_yrs, n_lat, n_lon)
#   chirps_cessation_doy  (n_chirps_yrs, n_lat, n_lon)
#   chirps_lgp_days       (n_chirps_yrs, n_lat, n_lon)
#   chirps_clim           {"onset": ..., "cessation": ..., "lgp": ...}
#   C_clim                (182, n_lat, n_lon)  climatological accumulated anomaly
#   Q_bar                 (n_lat, n_lon)       window mean precipitation
#   d_s, d_e              (n_lat, n_lon)       climatological season bounds (DOY)
#   t33_onset, t67_onset  (n_lat, n_lon)       tercile boundaries
#   lm                    (n_lat, n_lon)       boolean land mask
#   target_lat, target_lon (1-D arrays)
#   cal_idx               indices into chirps arrays for CAL years
#   WIN_DOY_START, WIN_DOY_END
#   OP_YEAR
#   BULLETIN_DIR          output directory
#
# MODELS dict structure:
# {
#   "ECMWF SEAS5": {
#       "onset_doy"     : np.ndarray  (n_members, n_years, n_lat, n_lon) DOY
#       "cessation_doy" : np.ndarray  (n_members, n_years, n_lat, n_lon) DOY
#       "lgp_days"      : np.ndarray  (n_members, n_years, n_lat, n_lon) days
#       "bc_daily"      : np.ndarray  (n_members, n_years, n_days, n_lat, n_lon) mm/day
#       "probs_damped"  : dict  {"onset":(3,n_yrs,n_lat,n_lon), "cessation":..., "lgp":...}
#       "alpha"         : dict  {"onset":(n_lat,n_lon), "cessation":..., "lgp":...}
#       "hitrate_cal"   : dict  {"onset":(n_lat,n_lon), "cessation":..., "lgp":...}
#       "hitrate_val"   : dict  {"onset":(n_lat,n_lon), "cessation":..., "lgp":...}
#       "rpss_val"      : dict  {"onset":(n_lat,n_lon), "cessation":..., "lgp":...}
#       "op_idx"        : int   index of OP_YEAR in the model year array
#       "color"         : str   hex colour for this model's plot traces
#       "n_members"     : int   ensemble size
#   },
#   "UKMO GloSea6": { ... },
#   ...
# }
# =============================================================================

import os, datetime
import numpy             as np
import matplotlib        as mpl
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches  as mpatches
import matplotlib.ticker   as mticker
import matplotlib.patheffects as mpe

try:
    import cartopy.crs     as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
except ImportError:
    HAS_CARTOPY = False

# =============================================================================
# COLOUR PALETTE
# =============================================================================
COL_HDR_BG       = "#0B1F3A"
COL_HDR_ACCENT   = "#C9920A"
COL_HDR_TITLE    = "#FFFFFF"
COL_HDR_SITE     = "#F5D98C"
COL_HDR_META     = "#FFFFFF"
COL_SUBHDR_BG    = "#2C4A6E"
COL_SUBHDR_TXT   = "#FFFFFF"
COL_DIVIDER_BG   = "#1A3255"
COL_DIVIDER_TXT  = "#FFFFFF"
COL_BODY_BG      = "#F4F7FB"
COL_PANEL_BG     = "#F8FAFC"
COL_PANEL_BG2    = "#EEF2F7"
COL_BORDER       = "#D1D9E0"
COL_FOOTER_BG    = "#0B1F3A"
COL_FOOTER_L1    = "#F5D98C"
COL_FOOTER_L2    = "#FFFFFF"
COL_TXT_DARK     = "#0A0A0A"
COL_TXT_NAVY     = "#0B1F3A"
COL_TXT_NAVY2    = "#1A3255"
COL_TXT_MID      = "#334155"
COL_TXT_MUTED    = "#475569"
COL_BN           = "#7C3A16"
COL_BN_LITE      = "#F2D9C8"
COL_NN           = "#92680A"
COL_NN_LITE      = "#FEF3CD"
COL_AN           = "#155D36"
COL_AN_LITE      = "#C8EDD8"
COL_DOM_OUTLINE  = "#C9920A"
COL_EARLY        = "#1B5EA6"
COL_LATE         = "#C0392B"
COL_NORMAL       = "#1E6B45"
COL_RISK_MED     = "#FCA981"
COL_RISK_HI      = "#E05C3A"
COL_RISK_CRIT    = "#8B0000"
COL_TEAL         = "#0E7490"
COL_MAP_SITE     = "#E63946"
COL_CHIRPS       = "#2C4A6E"

# Logo path — matches single-model bulletin
if "ILRI_LOGO_PATH" not in globals():
    ILRI_LOGO_PATH = r"C:\Users\yonas\Documents\ILRI\onset-kenya\ILRI_logo1.png"

# Default per-model colours (used if model dict has no "color" key)
MM_MODEL_COLORS = [
    "#1B5EA6",  # ECMWF SEAS5        — blue
    "#C0392B",  # UKMO GloSea6       — red
    "#1E6B45",  # Meteo-France       — green
    "#8B4513",  # DWD GCFS2.1        — brown
    "#7B0EA6",  # CMCC-SPS4          — purple
    "#C9920A",  # NCEP CFSv2         — gold
    "#0E7490",  # ECCC CanSIPS       — teal
    "#E63946",  # BOM ACCESS-S2      — crimson
]

# =============================================================================
# FONT CONSTANTS
# =============================================================================
FS_MM_HDR_TITLE  = 16.0
FS_MM_HDR_SITE   = 13.5
FS_MM_HDR_META   = 7.4
FS_MM_SEC        = 11.0
FS_MM_TBL_HDR    = 10.0
FS_MM_TBL_MODEL  = 11.0
FS_MM_TBL_VAL    = 10.5
FS_MM_TBL_SMALL  = 9.0
FS_MM_BAR_TITLE  = 8.5
FS_MM_BAR_VALUE  = 9.0
FS_MM_BAR_XTICK  = 7.0
FS_MM_PLUME_TTL  = 13.0
FS_MM_PLUME_AXIS = 10.5
FS_MM_PLUME_TICK = 9.0
FS_MM_PLUME_LEG  = 9.0
FS_MM_HEAT_LBL   = 10.5
FS_MM_CONS       = 9.0
FS_MM_SKILL_HDR  = 10.0
FS_MM_SKILL_VAL  = 10.0
FS_MM_MAP_TITLE  = 13.0
FS_MM_FOOTER     = 7.0

FONT_BODY = {"family": "Segoe UI", "fallback": "sans-serif"}
FONT_HDR  = {"family": "Calibri",  "fallback": "sans-serif"}
FONT_MONO = {"family": "Consolas", "fallback": "monospace"}

def _ff(fd):
    import matplotlib.font_manager as _fm
    if any(f.name == fd["family"] for f in _fm.fontManager.ttflist):
        return fd["family"]
    return fd["fallback"]

# =============================================================================
# SHARED HELPERS
# =============================================================================
def _doy_to_date_str(doy, year=None):
    if year is None: year = OP_YEAR
    try:
        if np.isnan(float(doy)): return "---"
    except (TypeError, ValueError):
        return "---"
    return (datetime.date(year, 1, 1) +
            datetime.timedelta(days=int(round(float(doy))) - 1)
            ).strftime("%d %b")

def _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER):
    ax.set_facecolor(fc)
    for sp in ax.spines.values():
        sp.set_edgecolor(ec); sp.set_linewidth(0.8)

def _hline(ax, y, color, lw=1.0, ls="-", x0=0.0, x1=1.0):
    # Use ax.plot instead of axhline — newer matplotlib rejects transform on axhline
    ax.plot([x0, x1], [y, y], color=color, lw=lw, ls=ls,
            transform=ax.transAxes, clip_on=False, zorder=10)

def _sec(ax, label):
    ax.axis("off")
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0, boxstyle="square,pad=0",
        facecolor=COL_DIVIDER_BG, edgecolor="none",
        transform=ax.transAxes, zorder=1, clip_on=False))
    ax.text(0.012, 0.50, f"   {label}",
            va="center", ha="left",
            fontsize=FS_MM_SEC, fontweight="bold",
            fontfamily=_ff(FONT_HDR),
            color=COL_DIVIDER_TXT,
            transform=ax.transAxes, zorder=2, clip_on=False)

def _pct(v, q):
    a = v[~np.isnan(v)]
    return float(np.percentile(a, q)) if len(a) > 0 else np.nan

def _tlbl(anom, thr=5.0):
    if   anom < -thr: return "Early",  COL_EARLY
    elif anom >  thr: return "Late",   COL_LATE
    else:             return "Normal", COL_NORMAL

def _skill_lbl(hr):
    if hr >= 0.50: return "Good",  COL_NORMAL
    if hr >= 0.40: return "Fair",  "#92680A"
    return               "Low",   COL_RISK_HI

# =============================================================================
# PER-MODEL PIXEL EXTRACTION
# =============================================================================
def _model_pixel(mkey, pi, pj):
    md  = MODELS[mkey]
    oi  = md["op_idx"]
    nm  = md["n_members"]

    on_m = md["onset_doy"][:,    oi, pi, pj]
    cs_m = md["cessation_doy"][:, oi, pi, pj]
    lg_m = md["lgp_days"][:,     oi, pi, pj]
    on_v = on_m[~np.isnan(on_m)]
    cs_v = cs_m[~np.isnan(cs_m)]
    lg_v = lg_m[~np.isnan(lg_m)]

    c_on = float(chirps_clim["onset"][pi, pj])
    c_cs = float(chirps_clim["cessation"][pi, pj])

    p_on  = md["probs_damped"]["onset"][:,     oi, pi, pj]
    p_cs  = md["probs_damped"]["cessation"][:, oi, pi, pj]
    p_lgp = md["probs_damped"]["lgp"][:,       oi, pi, pj]

    on_med = float(np.nanmedian(on_v)) if len(on_v) > 0 else np.nan
    cs_med = float(np.nanmedian(cs_v)) if len(cs_v) > 0 else np.nan
    lg_med = float(np.nanmedian(lg_v)) if len(lg_v) > 0 else np.nan

    return {
        "on_med": on_med, "cs_med": cs_med, "lg_med": lg_med,
        "on_anom": on_med - c_on if not np.isnan(on_med) else 0.0,
        "cs_anom": cs_med - c_cs if not np.isnan(cs_med) else 0.0,
        "on_p10": _pct(on_v, 10), "on_p90": _pct(on_v, 90),
        "cs_p10": _pct(cs_v, 10), "cs_p90": _pct(cs_v, 90),
        "lg_p10": _pct(lg_v, 10), "lg_p90": _pct(lg_v, 90),
        "p_on": p_on, "p_cs": p_cs, "p_lgp": p_lgp,
        "dom_on":  int(np.argmax(p_on)),
        "dom_cs":  int(np.argmax(p_cs)),
        "dom_lgp": int(np.argmax(p_lgp)),
        "agree_on":  float(np.max(p_on)),
        "agree_cs":  float(np.max(p_cs)),
        "agree_lgp": float(np.max(p_lgp)),
        "p_fail": float(np.sum(np.isnan(on_m))) / max(nm, 1),
        "hr_on":  float(np.nanmean(md["hitrate_cal"]["onset"][lm])),
        "hr_cs":  float(np.nanmean(md["hitrate_cal"]["cessation"][lm])),
        "hr_lgp": float(np.nanmean(md["hitrate_cal"]["lgp"][lm])),
        "rpss_on":  float(np.nanmean(md["rpss_val"]["onset"][lm]))    if not np.all(np.isnan(md["rpss_val"]["onset"][lm]))    else np.nan,
        "rpss_cs":  float(np.nanmean(md["rpss_val"]["cessation"][lm])) if not np.all(np.isnan(md["rpss_val"]["cessation"][lm])) else np.nan,
        "rpss_lgp": float(np.nanmean(md["rpss_val"]["lgp"][lm]))      if not np.all(np.isnan(md["rpss_val"]["lgp"][lm]))      else np.nan,
        "alpha_on": float(np.nanmean(md["alpha"]["onset"][lm])),
        "nm": nm,
        "on_v": on_v, "cs_v": cs_v, "lg_v": lg_v,
    }


def _consensus(pixel_stats, skill_thr=1/3):
    """
    Equal-weight MMM and skill-screened equal-weight MMM.
    Skill screen: include only models with domain-mean CAL HR > skill_thr.
    """
    mn  = list(pixel_stats.keys())
    out = {}
    for vn, pkey, hrkey in [
        ("on",  "p_on",  "hr_on"),
        ("cs",  "p_cs",  "hr_cs"),
        ("lgp", "p_lgp", "hr_lgp"),
    ]:
        probs_all = np.array([pixel_stats[m][pkey] for m in mn])
        eq = probs_all.mean(axis=0)

        passed = [m for m in mn if pixel_stats[m][hrkey] > skill_thr]
        if len(passed) >= 2:
            sk = np.array([pixel_stats[m][pkey] for m in passed]).mean(axis=0)
        else:
            sk = eq; passed = mn

        out[vn] = {"eq": eq, "sk": sk,
                   "n_passed": len(passed), "n_total": len(mn),
                   "passed": passed}
    return out


# =============================================================================
# HEADER
# =============================================================================
def _draw_mm_header(fig, site_name, glat, glon, dkm,
                    hdr_bot, hdr_h, sub_bot, sub_h):
    fig.patches.append(mpatches.FancyBboxPatch(
        (0.0, hdr_bot), 1.0, hdr_h, boxstyle="square,pad=0",
        facecolor=COL_HDR_BG, edgecolor="none",
        transform=fig.transFigure, zorder=10, clip_on=False))
    fig.patches.append(mpatches.FancyBboxPatch(
        (0.0, hdr_bot + hdr_h - 0.004), 1.0, 0.004,
        boxstyle="square,pad=0", facecolor=COL_HDR_ACCENT,
        edgecolor="none", transform=fig.transFigure,
        zorder=11, clip_on=False))
    fig.text(0.50, hdr_bot + hdr_h * 0.78,
             "MULTI-MODEL SEASONAL FORECAST BULLETIN",
             ha="center", va="center",
             fontsize=FS_MM_HDR_TITLE, fontweight="bold",
             color=COL_HDR_TITLE, fontfamily=_ff(FONT_HDR),
             transform=fig.transFigure, zorder=12)
    fig.text(0.50, hdr_bot + hdr_h * 0.42,
             site_name, ha="center", va="center",
             fontsize=FS_MM_HDR_SITE, fontweight="bold",
             color=COL_HDR_SITE, fontfamily=_ff(FONT_HDR),
             transform=fig.transFigure, zorder=12)
    for k, txt in enumerate([
        f"Lat: {glat:.4f} N   Lon: {glon:.4f} E   Grid delta: {dkm:.1f} km",
        f"Init: {MM_INIT_DATE}   Valid: {MM_VALID_STR}",
        f"N models: {len(MODELS)}   Issued: {MM_ISSUED_STR}",
    ]):
        fig.text(0.01 + k * 0.33, hdr_bot + hdr_h * 0.10,
                 txt, ha="left", va="center",
                 fontsize=FS_MM_HDR_META, color=COL_HDR_META,
                 fontfamily=_ff(FONT_MONO),
                 transform=fig.transFigure, zorder=12)

    fig.patches.append(mpatches.FancyBboxPatch(
        (0.0, sub_bot), 1.0, sub_h, boxstyle="square,pad=0",
        facecolor=COL_SUBHDR_BG, edgecolor="none",
        transform=fig.transFigure, zorder=10, clip_on=False))
    fig.text(0.012, sub_bot + sub_h * 0.50,
             "Models:  " + "  |  ".join(MODELS.keys()),
             ha="left", va="center",
             fontsize=FS_MM_HDR_META, color=COL_SUBHDR_TXT,
             fontfamily=_ff(FONT_MONO),
             transform=fig.transFigure, zorder=11)

    # Third header band removed — ruleset/CHIRPS line no longer displayed

    # ── Logo — top-right of header band (same position as single-model bulletin) ─
    LOGO_LEFT = 0.884; LOGO_W = 0.112
    try:
        import matplotlib.image as _mpimg
        logo    = _mpimg.imread(ILRI_LOGO_PATH)
        ax_logo = fig.add_axes(
            [LOGO_LEFT, hdr_bot + 0.002, LOGO_W, hdr_h - 0.004])
        ax_logo.imshow(logo, aspect="equal", interpolation="lanczos")
        ax_logo.axis("off"); ax_logo.patch.set_alpha(0); ax_logo.set_zorder(13)
    except Exception:
        fig.text(LOGO_LEFT + LOGO_W / 2, hdr_bot + hdr_h * 0.50,
                 "ILRI", ha="center", va="center",
                 fontsize=FS_MM_HDR_TITLE, fontweight="bold",
                 color=COL_HDR_ACCENT, zorder=12,
                 transform=fig.transFigure)


# =============================================================================
# TIMING SUMMARY TABLE
# =============================================================================
def _draw_timing_table(ax, pixel_stats):
    ax.axis("off")
    _box(ax, fc=COL_PANEL_BG2, ec=COL_TXT_NAVY2)
    ax.text(0.50, 0.985,
            "MULTI-MODEL TIMING SUMMARY  (Ensemble Median  |  P10-P90 spread)",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=13.0, fontweight="bold", color=COL_TXT_NAVY,
            fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.930, COL_TXT_NAVY2, lw=1.2, x0=0.01, x1=0.99)

    for x, hdr in [
        (0.01, "Model"),         (0.22, "N"),
        (0.27, "Onset P50\n(date)"),    (0.43, "Cess P50\n(date)"),
        (0.58, "LGP P50\n(days)"),      (0.67, "Onset\nAnom"),
        (0.76, "Onset\nTiming"),        (0.86, "Onset P10-P90"),
    ]:
        ax.text(x, 0.885, hdr, transform=ax.transAxes,
                fontsize=FS_MM_TBL_HDR, fontweight="bold",
                color=COL_TXT_NAVY2, va="top",
                fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.810, COL_BORDER, lw=0.7, x0=0.01, x1=0.99)

    model_keys = list(pixel_stats.keys())
    row_h = 0.75 / max(len(model_keys), 1)
    y = 0.790

    for k, mkey in enumerate(model_keys):
        ps   = pixel_stats[mkey]
        col  = MODELS[mkey].get("color", MM_MODEL_COLORS[k % len(MM_MODEL_COLORS)])
        bg   = COL_PANEL_BG if k % 2 == 0 else COL_PANEL_BG2
        tlbl, tcol = _tlbl(ps["on_anom"])
        row_mid = y - row_h / 2

        ax.add_patch(mpatches.FancyBboxPatch(
            (0.01, y - row_h + 0.003), 0.98, row_h - 0.006,
            boxstyle="square,pad=0", facecolor=bg,
            edgecolor="none", alpha=0.6,
            transform=ax.transAxes, zorder=0))
        ax.add_patch(mpatches.Circle(
            (0.018, row_mid), 0.010,
            color=col, transform=ax.transAxes, zorder=3))

        on_str = (f"DOY {ps['on_med']:.0f}  {_doy_to_date_str(ps['on_med'])}"
                  if not np.isnan(ps["on_med"]) else "---")
        cs_str = (f"DOY {ps['cs_med']:.0f}  {_doy_to_date_str(ps['cs_med'])}"
                  if not np.isnan(ps["cs_med"]) else "---")
        sp_str = (f"{_doy_to_date_str(ps['on_p10'])} - "
                  f"{_doy_to_date_str(ps['on_p90'])}")

        for x, txt, fs, fc, bold in [
            (0.03, mkey,                      FS_MM_TBL_MODEL, col,      True),
            (0.22, str(ps["nm"]),             FS_MM_TBL_SMALL, COL_TXT_MID, False),
            (0.27, on_str,                    FS_MM_TBL_VAL,   COL_TXT_NAVY, False),
            (0.43, cs_str,                    FS_MM_TBL_VAL,   COL_TXT_NAVY, False),
            (0.58, f"{ps['lg_med']:.0f}d",   FS_MM_TBL_VAL,   COL_TXT_NAVY, False),
            (0.67, f"{ps['on_anom']:+.1f}d", FS_MM_TBL_VAL,   tcol,    True),
            (0.76, tlbl,                      FS_MM_TBL_VAL,   tcol,    True),
            (0.86, sp_str,                    FS_MM_TBL_SMALL, COL_TXT_MID, False),
        ]:
            ax.text(x, row_mid, txt, transform=ax.transAxes,
                    fontsize=fs, va="center", color=fc,
                    fontweight="bold" if bold else "normal",
                    fontfamily=_ff(FONT_BODY))
        y -= row_h
        _hline(ax, y + 0.003, COL_BORDER, lw=0.3, x0=0.01, x1=0.99)

    # CHIRPS CAL reference
    c_on  = float(np.nanmean(chirps_clim["onset"][lm]))
    c_cs  = float(np.nanmean(chirps_clim["cessation"][lm]))
    c_lgp = float(np.nanmean(chirps_clim["lgp"][lm]))
    _hline(ax, y + 0.002, COL_TXT_NAVY2, lw=1.0, x0=0.01, x1=0.99)
    ax.text(0.03, max(y - 0.016, 0.01),
            f"CHIRPS CAL reference:  Onset DOY {c_on:.0f} "
            f"({_doy_to_date_str(c_on)})   "
            f"Cessation DOY {c_cs:.0f} ({_doy_to_date_str(c_cs)})   "
            f"LGP {c_lgp:.0f}d",
            transform=ax.transAxes, fontsize=6.5, va="top",
            color=COL_TXT_MUTED, style="italic",
            fontfamily=_ff(FONT_BODY))


# =============================================================================
# A(D) PLUME COMPARISON
# =============================================================================
def _draw_ad_plume(ax, pi, pj):
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
    _win_doys  = np.arange(WIN_DOY_START, WIN_DOY_END + 1, dtype=np.int32)
    _c_clim_px = C_clim[:, pi, pj]
    _ds_px     = int(round(float(d_s[pi, pj])))
    _de_px     = int(round(float(d_e[pi, pj])))
    _ds_k      = int(np.nanargmin(_c_clim_px))
    _de_k      = _ds_k + int(np.nanargmax(_c_clim_px[_ds_k:]))

    ax.axvspan(WIN_DOY_START, _ds_px, color="#FDE8D8", alpha=0.30, zorder=0)
    ax.axvspan(_ds_px, _de_px,        color="#C8EDD8", alpha=0.30, zorder=0)
    ax.axvspan(_de_px, WIN_DOY_END,   color="#EEF2F7", alpha=0.25, zorder=0)
    ax.axhline(0, color="black", lw=0.7, ls="--", alpha=0.35)

    ax.plot(_win_doys, _c_clim_px, color=COL_CHIRPS,
            lw=2.8, zorder=6, label="CHIRPS CAL C(d)")

    ax.plot(_ds_px, _c_clim_px[_ds_k], "o",
            color="magenta", ms=8, mec="white", mew=1.2, zorder=8)
    ax.plot(_de_px, _c_clim_px[_de_k], "o",
            color="magenta", ms=8, mec="white", mew=1.2, zorder=8)
    ax.annotate(f"d_s DOY {_ds_px}\n{_doy_to_date_str(_ds_px)}",
                xy=(_ds_px, _c_clim_px[_ds_k]),
                xytext=(_ds_px - 14, _c_clim_px[_ds_k] * 0.60),
                fontsize=5.5, color="magenta", ha="center",
                fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="magenta", lw=0.8),
                path_effects=[mpe.withStroke(linewidth=1.8, foreground="white")])
    ax.annotate(f"d_e DOY {_de_px}\n{_doy_to_date_str(_de_px)}",
                xy=(_de_px, _c_clim_px[_de_k]),
                xytext=(_de_px + 14, _c_clim_px[_de_k] * 0.80),
                fontsize=5.5, color="magenta", ha="center",
                fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="magenta", lw=0.8),
                path_effects=[mpe.withStroke(linewidth=1.8, foreground="white")])

    Q_bar_px = float(Q_bar[pi, pj])
    for k, (mkey, md) in enumerate(MODELS.items()):
        col    = md.get("color", MM_MODEL_COLORS[k % len(MM_MODEL_COLORS)])
        oi     = md["op_idx"]
        all_bc = md["bc_daily"][:, oi, :, pi, pj]  # (n_mem, n_days)

        # Skip if bc_daily is a zero stub (LOAD_BC_DAILY=False or file missing)
        if np.all(all_bc == 0):
            continue

        # Trim _win_doys to match actual forecast days (181 or 182)
        _nd    = all_bc.shape[1]
        _wdoys = _win_doys[:_nd]

        A_all  = np.nancumsum(all_bc - Q_bar_px, axis=1)
        A_med  = np.nanmedian(A_all, axis=0)
        ax.plot(_wdoys, A_med, color=col, lw=1.6,
                zorder=5, label=mkey, alpha=0.88)
        on_med = float(np.nanmedian(md["onset_doy"][:, oi, pi, pj]))
        if not np.isnan(on_med):
            ki = int(min(max(int(on_med) - WIN_DOY_START, 0), _nd - 1))
            ax.plot(on_med, A_med[ki], "D",
                    color=col, ms=5, mec="white", mew=0.8, zorder=7)

    ax.set_xlim(WIN_DOY_START, WIN_DOY_END)
    _mo = [(32,"Feb"),(60,"Mar"),(91,"Apr"),(121,"May"),
           (152,"Jun"),(182,"Jul"),(213,"Aug")]
    ax.set_xticks([d for d,_ in _mo])
    ax.set_xticklabels([m for _,m in _mo],
                       fontsize=FS_MM_PLUME_TICK, color=COL_TXT_MID)
    ax.set_ylabel("C(d) / A(D) mm", fontsize=FS_MM_PLUME_AXIS,
                  color=COL_TXT_MID)
    ax.set_title("Multi-Model A(D) vs CHIRPS C(d)"
                 "  |  Median per model  |  diamond = onset",
                 fontsize=FS_MM_PLUME_TTL, fontweight="bold",
                 color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))
    ax.legend(fontsize=FS_MM_PLUME_LEG, ncol=2,
              loc="lower right", framealpha=0.90,
              edgecolor=COL_BORDER, handlelength=1.4, labelspacing=0.3)
    ax.grid(True, lw=0.3, alpha=0.30)
    ax.tick_params(labelsize=FS_MM_PLUME_TICK, colors=COL_TXT_MID)


# =============================================================================
# MULTI-MODEL GROUPED BAR CHARTS
# =============================================================================
def _draw_mm_bars(axes, pixel_stats):
    model_keys = list(pixel_stats.keys())
    n   = len(model_keys)
    w   = 0.22
    gap = 0.08
    grp = w * 3 + gap

    vns = [("on",  "Onset of Rains",          "p_on",  "dom_on"),
           ("cs",  "Cessation of Rains",       "p_cs",  "dom_cs"),
           ("lgp", "Length of Growing Period", "p_lgp", "dom_lgp")]

    for ax, (vn, vname, pkey, domkey) in zip(axes, vns):
        _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
        ax.axhline(1/3, color=COL_TXT_MUTED, lw=1.0, ls="--",
                   alpha=0.60, zorder=3)
        ax.axhspan(0, 1/3, color=COL_PANEL_BG2, alpha=0.50, zorder=0)

        xtick_pos = []; xtick_lbl = []
        for ki, mkey in enumerate(model_keys):
            ps   = pixel_stats[mkey]
            col  = MODELS[mkey].get("color",
                                     MM_MODEL_COLORS[ki % len(MM_MODEL_COLORS)])
            pb   = ps[pkey]
            dom  = ps[domkey]
            x0   = ki * grp

            for bi, (pv, bc) in enumerate(zip(pb, [COL_BN, COL_NN, COL_AN])):
                xb = x0 + bi * w
                ax.bar(xb, pv, width=w * 0.90,
                       color=bc, alpha=0.80,
                       edgecolor="white", linewidth=0.5, zorder=2)
                if bi == dom:
                    ax.bar(xb, pv, width=w * 0.90,
                           color="none", edgecolor=col,
                           linewidth=2.0, zorder=4)
                if pv >= 0.38:
                    ax.text(xb, pv + 0.010, f"{pv:.2f}",
                            ha="center", va="bottom",
                            fontsize=5.8, fontweight="bold",
                            color=COL_TXT_DARK)

            xtick_pos.append(x0 + w)
            xtick_lbl.append(mkey.split()[0][:6])

        ax.set_xticks(xtick_pos)
        ax.set_xticklabels(xtick_lbl, fontsize=6.5, color=COL_TXT_MID,
                           rotation=25, ha="right")
        ax.set_ylim(0, 0.72)
        ax.set_ylabel("Probability", fontsize=FS_MM_PLUME_AXIS,
                      color=COL_TXT_MID)
        ax.set_title(f"{vname}\n"
                     "BN = brown  NN = gold  AN = green  |  "
                     "outline = dominant",
                     fontsize=FS_MM_BAR_TITLE, fontweight="bold",
                     color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))
        ax.tick_params(axis="y", labelsize=7.0, colors=COL_TXT_MUTED)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


# =============================================================================
# CONSENSUS FORECAST PANEL
# =============================================================================
def _draw_consensus(ax, consensus):
    ax.axis("off")
    _box(ax, fc=COL_PANEL_BG2, ec=COL_TXT_NAVY2)
    ax.text(0.50, 0.985, "MULTI-MODEL CONSENSUS FORECAST",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=9.5, fontweight="bold", color=COL_TXT_NAVY,
            fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.920, COL_TXT_NAVY2, lw=1.2, x0=0.01, x1=0.99)
    ax.text(0.25, 0.880, "Equal-Weight MMM",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=8.0, fontweight="bold", color=COL_TXT_NAVY2,
            fontfamily=_ff(FONT_HDR))
    ax.text(0.75, 0.880,
            "Skill-Screened MMM  (HR > 0.333)",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=8.0, fontweight="bold", color=COL_TXT_NAVY2,
            fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.790, COL_BORDER, lw=0.8, x0=0.01, x1=0.99)
    # axvline rejects transform= in newer matplotlib — use ax.plot instead
    ax.plot([0.50, 0.50], [0.05, 0.95], color=COL_BORDER, lw=1.0,
            transform=ax.transAxes, clip_on=False)

    vn_rows  = [("on",  "Onset",     COL_BN_LITE),
                ("cs",  "Cessation", COL_NN_LITE),
                ("lgp", "LGP",       COL_AN_LITE)]
    cat_cols = [COL_BN, COL_NN, COL_AN]
    cats     = ["BN", "NN", "AN"]
    y = 0.755; row_h = 0.205

    for vn, vname, rbg in vn_rows:
        cons     = consensus[vn]
        row_bot  = y - row_h + 0.008
        row_mid  = y - row_h / 2

        for x0 in [0.02, 0.51]:
            ax.add_patch(mpatches.FancyBboxPatch(
                (x0, row_bot), 0.47, row_h - 0.012,
                boxstyle="square,pad=0", facecolor=rbg,
                edgecolor="none", alpha=0.40,
                transform=ax.transAxes, zorder=0))

        for x0 in [0.03, 0.52]:
            ax.text(x0, row_mid, vname, transform=ax.transAxes,
                    fontsize=8.5, fontweight="bold",
                    va="center", color=COL_TXT_NAVY,
                    fontfamily=_ff(FONT_BODY))

        for x_off, probs, n_pass, n_tot in [
            (0.14, cons["eq"], len(MODELS),       len(MODELS)),
            (0.62, cons["sk"], cons["n_passed"],  cons["n_total"]),
        ]:
            dom = int(np.argmax(probs))
            for bi, (pv, cat, cc) in enumerate(zip(probs, cats, cat_cols)):
                bx = x_off + bi * 0.082
                by = row_mid - 0.062
                bh = pv * 0.360
                ax.add_patch(mpatches.Rectangle(
                    (bx - 0.026, by), 0.054, bh,
                    facecolor=cc, edgecolor="white",
                    linewidth=0.5, alpha=0.85,
                    transform=ax.transAxes, zorder=2))
                if bi == dom:
                    ax.add_patch(mpatches.Rectangle(
                        (bx - 0.026, by), 0.054, bh,
                        facecolor="none",
                        edgecolor=COL_DOM_OUTLINE, linewidth=2.0,
                        transform=ax.transAxes, zorder=3))
                ax.text(bx, by + bh + 0.012, f"{pv:.2f}",
                        ha="center", va="bottom",
                        transform=ax.transAxes,
                        fontsize=7.5, fontweight="bold",
                        color=cc)
                ax.text(bx, by - 0.018, cat, ha="center", va="top",
                        transform=ax.transAxes, fontsize=6.5,
                        color=COL_TXT_MID, fontfamily=_ff(FONT_BODY))

            lbl = (f"{n_tot}/{n_tot} models"
                   if n_pass == n_tot
                   else f"{n_pass}/{n_tot} models\n(screened)")
            ax.text(x_off + 0.082, row_mid + 0.062, lbl,
                    ha="center", va="bottom",
                    transform=ax.transAxes, fontsize=5.8,
                    color=COL_TXT_MUTED, style="italic",
                    fontfamily=_ff(FONT_BODY))

        y -= row_h
        _hline(ax, y + 0.008, COL_BORDER, lw=0.4, x0=0.01, x1=0.99)

    ax.text(0.02, 0.02,
            "Equal-weight: all models averaged.   "
            "Skill-screened: models with domain-mean CAL HR > 0.333 only.   "
            "Outline = dominant category.   Dashed = 1/3 baseline.",
            transform=ax.transAxes, fontsize=5.8, va="bottom",
            color=COL_TXT_MUTED, style="italic",
            fontfamily=_ff(FONT_BODY))


# =============================================================================
# ENSEMBLE AGREEMENT HEATMAP
# =============================================================================
def _draw_agreement_heatmap(ax, pixel_stats):
    model_keys = list(pixel_stats.keys())
    n = len(model_keys)
    vn_labels = ["Onset", "Cessation", "LGP"]
    ak_keys   = ["agree_on", "agree_cs", "agree_lgp"]

    data = np.array([[pixel_stats[m][k] for m in model_keys]
                     for k in ak_keys])    # (3, n_models)

    cmap = mpl.colormaps.get_cmap("RdYlGn")
    norm = mpl.colors.Normalize(vmin=0.33, vmax=0.70)

    for ri in range(3):
        for ci in range(n):
            v    = data[ri, ci]
            rgba = cmap(norm(v))
            ax.add_patch(mpatches.FancyBboxPatch(
                (ci / n + 0.002, (2 - ri) / 3 + 0.012),
                1/n - 0.004, 1/3 - 0.020,
                boxstyle="round,pad=0.01",
                facecolor=rgba, edgecolor="white",
                linewidth=0.8, transform=ax.transAxes, zorder=2))
            ax.text(ci/n + 1/(2*n), (2-ri)/3 + 1/6,
                    f"{v:.0%}", ha="center", va="center",
                    transform=ax.transAxes,
                    fontsize=FS_MM_HEAT_LBL, fontweight="bold",
                    color="white" if v > 0.55 else COL_TXT_DARK,
                    fontfamily=_ff(FONT_BODY))

    for ci, mkey in enumerate(model_keys):
        ax.text(ci/n + 1/(2*n), -0.06,
                mkey.split()[0][:8], ha="center", va="top",
                transform=ax.transAxes, fontsize=6.0,
                color=COL_TXT_MID, rotation=22,
                fontfamily=_ff(FONT_BODY))
    for ri, lbl in enumerate(vn_labels):
        ax.text(-0.01, (2-ri)/3 + 1/6, lbl, ha="right", va="center",
                transform=ax.transAxes, fontsize=7.5,
                fontweight="bold", color=COL_TXT_NAVY,
                fontfamily=_ff(FONT_BODY))

    ax.axis("off")
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
    ax.set_title("Ensemble Agreement  |  33% = no signal  |  "
                 "Green > 50% = strong signal",
                 fontsize=8.0, fontweight="bold",
                 color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))

    sm  = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cax = ax.inset_axes([0.02, -0.20, 0.96, 0.06])
    cb  = plt.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_label("Ensemble Agreement (fraction dominant tercile)",
                 fontsize=6.0, color=COL_TXT_MID)
    cb.ax.tick_params(labelsize=5.5)
    cb.set_ticks([0.33, 0.40, 0.50, 0.60, 0.70])
    cb.set_ticklabels(["0.33\n(baseline)", "0.40", "0.50", "0.60", "0.70"])


# =============================================================================
# MULTI-MODEL RISK RANGES
# =============================================================================
def _draw_mm_risk(ax, pixel_stats):
    ax.axis("off")
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
    ax.set_title(
        "Multi-Model Risk Range  (min - median - max across models)"
        "  |  vertical bar = median  |  shaded = min-max range"
        "  |  dotted line = 1/3 baseline",
        fontsize=13.0, fontweight="bold",
        color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))

    LATE_THRESH  = float(np.nanmedian(t67_onset[lm]))
    EARLY_THRESH = float(np.nanmedian(t33_onset[lm]))
    model_keys   = list(pixel_stats.keys())

    def _rv(fn):
        return np.array([fn(pixel_stats[m]) for m in model_keys])

    risks = [
        ("P(Late Onset)",
         f"onset > DOY {LATE_THRESH:.0f}  ({_doy_to_date_str(LATE_THRESH)})",
         _rv(lambda ps: (float(np.mean(ps["on_v"] > LATE_THRESH))
                          if len(ps["on_v"]) > 0 else 0.)),
         COL_RISK_HI),
        ("P(Early Onset)",
         f"onset < DOY {EARLY_THRESH:.0f}  ({_doy_to_date_str(EARLY_THRESH)})",
         _rv(lambda ps: (float(np.mean(ps["on_v"] < EARLY_THRESH))
                          if len(ps["on_v"]) > 0 else 0.)),
         COL_EARLY),
        ("P(LGP < 35d)", "Near-total crop failure",
         _rv(lambda ps: (float(np.mean(ps["lg_v"] < 35))
                          if len(ps["lg_v"]) > 0 else 0.)),
         COL_RISK_CRIT),
        ("P(LGP < 45d)", "Below maize minimum requirement",
         _rv(lambda ps: (float(np.mean(ps["lg_v"] < 45))
                          if len(ps["lg_v"]) > 0 else 0.)),
         COL_RISK_HI),
        ("P(LGP < 60d)", "Below standard maize maturity",
         _rv(lambda ps: (float(np.mean(ps["lg_v"] < 60))
                          if len(ps["lg_v"]) > 0 else 0.)),
         COL_RISK_MED),
        ("P(Season Failure)", "No onset detected in member",
         _rv(lambda ps: ps["p_fail"]),
         COL_RISK_CRIT),
    ]

    n_r   = len(risks)
    row_h = 0.82 / n_r
    y     = 0.90
    BL    = 0.35    # left edge of bar track
    BW    = 0.55    # bar track width

    for (label, sub, vals, col) in risks:
        v_min = float(np.nanmin(vals))
        v_med = float(np.nanmedian(vals))
        v_max = float(np.nanmax(vals))
        rm    = y - row_h / 2

        ax.text(0.01, rm + 0.010, label,
                transform=ax.transAxes, fontsize=7.5,
                fontweight="bold", va="center", color=COL_TXT_NAVY,
                fontfamily=_ff(FONT_BODY))
        ax.text(0.01, rm - 0.025, sub,
                transform=ax.transAxes, fontsize=6.0,
                va="center", color=COL_TXT_MUTED, style="italic",
                fontfamily=_ff(FONT_BODY))

        # Track
        ax.add_patch(mpatches.FancyBboxPatch(
            (BL, rm - 0.018), BW, 0.036,
            boxstyle="round,pad=0.002",
            facecolor=COL_PANEL_BG2, edgecolor=COL_BORDER,
            linewidth=0.5, transform=ax.transAxes, zorder=1))
        # 1/3 reference tick
        ax.add_patch(mpatches.Rectangle(
            (BL + BW/3 - 0.002, rm - 0.024), 0.004, 0.048,
            facecolor=COL_TXT_MUTED, alpha=0.40,
            transform=ax.transAxes, zorder=2))
        # Range fill
        rx = BL + v_min * BW
        rw = max((v_max - v_min) * BW, 0.004)
        ax.add_patch(mpatches.FancyBboxPatch(
            (rx, rm - 0.014), rw, 0.028,
            boxstyle="round,pad=0.001",
            facecolor=col, edgecolor="none", alpha=0.35,
            transform=ax.transAxes, zorder=2))
        # Median bar
        ax.add_patch(mpatches.Rectangle(
            (BL + v_med * BW - 0.005, rm - 0.020), 0.010, 0.040,
            facecolor=col, edgecolor="white",
            linewidth=0.8, transform=ax.transAxes, zorder=3))
        # Values
        ax.text(BL - 0.01, rm, f"min={v_min:.2f}",
                ha="right", va="center", transform=ax.transAxes,
                fontsize=6.0, color=COL_TXT_MID, fontfamily=_ff(FONT_BODY))
        ax.text(BL + BW + 0.01, rm,
                f"med={v_med:.2f}  max={v_max:.2f}",
                ha="left", va="center", transform=ax.transAxes,
                fontsize=6.0, color=COL_TXT_MID, fontfamily=_ff(FONT_BODY))

        y -= row_h
        _hline(ax, y + 0.005, COL_BORDER, lw=0.3, x0=0.01, x1=0.99)

    for tick in [0, 0.25, 1/3, 0.50, 0.75, 1.0]:
        ax.text(BL + tick * BW, 0.025, f"{tick:.0%}",
                ha="center", va="top", transform=ax.transAxes,
                fontsize=5.5, color=COL_TXT_MUTED,
                fontfamily=_ff(FONT_BODY))


# =============================================================================
# PER-MODEL SKILL TABLE
# =============================================================================
def _draw_skill_table(ax, pixel_stats):
    ax.axis("off")
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
    ax.text(0.50, 0.985,
            "PER-MODEL FORECAST SKILL  (domain-mean, land pixels)",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=13.0, fontweight="bold", color=COL_TXT_NAVY,
            fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.930, COL_TXT_NAVY2, lw=1.2, x0=0.01, x1=0.99)

    for x, hdr in [
        (0.01, "Model"),    (0.22, "N"),
        (0.29, "alpha*\nonset"),
        (0.37, "CAL HR\nonset"),  (0.45, "VAL HR\nonset"),
        (0.53, "VAL RPSS\nonset"),
        (0.62, "VAL HR\ncess"),   (0.71, "VAL RPSS\ncess"),
        (0.80, "VAL HR\nLGP"),    (0.88, "Skill\nscreen"),
    ]:
        ax.text(x, 0.885, hdr, transform=ax.transAxes,
                fontsize=FS_MM_SKILL_HDR, fontweight="bold",
                color=COL_TXT_NAVY2, va="top",
                fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.810, COL_BORDER, lw=0.7, x0=0.01, x1=0.99)

    model_keys = list(pixel_stats.keys())
    row_h = 0.70 / max(len(model_keys), 1)
    y     = 0.790

    def _hrc(hr): return COL_NORMAL if hr > 0.40 else ("#92680A" if hr > 1/3 else COL_RISK_HI)
    def _rc(r):   return COL_NORMAL if r > 0.01  else (COL_TXT_MID if r > -0.01 else COL_RISK_HI)

    for k, mkey in enumerate(model_keys):
        ps   = pixel_stats[mkey]
        col  = MODELS[mkey].get("color", MM_MODEL_COLORS[k % len(MM_MODEL_COLORS)])
        bg   = COL_PANEL_BG if k % 2 == 0 else COL_PANEL_BG2
        slbl, scol = _skill_lbl(ps["hr_on"])
        passed = "YES" if ps["hr_on"] > 1/3 else "NO"
        pcol   = COL_NORMAL if passed == "YES" else COL_RISK_HI
        row_mid = y - row_h / 2

        ax.add_patch(mpatches.FancyBboxPatch(
            (0.01, y - row_h + 0.003), 0.98, row_h - 0.006,
            boxstyle="square,pad=0", facecolor=bg,
            edgecolor="none", alpha=0.55,
            transform=ax.transAxes, zorder=0))
        ax.add_patch(mpatches.Circle(
            (0.018, row_mid), 0.010,
            color=col, transform=ax.transAxes, zorder=3))

        for x, txt, fs, fc, bold in [
            (0.03, mkey,                        FS_MM_SKILL_VAL+0.5, col,            True),
            (0.22, str(ps["nm"]),               FS_MM_SKILL_VAL,     COL_TXT_MID,    False),
            (0.29, f"{ps['alpha_on']:.3f}",     FS_MM_SKILL_VAL,     COL_TXT_MID,    False),
            (0.37, f"{ps['hr_on']:.3f}",        FS_MM_SKILL_VAL,     _hrc(ps["hr_on"]),   True),
            (0.45, f"{ps['hr_on']:.3f}",        FS_MM_SKILL_VAL,     _hrc(ps["hr_on"]),   True),
            (0.53, f"{ps['rpss_on']:+.3f}",     FS_MM_SKILL_VAL,     _rc(ps["rpss_on"]),  True),
            (0.62, f"{ps['hr_cs']:.3f}",        FS_MM_SKILL_VAL,     _hrc(ps["hr_cs"]),   False),
            (0.71, f"{ps['rpss_cs']:+.3f}",     FS_MM_SKILL_VAL,     _rc(ps["rpss_cs"]),  False),
            (0.80, f"{ps['hr_lgp']:.3f}",       FS_MM_SKILL_VAL,     _hrc(ps["hr_lgp"]),  False),
            (0.88, f"{passed}  ({slbl})",        FS_MM_SKILL_VAL,     pcol,            True),
        ]:
            ax.text(x, row_mid, txt, transform=ax.transAxes,
                    fontsize=fs, va="center", color=fc,
                    fontweight="bold" if bold else "normal",
                    fontfamily=_ff(FONT_BODY))
        y -= row_h
        _hline(ax, y + 0.003, COL_BORDER, lw=0.3, x0=0.01, x1=0.99)

    ax.text(0.01, max(y - 0.015, 0.01),
            "Skill screen: HR > 0.333 (above climatological baseline)   |   "
            "HR = Hit Rate   |   RPSS = Ranked Probability Skill Score   |   "
            "alpha* = pooling weight (0 = climatology, 1 = pure model)",
            transform=ax.transAxes, fontsize=6.0, va="top",
            color=COL_TXT_MUTED, style="italic",
            fontfamily=_ff(FONT_BODY))


# =============================================================================
# FOOTER
# =============================================================================
def _draw_mm_footer(fig, ftr_h):
    fig.patches.append(mpatches.FancyBboxPatch(
        (0.0, 0.0), 1.0, ftr_h, boxstyle="square,pad=0",
        facecolor=COL_FOOTER_BG, edgecolor="none",
        transform=fig.transFigure, zorder=10, clip_on=False))
    fig.patches.append(mpatches.FancyBboxPatch(
        (0.0, ftr_h - 0.003), 1.0, 0.003,
        boxstyle="square,pad=0", facecolor=COL_HDR_ACCENT,
        edgecolor="none", transform=fig.transFigure,
        zorder=11, clip_on=False))
    model_str = "  |  ".join(MODELS.keys())
    fig.text(0.012, ftr_h * 0.72,
             f"MULTI-MODEL FORECAST  |  {model_str}  "
             f"|  Issued: {MM_ISSUED_STR}",
             ha="left", va="center",
             fontsize=FS_MM_FOOTER, fontweight="bold",
             color=COL_FOOTER_L1, fontfamily=_ff(FONT_HDR),
             transform=fig.transFigure, zorder=12)
    fig.text(0.012, ftr_h * 0.28,
             f"ILRI Climate Services   |   ICPAC Regional Climate Centre   |   "
             f"Kenya MAM {OP_YEAR}   |   Detection: Dunning et al. (2016)   |   "
             f"Calibration: QM-BC + alpha-pooling   |   "
             f"Valid: {MM_VALID_STR}",
             ha="left", va="center",
             fontsize=FS_MM_FOOTER, color=COL_FOOTER_L2,
             fontfamily=_ff(FONT_MONO),
             transform=fig.transFigure, zorder=12)

    # ── Footer logo ───────────────────────────────────────────────────────────
    LOGO_LEFT_FTR = 0.900; LOGO_W_FTR = 0.095
    try:
        import matplotlib.image as _mpimg2
        logo_ftr    = _mpimg2.imread(ILRI_LOGO_PATH)
        ax_logo_ftr = fig.add_axes(
            [LOGO_LEFT_FTR, 0.002, LOGO_W_FTR, ftr_h - 0.006])
        ax_logo_ftr.imshow(logo_ftr, aspect="equal", interpolation="lanczos")
        ax_logo_ftr.axis("off"); ax_logo_ftr.patch.set_alpha(0)
        ax_logo_ftr.set_zorder(13)
    except Exception:
        fig.text(LOGO_LEFT_FTR + LOGO_W_FTR / 2, ftr_h * 0.50,
                 "ILRI", ha="center", va="center",
                 fontsize=FS_MM_FOOTER, fontweight="bold",
                 color=COL_HDR_ACCENT, zorder=12,
                 transform=fig.transFigure)



# =============================================================================
# NEW PANEL 1 — EXCEEDANCE PROBABILITY CURVES
# P(onset <= DOY X) for each model + pooled MMM + CHIRPS historical
# =============================================================================
def _draw_exceedance(ax, pixel_stats):
    """
    Cumulative exceedance curves: P(onset on or before DOY X).
    One coloured line per model + thick black pooled MMM + grey CHIRPS reference.
    """
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
    doy_range = np.arange(40, 161, 1, dtype=np.float32)

    model_keys = list(pixel_stats.keys())

    # CHIRPS historical ECDF
    chirps_on = chirps_onset_doy[cal_idx, pixel_stats[model_keys[0]].get("_pi", 0),
                                  pixel_stats[model_keys[0]].get("_pj", 0)] \
        if "_pi" in pixel_stats[model_keys[0]] else None
    # We pass pi,pj via pixel_stats._pi/_pj; fall back to stored on_v arrays
    # Use chirps_onset_doy directly with cal_idx for the pixel
    # (pi, pj stored as hidden keys in pixel_stats by _model_pixel_with_coords)
    # Fallback: reconstruct from timing table CHIRPS CAL mean only
    c_on_mean = float(np.nanmean(chirps_clim["onset"][lm]))

    # Per-model curves
    all_pooled = []
    for k, (mkey, ps) in enumerate(pixel_stats.items()):
        col = MODELS[mkey].get("color", MM_MODEL_COLORS[k % len(MM_MODEL_COLORS)])
        on_v = ps["on_v"]
        if len(on_v) < 2:
            continue
        ecdf = np.array([np.mean(on_v <= d) for d in doy_range])
        ax.plot(doy_range, ecdf, color=col, lw=1.8, alpha=0.80,
                label=mkey, zorder=4)
        all_pooled.extend(on_v.tolist())

    # Pooled MMM curve
    if all_pooled:
        pooled = np.array(all_pooled)
        ecdf_mm = np.array([np.mean(pooled <= d) for d in doy_range])
        ax.plot(doy_range, ecdf_mm, color=COL_TXT_DARK, lw=2.8,
                ls="-", label="MMM Pooled", zorder=6)

    # CHIRPS CAL reference vertical line at climatological mean
    ax.axvline(c_on_mean, color=COL_CHIRPS, lw=1.8, ls="--",
               alpha=0.70, label=f"CHIRPS CAL mean\n(DOY {c_on_mean:.0f})")

    # Tercile boundaries
    _t33 = float(np.nanmedian(t33_onset[lm]))
    _t67 = float(np.nanmedian(t67_onset[lm]))
    ax.axvline(_t33, color=COL_EARLY, lw=1.0, ls=":", alpha=0.60)
    ax.axvline(_t67, color=COL_LATE,  lw=1.0, ls=":", alpha=0.60)
    ax.text(_t33 - 0.5, 0.96, f"t33\n{_t33:.0f}", ha="right", va="top",
            fontsize=7.5, color=COL_EARLY, transform=ax.get_xaxis_transform())
    ax.text(_t67 + 0.5, 0.96, f"t67\n{_t67:.0f}", ha="left", va="top",
            fontsize=7.5, color=COL_LATE, transform=ax.get_xaxis_transform())

    ax.axhline(0.333, color=COL_TXT_MUTED, lw=0.8, ls="--", alpha=0.50)
    ax.axhline(0.667, color=COL_TXT_MUTED, lw=0.8, ls="--", alpha=0.50)
    ax.text(41, 0.333, "BN boundary (0.33)", fontsize=7.0,
            color=COL_TXT_MUTED, va="bottom")
    ax.text(41, 0.667, "AN boundary (0.67)", fontsize=7.0,
            color=COL_TXT_MUTED, va="bottom")

    ax.set_xlim(40, 160)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Onset DOY", fontsize=FS_MM_PLUME_AXIS, color=COL_TXT_MID)
    ax.set_ylabel("P(onset ≤ DOY)", fontsize=FS_MM_PLUME_AXIS, color=COL_TXT_MID)
    ax.set_title("Exceedance Probability  |  P(onset ≤ DOY X)"
                 "  |  Dashed = CHIRPS CAL mean  |  Dotted = tercile bounds",
                 fontsize=FS_MM_PLUME_TTL, fontweight="bold",
                 color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))
    ax.legend(fontsize=FS_MM_PLUME_LEG, ncol=2, loc="lower right",
              framealpha=0.88, edgecolor=COL_BORDER, handlelength=1.4)
    ax.tick_params(labelsize=FS_MM_PLUME_TICK, colors=COL_TXT_MID)
    ax.grid(True, lw=0.3, alpha=0.30)

    # Month labels on x-axis
    for doy, mon in [(32,"Feb"),(60,"Mar"),(91,"Apr"),(121,"May"),(152,"Jun")]:
        if 40 <= doy <= 160:
            ax.text(doy, -0.06, mon, ha="center", va="top",
                    fontsize=7.5, color=COL_TXT_MUTED,
                    transform=ax.get_xaxis_transform())


# =============================================================================
# NEW PANEL 2 — FAN CHART (onset DOY uncertainty envelope)
# P10/P25/P50/P75/P90 shaded bands per model + pooled
# =============================================================================
def _draw_fan_chart(ax, pixel_stats):
    """
    Horizontal fan chart showing P10/P25/P75/P90 onset DOY spread.
    One row per model, with a pooled MMM row at the bottom.
    """
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)
    ax.axis("off")

    model_keys = list(pixel_stats.keys())
    n = len(model_keys)
    c_on = float(np.nanmean(chirps_clim["onset"][lm]))

    ax.text(0.50, 0.985, "Fan Chart  |  Onset DOY Uncertainty Envelope"
            "  |  P10/P25/P50/P75/P90  |  ▲ = CHIRPS CAL mean",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=FS_MM_PLUME_TTL, fontweight="bold",
            color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))

    _hline(ax, 0.920, COL_TXT_NAVY2, lw=1.0, x0=0.01, x1=0.99)

    # Column headers
    ax.text(0.02, 0.875, "Model", transform=ax.transAxes,
            fontsize=FS_MM_TBL_HDR, fontweight="bold",
            color=COL_TXT_NAVY2, va="top", fontfamily=_ff(FONT_HDR))
    for xp, lbl in [(0.35, "P10"), (0.46, "P25"), (0.57, "P50"),
                     (0.68, "P75"), (0.79, "P90")]:
        ax.text(xp, 0.875, lbl, transform=ax.transAxes,
                fontsize=FS_MM_TBL_HDR, fontweight="bold",
                color=COL_TXT_NAVY2, va="top", ha="center",
                fontfamily=_ff(FONT_HDR))
    ax.text(0.91, 0.875, "Spread\n(P90−P10)", transform=ax.transAxes,
            fontsize=FS_MM_TBL_HDR, fontweight="bold",
            color=COL_TXT_NAVY2, va="top", ha="center",
            fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.820, COL_BORDER, lw=0.6, x0=0.01, x1=0.99)

    # Determine bar x-axis range (DOY 40–160 mapped to axes 0.20–0.88)
    DOY_MIN, DOY_MAX = 40.0, 160.0
    BAR_L, BAR_R = 0.20, 0.88

    def _doy_to_x(doy):
        return BAR_L + (doy - DOY_MIN) / (DOY_MAX - DOY_MIN) * (BAR_R - BAR_L)

    # CHIRPS CAL mean marker line
    cx = _doy_to_x(c_on)

    row_h = 0.76 / max(n + 1, 1)
    y = 0.800

    all_pooled = []
    for k, mkey in enumerate(model_keys):
        ps  = pixel_stats[mkey]
        col = MODELS[mkey].get("color", MM_MODEL_COLORS[k % len(MM_MODEL_COLORS)])
        on_v = ps["on_v"]
        bg = COL_PANEL_BG if k % 2 == 0 else COL_PANEL_BG2
        row_mid = y - row_h / 2
        all_pooled.extend(on_v.tolist())

        ax.add_patch(mpatches.FancyBboxPatch(
            (0.01, y - row_h + 0.002), 0.98, row_h - 0.004,
            boxstyle="square,pad=0", facecolor=bg,
            edgecolor="none", alpha=0.55, transform=ax.transAxes, zorder=0))
        ax.add_patch(mpatches.Circle(
            (0.015, row_mid), 0.010,
            color=col, transform=ax.transAxes, zorder=3))

        if len(on_v) < 2:
            ax.text(0.03, row_mid, mkey, transform=ax.transAxes,
                    fontsize=FS_MM_TBL_MODEL, va="center", color=COL_TXT_MUTED)
            y -= row_h; continue

        p10, p25, p50, p75, p90 = [float(np.percentile(on_v, q))
                                    for q in [10, 25, 50, 75, 90]]
        spread = p90 - p10

        # Model name
        ax.text(0.03, row_mid, mkey, transform=ax.transAxes,
                fontsize=FS_MM_TBL_MODEL, va="center",
                color=COL_TXT_NAVY, fontweight="bold",
                fontfamily=_ff(FONT_BODY))

        # Fan bar: P10-P90 light, P25-P75 medium, P50 marker
        bh = row_h * 0.38
        by = row_mid - bh / 2
        # P10-P90 outer band
        ax.add_patch(mpatches.Rectangle(
            (_doy_to_x(p10), by), _doy_to_x(p90) - _doy_to_x(p10), bh,
            facecolor=col, edgecolor="none", alpha=0.18,
            transform=ax.transAxes, zorder=1))
        # P25-P75 inner band
        ax.add_patch(mpatches.Rectangle(
            (_doy_to_x(p25), by), _doy_to_x(p75) - _doy_to_x(p25), bh,
            facecolor=col, edgecolor="none", alpha=0.45,
            transform=ax.transAxes, zorder=2))
        # P50 median line
        ax.add_patch(mpatches.Rectangle(
            (_doy_to_x(p50) - 0.003, by - 0.005), 0.006, bh + 0.010,
            facecolor=col, edgecolor="white", linewidth=0.6,
            transform=ax.transAxes, zorder=3))
        # CHIRPS CAL mean reference
        ax.add_patch(mpatches.Rectangle(
            (cx - 0.002, by - 0.008), 0.004, bh + 0.016,
            facecolor=COL_CHIRPS, edgecolor="none", alpha=0.70,
            transform=ax.transAxes, zorder=4))

        # Value columns
        for xp, val in [(0.35, p10), (0.46, p25), (0.57, p50),
                         (0.68, p75), (0.79, p90)]:
            ax.text(xp, row_mid, f"{val:.0f}", transform=ax.transAxes,
                    fontsize=FS_MM_TBL_SMALL, va="center", ha="center",
                    color=COL_TXT_MID, fontfamily=_ff(FONT_BODY))
        ax.text(0.91, row_mid, f"{spread:.0f}d", transform=ax.transAxes,
                fontsize=FS_MM_TBL_SMALL, va="center", ha="center",
                color=COL_LATE if spread > 25 else COL_NORMAL,
                fontweight="bold", fontfamily=_ff(FONT_BODY))

        y -= row_h
        _hline(ax, y + 0.002, COL_BORDER, lw=0.25, x0=0.01, x1=0.99)

    # Pooled MMM row
    if all_pooled:
        pooled = np.array(all_pooled)
        _hline(ax, y + 0.002, COL_TXT_NAVY2, lw=0.8, x0=0.01, x1=0.99)
        p10m, p25m, p50m, p75m, p90m = [float(np.percentile(pooled, q))
                                          for q in [10, 25, 50, 75, 90]]
        row_mid = y - row_h / 2
        ax.text(0.03, row_mid, "MMM Pooled", transform=ax.transAxes,
                fontsize=FS_MM_TBL_MODEL, va="center",
                color=COL_TXT_NAVY, fontweight="bold",
                fontfamily=_ff(FONT_BODY))
        bh = row_h * 0.42
        by = row_mid - bh / 2
        ax.add_patch(mpatches.Rectangle(
            (_doy_to_x(p10m), by), _doy_to_x(p90m) - _doy_to_x(p10m), bh,
            facecolor=COL_TXT_NAVY2, edgecolor="none", alpha=0.15,
            transform=ax.transAxes, zorder=1))
        ax.add_patch(mpatches.Rectangle(
            (_doy_to_x(p25m), by), _doy_to_x(p75m) - _doy_to_x(p25m), bh,
            facecolor=COL_TXT_NAVY2, edgecolor="none", alpha=0.40,
            transform=ax.transAxes, zorder=2))
        ax.add_patch(mpatches.Rectangle(
            (_doy_to_x(p50m) - 0.003, by - 0.006), 0.006, bh + 0.012,
            facecolor=COL_TXT_DARK, edgecolor="white", linewidth=0.6,
            transform=ax.transAxes, zorder=3))
        for xp, val in [(0.35, p10m), (0.46, p25m), (0.57, p50m),
                         (0.68, p75m), (0.79, p90m)]:
            ax.text(xp, row_mid, f"{val:.0f}", transform=ax.transAxes,
                    fontsize=FS_MM_TBL_SMALL, va="center", ha="center",
                    color=COL_TXT_NAVY, fontweight="bold",
                    fontfamily=_ff(FONT_BODY))
        ax.text(0.91, row_mid, f"{p90m-p10m:.0f}d", transform=ax.transAxes,
                fontsize=FS_MM_TBL_SMALL, va="center", ha="center",
                color=COL_TXT_NAVY, fontweight="bold",
                fontfamily=_ff(FONT_BODY))

    # DOY axis at the bottom (inside axes coords)
    ax.text(cx, max(y - row_h * 0.6, 0.02), "▲", transform=ax.transAxes,
            ha="center", fontsize=8, color=COL_CHIRPS, va="bottom")
    ax.text(cx, max(y - row_h * 0.6 - 0.04, 0.01),
            f"CAL\n{c_on:.0f}", transform=ax.transAxes,
            ha="center", fontsize=6.5, color=COL_CHIRPS, va="top")
    ax.text(0.02, 0.01, "Light shading = P10–P90   |   Dark shading = P25–P75"
            "   |   Vertical bar = P50   |   ▲ = CHIRPS CAL mean",
            transform=ax.transAxes, fontsize=6.5, va="bottom",
            color=COL_TXT_MUTED, style="italic", fontfamily=_ff(FONT_BODY))


# =============================================================================
# NEW PANEL 3 — TAYLOR DIAGRAM
# Normalised std dev / correlation / RMSE per model vs CHIRPS CAL onset
# =============================================================================
def _draw_taylor_diagram(ax, pixel_stats):
    """
    Taylor diagram comparing each model's ensemble mean onset DOY
    against CHIRPS observed onset over the calibration period.
    Radial axis = normalised std dev (model / CHIRPS).
    Azimuthal axis = arccos(correlation).
    Contours = normalised RMSE.
    """
    _box(ax, fc=COL_PANEL_BG, ec=COL_BORDER)

    model_keys = list(pixel_stats.keys())

    # CHIRPS CAL onset at all land pixels — used for domain-mean Taylor stats
    chirps_cal = chirps_onset_doy[cal_idx]   # (n_cal, n_lat, n_lon)
    chirps_land = chirps_cal[:, lm]           # (n_cal, n_land)
    # Domain-mean per year
    obs_ts = np.nanmean(chirps_land, axis=1)  # (n_cal,)
    obs_std = float(np.nanstd(obs_ts, ddof=1))
    if obs_std < 0.01:
        obs_std = 1.0   # guard against degenerate case

    # Max radial extent
    r_max = 1.8

    # Draw reference arcs and RMSE contours
    theta_arr = np.linspace(0, np.pi / 2, 200)

    # Correlation arc at r=1 (obs reference point)
    ax.plot(np.cos(theta_arr), np.sin(theta_arr),
            color=COL_CHIRPS, lw=1.8, ls="-", alpha=0.70)

    # Radial grid lines
    for r in [0.5, 1.0, 1.5, r_max]:
        ax.plot(r * np.cos(theta_arr), r * np.sin(theta_arr),
                color=COL_BORDER, lw=0.6, ls="-", alpha=0.50)
        ax.text(r * np.cos(np.deg2rad(75)), r * np.sin(np.deg2rad(75)),
                f"{r:.1f}", ha="center", va="center",
                fontsize=7.0, color=COL_TXT_MUTED)

    # Correlation lines (azimuthal)
    for corr in [0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99]:
        th = np.arccos(corr)
        ax.plot([0, r_max * np.cos(th)], [0, r_max * np.sin(th)],
                color=COL_BORDER, lw=0.5, ls="--", alpha=0.45)
        rx = (r_max + 0.08) * np.cos(th)
        ry = (r_max + 0.08) * np.sin(th)
        if 0 <= rx <= r_max + 0.15 and ry >= 0:
            ax.text(rx, ry, f"{corr:.2f}", ha="center", va="center",
                    fontsize=6.5, color=COL_TXT_MUTED, rotation=0)

    # RMSE contours centred on obs point (1, 0)
    for rmse_n in [0.5, 1.0, 1.5]:
        th2 = np.linspace(0, np.pi, 300)
        xc = 1 + rmse_n * np.cos(th2)
        yc = rmse_n * np.sin(th2)
        mask = (xc >= 0) & (yc >= 0) & (np.sqrt(xc**2 + yc**2) <= r_max)
        if mask.sum() > 2:
            ax.plot(xc[mask], yc[mask],
                    color=COL_RISK_MED, lw=0.7, ls=":", alpha=0.55)
            # Label at the arc midpoint
            mid = mask.nonzero()[0][len(mask.nonzero()[0]) // 2]
            ax.text(xc[mid], yc[mid], f"RMSE={rmse_n:.1f}",
                    ha="center", va="center",
                    fontsize=6.0, color=COL_RISK_MED,
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=0.5))

    # Reference point (CHIRPS = perfect score)
    ax.plot(1.0, 0.0, "*", color=COL_CHIRPS, markersize=14,
            markeredgecolor="white", markeredgewidth=0.8, zorder=8)
    ax.text(1.02, -0.08, "CHIRPS\nREF", ha="center", va="top",
            fontsize=7.0, color=COL_CHIRPS, fontweight="bold")

    # Per-model points
    for k, mkey in enumerate(model_keys):
        col = MODELS[mkey].get("color", MM_MODEL_COLORS[k % len(MM_MODEL_COLORS)])
        md = MODELS[mkey]
        oi = md["op_idx"]
        n_yrs_cal = len(cal_idx)

        # Get model ensemble mean onset per CAL year for all land pixels
        model_cal_yrs = md["model_years"]
        # Find which model year indices correspond to CAL_YEARS
        cal_model_idx = np.where(np.isin(model_cal_yrs, CAL_YEARS))[0]
        if len(cal_model_idx) < 5:
            ax.plot(0.3, 0.1 + k * 0.05, "x", color=col, ms=8)
            ax.text(0.35, 0.1 + k * 0.05,
                    f"{mkey} (insuf. cal years)",
                    fontsize=6.5, va="center", color=col)
            continue

        ens_mean_land = np.nanmean(
            md["onset_doy"][:, cal_model_idx, :, :][:, :, lm], axis=0
        )  # (n_cal_model, n_land)
        mod_ts = np.nanmean(ens_mean_land, axis=1)  # domain-mean per year

        # Align to common length (use shorter)
        n_common = min(len(obs_ts), len(mod_ts))
        o = obs_ts[:n_common]; m = mod_ts[:n_common]
        valid = ~(np.isnan(o) | np.isnan(m))
        if valid.sum() < 4:
            continue

        corr = float(np.corrcoef(o[valid], m[valid])[0, 1])
        std_n = float(np.nanstd(m[valid], ddof=1)) / obs_std  # normalised
        corr = max(-1.0, min(1.0, corr))
        theta = np.arccos(corr)
        rx = std_n * np.cos(theta)
        ry = std_n * np.sin(theta)

        ax.plot(rx, ry, "o", color=col, markersize=10,
                markeredgecolor="white", markeredgewidth=0.8, zorder=7)
        # Short label beside marker
        short = mkey.split()[0][:5]
        ax.text(rx + 0.04, ry + 0.04, short,
                fontsize=6.5, color=col, va="bottom", fontweight="bold")

    # Axes labels
    ax.set_xlim(-0.05, r_max + 0.20)
    ax.set_ylim(-0.15, r_max + 0.15)
    ax.set_aspect("equal")
    ax.set_xlabel("Normalised Std Dev  (σ_model / σ_CHIRPS)",
                  fontsize=FS_MM_PLUME_AXIS, color=COL_TXT_MID)
    ax.set_ylabel("Normalised Std Dev",
                  fontsize=FS_MM_PLUME_AXIS, color=COL_TXT_MID)
    ax.set_title("Taylor Diagram  |  Onset DOY  |  CAL Period"
                 "  |  ★ = CHIRPS reference  |  Arcs = correlation",
                 fontsize=FS_MM_PLUME_TTL, fontweight="bold",
                 color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))
    ax.tick_params(labelsize=FS_MM_PLUME_TICK, colors=COL_TXT_MID)
    ax.grid(False)

    # Remove negative y ticks
    ax.set_yticks([t for t in ax.get_yticks() if t >= 0])


# =============================================================================
# NEW PANEL 4 — INTER-MODEL SPREAD MAP
# Kenya map showing std dev of model-median onset DOY across models
# =============================================================================
def _draw_spread_map(ax_or_fig_ax, pixel_stats, pi, pj, glat, glon):
    """
    Kenya map coloured by inter-model spread (std dev of model-median onset DOY).
    Site pixel marked with star. Colourbar shows spread in days.
    """
    # Compute inter-model spread at every land pixel
    model_keys = list(pixel_stats.keys())
    spread_map = np.full((n_lat, n_lon), np.nan, dtype=np.float32)

    for ii in range(n_lat):
        for jj in range(n_lon):
            if not lm[ii, jj]:
                continue
            medians = []
            for mkey in model_keys:
                md = MODELS[mkey]
                oi = md["op_idx"]
                on_px = md["onset_doy"][:, oi, ii, jj]
                on_v  = on_px[~np.isnan(on_px)]
                if len(on_v) > 0:
                    medians.append(float(np.nanmedian(on_v)))
            if len(medians) >= 2:
                spread_map[ii, jj] = float(np.std(medians, ddof=1))

    ax = ax_or_fig_ax
    if HAS_CARTOPY:
        import cartopy.crs as _ccrs
        import cartopy.feature as _cfeat
        ax.set_extent([33.2, 42.5, -5.0, 5.0], crs=_ccrs.PlateCarree())
        ax.add_feature(_cfeat.LAND,     facecolor="#EDE8D8", zorder=0)
        ax.add_feature(_cfeat.OCEAN,    facecolor="#C8DCF0", zorder=0)
        ax.add_feature(_cfeat.BORDERS,  linewidth=0.5, edgecolor="#5A6E80", zorder=2)
        ax.add_feature(_cfeat.COASTLINE,linewidth=0.7, edgecolor="#3A5A7A", zorder=2)

        # Plot spread as coloured dots per pixel
        cmap = mpl.colormaps.get_cmap("YlOrRd")
        vmin, vmax = 0, max(float(np.nanmax(spread_map)), 1)
        norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        for ii in range(n_lat):
            for jj in range(n_lon):
                if not lm[ii, jj] or np.isnan(spread_map[ii, jj]): continue
                clat = float(target_lat[ii]); clon = float(target_lon[jj])
                ax.plot(clon, clat, "s",
                        color=cmap(norm(spread_map[ii, jj])),
                        markersize=7, transform=_ccrs.PlateCarree(),
                        markeredgecolor="none", alpha=0.88, zorder=3)

        # Site marker
        ax.plot(glon, glat, "*", color=COL_MAP_SITE, markersize=14,
                markeredgecolor="white", markeredgewidth=0.8,
                transform=_ccrs.PlateCarree(), zorder=6)

        gl = ax.gridlines(draw_labels=True, linewidth=0.3,
                          color="grey", alpha=0.40)
        gl.top_labels = False; gl.right_labels = False
        gl.xlabel_style = {"size": 5.5, "color": COL_TXT_MUTED}
        gl.ylabel_style = {"size": 5.5, "color": COL_TXT_MUTED}

        # Colourbar
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cax = ax.inset_axes([0.02, -0.14, 0.96, 0.06])
        cb  = plt.colorbar(sm, cax=cax, orientation="horizontal")
        cb.set_label("Inter-model spread (std dev, days)",
                     fontsize=7.0, color=COL_TXT_MID)
        cb.ax.tick_params(labelsize=6.5)
    else:
        ax.axis("off")
        mean_spread = float(np.nanmean(spread_map[lm]))
        ax.text(0.50, 0.60,
                f"Mean inter-model spread\n{mean_spread:.1f} days",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=10, color=COL_TXT_NAVY)
        ax.text(0.50, 0.35, "(install cartopy for spatial map)",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=8, color=COL_TXT_MUTED, style="italic")

    ax.set_title("Inter-Model Spread  |  Std Dev of model-median onset DOY"
                 "  |  ★ = site",
                 fontsize=FS_MM_MAP_TITLE, fontweight="bold",
                 color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR), pad=3)


# =============================================================================
# NEW PANEL 5 — ANALOGUE YEARS
# Top 3 CHIRPS years whose observed onset is closest to the MMM P50 forecast
# =============================================================================
def _draw_analogue_years(ax, pixel_stats):
    """
    Analogue years panel: find the 3 CHIRPS historical years whose observed
    onset DOY is closest to the multi-model consensus P50, then display
    each analogue year's actual onset, cessation, LGP, and season outcome.
    """
    ax.axis("off")
    _box(ax, fc=COL_PANEL_BG2, ec=COL_TXT_NAVY2)

    ax.text(0.50, 0.985,
            "Analogue Years  |  Top 3 CHIRPS historical years closest to"
            " MMM P50 onset  |  Based on pixel-level observations",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=FS_MM_PLUME_TTL, fontweight="bold",
            color=COL_TXT_NAVY, fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.920, COL_TXT_NAVY2, lw=1.0, x0=0.01, x1=0.99)

    model_keys = list(pixel_stats.keys())

    # Compute MMM P50 onset at this pixel
    all_on = []
    for mkey, ps in pixel_stats.items():
        all_on.extend(ps["on_v"].tolist())
    if len(all_on) < 2:
        ax.text(0.50, 0.50, "Insufficient ensemble data for analogue search",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=9, color=COL_TXT_MUTED, style="italic")
        return

    mmm_p50 = float(np.nanmedian(all_on))

    # Get CHIRPS onset/cessation/LGP at this pixel
    # Use the pixel index stored in pixel_stats (we pass via hidden _pi/_pj keys)
    # Fall back to domain mean if pixel not available
    _pi = pixel_stats[model_keys[0]].get("_pi", None)
    _pj = pixel_stats[model_keys[0]].get("_pj", None)

    if _pi is not None:
        obs_on  = chirps_onset_doy[cal_idx, _pi, _pj]
        obs_cs  = chirps_cessation_doy[cal_idx, _pi, _pj]
        obs_lgp = chirps_lgp_days[cal_idx, _pi, _pj]
    else:
        obs_on  = np.nanmean(chirps_onset_doy[cal_idx], axis=(1,2))
        obs_cs  = np.nanmean(chirps_cessation_doy[cal_idx], axis=(1,2))
        obs_lgp = np.nanmean(chirps_lgp_days[cal_idx], axis=(1,2))

    obs_years = chirps_years[cal_idx]

    # Find top 3 closest years (by abs difference in onset DOY)
    valid_mask = ~np.isnan(obs_on)
    diffs = np.where(valid_mask, np.abs(obs_on - mmm_p50), np.inf)
    top3_idx = np.argsort(diffs)[:3]

    # CHIRPS CAL climatology for anomaly reference
    c_on_mean  = float(np.nanmean(obs_on[valid_mask]))
    c_cs_mean  = float(np.nanmean(obs_cs[valid_mask]))
    c_lgp_mean = float(np.nanmean(obs_lgp[valid_mask]))

    # Column headers
    cols = [
        (0.04, "Year"),
        (0.18, "Onset\n(DOY / date)"),
        (0.34, "Cessation\n(DOY / date)"),
        (0.50, "LGP\n(days)"),
        (0.63, "Onset\nanom"),
        (0.73, "LGP\nanom"),
        (0.83, "Season\nOutcome"),
    ]
    for x, hdr in cols:
        ax.text(x, 0.875, hdr, transform=ax.transAxes,
                fontsize=FS_MM_TBL_HDR, fontweight="bold",
                color=COL_TXT_NAVY2, va="top", fontfamily=_ff(FONT_HDR))
    _hline(ax, 0.820, COL_BORDER, lw=0.6, x0=0.01, x1=0.99)

    # Forecast row (MMM P50) for reference
    mmm_cs_vals = [ps["cs_v"] for ps in pixel_stats.values() if len(ps["cs_v"]) > 0]
    mmm_lgp_vals = [ps["lg_v"] for ps in pixel_stats.values() if len(ps["lg_v"]) > 0]
    mmm_p50_cs  = float(np.nanmedian(np.concatenate(mmm_cs_vals))) if mmm_cs_vals else np.nan
    mmm_p50_lgp = float(np.nanmedian(np.concatenate(mmm_lgp_vals))) if mmm_lgp_vals else np.nan

    row_h = 0.78 / 4   # 4 rows: 1 forecast + 3 analogues

    def _outcome(on_anom, lgp_val, lgp_mean):
        """Classify season outcome."""
        if np.isnan(lgp_val): return "No data", COL_TXT_MUTED
        if lgp_val < 35:     return "Failure",  COL_RISK_CRIT
        if lgp_val < 45:     return "Very poor", COL_RISK_HI
        if lgp_val < 60:     return "Poor",      COL_RISK_MED
        if on_anom > 7:      return "Late/OK",   COL_NN
        if on_anom < -7:     return "Early/OK",  COL_EARLY
        return                      "Normal",    COL_NORMAL

    y = 0.800

    # Forecast reference row
    row_mid = y - row_h / 2
    on_anom_fc = mmm_p50 - c_on_mean
    tlbl, tcol = _tlbl(on_anom_fc)
    outcome_lbl, outcome_col = _outcome(on_anom_fc, mmm_p50_lgp, c_lgp_mean)
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.01, y - row_h + 0.002), 0.98, row_h - 0.004,
        boxstyle="square,pad=0", facecolor="#EEF2FF",
        edgecolor=COL_TXT_NAVY2, linewidth=0.6, alpha=0.60,
        transform=ax.transAxes, zorder=0))

    for x, txt, col, bold in [
        (0.04, f"2026\n(Forecast)", COL_TXT_NAVY, True),
        (0.18, f"DOY {mmm_p50:.0f}\n({_doy_to_date_str(mmm_p50)})",
         COL_TXT_NAVY, True),
        (0.34, f"DOY {mmm_p50_cs:.0f}\n({_doy_to_date_str(mmm_p50_cs)})"
         if not np.isnan(mmm_p50_cs) else "---", COL_TXT_NAVY, False),
        (0.50, f"{mmm_p50_lgp:.0f}d" if not np.isnan(mmm_p50_lgp) else "---",
         COL_TXT_NAVY, True),
        (0.63, f"{on_anom_fc:+.1f}d", tcol, True),
        (0.73, f"{mmm_p50_lgp - c_lgp_mean:+.1f}d"
         if not np.isnan(mmm_p50_lgp) else "---", COL_TXT_NAVY, False),
        (0.83, "MMM P50", COL_TXT_NAVY2, True),
    ]:
        ax.text(x, row_mid, txt, transform=ax.transAxes,
                fontsize=FS_MM_TBL_VAL, va="center", color=col,
                fontweight="bold" if bold else "normal",
                fontfamily=_ff(FONT_BODY))
    y -= row_h
    _hline(ax, y + 0.003, COL_TXT_NAVY2, lw=0.8, x0=0.01, x1=0.99)

    # 3 analogue rows
    rank_colors = ["#C9920A", "#8B8B8B", "#A0522D"]   # gold, silver, bronze
    for rank, idx in enumerate(top3_idx):
        yr  = int(obs_years[idx])
        on  = float(obs_on[idx])
        cs  = float(obs_cs[idx])
        lgp = float(obs_lgp[idx])
        on_anom = on - c_on_mean
        lgp_anom = lgp - c_lgp_mean
        diff    = on - mmm_p50
        tlbl2, tcol2 = _tlbl(on_anom)
        outcome_lbl2, outcome_col2 = _outcome(on_anom, lgp, c_lgp_mean)
        bg = COL_PANEL_BG if rank % 2 == 0 else COL_PANEL_BG2
        row_mid = y - row_h / 2

        ax.add_patch(mpatches.FancyBboxPatch(
            (0.01, y - row_h + 0.002), 0.98, row_h - 0.004,
            boxstyle="square,pad=0", facecolor=bg,
            edgecolor="none", alpha=0.55, transform=ax.transAxes, zorder=0))

        # Rank badge
        ax.add_patch(mpatches.Circle(
            (0.025, row_mid), 0.018,
            color=rank_colors[rank], transform=ax.transAxes, zorder=3))
        ax.text(0.025, row_mid, str(rank+1), ha="center", va="center",
                transform=ax.transAxes, fontsize=7.0, fontweight="bold",
                color="white", fontfamily=_ff(FONT_HDR))

        for x, txt, col, bold in [
            (0.04, f"{yr}\n(Δ={diff:+.1f}d)", rank_colors[rank], True),
            (0.18, f"DOY {on:.0f}\n({_doy_to_date_str(on, year=yr)})",
             COL_TXT_NAVY, False),
            (0.34, f"DOY {cs:.0f}\n({_doy_to_date_str(cs, year=yr)})"
             if not np.isnan(cs) else "---", COL_TXT_NAVY, False),
            (0.50, f"{lgp:.0f}d" if not np.isnan(lgp) else "---",
             COL_TXT_NAVY, True),
            (0.63, f"{on_anom:+.1f}d", tcol2, True),
            (0.73, f"{lgp_anom:+.1f}d",
             COL_NORMAL if lgp_anom >= 0 else COL_RISK_HI, True),
            (0.83, outcome_lbl2, outcome_col2, True),
        ]:
            ax.text(x, row_mid, txt, transform=ax.transAxes,
                    fontsize=FS_MM_TBL_VAL, va="center", color=col,
                    fontweight="bold" if bold else "normal",
                    fontfamily=_ff(FONT_BODY))
        y -= row_h
        _hline(ax, y + 0.002, COL_BORDER, lw=0.25, x0=0.01, x1=0.99)

    # Footer note
    ax.text(0.02, 0.01,
            f"MMM P50 onset = DOY {mmm_p50:.0f}  ({_doy_to_date_str(mmm_p50)})"
            f"   |   CHIRPS CAL mean onset = DOY {c_on_mean:.0f}"
            f"   |   Ranked by |observed onset − MMM P50|",
            transform=ax.transAxes, fontsize=6.5, va="bottom",
            color=COL_TXT_MUTED, style="italic", fontfamily=_ff(FONT_BODY))


# =============================================================================
# MAIN GENERATOR
# =============================================================================
def generate_mm_bulletin(site_name, lat_q, lon_q):
    """
    Generate a multi-model bulletin PNG for one site.

    Parameters
    ----------
    site_name : str   display name for the site
    lat_q     : float site latitude  (degrees N)
    lon_q     : float site longitude (degrees E)

    Returns
    -------
    png_path : str   path to saved PNG
    """
    # Nearest land pixel
    li   = np.argwhere(lm)
    la   = target_lat[li[:, 0]]
    lo   = target_lon[li[:, 1]]
    b    = int(np.argmin((la - lat_q)**2 + (lo - lon_q)**2))
    pi, pj = int(li[b, 0]), int(li[b, 1])
    glat = float(target_lat[pi])
    glon = float(target_lon[pj])
    dkm  = float(np.sqrt(((glat - lat_q) * 111)**2 +
                         ((glon - lon_q) * 111 *
                          np.cos(np.radians(glat)))**2))
    print(f"  {site_name:<42}: ({pi},{pj}) "
          f"[{glat:.2f},{glon:.2f}] delta={dkm:.1f}km")

    # Extract stats
    pixel_stats = {m: _model_pixel(m, pi, pj) for m in MODELS}
    # Store pixel coords in each entry so analogue/exceedance panels can access
    for _ps in pixel_stats.values():
        _ps["_pi"] = pi; _ps["_pj"] = pj

    # Layout constants
    HDR_H  = 0.062;  SUB_H = 0.018;  FTR_H = 0.040
    HDR_BOT = 1.0 - HDR_H
    SUB_BOT = HDR_BOT - SUB_H
    PAR_BOT = SUB_BOT          # third header band removed
    GS_TOP  = SUB_BOT - 0.006  # tight gap below sub-header
    GS_BOT  = FTR_H + 0.005

    n_models = len(MODELS)
    fig_h    = max(42, 34 + n_models * 1.1)   # tighter scaling
    fig = plt.figure(figsize=(22, fig_h))
    fig.patch.set_facecolor(COL_BODY_BG)

    gs = gridspec.GridSpec(
        9, 4, figure=fig,
        hspace=0.25, wspace=0.28,
        top=GS_TOP, bottom=GS_BOT, left=0.05, right=0.970,
        height_ratios=[
            0.16,                              # 0  section divider
            2.20,                              # 1  map + plume
            0.16,                              # 2  section divider (timing)
            max(0.90, 0.13 * n_models + 0.55), # 3  timing table
            0.16,                              # 4  section divider (taylor)
            2.20,                              # 5  taylor diagram
            0.16,                              # 6  section divider (risk)
            1.50,                              # 7  risk ranges
            0.10,                              # 8  bottom spacer
        ])

    # Header
    _draw_mm_header(fig, site_name, glat, glon, dkm,
                    HDR_BOT, HDR_H, SUB_BOT, SUB_H)

    # Section dividers
    _sec(fig.add_subplot(gs[0, :]),
         "SITE LOCATION   |   MULTI-MODEL A(D) ACCUMULATED ANOMALY"
         "  —  Ensemble Median per model  |  ◆ = Onset")
    _sec(fig.add_subplot(gs[2, :]),
         "ENSEMBLE TIMING SUMMARY  —  Median  |  P10–P90 spread"
         "   |   Anomaly vs CHIRPS CAL  |  Early / Normal / Late")
    _sec(fig.add_subplot(gs[4, :]),
         "MODEL PERFORMANCE  —  Taylor Diagram"
         "  |  Normalised Std Dev  |  Correlation  |  RMSE  vs CHIRPS CAL")
    _sec(fig.add_subplot(gs[6, :]),
         "RISK ASSESSMENT   |   MULTI-MODEL RANGE"
         "  —  Min / Median / Max  |  Vertical bar = median  |  Shaded = range")


    # Row 1: Map | A(D) plume | Timing table
    if HAS_CARTOPY:
        ax_map = fig.add_subplot(gs[1, 0],
                                 projection=ccrs.PlateCarree())
        ax_map.set_extent([33.2, 42.5, -5.0, 5.0],
                          crs=ccrs.PlateCarree())
        ax_map.add_feature(cfeature.LAND,
                           facecolor="#EDE8D8", zorder=0)
        ax_map.add_feature(cfeature.OCEAN,
                           facecolor="#C8DCF0", zorder=0)
        ax_map.add_feature(cfeature.BORDERS,
                           linewidth=0.5, edgecolor="#5A6E80", zorder=2)
        ax_map.add_feature(cfeature.COASTLINE,
                           linewidth=0.7, edgecolor="#3A5A7A", zorder=2)
        ax_map.plot(glon, glat, "*", color=COL_MAP_SITE, markersize=16,
                    markeredgecolor="#FFFFFF", markeredgewidth=1.0,
                    transform=ccrs.PlateCarree(), zorder=6)

        # ── Coordinate annotation box below the star ──────────────────────
        import matplotlib.patheffects as _mpe
        _coord_txt = (f"{abs(lat_q):.4f}{'°N' if lat_q>=0 else '°S'}  "
                      f"{abs(lon_q):.4f}{'°E' if lon_q>=0 else '°W'}")
        _grid_txt  = (f"Grid: {glat:.3f}°{'N' if glat>=0 else 'S'}  "
                      f"{glon:.3f}°{'E' if glon>=0 else 'W'}  "
                      f"(Δ {dkm:.1f} km)")
        # White box background + coord text near the star
        ax_map.annotate(
            _coord_txt,
            xy=(glon, glat), xycoords=ccrs.PlateCarree()._as_mpl_transform(ax_map),
            xytext=(4, -18), textcoords="offset points",
            fontsize=6.5, fontweight="bold", color=COL_MAP_SITE,
            ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.25", fc="white",
                      ec=COL_MAP_SITE, alpha=0.90, lw=0.8),
            path_effects=[_mpe.withStroke(linewidth=1.5, foreground="white")],
            zorder=8)
        # Grid pixel text below
        ax_map.annotate(
            _grid_txt,
            xy=(glon, glat), xycoords=ccrs.PlateCarree()._as_mpl_transform(ax_map),
            xytext=(4, -34), textcoords="offset points",
            fontsize=5.5, color=COL_TXT_MUTED,
            ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.20", fc="white",
                      ec=COL_BORDER, alpha=0.85, lw=0.5),
            zorder=8)

        gl = ax_map.gridlines(draw_labels=True, linewidth=0.3,
                              color="grey", alpha=0.40)
        gl.top_labels   = False
        gl.right_labels = False
        gl.xlabel_style = {"size": 5.5, "color": COL_TXT_MUTED}
        gl.ylabel_style = {"size": 5.5, "color": COL_TXT_MUTED}
        ax_map.set_title(
            f"Site Location   {abs(lat_q):.4f}°{'N' if lat_q>=0 else 'S'}"
            f"  {abs(lon_q):.4f}°{'E' if lon_q>=0 else 'W'}",
            fontsize=FS_MM_MAP_TITLE, fontweight="bold",
            fontfamily=_ff(FONT_HDR), color=COL_TXT_NAVY, pad=3)
    else:
        ax_map = fig.add_subplot(gs[1, 0])
        ax_map.axis("off")
        ax_map.set_facecolor(COL_PANEL_BG2)
        ax_map.text(0.50, 0.58,
                    f"{abs(lat_q):.4f}°{'N' if lat_q>=0 else 'S'}"
                    f"  {abs(lon_q):.4f}°{'E' if lon_q>=0 else 'W'}",
                    ha="center", va="center",
                    transform=ax_map.transAxes,
                    fontsize=10, fontweight="bold", color=COL_MAP_SITE)
        ax_map.text(0.50, 0.38,
                    f"Grid: {glat:.3f}° {glon:.3f}°\n\u0394 {dkm:.1f} km",
                    ha="center", va="center",
                    transform=ax_map.transAxes,
                    fontsize=8, color=COL_TXT_MUTED)

    # Row 1: map (col 0) | plume full width (cols 1:4)
    ax_plume = fig.add_subplot(gs[1, 1:4])
    _draw_ad_plume(ax_plume, pi, pj)

    # Row 3: timing summary table — full width
    ax_tbl = fig.add_subplot(gs[3, :])
    _draw_timing_table(ax_tbl, pixel_stats)

    # Row 5: Taylor diagram — full width
    ax_tay = fig.add_subplot(gs[5, :])
    _draw_taylor_diagram(ax_tay, pixel_stats)

    # Row 7: risk ranges
    ax_risk = fig.add_subplot(gs[7, :])
    _draw_mm_risk(ax_risk, pixel_stats)



    # Footer
    _draw_mm_footer(fig, FTR_H)

    # Save PNG
    safe    = site_name.replace(" ", "_").replace("/", "-").replace(",", "")
    out_png = os.path.join(BULLETIN_DIR,
                           f"bulletin_mm_{safe}_MAM{OP_YEAR}.png")
    fig.savefig(out_png, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"    PNG saved  ->  {out_png}")
    return out_png


# =============================================================================
# BATCH RUN
# =============================================================================
print(f"\nGenerating {len(SITES)} multi-model bulletin(s) ...")
print("=" * 70)
mm_failed = []
for s in SITES:
    try:
        png = generate_mm_bulletin(s["site_name"], s["lat"], s["lon"])
        try:
            # Reuse export_bulletin_to_pdf from single-model bulletin if available
            export_bulletin_to_pdf(png, margin_mm=10)
        except NameError:
            # Inline PDF export if single-model bulletin not exec-ed
            try:
                from reportlab.lib.pagesizes import A3
                from reportlab.lib.units    import mm
                from reportlab.pdfgen       import canvas as rl_canvas
                from PIL                    import Image as PILImage
                PILImage.MAX_IMAGE_PIXELS = None
                page_w, page_h = A3; margin = 10 * mm
                img = PILImage.open(png)
                iw, ih   = img.size
                scale    = min((page_w - 2*margin) / (iw/150*72),
                               (page_h - 2*margin) / (ih/150*72))
                dw, dh   = iw/150*72*scale, ih/150*72*scale
                xo       = margin + ((page_w - 2*margin) - dw) / 2
                yo       = margin + ((page_h - 2*margin) - dh) / 2
                pdf_path = png.replace(".png", ".pdf")
                c = rl_canvas.Canvas(pdf_path, pagesize=(page_w, page_h))
                c.setTitle(f"Multi-Model Bulletin MAM {OP_YEAR}")
                c.drawImage(png, xo, yo, width=dw, height=dh,
                            preserveAspectRatio=True, mask="auto")
                c.save()
                print(f"    PDF saved  ->  {pdf_path}")
            except Exception as _epdf:
                print(f"    PDF skipped: {_epdf}")
        except Exception as _epdf:
            print(f"    PDF skipped: {_epdf}")
    except Exception as _e:
        import traceback
        print(f"  ERROR  {s['site_name']}: {_e}")
        traceback.print_exc()
        mm_failed.append(s["site_name"])

print("=" * 70)
print(f"Done: {len(SITES)-len(mm_failed)}/{len(SITES)} multi-model bulletins")
if mm_failed:
    print(f"Failed: {mm_failed}")
print(f"Output: {BULLETIN_DIR}")
