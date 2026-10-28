#!/usr/bin/env python3
"""
fao_water_balance.py
────────────────────
FAO crop-water-requirement / soil-water-balance onset, cessation and length of growing period (LGP) for the
Kenya Short Rains: the platform's fifth onset method, next to Dunning and Agri rules 1–3.

Five dates, kept apart in every output (they are not interchangeable):

  rainfall onset              first wet day from which rain over the next W days ≥ r × ET0 over them
  agricultural onset          start of sustained crop-available moisture: rain ≥ r × ET0 over W days, PAW/TAW ≥ θon
                              on that day and the next persistence−1 days, and no run of ≥ D days with PAW/TAW < θon
                              in the false-onset look-ahead L (else the candidate is rejected as a false onset)
  rainfall cessation          first day after the search start from which rain < r × ET0 in N consecutive W-day windows
  agricultural cessation      first day of ≥ 7 consecutive days with PAW/TAW < θc, ETa/ETc < s and a W-day rain
                              deficit (P < r × ET0 over the W days ending that day)
  crop-water cessation        first day after the climatological rainfall peak from which rain over 21 days
                              < 0.5 × ETc over them, with PAW/TAW falling below θc within them

  LGP_rain = rainfall cessation − rainfall onset + 1;  LGP_ag = agricultural cessation − agricultural onset + 1;
  LGP_crop = crop-water cessation − agricultural onset + 1.

Conceptual sequence (end of season): rainfall deficit begins → P/ET0 < 0.5 → soil-water reserves decline → crop
water stress increases (Ks < 1) → ETa/ETc declines → PAW approaches critical levels → agricultural cessation.
Onset: effective rainfall begins → storage rises → establishment threshold reached → moisture persists →
agricultural onset.

Physics (FAO-56):
  ET0   Penman-Monteith (Eq. 6) from ERA5-Land Tmax, Tmin, dewpoint, 10 m wind (→ 2 m, Eq. 47), solar radiation
        and pressure; Rn = 0.77 Rs − Rnl (Eqs. 38–39), Rso from elevation (Eq. 37), G = 0 for daily steps
  ETc   = Kc × ET0, Kc by growth stage from the agricultural onset (planting) day; Kc_ini before it
  TAW   = 1000 (θFC − θWP) Zr  (θ from SoilGrids + Saxton & Rawls 2006, averaged over the rooting depth)
  RAW   = p × TAW;  Ks = 1 for Dr ≤ RAW, (TAW − Dr)/(TAW − RAW) above;  ETa = Ks × ETc
  SW_t  = SW_t−1 + P_eff − ETa − runoff − drainage, 0 ≤ SW ≤ TAW;  SW is the plant-available water PAW above θWP
        (rain refills the root zone first; water above TAW drains; Ks from the previous day's depletion)

Two water-balance passes per season: the first with Kc_ini throughout finds the agricultural onset (the false-onset
look-ahead lies inside the crop's initial stage, so Kc_ini is the crop's own Kc there); the second runs the crop Kc
curve from that onset and gives ETc, ETa, Ks and PAW for the cessation tests.

Modes:
  historical   CHIRPS v3 + ERA5-Land + SoilGrids, 1993 – latest, initial storage on 1 Aug from ERA5-Land
               root-zone soil moisture (scaled 2nd–98th percentile) → outputs/fao_wb/historical/
  forecast     a seasonal run (outputs/ecmwf_oct*): observed CHIRPS v3 / ERA5-Land water balance up to the
               run's first forecast day, then every SEAS5 member (EQM to CHIRPS v3) with ERA5-Land ET0 climatology
               → <run>/fao_wb_<agricultural|rainfall|cropwater>/ (same layout as the Agri rules; packed for the API)

All thresholds, windows, crop parameters and sources: config/fao_water_balance.yaml.

Usage:
  python scripts/fao_water_balance.py historical
  python scripts/fao_water_balance.py forecast outputs/ecmwf_oct_obs_latest
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CFG_PATH = BASE_DIR / "config" / "fao_water_balance.yaml"
OUT_HIST = BASE_DIR / "outputs" / "fao_wb" / "historical"
CHIRPS3 = BASE_DIR / "data" / "chirps_v3"
ERA5 = BASE_DIR / "data" / "era5land"
SOIL = BASE_DIR / "data" / "soilgrids" / "soil_hydraulics_kenya_p25.nc"
ET0_DIR = BASE_DIR / "outputs" / "fao_wb" / "et0"
LATE = 500.0                        # sentinel DOY for "none by the search end" in terciles (as onset_rules.py)

FLAGS = {"no_rainfall_onset": 1, "no_agricultural_onset": 2, "false_onset_rejected": 4, "no_rainfall_cessation": 8,
         "no_agricultural_cessation": 16, "no_crop_water_cessation": 32, "insufficient_input_data": 64,
         "incomplete_season": 128, "soil_parameters_unavailable": 256,
         "onset_at_search_start": 512}     # 512: wet already on the first search day (long-rains / August rains carry-over)


# ── Configuration ───────────────────────────────────────────────────────────
def load_config(path=CFG_PATH):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg["crop_params"] = cfg["crops"][cfg["crop"]]
    return cfg


def md_doy(md, after_doy=0):
    """'MM-DD' → day of year in the season year (2025 calendar, no leap day); dates before after_doy roll into the
    next year (DOY > 365)."""
    d = pd.Timestamp(f"2025-{'02-28' if md == '02-29' else md}").dayofyear
    return d + 365 if d < after_doy else d


def season_days(cfg):
    """t0 DOY (water-balance start), n days (to the cessation search end) and the search bounds as day indices."""
    t0 = md_doy(cfg["water_balance"]["start"])
    on_lo = md_doy(cfg["onset"]["search_start"]) - t0
    on_hi = md_doy(cfg["onset"]["search_end"], t0) - t0
    cs_lo = md_doy(cfg["cessation"]["search_start"], t0) - t0
    cs_hi = md_doy(cfg["cessation"]["search_end"], t0) - t0
    return t0, cs_hi + 1, dict(on_lo=on_lo, on_hi=on_hi, cs_lo=cs_lo, cs_hi=cs_hi)


# ── FAO-56 reference evapotranspiration ─────────────────────────────────────
def svp(t):
    """Saturation vapour pressure (kPa) at t (°C), FAO-56 Eq. 11."""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def u2_from_u10(u10):
    """Wind speed at 2 m from 10 m (FAO-56 Eq. 47)."""
    return u10 * 4.87 / np.log(67.8 * 10.0 - 5.42)


def et0_fao56(tmax, tmin, tdew, u2, rs, p_kpa, lat_deg, doy, elev_m):
    """Daily FAO-56 Penman-Monteith reference evapotranspiration (mm/day).
    tmax, tmin, tdew °C; u2 m/s; rs MJ m-2 day-1; p_kpa kPa; lat_deg, elev_m broadcastable; doy day of year."""
    t = (tmax + tmin) / 2.0                                              # Eq. 9 (daily mean for PM)
    es = (svp(tmax) + svp(tmin)) / 2.0                                   # Eq. 12
    ea = svp(tdew)                                                       # Eq. 14
    delta = 4098.0 * svp(t) / (t + 237.3) ** 2                           # Eq. 13
    gamma = 0.665e-3 * p_kpa                                             # Eq. 8
    phi = np.deg2rad(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi / 365 * doy)                       # Eq. 23
    dec = 0.409 * np.sin(2 * np.pi / 365 * doy - 1.39)                   # Eq. 24
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))           # Eq. 25
    ra = 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))  # Eq. 21
    rso = (0.75 + 2e-5 * elev_m) * ra                                    # Eq. 37
    rns = (1 - 0.23) * rs                                                # Eq. 38
    ratio = np.clip(np.where(rso > 0, rs / np.where(rso > 0, rso, 1), 1.0), 0.25, 1.0)
    sigma = 4.903e-9
    rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0))) * (1.35 * ratio - 0.35)  # Eq. 39
    rn = rns - rnl
    g = 0.0                                                              # Eq. 42: daily G ≈ 0
    num = 0.408 * delta * (rn - g) + gamma * 900.0 / (t + 273.0) * u2 * (es - ea)
    return np.maximum(num / (delta + gamma * (1 + 0.34 * u2)), 0.0)


def elevation_from_pressure(p_kpa):
    """Elevation (m) consistent with a mean surface pressure (inverse of FAO-56 Eq. 7)."""
    return (1 - (p_kpa / 101.3) ** (1 / 5.26)) * 293.0 / 0.0065


# ── Soil ────────────────────────────────────────────────────────────────────
def taw_mm(zr, soil_path=SOIL):
    """TAW (lat, lon) = 1000 × depth-weighted mean (θFC − θWP) over 0..Zr × Zr, and the θ means; NaN = no soil data."""
    with xr.open_dataset(soil_path) as ds:
        top, bot = ds["depth_top"].values, ds["depth_bottom"].values
        w = np.clip(np.minimum(bot, zr) - top, 0, None)                  # metres of each layer inside the root zone
        w = w / w.sum()
        fc = np.tensordot(w, ds["theta_fc"].values, axes=1)
        wp = np.tensordot(w, ds["theta_wp"].values, axes=1)
    return 1000.0 * (fc - wp) * zr, fc, wp


# ── Crop coefficient ────────────────────────────────────────────────────────
def kc_curve(days_since_planting, crop):
    """FAO-56 Kc by growth stage (piecewise linear, Fig. 25) for days since planting (array; < 0 → Kc_ini)."""
    k, s = crop["kc"], crop["stage_days"]
    a = s["initial"]; b = a + s["development"]; c = b + s["mid"]; d = c + s["late"]
    x = np.asarray(days_since_planting, dtype=np.float32)
    return np.interp(x, [0, a, b, c, d], [k["initial"], k["initial"], k["mid"], k["mid"], k["end"]]).astype(np.float32)


# ── Water balance ───────────────────────────────────────────────────────────
def water_balance(P, ET0, KC, taw, p_table, sw0, wb_cfg):
    """
    Daily root-zone bucket (FAO-56 ch. 8) for N independent series.
    P, ET0, KC : (N, T) mm/day, mm/day, - (NaN P or ET0 = unknown: the balance stops there and stays NaN)
    taw (N,), p_table (scalar), sw0 (N,) initial plant-available water (mm).
    Returns dict of (N, T): SW (= PAW, end of day), ETc, ETa, Ks, drainage, runoff.
    """
    N, T = P.shape
    out = {k: np.full((N, T), np.nan, np.float32) for k in ("SW", "ETc", "ETa", "Ks", "drainage", "runoff")}
    sw = np.clip(sw0, 0, taw).astype(np.float32)
    alive = np.isfinite(sw) & np.isfinite(taw)
    cap = wb_cfg.get("infiltration_cap_mm_day", np.inf) if wb_cfg.get("runoff") == "infiltration_cap" else np.inf
    for t in range(T):
        p, e0 = P[:, t], ET0[:, t]
        alive &= np.isfinite(p) & np.isfinite(e0)
        etc = KC[:, t] * e0
        pt = p_table + 0.04 * (5.0 - etc) if wb_cfg.get("adjust_p_for_etc", True) else np.full(N, p_table)
        raw = np.clip(pt, 0.1, 0.8) * taw
        dr = taw - sw                                                    # depletion at the end of the previous day
        with np.errstate(invalid="ignore", divide="ignore"):
            ks = np.where(dr <= raw, 1.0, (taw - dr) / np.maximum(taw - raw, 1e-6))
        ks = np.clip(ks, 0.0, 1.0)
        runoff = np.maximum(p - cap, 0.0)
        infil = p - runoff
        eta = np.minimum(ks * etc, sw + infil)                           # cannot take more water than there is
        new = sw + infil - eta
        drain = np.maximum(new - taw, 0.0)
        new = np.clip(new - drain, 0.0, taw)
        for k, v in (("SW", new), ("ETc", etc), ("ETa", eta), ("Ks", ks), ("drainage", drain), ("runoff", runoff)):
            out[k][:, t] = np.where(alive, v, np.nan)
        sw = np.where(alive, new, sw)
    return out


# ── Window helpers (forward windows [t, t+w-1]; NaN when not fully known) ───
def _cs(a):
    return np.concatenate([np.zeros((a.shape[0], 1), np.float64), np.cumsum(a, axis=1, dtype=np.float64)], axis=1)


def fwd_sum(a, w):
    N, T = a.shape
    out = np.full((N, T), np.nan, np.float32)
    if T >= w:
        known = _cs(np.isfinite(a).astype(np.float32))
        s = _cs(np.nan_to_num(a))
        ok = (known[:, w:] - known[:, :T - w + 1]) == w
        out[:, :T - w + 1] = np.where(ok, s[:, w:] - s[:, :T - w + 1], np.nan)
    return out


def trail_sum(a, w):
    f = fwd_sum(a, w)
    out = np.full_like(f, np.nan)
    out[:, w - 1:] = f[:, :f.shape[1] - w + 1]
    return out


def fwd_all(mask, n):
    """True where mask holds on every day t..t+n-1 (False when the window runs past the data)."""
    N, T = mask.shape
    out = np.zeros((N, T), bool)
    if T >= n:
        c = _cs(mask.astype(np.float32))
        out[:, :T - n + 1] = (c[:, n:] - c[:, :T - n + 1]) == n
    return out


def first_true(mask, lo, hi):
    """First column t with lo ≤ t ≤ hi and mask True, per row (NaN = none). lo, hi: (N,) or scalars."""
    N, T = mask.shape
    t = np.arange(T)[None, :]
    m = mask & (t >= np.asarray(lo).reshape(-1, 1)) & (t <= np.asarray(hi).reshape(-1, 1))
    return np.where(m.any(axis=1), np.argmax(m, axis=1), np.nan).astype(np.float32)


# ── One season for N series ─────────────────────────────────────────────────
def season(P, ET0, taw, sw0, cfg, peak_idx=None, keep_daily=False):
    """
    P, ET0 : (N, T) from the water-balance start (cfg water_balance.start), NaN = no data.
    taw, sw0 : (N,); peak_idx : (N,) day index of the climatological rainfall peak (crop-water cessation search).
    Returns dict of (N,) day indices (NaN = none), LGPs, flags, and the daily diagnostics if keep_daily.
    """
    crop, on, cs = cfg["crop_params"], cfg["onset"], cfg["cessation"]
    _, T, b = season_days(cfg)
    N = P.shape[0]
    W, r = on["window_days"], on["rain_to_et0_ratio"]
    L, Dd = on["false_onset_lookahead_days"], on["false_onset_dry_days"]
    p_tab = crop["depletion_fraction_p"]
    kc0 = crop["kc"]["initial"] if cfg["water_balance"].get("kc_before_onset", "initial") == "initial" \
        else float(cfg["water_balance"]["kc_before_onset"])
    known = np.isfinite(P) & np.isfinite(ET0)
    last_known = np.where(known.any(axis=1), T - 1 - np.argmax(known[:, ::-1], axis=1), -1)
    t = np.arange(T)[None, :]

    # 1) rainfall onset / cessation: P and ET0 only
    Pw, Ew = fwd_sum(P, W), fwd_sum(ET0, W)
    wet = P >= on.get("rainfall_first_day_wet_mm", 0.0)
    rain_on = first_true((Pw >= r * Ew) & wet, b["on_lo"], b["on_hi"])
    Wc, rc_ = cs["window_days"], cs["rain_to_et0_ratio"]
    Pwc, Ewc = fwd_sum(P, Wc), fwd_sum(ET0, Wc)
    dry_w = Pwc < rc_ * Ewc                                              # False where unknown
    n_w = cs["rainfall_persistence_windows"]
    cond = dry_w.copy()
    for k in range(1, n_w):
        sh = np.zeros_like(dry_w); sh[:, :T - k * Wc] = dry_w[:, k * Wc:]
        cond &= sh
    lo = np.where(np.isfinite(rain_on), np.maximum(b["cs_lo"], rain_on + W), T)
    rain_cs = first_true(cond, lo, b["cs_hi"])

    # 2) agricultural onset: water balance with Kc_ini (pass A)
    wbA = water_balance(P, ET0, np.full((N, T), kc0, np.float32), taw, p_tab, sw0, cfg["water_balance"])
    with np.errstate(invalid="ignore", divide="ignore"):
        fA = wbA["SW"] / taw[:, None]
    th_on = on["paw_fraction_threshold"]
    cand = (Pw >= r * Ew) & fwd_all(fA >= th_on, on["persistence_days"])
    dry_run = fwd_all(fA < th_on, Dd)                                    # a damaging dry run starts on day s
    c = _cs(dry_run.astype(np.float32))                                  # any run start in (t, t + L − Dd + 1]
    hi_s = np.minimum(np.arange(T) + L - Dd + 1, T - 1)
    bad = (c[:, hi_s + 1] - c[:, np.minimum(np.arange(T) + 1, T)]) > 0
    resolved = (t + L) <= last_known[:, None]                            # look-ahead fully observed / forecast
    accepted = cand & ~bad & resolved
    ag_on = first_true(accepted, b["on_lo"], b["on_hi"])
    rejected = cand & bad & resolved & (t >= b["on_lo"]) & (t <= np.where(np.isfinite(ag_on), ag_on, b["on_hi"])[:, None])
    n_rejected = (rejected & ~np.concatenate([np.zeros((N, 1), bool), rejected[:, :-1]], axis=1)).sum(axis=1)

    # 3) crop water balance from the agricultural onset (pass B)
    dsp = np.where(np.isfinite(ag_on)[:, None], t - np.nan_to_num(ag_on)[:, None], -1)
    KC = np.where(dsp >= 0, kc_curve(dsp, crop), kc0).astype(np.float32)
    wb = water_balance(P, ET0, KC, taw, p_tab, sw0, cfg["water_balance"])
    with np.errstate(invalid="ignore", divide="ignore"):
        f = wb["SW"] / taw[:, None]
        ref = wb["ETc"] if cs.get("et_stress_reference", "etc") == "etc" else ET0
        stress_ratio = np.where(ref > 0, wb["ETa"] / ref, 1.0)
    Pt, Et = trail_sum(P, Wc), trail_sum(ET0, Wc)
    th_c = cs["paw_fraction_threshold"]
    stress = (f < th_c) & (stress_ratio < cs["et_stress_ratio"]) & (Pt < rc_ * Et)
    lo_ag = np.where(np.isfinite(ag_on), np.maximum(b["cs_lo"], ag_on + L), T)
    ag_cs = first_true(fwd_all(stress, cs["stress_persistence_days"]), lo_ag, b["cs_hi"])

    # 4) crop-water-requirement cessation
    cw = cs["crop_water"]
    n21 = cw["persistence_days"]
    P21, C21 = fwd_sum(P, n21), fwd_sum(wb["ETc"], n21)
    below = ~fwd_all(f >= cw["paw_fraction_threshold"], n21) & fwd_all(np.isfinite(f), n21)
    crop_cond = (P21 < cw["rain_to_etc_ratio"] * C21) & below
    start = np.full(N, b["cs_lo"], np.float32) if (cw.get("after") != "climatological_peak" or peak_idx is None) \
        else np.asarray(peak_idx, np.float32)
    lo_cw = np.where(np.isfinite(ag_on), np.maximum(start, ag_on + L), T)
    crop_cs = first_true(crop_cond, lo_cw, b["cs_hi"])

    # 5) LGPs and flags
    lgp_rain = rain_cs - rain_on + 1
    lgp_ag = ag_cs - ag_on + 1
    lgp_crop = crop_cs - ag_on + 1
    flags = np.zeros(N, np.int32)
    for name, cond_ in (("no_rainfall_onset", np.isnan(rain_on)), ("no_agricultural_onset", np.isnan(ag_on)),
                        ("false_onset_rejected", n_rejected > 0), ("no_rainfall_cessation", np.isnan(rain_cs)),
                        ("no_agricultural_cessation", np.isnan(ag_cs)), ("no_crop_water_cessation", np.isnan(crop_cs)),
                        ("insufficient_input_data", (~known[:, :max(last_known.max(), 0) + 1]).mean(axis=1) > 0.05),
                        ("incomplete_season", last_known < T - 1),
                        ("soil_parameters_unavailable", ~np.isfinite(taw)),
                        ("onset_at_search_start", (rain_on == b["on_lo"]) | (ag_on == b["on_lo"]))):
        flags |= np.where(cond_, FLAGS[name], 0).astype(np.int32)
    res = dict(rainfall_onset=rain_on, agricultural_onset=ag_on, rainfall_cessation=rain_cs,
               agricultural_cessation=ag_cs, crop_water_cessation=crop_cs, rainfall_LGP_days=lgp_rain,
               agricultural_LGP_days=lgp_ag, crop_water_LGP_days=lgp_crop, false_onsets_rejected=n_rejected.astype(np.float32),
               flags=flags)
    if keep_daily:
        with np.errstate(invalid="ignore", divide="ignore"):
            res["daily"] = dict(PAW_mm=wb["SW"], PAW_fraction=np.clip(f, 0, 1), ET0_daily=ET0, ETc_daily=wb["ETc"],
                                ETa_daily=wb["ETa"], Ks=wb["Ks"], Kc=KC, drainage_mm=wb["drainage"],
                                rainfall_to_ET0_ratio=Pt / Et, rainfall_to_ETc_ratio=Pt / trail_sum(wb["ETc"], Wc))
    return res


# ── Grid and inputs ─────────────────────────────────────────────────────────
def grid():
    """Platform 0.25° Kenya grid and land mask (cells with CHIRPS data in the seasonal outputs)."""
    g = xr.open_dataarray(BASE_DIR / "outputs" / "ecmwf_oct_obs_latest" / "chirps_Q_bar.nc")
    return g.lat.values, g.lon.values, np.isfinite(g.values)


def season_dates(y, t0, T):
    """T dates from the calendar day of DOY t0 (2025 numbering) in year y: the season always starts on the same
    month-day (1 Aug), also in leap years, and day indices + t0 stay in the no-leap-day DOY convention."""
    md = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=t0 - 1)).strftime("%m-%d")
    return pd.date_range(pd.Timestamp(f"{y}-{md}"), periods=T)


def chirps3_season(y, t0, T, lat, lon):
    """CHIRPS v3 (T, lat, lon) from DOY t0 of year y (into y+1); NaN where not available."""
    dates = season_dates(y, t0, T)
    out = np.full((T, len(lat), len(lon)), np.nan, np.float32)
    for yy in (y, y + 1):
        f = CHIRPS3 / f"chirps_v3_p25_kenya_{yy}.nc"
        if not f.exists():
            continue
        with xr.open_dataset(f) as ds:
            p = ds["precip"].reindex(lat=lat, lon=lon, method="nearest", tolerance=0.01)
            idx = pd.DatetimeIndex(p.time.values)
            pos = dates.get_indexer(idx)
            ok = pos >= 0
            out[pos[ok]] = p.values[ok]
    return out


def _to_p25(a, src_lat, src_lon, lat, lon):
    """Area-mean regrid from ERA5-Land 0.1° to the 0.25° cells: nearest to 0.05° sub-cells, then 5 × 5 mean."""
    sub_lat = (lat[:, None] + (np.arange(5) - 2) * 0.05).ravel()
    sub_lon = (lon[:, None] + (np.arange(5) - 2) * 0.05).ravel()
    da = xr.DataArray(a, dims=("time", "lat", "lon"), coords={"lat": src_lat, "lon": src_lon}).sortby("lat")
    s = da.sel(lat=sub_lat, lon=sub_lon, method="nearest").values
    with np.errstate(invalid="ignore"):
        return np.nanmean(s.reshape(s.shape[0], len(lat), 5, len(lon), 5), axis=(2, 4)).astype(np.float32)


def _open_era5(path):
    ds = xr.open_dataset(path)
    ren = {k: v for k, v in {"valid_time": "time", "latitude": "lat", "longitude": "lon"}.items() if k in ds.dims or k in ds.coords}
    return ds.rename(ren)


def build_et0(y, lat, lon, force=False):
    """Daily FAO-56 ET0 and ERA5-Land root-zone soil moisture (0–100 cm) for calendar year y on the 0.25° grid
    (months available in data/era5land) → ET0_DIR/et0_<y>.nc; None when the inputs are missing."""
    dest = ET0_DIR / f"et0_{y}.nc"
    files = {k: ERA5 / f"{k}_{y}.nc" for k in ("t2m_max", "t2m_min", "met", "swvl")}
    if not all(f.exists() and f.stat().st_size > 0 for f in files.values()):
        return dest if dest.exists() else None                      # e.g. built by fao_era5land_gee.py (Earth Engine)
    if dest.exists() and not force and dest.stat().st_mtime > max(f.stat().st_mtime for f in files.values()):
        return dest
    tx, tn = _open_era5(files["t2m_max"]), _open_era5(files["t2m_min"])
    met, sw = _open_era5(files["met"]), _open_era5(files["swvl"])
    days = pd.DatetimeIndex(tx.time.values).normalize()
    la, lo = tx.lat.values, tx.lon.values
    # 6-hourly wind speed and dewpoint → daily means (UTC day); radiation: the 00 UTC value of day d+1 is day d's total
    mt = pd.DatetimeIndex(met.time.values)
    spd = np.hypot(met["u10"].values, met["v10"].values)
    day_of = mt.normalize()
    u10 = pd.DataFrame(spd.reshape(len(mt), -1)).groupby(day_of).mean()
    d2m = pd.DataFrame(met["d2m"].values.reshape(len(mt), -1)).groupby(day_of).mean()
    at0 = mt.hour == 0
    rs = pd.DataFrame(met["ssrd"].values[at0].reshape(int(at0.sum()), -1), index=mt[at0] - pd.Timedelta(days=1))
    shape = (len(la), len(lo))
    pick = lambda df: np.stack([df.loc[d].values.reshape(shape) if d in df.index else np.full(shape, np.nan) for d in days])
    with xr.open_dataset(ERA5 / "sp_mean_2010.nc") as spd_ds:
        spd_ds = spd_ds.rename({k: v for k, v in {"valid_time": "time", "latitude": "lat", "longitude": "lon"}.items() if k in spd_ds.dims})
        p_kpa = spd_ds["sp"].mean("time").values / 1000.0
    tmax = tx["t2m"].values - 273.15
    tmin = tn["t2m"].values - 273.15
    et0 = et0_fao56(tmax, tmin, pick(d2m) - 273.15, u2_from_u10(pick(u10)), pick(rs) / 1e6, p_kpa[None],
                    la[None, :, None], days.dayofyear.values[:, None, None], elevation_from_pressure(p_kpa)[None])
    st = pd.DatetimeIndex(sw.time.values).normalize()
    rz = (0.07 * sw["swvl1"].values + 0.21 * sw["swvl2"].values + 0.72 * sw["swvl3"].values)      # 0–100 cm
    rz_d = np.stack([rz[st == d][0] if (st == d).any() else np.full(shape, np.nan) for d in days])
    ds = xr.Dataset({"ET0": (("time", "lat", "lon"), _to_p25(et0, la, lo, lat, lon)),
                     "theta_rootzone": (("time", "lat", "lon"), _to_p25(rz_d, la, lo, lat, lon))},
                    coords={"time": days, "lat": lat, "lon": lon})
    ds["ET0"].attrs.update(units="mm/day", long_name="FAO-56 Penman-Monteith reference evapotranspiration (ERA5-Land)")
    ds["theta_rootzone"].attrs.update(units="m3 m-3", long_name="ERA5-Land volumetric soil water 0–100 cm (layers 1–3)")
    ET0_DIR.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(dest, encoding={k: {"zlib": True, "complevel": 4} for k in ds.data_vars})
    print(f"[fao] ET0 {y}: {len(days)} days, domain mean {np.nanmean(ds['ET0'].values):.2f} mm/day → {dest.name}")
    return dest


def era5_season(y, t0, T, lat, lon, var="ET0"):
    """ERA5-Land-derived (T, lat, lon) of var from DOY t0 of y (into y+1); NaN where not available."""
    dates = season_dates(y, t0, T)
    out = np.full((T, len(lat), len(lon)), np.nan, np.float32)
    for yy in (y, y + 1):
        f = build_et0(yy, lat, lon)
        if f is None:
            continue
        with xr.open_dataset(f) as ds:
            pos = dates.get_indexer(pd.DatetimeIndex(ds.time.values))
            ok = pos >= 0
            out[pos[ok]] = ds[var].values[ok]
    return out


def et0_climatology(cfg, lat, lon):
    """ET0 by season day (T, lat, lon): CAL-year mean for each calendar day, ±7-day smoothed; cached."""
    t0, T, _ = season_days(cfg)
    dest = ET0_DIR / "et0_climatology.nc"
    y0, y1 = cfg["sources"]["calibration_years"]
    if dest.exists():
        with xr.open_dataarray(dest) as da:
            if da.attrs.get("years") == f"{y0}-{y1}" and da.sizes["day"] == T:
                return da.values.astype(np.float32)
    stack = np.stack([era5_season(y, t0, T, lat, lon) for y in range(y0, y1 + 1)])
    with np.errstate(invalid="ignore"):
        clim = np.nanmean(stack, axis=0)
    k = 15
    pad = np.concatenate([clim[:1].repeat(7, 0), clim, clim[-1:].repeat(7, 0)])
    sm = np.stack([np.nanmean(pad[i:i + k], axis=0) for i in range(T)]).astype(np.float32)
    xr.DataArray(sm, dims=("day", "lat", "lon"), coords={"day": np.arange(T), "lat": lat, "lon": lon},
                 attrs={"years": f"{y0}-{y1}", "first_doy": t0, "units": "mm/day"}).to_netcdf(dest)
    return sm


def initial_storage(cfg, y, t0, lat, lon, taw):
    """Plant-available water (lat, lon) on the water-balance start day of year y: ERA5-Land 0–100 cm soil moisture
    scaled between its 2nd and 98th percentile (CAL years, season days) × TAW; 0 when not available or configured."""
    if cfg["water_balance"].get("initial_storage") != "era5land_scaled":
        return np.zeros_like(taw)
    _, T, _ = season_days(cfg)
    dest = ET0_DIR / "theta_rootzone_percentiles.nc"
    y0, y1 = cfg["sources"]["calibration_years"]
    if dest.exists():
        with xr.open_dataset(dest) as ds:
            q02, q98 = ds["q02"].values, ds["q98"].values
    else:
        stack = np.stack([era5_season(yy, t0, T, lat, lon, "theta_rootzone") for yy in range(y0, y1 + 1)])
        with np.errstate(invalid="ignore"):
            q02, q98 = np.nanpercentile(stack, 2, axis=(0, 1)), np.nanpercentile(stack, 98, axis=(0, 1))
        xr.Dataset({"q02": (("lat", "lon"), q02), "q98": (("lat", "lon"), q98)}, coords={"lat": lat, "lon": lon}).to_netcdf(dest)
    th = era5_season(y, t0, 1, lat, lon, "theta_rootzone")[0]
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.clip((th - q02) / (q98 - q02), 0, 1)
    return np.where(np.isfinite(frac), frac * taw, 0.0).astype(np.float32)


def climatological_peak(cfg, lat, lon):
    """Day index (lat, lon) of the CHIRPS v3 climatological rainfall peak (CAL years, 31-day mean) in 1 Oct – 31 Dec."""
    t0, T, _ = season_days(cfg)
    y0, y1 = cfg["sources"]["calibration_years"]
    stack = np.stack([chirps3_season(y, t0, T, lat, lon) for y in range(y0, y1 + 1)])
    with np.errstate(invalid="ignore"):
        clim = np.nanmean(stack, axis=0)
    sm = np.stack([np.nanmean(clim[max(0, i - 15):i + 16], axis=0) for i in range(T)])
    a, b = 274 - t0, 365 - t0
    with np.errstate(invalid="ignore"):
        idx = np.where(np.isfinite(sm[a:b + 1]).any(axis=0), np.nanargmax(np.nan_to_num(sm[a:b + 1], nan=-1), axis=0) + a, np.nan)
    return idx.astype(np.float32)


def fill_et0(et0, clim, p):
    """ET0 where ERA5-Land is not yet available but rainfall is (the ~5-day ERA5-Land lag): climatology."""
    return np.where(np.isnan(et0) & np.isfinite(p), clim, et0).astype(np.float32)


# ── Historical mode ─────────────────────────────────────────────────────────
DEFINITIONS = {
    "agricultural": dict(onset="agricultural_onset", cessation="agricultural_cessation", lgp="agricultural_LGP_days",
                         label="FAO water balance: agricultural onset, agricultural cessation, agricultural LGP"),
    "rainfall": dict(onset="rainfall_onset", cessation="rainfall_cessation", lgp="rainfall_LGP_days",
                     label="FAO water balance: rainfall onset, rainfall cessation, rainfall LGP"),
    "cropwater": dict(onset="agricultural_onset", cessation="crop_water_cessation", lgp="crop_water_LGP_days",
                      label="FAO water balance: agricultural onset, crop-water-requirement cessation, crop-water LGP"),
}
DATE_VARS = ("rainfall_onset", "agricultural_onset", "rainfall_cessation", "agricultural_cessation", "crop_water_cessation")
LGP_VARS = ("rainfall_LGP_days", "agricultural_LGP_days", "crop_water_LGP_days")


def run_historical(cfg, years=None, keep_daily=True):
    lat, lon, lm = grid()
    t0, T, b = season_days(cfg)
    crop = cfg["crop_params"]
    taw, fc, wp = taw_mm(crop["rooting_depth_m"])
    taw = np.where(lm, taw, np.nan).astype(np.float32)
    clim = et0_climatology(cfg, lat, lon)
    peak = climatological_peak(cfg, lat, lon)
    years = years or [y for y in range(1993, 2100) if (CHIRPS3 / f"chirps_v3_p25_kenya_{y}.nc").exists()]
    S = int(lm.sum())
    res = {k: np.full((len(years), *lm.shape), np.nan, np.float32) for k in (*DATE_VARS, *LGP_VARS, "false_onsets_rejected")}
    flags = np.zeros((len(years), *lm.shape), np.int32)
    OUT_HIST.mkdir(parents=True, exist_ok=True)
    for i, y in enumerate(years):
        P = chirps3_season(y, t0, T, lat, lon)[:, lm].T
        E = fill_et0(era5_season(y, t0, T, lat, lon)[:, lm].T, clim[:, lm].T, P)
        sw0 = initial_storage(cfg, y, t0, lat, lon, taw)[lm]
        r = season(P, E, taw[lm], sw0, cfg, peak_idx=peak[lm], keep_daily=keep_daily)
        for k in res:
            res[k][i][lm] = r[k] + (t0 if k in DATE_VARS else 0)
        flags[i][lm] = r["flags"]
        if keep_daily:
            dates = season_dates(y, t0, T)
            ds = xr.Dataset({k: (("time", "lat", "lon"), _unflat(v.T, lm)) for k, v in r["daily"].items()},
                            coords={"time": dates, "lat": lat, "lon": lon})
            ds["precip"] = (("time", "lat", "lon"), _unflat(P.T, lm))
            ds.attrs.update(crop=cfg["crop"], note="PAW_mm is root-zone water above θWP (the bucket storage SW)")
            ds.to_netcdf(OUT_HIST / f"daily_{y}.nc", encoding={k: {"zlib": True, "complevel": 4, "dtype": "float32"} for k in ds.data_vars})
        on = np.nanmedian(res["agricultural_onset"][i][lm]); cs_ = np.nanmedian(res["agricultural_cessation"][i][lm])
        print(f"[fao] {y}: median agricultural onset DOY {on:.0f}, cessation {cs_:.0f}; "
              f"no agricultural onset {np.mean(np.isnan(res['agricultural_onset'][i][lm])) * 100:.0f}% of cells")
    ds = xr.Dataset({f"{k}_doy" if k in DATE_VARS else k: (("year", "lat", "lon"), v) for k, v in res.items()},
                    coords={"year": years, "lat": lat, "lon": lon})
    for k in DATE_VARS:
        ds[f"{k}_doy"].attrs.update(units="day of year of the season year (> 365 = next year)", long_name=k.replace("_", " "))
    ds["onset_DOY"] = ds["agricultural_onset_doy"].assign_attrs(note="alias of agricultural_onset_doy")
    ds["cessation_DOY"] = ds["agricultural_cessation_doy"].assign_attrs(note="alias of agricultural_cessation_doy")
    ds["flags"] = (("year", "lat", "lon"), flags)
    ds["flags"].attrs.update(meaning=json.dumps(FLAGS))
    ds["TAW_mm"] = (("lat", "lon"), taw)
    ds["theta_FC"] = (("lat", "lon"), np.where(lm, fc, np.nan).astype(np.float32))
    ds["theta_WP"] = (("lat", "lon"), np.where(lm, wp, np.nan).astype(np.float32))
    ds["climatological_peak_doy"] = (("lat", "lon"), peak + t0)
    ds.attrs.update(crop=cfg["crop"], config=json.dumps({k: cfg[k] for k in ("crop", "onset", "cessation", "water_balance")}),
                    sources="CHIRPS v3 daily; ERA5-Land (FAO-56 ET0); SoilGrids 2.0 + Saxton & Rawls 2006")
    dest = OUT_HIST / "fao_wb_seasons.nc"
    if dest.exists():                                                   # update these years, keep the others
        with xr.open_dataset(dest) as old:
            old = old.load()
        keep = old.sel(year=[y for y in old.year.values if y not in years])
        if keep.sizes["year"]:
            yv = [k for k in ds.data_vars if "year" in ds[k].dims]
            merged = xr.concat([keep[yv], ds[yv]], dim="year").sortby("year")
            ds = merged.assign({k: ds[k] for k in ds.data_vars if k not in yv}).assign_attrs(ds.attrs)
    ds.to_netcdf(dest.with_suffix(".part"))
    dest.with_suffix(".part").replace(dest)
    print(f"[fao] historical → {dest} ({len(years)} seasons, {S} land cells)")
    return dest


def _unflat(a, lm):
    """(T, S) → (T, lat, lon) with NaN off the mask."""
    out = np.full((a.shape[0], *lm.shape), np.nan, np.float32)
    out[:, lm] = a
    return out


# ── Forecast mode ───────────────────────────────────────────────────────────
SEAS5_OCT = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_oct"
BC_CACHE = BASE_DIR / "outputs" / "fao_wb" / "seas5_oct_bc_chirps3.nc"


def seas5_oct_bc(cfg, m_years, lat, lon, lm):
    """(member, year, 151, lat, lon) SEAS5 1 Oct members, 1 Oct – 28 Feb, quantile-mapped to CHIRPS v3 per land cell
    and day (CHIRPS pool: CAL years, day ± qm_window; model pool: same day, CAL years, all members). Cached."""
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import process_ecmwf_september as pes
    files = [SEAS5_OCT / f"ecmwf_{y}10_d01.nc" for y in m_years]
    w = cfg["forecast"]["qm_window_days"]
    n_day, n_mem = 151, pes.N_MEMBERS_COMMON
    if BC_CACHE.exists() and BC_CACHE.stat().st_mtime > max(f.stat().st_mtime for f in files if f.exists()):
        with xr.open_dataarray(BC_CACHE) as da:
            if np.array_equal(da.year.values, m_years) and da.attrs.get("qm_window") == w:
                return da.values.astype(np.float32)
    raw = np.full((n_mem, len(m_years), n_day, len(lat), len(lon)), np.nan, np.float32)
    for yi, f in enumerate(files):
        if not f.exists():
            continue
        with xr.open_dataset(f) as ds:
            tp = ds["tp"].squeeze("forecast_reference_time", drop=True) if "forecast_reference_time" in ds["tp"].dims else ds["tp"]
            v = tp.reindex(latitude=lat, longitude=lon, method="nearest").values[:n_mem, :n_day]
        acc = np.concatenate([np.zeros_like(v[:, :1]), v], axis=1)       # forecast_period k = accumulation to the end of day k
        raw[:v.shape[0], yi, :v.shape[1]] = np.clip(np.diff(acc, axis=1), 0, None) * 1000.0
    t0 = 274 - w                                                        # CHIRPS v3 pool from 1 Oct − w to 28 Feb + w
    cal = list(range(*[cfg["sources"]["calibration_years"][0], cfg["sources"]["calibration_years"][1] + 1]))
    pool = np.stack([chirps3_season(y, t0, n_day + 2 * w, lat, lon) for y in cal])     # (cal, n_day + 2w, lat, lon)
    cal_e = np.isin(m_years, cal)
    bc = raw.copy()
    for pi, pj in np.argwhere(lm):
        for d in range(n_day):
            c_pool = pool[:, d:d + 2 * w + 1, pi, pj].ravel()
            s_pool = raw[:, cal_e, d, pi, pj].ravel()
            c_pool, s_pool = c_pool[np.isfinite(c_pool)], s_pool[np.isfinite(s_pool)]
            if len(c_pool) and len(s_pool):
                bc[:, :, d, pi, pj] = pes._build_qm_transfer(c_pool, s_pool)(raw[:, :, d, pi, pj])
    bc[:, :, :, ~lm] = np.nan
    BC_CACHE.parent.mkdir(parents=True, exist_ok=True)
    xr.DataArray(bc, dims=("member", "year", "day", "lat", "lon"), name="pr",
                 coords={"member": np.arange(1, n_mem + 1), "year": m_years, "day": np.arange(n_day), "lat": lat, "lon": lon},
                 attrs={"units": "mm/day", "first_doy": 274, "qm_window": w,
                        "long_name": "SEAS5 1 Oct members quantile-mapped to CHIRPS v3 (CAL years)"}
                 ).to_netcdf(BC_CACHE, encoding={"pr": {"zlib": True, "complevel": 4}})
    print(f"[fao] SEAS5 1 Oct members bias-corrected to CHIRPS v3 → {BC_CACHE}")
    return bc


def obs_end_doy(run_dir):
    """Last observed day used by a run: 30 Sep for the 1 Oct runs; the latest CHIRPS v3 day for "+ latest obs"."""
    if not Path(run_dir).name.endswith("obs_latest"):
        return 273
    with xr.open_dataset(CHIRPS3 / f"chirps_v3_p25_kenya_{pd.Timestamp.today().year}.nc") as ds:
        last = pd.Timestamp(ds.time.values[-1])
    return md_doy(f"{last:%m-%d}")


def run_forecast(cfg, run_dir):
    run_dir = Path(run_dir)
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import agro_onset as ao
    lat, lon, lm = grid()
    t0, T, b = season_days(cfg)
    crop = cfg["crop_params"]
    taw, _, _ = taw_mm(crop["rooting_depth_m"])
    taw = np.where(lm, taw, np.nan).astype(np.float32)
    hist = xr.open_dataset(OUT_HIST / "fao_wb_seasons.nc")
    with xr.open_dataarray(run_dir / "ECMWF_bc_daily_all_years.nc") as bc_v2:
        m_years = bc_v2.year.values.astype(int)
    mem = seas5_oct_bc(cfg, m_years, lat, lon, lm)                     # (m, year, 151, lat, lon) from DOY 274
    n_mem = mem.shape[0]
    clim = et0_climatology(cfg, lat, lon)
    peak = climatological_peak(cfg, lat, lon)
    oe = obs_end_doy(run_dir)
    k_obs = oe - t0 + 1                                                 # season days observed (from t0)
    print(f"[fao] {run_dir.name}: observed CHIRPS v3 / ERA5-Land to DOY {oe}, then {n_mem} SEAS5 members "
          f"(EQM to CHIRPS v3) with ERA5-Land ET0 climatology, to DOY {t0 + T - 1}")
    S = int(lm.sum())
    res = {k: np.full((n_mem, len(m_years), *lm.shape), np.nan, np.float32) for k in (*DATE_VARS, *LGP_VARS)}
    paw_q = None
    has_year = np.isfinite(mem[:, :, 0]).any(axis=(0, 2, 3))
    for yi, y in enumerate(m_years):
        if not has_year[yi]:
            continue
        P_obs = chirps3_season(y, t0, T, lat, lon)[:, lm].T                # (S, T)
        E_obs = fill_et0(era5_season(y, t0, T, lat, lon)[:, lm].T, clim[:, lm].T, P_obs)
        P = np.empty((n_mem, S, T), np.float32)
        E = np.empty((n_mem, S, T), np.float32)
        P[:] = P_obs[None]; E[:] = clim[:, lm].T[None]
        E[:, :, :k_obs] = E_obs[None, :, :k_obs]
        f0 = 274 - t0                                                   # members start on 1 Oct
        m_part = np.moveaxis(mem[:, yi][:, :, lm], 1, 2)                 # (m, S, 151)
        P[:, :, max(k_obs, f0):] = m_part[:, :, max(k_obs, f0) - f0:]
        sw0 = initial_storage(cfg, y, t0, lat, lon, taw)[lm]
        r = season(P.reshape(-1, T), E.reshape(-1, T), np.tile(taw[lm], n_mem), np.tile(sw0, n_mem), cfg,
                   peak_idx=np.tile(peak[lm], n_mem), keep_daily=(yi == int(np.where(has_year)[0][-1])))
        for k in res:
            res[k][:, yi][:, lm] = (r[k] + (t0 if k in DATE_VARS else 0)).reshape(n_mem, S)
        if "daily" in r:                                                # operational year: PAW/TAW outlook
            f = r["daily"]["PAW_fraction"].reshape(n_mem, S, T)
            th = cfg["cessation"]["paw_fraction_threshold"]
            with np.errstate(invalid="ignore"):
                paw_q = dict(p10=np.nanpercentile(f, 10, axis=0), p50=np.nanpercentile(f, 50, axis=0),
                             p90=np.nanpercentile(f, 90, axis=0), p_below=np.mean(f < th, axis=0))
            op_year = y
    # CHIRPS v3 (observed) seasons for terciles and skill: complete seasons only
    c_years = np.array([y for y in hist.year.values.astype(int) if y < pd.Timestamp.today().year])
    by = lambda doy: (lambda d: f"{d.day} {d:%b}")(pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(doy) - 1))
    for dname, dd in DEFINITIONS.items():
        out = run_dir / f"fao_wb_{dname}"
        out.mkdir(parents=True, exist_ok=True)
        e = {"onset": res[dd["onset"]], "cessation": res[dd["cessation"]], "lgp": res[dd["lgp"]]}
        c = {"onset": hist[f"{dd['onset']}_doy"].sel(year=c_years).values, "cessation": hist[f"{dd['cessation']}_doy"].sel(year=c_years).values,
             "lgp": hist[dd["lgp"]].sel(year=c_years).values}
        c_valid = lm[None]
        e_valid = lm[None, None] & has_year[None, :, None, None]
        c_f = dict(zip(("onset", "cessation", "lgp"), for_terciles(c["onset"], c["cessation"], c["lgp"], c_valid)))
        e_f = dict(zip(("onset", "cessation", "lgp"), for_terciles(e["onset"], e["cessation"], e["lgp"], e_valid)))
        g = {"lat": lat, "lon": lon}
        summ = {}
        for v in ("onset", "cessation", "lgp"):
            t33, t67, p_d, alpha, skill, corr, mae = ao.tercile_probs_skill(c_f[v], e_f[v], c_years, m_years, lm)
            # No tercile forecast where the climatology has no spread (t33 = t67): e.g. onset on the first search day
            # in most years (western Kenya, the coast) — every member would count as "late" with a perfect score
            flat = np.isfinite(t33) & (t33 == t67)
            p_d = np.where(flat[None, None], np.nan, p_d)
            skill = {k: np.where(flat, np.nan, a) for k, a in skill.items()}
            alpha = np.where(flat, np.nan, alpha)
            for name, a in {"t33": t33, "t67": t67, "alpha": alpha, "corr_median": corr, "mae_median": mae, **skill}.items():
                _save(a, ["lat", "lon"], g, out / f"{name}_{v}.nc")
            _save(p_d, ["category", "year", "lat", "lon"], {"year": m_years, **g}, out / f"probs_damped_{v}.nc")
            _save(c[v], ["year", "lat", "lon"], {"year": c_years, **g}, out / f"CHIRPS_{v}.nc")
            _save(e[v], ["member", "year", "lat", "lon"], {"member": np.arange(1, n_mem + 1), "year": m_years, **g},
                  out / f"ECMWF_{v}_all_years.nc")
            summ[v] = float(np.nanmean(skill["rpss_val"][lm]))
        if paw_q is not None and dname == "agricultural":
            xr.Dataset({k: (("lat", "lon", "day"), _unflat(v.T, lm).transpose(1, 2, 0)) for k, v in paw_q.items()},
                       coords={"lat": lat, "lon": lon, "day": np.arange(T)},
                       attrs={"first_doy": t0, "year": int(op_year), "threshold": cfg["cessation"]["paw_fraction_threshold"]}
                       ).to_netcdf(out / "paw_outlook.nc")
        (out / "method.json").write_text(json.dumps({
            "method": "fao", "definition": dname, "label": dd["label"], "variables": {k: dd[k] for k in ("onset", "cessation", "lgp")},
            "crop": cfg["crop"], "crop_label": crop["label"], "kc": crop["kc"], "stage_days": crop["stage_days"],
            "rooting_depth_m": crop["rooting_depth_m"], "depletion_fraction_p": crop["depletion_fraction_p"],
            "onset": cfg["onset"], "cessation": cfg["cessation"], "water_balance": cfg["water_balance"],
            "search_doy": [md_doy(cfg["onset"]["search_start"]), md_doy(cfg["onset"]["search_end"], t0)],
            "data_end_doy": int(t0 + T - 1), "onset_by": by(md_doy(cfg["onset"]["search_end"], t0)),
            "none_by": by(t0 + T - 1), "member_start_doy": int(max(oe + 1, 274)), "obs_end_doy": int(oe),
            "rainfall": "CHIRPS v3", "et0": "FAO-56 Penman-Monteith, ERA5-Land (observed days); ERA5-Land climatology (forecast days)",
            "soil": "SoilGrids 2.0 + Saxton & Rawls (2006)", "late_sentinel_doy": LATE,
            "skill": bool(np.isfinite(summ["onset"]))}, indent=1))
        op = int(np.where(has_year)[0][-1])
        med = lambda a: np.nanmedian(a[:, op][:, lm])
        print(f"[fao] {dname:12s} → {out.name}: {m_years[op]} median onset DOY {med(e['onset']):.0f}, cessation "
              f"{med(e['cessation']):.0f}, LGP {med(e['lgp']):.0f} d; RPSS val onset {summ['onset']:+.2f} "
              f"cessation {summ['cessation']:+.2f} lgp {summ['lgp']:+.2f}")


def for_terciles(on, cs, lg, valid):
    """As onset_rules.for_terciles: none → late; LGP 0 without onset, LATE − onset without cessation."""
    has_on = np.isfinite(on)
    on_f = np.where(valid & ~has_on, LATE, on)
    cs_f = np.where(valid & has_on & np.isnan(cs), LATE, cs)
    lg_f = np.where(valid & ~has_on, 0.0, np.where(valid & has_on & np.isnan(cs), LATE - on, lg))
    return on_f, cs_f, lg_f


def _save(vals, dims, coords, path):
    xr.DataArray(vals, dims=dims, coords=coords).to_netcdf(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    h = sub.add_parser("historical"); h.add_argument("--years", type=int, nargs="*"); h.add_argument("--no-daily", action="store_true")
    f = sub.add_parser("forecast"); f.add_argument("run_dir")
    ap.add_argument("--config", default=str(CFG_PATH))
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config(a.config)
    if a.mode == "historical":
        run_historical(cfg, a.years, keep_daily=not a.no_daily)
    else:
        run_forecast(cfg, a.run_dir)
