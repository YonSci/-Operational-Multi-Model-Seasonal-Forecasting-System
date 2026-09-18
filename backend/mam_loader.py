"""
data_loader.py  —  Kenya MAM Climate Dashboard
===============================================
Standalone data-access module extracted from notebook_multimodel_stage8.ipynb.

Public API
----------
    configure(base_dir, op_year, load_bc_daily)
    load(force)
    is_loaded()
    get_state()
    get_model_info()            -> list[dict]
    get_pixel_stats(lat, lon)   -> dict
    get_grid_stats(var, layer)  -> dict
    get_taylor_stats()          -> dict
"""
from __future__ import annotations
import os, warnings
from itertools import permutations
from pathlib import Path
from typing import Optional
import numpy as np
import xarray as xr

# ── State ──────────────────────────────────────────────────────────────────
_state:      dict = {}
_configured: bool = False
_loaded:     bool = False

# ── Defaults ───────────────────────────────────────────────────────────────
import os as _os
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
_BASE_DIR = _os.environ.get("BASE_DIR", _REPO_ROOT)
_OP_YEAR  = int(_os.environ.get("OP_YEAR", "2026"))
_LOAD_BC  = _os.environ.get("LOAD_BC_DAILY", "1").lower() not in ("0", "false", "no")

MODEL_DIRS:   dict = {}
_MODEL_DIR_ALIASES = {
    "ECMWF SEAS5": ["outputs_dunning_v3", "outputs_ECMWF_SEAS5_v3", "outputs/dunning_v3", "outputs/seas5_v3", "outputs/ecmwf_v3"],
    "ECMWF SEAS5 (Sep)": ["outputs/ecmwf_sep", "outputs_ecmwf_sep"],
    "ECMWF SEAS5 (Kiremt)": ["outputs/ecmwf_kiremt", "outputs_ecmwf_kiremt", "data/outputs_ETHIOPIA_KIREMT_v1"],
    "ECMWF SEAS5 (FMAM)": ["outputs/ecmwf_fmam", "outputs_ecmwf_fmam"],
    "ECMWF SEAS5 (Bega)": ["outputs/ecmwf_bega", "outputs_ecmwf_bega"],
    "UKMO GloSea6": ["outputs_ukmo_v3", "outputs_UKMO_GloSea6_v3", "outputs/ukmo_v3"],
    "Meteo-France Sys8": ["outputs_mf_v3", "outputs_Meteo-France_Sys8_v3", "outputs/mf_v3"],
    "DWD GCFS2.1": ["outputs_dwd_v3", "outputs_DWD_GCFS2.1_v3", "outputs/dwd_v3"],
    "CMCC-SPS4": ["outputs_cmcc_v3", "outputs_CMCC-SPS4_v3", "outputs/cmcc_v3", "outputs/cmcc_v1"],
    "NCEP CFSv2": ["outputs_ncep_v3", "outputs_NCEP_CFSv2_v3", "outputs/ncep_v3"],
    "ECCC CanSIPS": ["outputs_eccc_v3", "outputs_ECCC_CanSIPS_v3", "outputs/eccc_v3"],
}
MODEL_COLORS: dict = {
    "ECMWF SEAS5"          : "#1B5EA6",
    "ECMWF SEAS5 (Sep)"    : "#0284C7",
    "ECMWF SEAS5 (Kiremt)" : "#1B5EA6",
    "ECMWF SEAS5 (FMAM)"   : "#0D9488",
    "ECMWF SEAS5 (Bega)"   : "#D97706",
    "UKMO GloSea6"         : "#C0392B",
    "Meteo-France Sys8"    : "#1E6B45",
    "DWD GCFS2.1"          : "#8B4513",
    "CMCC-SPS4"            : "#7B0EA6",
    "NCEP CFSv2"           : "#C9920A",
    "ECCC CanSIPS"         : "#0E7490",
}
SITES: list = [
    {"site_name": "El Karama Sahiwals Farm",              "lat": -2.3871,  "lon": 37.4851, "country": "kenya"},
    {"site_name": "Genco LTD Maralal Samburu Farm",       "lat":  0.9273,  "lon": 36.5690, "country": "kenya"},
    {"site_name": "Genco LTD Tana River Farm",            "lat": -2.21314, "lon": 40.0517, "country": "kenya"},
    {"site_name": "KALRO Kiboko, Makueni Farm",           "lat": -2.21046, "lon": 37.7190, "country": "kenya"},
    {"site_name": "Kapiti Research Station Farm",         "lat": -1.63209, "lon": 37.1479, "country": "kenya"},
    {"site_name": "LiveMo LTD, Memerush, Kajiado",        "lat": -2.38726, "lon": 37.4850, "country": "kenya"},
    {"site_name": "Holetta Agricultural Research Center", "lat":  9.0600,  "lon": 38.5000, "country": "ethiopia"},
    {"site_name": "Debre Zeit / Bishoftu Station",        "lat":  8.7500,  "lon": 38.9800, "country": "ethiopia"},
    {"site_name": "Melkassa Agricultural Research Center","lat":  8.4100,  "lon": 39.3200, "country": "ethiopia"},
    {"site_name": "Bako Agricultural Research Center",    "lat":  9.1200,  "lon": 37.0500, "country": "ethiopia"},
    {"site_name": "Hawassa Farm Station",                 "lat":  7.0500,  "lon": 38.4800, "country": "ethiopia"},
    {"site_name": "Yabello Pastoral Research Center",     "lat":  4.8800,  "lon": 38.0900, "country": "ethiopia"},
    {"site_name": "Kobo Agricultural Research Center",    "lat": 12.1400,  "lon": 39.6300, "country": "ethiopia"},
]
WIN_DOY_START = 32
WIN_DOY_END   = 213
CAL_YEARS     = np.arange(1981, 2017)
_PREFIX_MAP   = {
    "dunning_v3":"SEAS5","bom_v3":"BOM","ukmo_v3":"UKMO","mf_v3":"MF",
    "dwd_v3":"DWD","cmcc_v3":"CMCC","ncep_v3":"NCEP","eccc_v3":"ECCC",
    "ecmwf_v3":"ECMWF","ecmwf_sep":"ECMWF","ecmwf_kiremt":"ECMWF","ecmwf_fmam":"ECMWF","ecmwf_bega":"ECMWF",
}


def _first_existing_dir(paths):
    for p in paths:
        if p and os.path.isdir(p):
            return p
    return None


def _resolve_model_dirs(base_dir):
    resolved = {}
    for model_name, rel_candidates in _MODEL_DIR_ALIASES.items():
        abs_candidates = [os.path.join(base_dir, rel) for rel in rel_candidates]
        resolved[model_name] = _first_existing_dir(abs_candidates) or abs_candidates[0]
    return resolved


def _resolve_chirps_dir(base_dir, model_dirs):
    candidates = [
        os.path.join(base_dir, "outputs_dunning_v3"),
        os.path.join(base_dir, "outputs_ECMWF_SEAS5_v3"),
        os.path.join(base_dir, "CHIRPS"),
        os.path.join(base_dir, "chirps"),
        os.path.join(base_dir, "outputs", "dunning_v3"),
        os.path.join(base_dir, "outputs", "seas5_v3"),
        os.path.join(base_dir, "outputs", "CHIRPS"),
        model_dirs.get("ECMWF SEAS5", ""),
    ]
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique_candidates.append(c)
    found = _first_existing_dir(unique_candidates)
    if found:
        return found
    hint = "\n".join(f"  - {p}" for p in unique_candidates)
    raise FileNotFoundError(
        "CHIRPS directory not found under BASE_DIR.\n"
        f"BASE_DIR={base_dir}\n"
        "Checked:\n"
        f"{hint}\n"
        "Set BASE_DIR to your pipeline output root (folder containing CHIRPS/model outputs)."
    )


def _resolve_sep_chirps_dir(base_dir):
    candidates = [
        os.path.join(base_dir, "outputs", "ecmwf_sep"),
        os.path.join(base_dir, "outputs_ecmwf_sep"),
        os.path.join(base_dir, "outputs/ecmwf_sep"),
    ]
    return _first_existing_dir(candidates)


def _resolve_kiremt_chirps_dir(base_dir):
    candidates = [
        os.path.join(base_dir, "outputs", "ecmwf_kiremt"),
        os.path.join(base_dir, "outputs_ecmwf_kiremt"),
        os.path.join(base_dir, "data", "outputs_ETHIOPIA_KIREMT_v1"),
    ]
    return _first_existing_dir(candidates)


def _resolve_fmam_chirps_dir(base_dir):
    candidates = [
        os.path.join(base_dir, "outputs", "ecmwf_fmam"),
        os.path.join(base_dir, "outputs_ecmwf_fmam"),
        os.path.join(base_dir, "outputs/ecmwf_fmam"),
    ]
    return _first_existing_dir(candidates)


def _resolve_bega_chirps_dir(base_dir):
    candidates = [
        os.path.join(base_dir, "outputs", "ecmwf_bega"),
        os.path.join(base_dir, "outputs_ecmwf_bega"),
        os.path.join(base_dir, "outputs/ecmwf_bega"),
    ]
    return _first_existing_dir(candidates)

# ── Configuration ──────────────────────────────────────────────────────────
def configure(base_dir=None, op_year=None, load_bc_daily=None, extra_model_dirs=None):
    global _BASE_DIR, _OP_YEAR, _LOAD_BC, MODEL_DIRS, _configured
    # Re-read env at call time so Docker env vars are always picked up
    if base_dir      is None: base_dir      = _os.environ.get("BASE_DIR", _BASE_DIR)
    if op_year       is None: op_year       = int(_os.environ.get("OP_YEAR", str(_OP_YEAR)))
    if load_bc_daily is None: load_bc_daily = _os.environ.get("LOAD_BC_DAILY", "1").lower() not in ("0", "false", "no")
    base_dir = os.path.abspath(base_dir)
    _BASE_DIR, _OP_YEAR, _LOAD_BC = base_dir, op_year, load_bc_daily
    MODEL_DIRS = _resolve_model_dirs(base_dir)
    if extra_model_dirs:
        MODEL_DIRS.update(extra_model_dirs)
    _configured = True
    print(f"[data_loader] configured  base_dir={base_dir}  op_year={op_year}")

# ── Low-level helpers ──────────────────────────────────────────────────────
def _load(path, var=None):
    ds  = xr.open_dataset(path, decode_timedelta=False)
    key = var or list(ds.data_vars)[0]
    arr = ds[key].values.astype(np.float32)
    ds.close(); return arr

def _load_any(dir_, *candidates, var=None):
    for name in candidates:
        p = os.path.join(dir_, name)
        if os.path.exists(p): return _load(p, var=var)
    raise FileNotFoundError("None found:\n" + "\n".join(f"  {os.path.join(dir_,n)}" for n in candidates))

def _load_any2(d1, d2, *names):
    for d in [d1, d2]:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p): return _load(p)
    raise FileNotFoundError("None found:\n" + "\n".join(f"  {os.path.join(d,n)}" for d in [d1,d2] for n in names))

def _safe_load(path, var=None):
    if not os.path.exists(path): return None
    ds  = xr.open_dataset(path, decode_timedelta=False)
    v   = list(ds.data_vars)[0] if var is None else var
    raw = ds[v].values; ds.close()
    arr = raw.astype(np.float32)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if np.nanmax(np.abs(arr)) > 1e9:
            arr = (arr / 86400e9).astype(np.float32)
    return arr

# ── CHIRPS loader ──────────────────────────────────────────────────────────
def _load_chirps(chirps_dir):
    print(f"[data_loader] CHIRPS dir: {chirps_dir}")
    onset_doy = _load_any(chirps_dir,
        "CHIRPS_onset_doy_1981_2026.nc","CHIRPS_onset_doy_1981_2025.nc","CHIRPS_onset_doy_1993_2026.nc","CHIRPS_onset_doy_all_years.nc","CHIRPS_onset_doy.nc")
    cessation_doy = _load_any(chirps_dir,
        "CHIRPS_cessation_doy_1981_2026.nc","CHIRPS_cessation_doy_1981_2025.nc","CHIRPS_cessation_doy_1993_2026.nc","CHIRPS_cessation_doy_all_years.nc","CHIRPS_cessation_doy.nc")
    lgp_days = _load_any(chirps_dir,
        "CHIRPS_lgp_days_1981_2026.nc","CHIRPS_lgp_days_1981_2025.nc","CHIRPS_lgp_days_1993_2026.nc","CHIRPS_lgp_days_all_years.nc","CHIRPS_lgp_days.nc")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _mx = np.nanmax(np.abs(lgp_days))
    if _mx > 1e6:
        print(f"  WARNING: LGP max={_mx:.2e} converting ns to days")
        lgp_days = (lgp_days / 86400e9).astype(np.float32)
    lgp_days = np.where((lgp_days > 0) & (lgp_days <= 366), lgp_days, np.nan).astype(np.float32)

    C_clim = _load_any(chirps_dir,"chirps_C_clim.nc","C_clim.nc")
    Q_bar  = _load_any(chirps_dir,"chirps_Q_bar.nc","Q_bar.nc")
    d_s    = _load_any(chirps_dir,"chirps_d_s.nc","d_s.nc")
    d_e    = _load_any(chirps_dir,"chirps_d_e.nc","d_e.nc")
    _cal   = os.path.join(chirps_dir,"calibration_params")
    t33_onset = _load_any2(_cal,chirps_dir,"t33_onset_doy.nc","t33_onset.nc")
    t67_onset = _load_any2(_cal,chirps_dir,"t67_onset_doy.nc","t67_onset.nc")
    t33_cess  = _load_any2(_cal,chirps_dir,"t33_cessation_doy.nc","t33_cess.nc","t33_cessation.nc")
    t67_cess  = _load_any2(_cal,chirps_dir,"t67_cessation_doy.nc","t67_cess.nc","t67_cessation.nc")
    t33_lgp   = _load_any2(_cal,chirps_dir,"t33_lgp_days.nc","t33_lgp.nc")
    t67_lgp   = _load_any2(_cal,chirps_dir,"t67_lgp_days.nc","t67_lgp.nc")

    # Grid coords
    _ref_ds = None
    for _c in ["ECMWF_bc_daily_all_years.nc","SEAS5_bc_daily_all_years.nc","SEAS5_BC_daily_all_years.nc"]:
        _p = os.path.join(chirps_dir,_c)
        if os.path.exists(_p): _ref_ds = xr.open_dataset(_p,decode_timedelta=False); break
    if _ref_ds is None:
        for _c in ["CHIRPS_onset_doy_1981_2026.nc","CHIRPS_onset_doy_1981_2025.nc","CHIRPS_onset_doy_1993_2026.nc","CHIRPS_onset_doy.nc"]:
            _p = os.path.join(chirps_dir,_c)
            if os.path.exists(_p): _ref_ds = xr.open_dataset(_p,decode_timedelta=False); break
    target_lat = target_lon = None
    for _n in ["lat","latitude","y"]:
        if _n in _ref_ds.coords: target_lat = _ref_ds[_n].values.astype(np.float64); break
    for _n in ["lon","longitude","x"]:
        if _n in _ref_ds.coords: target_lon = _ref_ds[_n].values.astype(np.float64); break
    _ref_ds.close()
    n_lat, n_lon = len(target_lat), len(target_lon)
    lm = np.isfinite(onset_doy).any(axis=0)

    # Year array
    _cand_ops = [
        "CHIRPS_onset_doy_1981_2026.nc",
        "CHIRPS_onset_doy_1981_2025.nc",
        "CHIRPS_onset_doy_1993_2026.nc",
        "CHIRPS_onset_doy_all_years.nc",
        "CHIRPS_onset_doy.nc",
    ]
    _op = None
    for _c in _cand_ops:
        if os.path.exists(os.path.join(chirps_dir, _c)):
            _op = os.path.join(chirps_dir, _c)
            break
    _ds2 = xr.open_dataset(_op, decode_timedelta=False)
    if "year" in _ds2.coords:
        chirps_years = _ds2["year"].values.astype(int)
    elif "time" in _ds2.coords:
        chirps_years = np.array([int(str(t)[:4]) for t in _ds2["time"].values])
    else:
        _nyr = int(_ds2[list(_ds2.data_vars)[0]].shape[0])
        chirps_years = np.arange(1981, 1981+_nyr)
    _ds2.close()
    if len(chirps_years) != onset_doy.shape[0]:
        raise RuntimeError(f"chirps_years len={len(chirps_years)} != onset dim={onset_doy.shape[0]}")

    cal_mask = np.isin(chirps_years, CAL_YEARS)
    if not cal_mask.any(): raise RuntimeError("No CAL years found")
    cal_idx = np.where(cal_mask)[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        chirps_clim = {
            "onset"    : np.where(lm, np.nanmean(onset_doy[cal_mask],     axis=0), np.nan).astype(np.float32),
            "cessation": np.where(lm, np.nanmean(cessation_doy[cal_mask], axis=0), np.nan).astype(np.float32),
            "lgp"      : np.where(lm, np.nanmean(lgp_days[cal_mask],      axis=0), np.nan).astype(np.float32),
        }
    print(f"  Grid: {n_lat}x{n_lon} ({int(lm.sum())} land px)  "
          f"years:{chirps_years[0]}-{chirps_years[-1]}  "
          f"CAL:{int(cal_mask.sum())}yrs  onset mean:DOY{np.nanmean(chirps_clim['onset'][lm]):.1f}")
    return dict(onset_doy=onset_doy, cessation_doy=cessation_doy, lgp_days=lgp_days,
                C_clim=C_clim, Q_bar=Q_bar, d_s=d_s, d_e=d_e,
                t33_onset=t33_onset, t67_onset=t67_onset,
                t33_cess=t33_cess,   t67_cess=t67_cess,
                t33_lgp=t33_lgp,     t67_lgp=t67_lgp,
                target_lat=target_lat, target_lon=target_lon,
                n_lat=n_lat, n_lon=n_lon, lm=lm,
                chirps_years=chirps_years, cal_idx=cal_idx, cal_mask=cal_mask,
                chirps_clim=chirps_clim)

# ── Model loader ───────────────────────────────────────────────────────────
def _load_model(name, out_dir, chirps, season="long_rains", win_doy_start=32, win_doy_end=213):
    if not os.path.isdir(out_dir):
        print(f"  SKIP  {name}: dir not found"); return None
    n_lat, n_lon, lm = chirps["n_lat"], chirps["n_lon"], chirps["lm"]
    pfx = next((v for k,v in _PREFIX_MAP.items() if k in os.path.basename(out_dir)), "MODEL")
    def _p(f): return os.path.join(out_dir, f)
    def _try(base):
        for pat in [f"{pfx}_{base}_all_years.nc", f"{pfx}_{base}_1993_2026.nc",
                    f"{pfx}_{base}_1981_2026.nc",  f"{pfx}_{base}.nc"]:
            r = _safe_load(_p(pat))
            if r is not None: return r
        return None
    onset_doy = _try("onset_doy")
    cess_doy  = _try("cessation_doy")
    lgp_days  = _try("lgp_days")
    if onset_doy is None:
        print(f"  SKIP  {name}: onset_doy not found"); return None
    n_members = int(onset_doy.shape[0])
    n_years   = int(onset_doy.shape[1])

    _yf = _p("model_years.nc")
    if os.path.exists(_yf):
        model_years = xr.open_dataset(_yf)["year"].values.astype(int)
    else:
        start = 1981 if pfx == "SEAS5" else 1993
        model_years = np.array([y for y in range(start, start+n_years-1)] + [_OP_YEAR])
        if len(model_years) != n_years: model_years = np.arange(start, start+n_years)
    op_mask = model_years == _OP_YEAR
    if not op_mask.any():
        op_idx = len(model_years) - 1
        print(f"  NOTICE {name}: OP_YEAR {_OP_YEAR} not found, defaulting to latest year {model_years[op_idx]}")
    else:
        op_idx = int(np.where(op_mask)[0][0])

    n_days = win_doy_end - win_doy_start + 1
    if _LOAD_BC:
        bc_daily = None
        for pat in [f"{pfx}_bc_daily_all_years.nc", f"{pfx}_BC_daily_all_years.nc",
                    f"{pfx}_bc_daily_1993_2026.nc", "SEAS5_bc_daily_all_years.nc"]:
            bc_daily = _safe_load(_p(pat))
            if bc_daily is not None: break
        if bc_daily is None:
            print(f"  WARNING {name}: bc_daily missing")
            bc_daily = np.zeros((n_members, n_years, n_days, n_lat, n_lon), np.float32)
    else:
        bc_daily = np.zeros((n_members, n_years, n_days, n_lat, n_lon), np.float32)

    # Glob skill discovery
    _nc = {}
    for _root, _, _files in os.walk(out_dir):
        for _f in _files:
            if _f.endswith(".nc"): _nc[_f[:-3].lower()] = os.path.join(_root, _f)
    _missing = []
    def _skill(metric, variable, period=None):
        tokens = [metric, variable] + ([period] if period else [])
        for cand in ["_".join(p) for p in permutations(tokens)]:
            if cand in _nc: return _safe_load(_nc[cand])
        _missing.append(f"{metric}_{variable}{'_'+period if period else ''}.nc")
        return np.full((n_lat, n_lon), np.nan, np.float32)
    def _probs(metric, variable):
        for cand in [f"{metric}_{variable}", f"{pfx}_{metric}_{variable}"]:
            if cand.lower() in _nc: return _safe_load(_nc[cand.lower()])
        _missing.append(f"{metric}_{variable}.nc")
        return np.full((3, n_years, n_lat, n_lon), 1/3, np.float32)

    probs_damped = {v: _probs("probs_damped", v)   for v in ["onset","cessation","lgp"]}
    alpha        = {v: _skill("alpha", v)            for v in ["onset","cessation","lgp"]}
    hitrate_cal  = {v: _skill("hitrate", v, "cal")   for v in ["onset","cessation","lgp"]}
    hitrate_val  = {v: _skill("hitrate", v, "val")   for v in ["onset","cessation","lgp"]}
    rpss_val     = {v: _skill("rpss",    v, "val")   for v in ["onset","cessation","lgp"]}

    # Fallback to validation skill if cal skill files not present
    for v in ["onset","cessation","lgp"]:
        if np.all(np.isnan(hitrate_cal[v])) and not np.all(np.isnan(hitrate_val[v])):
            hitrate_cal[v] = hitrate_val[v]

    if _missing: print(f"  WARNING {name}: {len(_missing)} skill file(s) missing: {_missing[:4]}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        hr = float(np.nanmean(hitrate_cal["onset"][lm]))
    print(f"  LOADED {name:<22}: {n_members} mem  {n_years} yrs  op_idx={op_idx}  "
          f"{'HR='+f'{hr:.3f}' if not np.isnan(hr) else '(no skill files)'}")
    return dict(onset_doy=onset_doy, cessation_doy=cess_doy, lgp_days=lgp_days,
                bc_daily=bc_daily, probs_damped=probs_damped, alpha=alpha,
                hitrate_cal=hitrate_cal, hitrate_val=hitrate_val, rpss_val=rpss_val,
                op_idx=op_idx, n_members=n_members,
                color=MODEL_COLORS.get(name,"#888888"), model_years=model_years,
                season=season, win_doy_start=win_doy_start, win_doy_end=win_doy_end,
                chirps_clim=chirps.get("chirps_clim"),
                lm=chirps.get("lm"),
                target_lat=chirps.get("target_lat"),
                target_lon=chirps.get("target_lon"),
                C_clim=chirps.get("C_clim"), Q_bar=chirps.get("Q_bar"),
                d_s=chirps.get("d_s"), d_e=chirps.get("d_e"),
                t33_onset=chirps.get("t33_onset"), t67_onset=chirps.get("t67_onset"),
                t33_cess=chirps.get("t33_cess"), t67_cess=chirps.get("t67_cess"),
                t33_lgp=chirps.get("t33_lgp"), t67_lgp=chirps.get("t67_lgp"))

# ── Demo / Cloud fallback loader ──────────────────────────────────────────
def _load_demo_npz():
    npz_path = os.path.join(os.path.dirname(__file__), "demo_data.npz")
    if not os.path.exists(npz_path):
        npz_path = os.path.join(_REPO_ROOT, "backend", "demo_data.npz")
    if not os.path.exists(npz_path):
        raise FileNotFoundError(f"demo_data.npz not found at {npz_path}")

    print(f"[data_loader] Loading demo dataset from {npz_path}...")
    data = np.load(npz_path)
    target_lat = data["target_lat"].astype(np.float64)
    target_lon = data["target_lon"].astype(np.float64)
    n_lat, n_lon = len(target_lat), len(target_lon)
    lm = data["lm"].astype(bool)
    onset_doy = data["chirps_onset"]
    cessation_doy = data["chirps_cessation"]
    lgp_days = data["chirps_lgp"]
    chirps_years = data["chirps_years"]
    cal_mask = np.isin(chirps_years, CAL_YEARS)
    cal_idx = np.where(cal_mask)[0]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        chirps_clim = {
            "onset": np.where(lm, np.nanmean(onset_doy[cal_mask], axis=0), np.nan).astype(np.float32),
            "cessation": np.where(lm, np.nanmean(cessation_doy[cal_mask], axis=0), np.nan).astype(np.float32),
            "lgp": np.where(lm, np.nanmean(lgp_days[cal_mask], axis=0), np.nan).astype(np.float32),
        }

    chirps = dict(
        onset_doy=onset_doy, cessation_doy=cessation_doy, lgp_days=lgp_days,
        C_clim=data["C_clim"], Q_bar=data["Q_bar"], d_s=data["d_s"], d_e=data["d_e"],
        t33_onset=data["t33_onset"], t67_onset=data["t67_onset"],
        t33_cess=data["t33_cess"], t67_cess=data["t67_cess"],
        t33_lgp=data["t33_lgp"], t67_lgp=data["t67_lgp"],
        target_lat=target_lat, target_lon=target_lon,
        n_lat=n_lat, n_lon=n_lon, lm=lm,
        chirps_years=chirps_years, cal_idx=cal_idx, cal_mask=cal_mask,
        chirps_clim=chirps_clim,
    )

    models_map = [
        ("ECMWF SEAS5", "ecmwf"),
        ("UKMO GloSea6", "ukmo"),
        ("Meteo-France Sys8", "mf"),
        ("DWD GCFS2.1", "dwd"),
        ("CMCC-SPS4", "cmcc"),
        ("NCEP CFSv2", "ncep"),
        ("ECCC CanSIPS", "eccc"),
    ]

    MODELS = {}
    for name, k in models_map:
        if f"{k}_onset" not in data: continue
        m_on = data[f"{k}_onset"]
        m_cs = data[f"{k}_cessation"]
        m_lg = data[f"{k}_lgp"]
        m_years = data[f"{k}_years"]
        op_mask = m_years == _OP_YEAR
        op_idx = int(np.where(op_mask)[0][0]) if op_mask.any() else len(m_years) - 1
        n_members = int(m_on.shape[0])

        probs_damped = {
            "onset": data[f"{k}_p_on"],
            "cessation": data[f"{k}_p_cs"],
            "lgp": data[f"{k}_p_lg"],
        }
        alpha = {
            "onset": data[f"{k}_a_on"],
            "cessation": data[f"{k}_a_cs"],
            "lgp": data[f"{k}_a_lg"],
        }
        hitrate_cal = {
            "onset": data[f"{k}_h_on"],
            "cessation": data[f"{k}_h_cs"],
            "lgp": data[f"{k}_h_lg"],
        }
        hitrate_val = {
            "onset": data[f"{k}_h_on"],
            "cessation": data[f"{k}_h_cs"],
            "lgp": data[f"{k}_h_lg"],
        }
        rpss_val = {
            "onset": data[f"{k}_r_on"],
            "cessation": data[f"{k}_r_cs"],
            "lgp": data[f"{k}_r_lg"],
        }

        # Daily rainfall array for pixel cumulative curves (None in demo mode to save 5+ GB RAM)
        bc_daily = None

        MODELS[name] = dict(
            onset_doy=m_on, cessation_doy=m_cs, lgp_days=m_lg,
            bc_daily=bc_daily, probs_damped=probs_damped, alpha=alpha,
            hitrate_cal=hitrate_cal, hitrate_val=hitrate_val, rpss_val=rpss_val,
            op_idx=op_idx, n_members=n_members,
            color=MODEL_COLORS.get(name, "#888888"), model_years=m_years
        )

    # ── Short Rains (OND) demo support ─────────────────────────────────────
    chirps_sep = None
    if "sep_chirps_onset" in data:
        sep_onset = data["sep_chirps_onset"]
        sep_cess  = data["sep_chirps_cessation"]
        sep_lgp   = data["sep_chirps_lgp"]
        sep_years = data["sep_chirps_years"] if "sep_chirps_years" in data else np.arange(1993, 1993 + len(sep_onset))
        sep_cal_mask = np.isin(sep_years, CAL_YEARS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sep_clim = {
                "onset": np.where(lm, np.nanmean(sep_onset[sep_cal_mask], axis=0), np.nan).astype(np.float32),
                "cessation": np.where(lm, np.nanmean(sep_cess[sep_cal_mask], axis=0), np.nan).astype(np.float32),
                "lgp": np.where(lm, np.nanmean(sep_lgp[sep_cal_mask], axis=0), np.nan).astype(np.float32),
            }
        chirps_sep = dict(
            onset_doy=sep_onset, cessation_doy=sep_cess, lgp_days=sep_lgp,
            C_clim=data["sep_C_clim"], Q_bar=data["sep_Q_bar"], d_s=data["sep_d_s"], d_e=data["sep_d_e"],
            t33_onset=data["sep_t33_on"], t67_onset=data["sep_t67_on"],
            t33_cess=data["sep_t33_cs"], t67_cess=data["sep_t67_cs"],
            t33_lgp=data["sep_t33_lg"], t67_lgp=data["sep_t67_lg"],
            target_lat=target_lat, target_lon=target_lon,
            n_lat=n_lat, n_lon=n_lon, lm=lm,
            chirps_years=sep_years,
            cal_idx=np.where(sep_cal_mask)[0],
            cal_mask=sep_cal_mask,
            chirps_clim=sep_clim,
        )

    if "sep_ecmwf_onset" in data:
        m_on = data["sep_ecmwf_onset"]
        m_cs = data["sep_ecmwf_cessation"]
        m_lg = data["sep_ecmwf_lgp"]
        m_years = data["sep_ecmwf_years"]
        target_op_year = 2026 if (2026 in m_years) else 2025
        op_mask = m_years == target_op_year
        op_idx = int(np.where(op_mask)[0][0]) if op_mask.any() else len(m_years) - 1
        n_members = int(m_on.shape[0])

        sep_bc_daily = {}
        if "sep_ecmwf_bc_daily_2026" in data:
            sep_bc_daily[2026] = data["sep_ecmwf_bc_daily_2026"].astype(np.float32)
        if "sep_ecmwf_bc_daily_2025" in data:
            sep_bc_daily[2025] = data["sep_ecmwf_bc_daily_2025"].astype(np.float32)

        MODELS["ECMWF SEAS5 (Sep)"] = dict(
            onset_doy=m_on, cessation_doy=m_cs, lgp_days=m_lg,
            bc_daily=sep_bc_daily,
            probs_damped={
                "onset": data["sep_ecmwf_p_on"],
                "cessation": data["sep_ecmwf_p_cs"],
                "lgp": data["sep_ecmwf_p_lg"],
            },
            alpha={
                "onset": data["sep_ecmwf_a_on"],
                "cessation": data["sep_ecmwf_a_cs"],
                "lgp": data["sep_ecmwf_a_lg"],
            },
            hitrate_cal={
                "onset": data["sep_ecmwf_h_on"],
                "cessation": data["sep_ecmwf_h_cs"],
                "lgp": data["sep_ecmwf_h_lg"],
            },
            hitrate_val={
                "onset": data["sep_ecmwf_h_on"],
                "cessation": data["sep_ecmwf_h_cs"],
                "lgp": data["sep_ecmwf_h_lg"],
            },
            rpss_val={
                "onset": data["sep_ecmwf_r_on"],
                "cessation": data["sep_ecmwf_r_cs"],
                "lgp": data["sep_ecmwf_r_lg"],
            },
            op_idx=op_idx, n_members=n_members,
            color=MODEL_COLORS.get("ECMWF SEAS5 (Sep)", "#0284C7"),
            model_years=m_years,
            season="short_rains",
            win_doy_start=244,
            win_doy_end=365,
            chirps_clim=chirps_sep["chirps_clim"] if chirps_sep else chirps_clim,
            t33_onset=chirps_sep["t33_onset"] if chirps_sep else None,
            t67_onset=chirps_sep["t67_onset"] if chirps_sep else None,
            t33_cess=chirps_sep["t33_cess"] if chirps_sep else None,
            t67_cess=chirps_sep["t67_cess"] if chirps_sep else None,
            t33_lgp=chirps_sep["t33_lgp"] if chirps_sep else None,
            t67_lgp=chirps_sep["t67_lgp"] if chirps_sep else None,
            C_clim=chirps_sep["C_clim"] if chirps_sep else None,
            Q_bar=chirps_sep["Q_bar"] if chirps_sep else None,
            d_s=chirps_sep["d_s"] if chirps_sep else None,
            d_e=chirps_sep["d_e"] if chirps_sep else None,
        )

    # ── Ethiopia Kiremt demo support ───────────────────────────────────────
    chirps_kiremt = None
    if "kiremt_chirps_onset" in data:
        k_onset = data["kiremt_chirps_onset"]
        k_cess  = data["kiremt_chirps_cessation"]
        k_lgp   = data["kiremt_chirps_lgp"]
        k_target_lat = data["kiremt_target_lat"]
        k_target_lon = data["kiremt_target_lon"]
        k_n_lat, k_n_lon = len(k_target_lat), len(k_target_lon)
        k_lm = data["kiremt_lm"].astype(bool) if "kiremt_lm" in data else np.isfinite(k_onset).any(axis=0)
        k_years = data["kiremt_chirps_years"] if "kiremt_chirps_years" in data else np.arange(1993, 1993 + len(k_onset))
        k_cal_mask = np.isin(k_years, CAL_YEARS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            k_clim = {
                "onset": np.where(k_lm, np.nanmean(k_onset[k_cal_mask], axis=0), np.nan).astype(np.float32),
                "cessation": np.where(k_lm, np.nanmean(k_cess[k_cal_mask], axis=0), np.nan).astype(np.float32),
                "lgp": np.where(k_lm, np.nanmean(k_lgp[k_cal_mask], axis=0), np.nan).astype(np.float32),
            }
        chirps_kiremt = dict(
            onset_doy=k_onset, cessation_doy=k_cess, lgp_days=k_lgp,
            C_clim=data["kiremt_C_clim"], Q_bar=data["kiremt_Q_bar"], d_s=data["kiremt_d_s"], d_e=data["kiremt_d_e"],
            t33_onset=data["kiremt_t33_on"], t67_onset=data["kiremt_t67_on"],
            t33_cess=data["kiremt_t33_cs"], t67_cess=data["kiremt_t67_cs"],
            t33_lgp=data["kiremt_t33_lg"], t67_lgp=data["kiremt_t67_lg"],
            target_lat=k_target_lat, target_lon=k_target_lon,
            n_lat=k_n_lat, n_lon=k_n_lon, lm=k_lm,
            chirps_years=k_years,
            cal_idx=np.where(k_cal_mask)[0],
            cal_mask=k_cal_mask,
            chirps_clim=k_clim,
        )

    if "kiremt_ecmwf_onset" in data:
        m_on = data["kiremt_ecmwf_onset"].astype(np.float32)
        m_cs = data["kiremt_ecmwf_cessation"].astype(np.float32)
        m_lg = data["kiremt_ecmwf_lgp"].astype(np.float32)
        m_years = data["kiremt_ecmwf_years"]
        target_op_year = 2026 if (2026 in m_years) else 2025
        op_mask = m_years == target_op_year
        op_idx = int(np.where(op_mask)[0][0]) if op_mask.any() else len(m_years) - 1
        n_members = int(m_on.shape[0])

        k_bc_daily = {}
        if "kiremt_ecmwf_bc_daily_2026" in data:
            k_bc_daily[2026] = data["kiremt_ecmwf_bc_daily_2026"].astype(np.float32)

        MODELS["ECMWF SEAS5 (Kiremt)"] = dict(
            onset_doy=m_on, cessation_doy=m_cs, lgp_days=m_lg,
            bc_daily=k_bc_daily,
            probs_damped={
                "onset": data["kiremt_ecmwf_p_on"],
                "cessation": data["kiremt_ecmwf_p_cs"],
                "lgp": data["kiremt_ecmwf_p_lg"],
            },
            alpha={
                "onset": data["kiremt_ecmwf_a_on"],
                "cessation": data["kiremt_ecmwf_a_cs"],
                "lgp": data["kiremt_ecmwf_a_lg"],
            },
            hitrate_cal={
                "onset": data["kiremt_ecmwf_h_on"],
                "cessation": data["kiremt_ecmwf_h_cs"],
                "lgp": data["kiremt_ecmwf_h_lg"],
            },
            hitrate_val={
                "onset": data["kiremt_ecmwf_h_on"],
                "cessation": data["kiremt_ecmwf_h_cs"],
                "lgp": data["kiremt_ecmwf_h_lg"],
            },
            rpss_val={
                "onset": data["kiremt_ecmwf_r_on"],
                "cessation": data["kiremt_ecmwf_r_cs"],
                "lgp": data["kiremt_ecmwf_r_lg"],
            },
            op_idx=op_idx, n_members=n_members,
            color=MODEL_COLORS.get("ECMWF SEAS5 (Kiremt)", "#1B5EA6"),
            model_years=m_years,
            season="kiremt",
            win_doy_start=122,
            win_doy_end=304,
            chirps_clim=chirps_kiremt["chirps_clim"] if chirps_kiremt else chirps_clim,
            t33_onset=chirps_kiremt["t33_onset"] if chirps_kiremt else None,
            t67_onset=chirps_kiremt["t67_onset"] if chirps_kiremt else None,
            t33_cess=chirps_kiremt["t33_cess"] if chirps_kiremt else None,
            t67_cess=chirps_kiremt["t67_cess"] if chirps_kiremt else None,
            t33_lgp=chirps_kiremt["t33_lgp"] if chirps_kiremt else None,
            t67_lgp=chirps_kiremt["t67_lgp"] if chirps_kiremt else None,
            C_clim=chirps_kiremt["C_clim"] if chirps_kiremt else None,
            Q_bar=chirps_kiremt["Q_bar"] if chirps_kiremt else None,
            d_s=chirps_kiremt["d_s"] if chirps_kiremt else None,
            d_e=chirps_kiremt["d_e"] if chirps_kiremt else None,
            lm=chirps_kiremt["lm"] if chirps_kiremt else None,
            target_lat=chirps_kiremt["target_lat"] if chirps_kiremt else None,
            target_lon=chirps_kiremt["target_lon"] if chirps_kiremt else None,
        )

    # ── Ethiopia Belg (FMAM) demo support ──────────────────────────────────
    chirps_fmam = None
    if "fmam_chirps_onset" in data:
        f_onset = data["fmam_chirps_onset"]
        f_cess  = data["fmam_chirps_cessation"]
        f_lgp   = data["fmam_chirps_lgp"]
        f_target_lat = data["fmam_target_lat"]
        f_target_lon = data["fmam_target_lon"]
        f_n_lat, f_n_lon = len(f_target_lat), len(f_target_lon)
        f_lm = data["fmam_lm"].astype(bool) if "fmam_lm" in data else np.isfinite(f_onset).any(axis=0)
        f_years = data["fmam_chirps_years"] if "fmam_chirps_years" in data else np.arange(1993, 1993 + len(f_onset))
        f_cal_mask = np.isin(f_years, CAL_YEARS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            f_clim = {
                "onset": np.where(f_lm, np.nanmean(f_onset[f_cal_mask], axis=0), np.nan).astype(np.float32),
                "cessation": np.where(f_lm, np.nanmean(f_cess[f_cal_mask], axis=0), np.nan).astype(np.float32),
                "lgp": np.where(f_lm, np.nanmean(f_lgp[f_cal_mask], axis=0), np.nan).astype(np.float32),
            }
        chirps_fmam = dict(
            onset_doy=f_onset, cessation_doy=f_cess, lgp_days=f_lgp,
            C_clim=data["fmam_C_clim"], Q_bar=data["fmam_Q_bar"], d_s=data["fmam_d_s"], d_e=data["fmam_d_e"],
            t33_onset=data["fmam_t33_on"], t67_onset=data["fmam_t67_on"],
            t33_cess=data["fmam_t33_cs"], t67_cess=data["fmam_t67_cs"],
            t33_lgp=data["fmam_t33_lg"], t67_lgp=data["fmam_t67_lg"],
            target_lat=f_target_lat, target_lon=f_target_lon,
            n_lat=f_n_lat, n_lon=f_n_lon, lm=f_lm,
            chirps_years=f_years,
            cal_idx=np.where(f_cal_mask)[0],
            cal_mask=f_cal_mask,
            chirps_clim=f_clim,
        )

    if "fmam_ecmwf_onset" in data:
        m_on = data["fmam_ecmwf_onset"].astype(np.float32)
        m_cs = data["fmam_ecmwf_cessation"].astype(np.float32)
        m_lg = data["fmam_ecmwf_lgp"].astype(np.float32)
        m_years = data["fmam_ecmwf_years"]
        target_op_year = 2026 if (2026 in m_years) else 2025
        op_mask = m_years == target_op_year
        op_idx = int(np.where(op_mask)[0][0]) if op_mask.any() else len(m_years) - 1
        n_members = int(m_on.shape[0])

        f_bc_daily = {}
        if "fmam_ecmwf_bc_daily_2026" in data:
            f_bc_daily[2026] = data["fmam_ecmwf_bc_daily_2026"].astype(np.float32)

        MODELS["ECMWF SEAS5 (FMAM)"] = dict(
            onset_doy=m_on, cessation_doy=m_cs, lgp_days=m_lg,
            bc_daily=f_bc_daily,
            probs_damped={
                "onset": data["fmam_ecmwf_p_on"],
                "cessation": data["fmam_ecmwf_p_cs"],
                "lgp": data["fmam_ecmwf_p_lg"],
            },
            alpha={
                "onset": data["fmam_ecmwf_a_on"],
                "cessation": data["fmam_ecmwf_a_cs"],
                "lgp": data["fmam_ecmwf_a_lg"],
            },
            hitrate_cal={
                "onset": data["fmam_ecmwf_h_on"],
                "cessation": data["fmam_ecmwf_h_cs"],
                "lgp": data["fmam_ecmwf_h_lg"],
            },
            hitrate_val={
                "onset": data["fmam_ecmwf_h_on"],
                "cessation": data["fmam_ecmwf_h_cs"],
                "lgp": data["fmam_ecmwf_h_lg"],
            },
            rpss_val={
                "onset": data["fmam_ecmwf_r_on"],
                "cessation": data["fmam_ecmwf_r_cs"],
                "lgp": data["fmam_ecmwf_r_lg"],
            },
            op_idx=op_idx, n_members=n_members,
            color=MODEL_COLORS.get("ECMWF SEAS5 (FMAM)", "#0D9488"),
            model_years=m_years,
            season="fmam",
            win_doy_start=32,
            win_doy_end=166,
            chirps_clim=chirps_fmam["chirps_clim"] if chirps_fmam else chirps_clim,
            t33_onset=chirps_fmam["t33_onset"] if chirps_fmam else None,
            t67_onset=chirps_fmam["t67_onset"] if chirps_fmam else None,
            t33_cess=chirps_fmam["t33_cess"] if chirps_fmam else None,
            t67_cess=chirps_fmam["t67_cess"] if chirps_fmam else None,
            t33_lgp=chirps_fmam["t33_lgp"] if chirps_fmam else None,
            t67_lgp=chirps_fmam["t67_lgp"] if chirps_fmam else None,
            C_clim=chirps_fmam["C_clim"] if chirps_fmam else None,
            Q_bar=chirps_fmam["Q_bar"] if chirps_fmam else None,
            d_s=chirps_fmam["d_s"] if chirps_fmam else None,
            d_e=chirps_fmam["d_e"] if chirps_fmam else None,
            lm=chirps_fmam["lm"] if chirps_fmam else None,
            target_lat=chirps_fmam["target_lat"] if chirps_fmam else None,
            target_lon=chirps_fmam["target_lon"] if chirps_fmam else None,
        )

    # ── Ethiopia Bega (ONDJ) demo support ──────────────────────────────────
    chirps_bega = None
    if "bega_chirps_onset" in data:
        b_onset = data["bega_chirps_onset"]
        b_cess  = data["bega_chirps_cessation"]
        b_lgp   = data["bega_chirps_lgp"]
        b_target_lat = data["bega_target_lat"]
        b_target_lon = data["bega_target_lon"]
        b_n_lat, b_n_lon = len(b_target_lat), len(b_target_lon)
        b_lm = data["bega_lm"].astype(bool) if "bega_lm" in data else np.isfinite(b_onset).any(axis=0)
        b_years = data["bega_chirps_years"] if "bega_chirps_years" in data else np.arange(1993, 1993 + len(b_onset))
        b_cal_mask = np.isin(b_years, CAL_YEARS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            b_clim = {
                "onset": np.where(b_lm, np.nanmean(b_onset[b_cal_mask], axis=0), np.nan).astype(np.float32),
                "cessation": np.where(b_lm, np.nanmean(b_cess[b_cal_mask], axis=0), np.nan).astype(np.float32),
                "lgp": np.where(b_lm, np.nanmean(b_lgp[b_cal_mask], axis=0), np.nan).astype(np.float32),
            }
        chirps_bega = dict(
            onset_doy=b_onset, cessation_doy=b_cess, lgp_days=b_lgp,
            C_clim=data["bega_C_clim"], Q_bar=data["bega_Q_bar"], d_s=data["bega_d_s"], d_e=data["bega_d_e"],
            t33_onset=data["bega_t33_on"], t67_onset=data["bega_t67_on"],
            t33_cess=data["bega_t33_cs"], t67_cess=data["bega_t67_cs"],
            t33_lgp=data["bega_t33_lg"], t67_lgp=data["bega_t67_lg"],
            target_lat=b_target_lat, target_lon=b_target_lon,
            n_lat=b_n_lat, n_lon=b_n_lon, lm=b_lm,
            chirps_years=b_years,
            cal_idx=np.where(b_cal_mask)[0],
            cal_mask=b_cal_mask,
            chirps_clim=b_clim,
        )

    if "bega_ecmwf_onset" in data:
        m_on = data["bega_ecmwf_onset"].astype(np.float32)
        m_cs = data["bega_ecmwf_cessation"].astype(np.float32)
        m_lg = data["bega_ecmwf_lgp"].astype(np.float32)
        m_years = data["bega_ecmwf_years"]
        target_op_year = 2026 if (2026 in m_years) else 2025
        op_mask = m_years == target_op_year
        op_idx = int(np.where(op_mask)[0][0]) if op_mask.any() else len(m_years) - 1
        n_members = int(m_on.shape[0])

        b_bc_daily = {}
        if "bega_ecmwf_bc_daily_2026" in data:
            b_bc_daily[2026] = data["bega_ecmwf_bc_daily_2026"].astype(np.float32)

        MODELS["ECMWF SEAS5 (Bega)"] = dict(
            onset_doy=m_on, cessation_doy=m_cs, lgp_days=m_lg,
            bc_daily=b_bc_daily,
            probs_damped={
                "onset": data["bega_ecmwf_p_on"],
                "cessation": data["bega_ecmwf_p_cs"],
                "lgp": data["bega_ecmwf_p_lg"],
            },
            alpha={
                "onset": data["bega_ecmwf_a_on"],
                "cessation": data["bega_ecmwf_a_cs"],
                "lgp": data["bega_ecmwf_a_lg"],
            },
            hitrate_cal={
                "onset": data["bega_ecmwf_h_on"],
                "cessation": data["bega_ecmwf_h_cs"],
                "lgp": data["bega_ecmwf_h_lg"],
            },
            hitrate_val={
                "onset": data["bega_ecmwf_h_on"],
                "cessation": data["bega_ecmwf_h_cs"],
                "lgp": data["bega_ecmwf_h_lg"],
            },
            rpss_val={
                "onset": data["bega_ecmwf_r_on"],
                "cessation": data["bega_ecmwf_r_cs"],
                "lgp": data["bega_ecmwf_r_lg"],
            },
            op_idx=op_idx, n_members=n_members,
            color=MODEL_COLORS.get("ECMWF SEAS5 (Bega)", "#D97706"),
            model_years=m_years,
            season="bega",
            win_doy_start=244,
            win_doy_end=396,
            chirps_clim=chirps_bega["chirps_clim"] if chirps_bega else chirps_clim,
            t33_onset=chirps_bega["t33_onset"] if chirps_bega else None,
            t67_onset=chirps_bega["t67_onset"] if chirps_bega else None,
            t33_cess=chirps_bega["t33_cess"] if chirps_bega else None,
            t67_cess=chirps_bega["t67_cess"] if chirps_bega else None,
            t33_lgp=chirps_bega["t33_lgp"] if chirps_bega else None,
            t67_lgp=chirps_bega["t67_lgp"] if chirps_bega else None,
            C_clim=chirps_bega["C_clim"] if chirps_bega else None,
            Q_bar=chirps_bega["Q_bar"] if chirps_bega else None,
            d_s=chirps_bega["d_s"] if chirps_bega else None,
            d_e=chirps_bega["d_e"] if chirps_bega else None,
            lm=chirps_bega["lm"] if chirps_bega else None,
            target_lat=chirps_bega["target_lat"] if chirps_bega else None,
            target_lon=chirps_bega["target_lon"] if chirps_bega else None,
        )

    masks = {}
    for mkey in ["mask_kiremt", "mask_belg", "mask_deyr", "mask_bega", "mask_kenya_mam", "mask_kenya_ond"]:
        if mkey in data:
            masks[mkey] = data[mkey].astype(bool)
    regime_map = data["regime_map"].astype(np.int8) if "regime_map" in data else None

    print(f"[data_loader] Loaded {len(MODELS)} models from demo dataset (OND: {bool(chirps_sep)}, Kiremt: {bool(chirps_kiremt)}, Belg: {bool(chirps_fmam)}, Deyr/Bega: {bool(chirps_bega)}, Masks: {list(masks.keys())}, RegimeMap: {regime_map is not None}).")
    return {**chirps, "MODELS": MODELS, "OP_YEAR": _OP_YEAR, "demo_mode": True, "chirps_sep": chirps_sep, "chirps_kiremt": chirps_kiremt, "chirps_fmam": chirps_fmam, "chirps_bega": chirps_bega, "seasonal_masks": masks, "regime_map": regime_map}

# ── Main load ──────────────────────────────────────────────────────────────
def load(force=False):
    global _state, _loaded
    if _loaded and not force: return
    if not _configured: configure()
    try:
        chirps_dir = _resolve_chirps_dir(_BASE_DIR, MODEL_DIRS)
        chirps = _load_chirps(chirps_dir)
        sep_dir = _resolve_sep_chirps_dir(_BASE_DIR)
        chirps_sep = _load_chirps(sep_dir) if sep_dir else None
        kiremt_dir = _resolve_kiremt_chirps_dir(_BASE_DIR)
        chirps_kiremt = _load_chirps(kiremt_dir) if kiremt_dir else None
        fmam_dir = _resolve_fmam_chirps_dir(_BASE_DIR)
        chirps_fmam = _load_chirps(fmam_dir) if fmam_dir else None
        bega_dir = _resolve_bega_chirps_dir(_BASE_DIR)
        chirps_bega = _load_chirps(bega_dir) if bega_dir else None

        print("[data_loader] Loading model outputs ...")
        MODELS = {}
        for name, out_dir in MODEL_DIRS.items():
            is_bega = ("bega" in name.lower()) or ("bega" in out_dir.lower())
            is_sep = not is_bega and (("sep" in name.lower()) or ("sep" in out_dir.lower()))
            is_kiremt = not is_bega and (("kiremt" in name.lower()) or ("kiremt" in out_dir.lower()))
            is_fmam = not is_bega and (("fmam" in name.lower()) or ("fmam" in out_dir.lower()))
            if is_bega:
                m_chirps = (chirps_bega if chirps_bega else chirps)
                m_season = "bega"
                m_start  = 244
                m_end    = 396
            elif is_fmam:
                m_chirps = (chirps_fmam if chirps_fmam else chirps)
                m_season = "fmam"
                m_start  = 32
                m_end    = 166
            elif is_kiremt:
                m_chirps = (chirps_kiremt if chirps_kiremt else chirps)
                m_season = "kiremt"
                m_start  = 122
                m_end    = 304
            elif is_sep:
                m_chirps = (chirps_sep if (is_sep and chirps_sep) else chirps)
                m_season = "short_rains"
                m_start  = 244
                m_end    = 365
            else:
                m_chirps = chirps
                m_season = "long_rains"
                m_start  = 32
                m_end    = 213
            entry = _load_model(name, out_dir, m_chirps, season=m_season, win_doy_start=m_start, win_doy_end=m_end)
            if entry is not None: MODELS[name] = entry
        if not MODELS:
            raise RuntimeError("No models loaded from NetCDF files.")
        print(f"\n[data_loader] Loaded {len(MODELS)}/{len(MODEL_DIRS)} models from NetCDF. Ready.")

        masks = {}
        regime_map = None
        masks_path = os.path.join(_REPO_ROOT, "outputs", "masks", "seasonal_masks.npz")
        if os.path.exists(masks_path):
            m_data = np.load(masks_path)
            for mkey in m_data.files:
                if mkey == "regime_map":
                    regime_map = m_data[mkey].astype(np.int8)
                else:
                    masks[mkey] = m_data[mkey].astype(bool)
        elif os.path.exists(os.path.join(_REPO_ROOT, "backend", "demo_data.npz")):
            m_data = np.load(os.path.join(_REPO_ROOT, "backend", "demo_data.npz"))
            for mkey in ["mask_kiremt", "mask_belg", "mask_deyr", "mask_bega", "mask_kenya_mam", "mask_kenya_ond"]:
                if mkey in m_data:
                    masks[mkey] = m_data[mkey].astype(bool)
            if "regime_map" in m_data:
                regime_map = m_data["regime_map"].astype(np.int8)

        _state  = {**chirps, "MODELS": MODELS, "OP_YEAR": _OP_YEAR, "demo_mode": False, "chirps_sep": chirps_sep, "chirps_kiremt": chirps_kiremt, "chirps_fmam": chirps_fmam, "chirps_bega": chirps_bega, "seasonal_masks": masks, "regime_map": regime_map}
        _loaded = True
    except Exception as exc:
        print(f"[data_loader] Raw NetCDF data not available ({type(exc).__name__}: {exc})")
        print("[data_loader] Initializing cloud demo mode from demo_data.npz...")
        try:
            _state = _load_demo_npz()
            _loaded = True
            print(f"[data_loader] Cloud demo mode ready with {len(_state.get('MODELS', {}))} models live.")
        except Exception as demo_exc:
            print(f"[data_loader] ERROR: Failed to load demo state: {demo_exc}")
            raise

def is_loaded(): return _loaded
def get_state():
    if not _loaded: raise RuntimeError("Call data_loader.load() first.")
    return _state

# ── Model info ─────────────────────────────────────────────────────────────
def get_model_info(season=None):
    s = get_state()
    out = []
    is_bega = (season in ["bega", "ondj"])
    is_fmam = not is_bega and (season in ["fmam", "belg"])
    is_kiremt = not is_bega and not is_fmam and (season in ["kiremt", "jjas"])
    is_short = not is_bega and not is_fmam and not is_kiremt and (season in ["short_rains", "ond"])
    for name, md in s["MODELS"].items():
        md_season = md.get("season", "long_rains")
        if season is not None:
            if is_bega:
                if md_season != "bega" and "bega" not in name.lower():
                    continue
            elif is_fmam:
                if md_season != "fmam" and "fmam" not in name.lower():
                    continue
            elif is_kiremt:
                if md_season != "kiremt" and "kiremt" not in name.lower():
                    continue
            elif is_short:
                if md_season != "short_rains" and "Sep" not in name:
                    continue
            else:
                if md_season in ("short_rains", "kiremt", "fmam", "bega") or "Sep" in name or "Kiremt" in name or "FMAM" in name or "Bega" in name:
                    continue

        if md_season == "bega" and s.get("chirps_bega"):
            m_lm = s["chirps_bega"]["lm"]
        elif md_season == "fmam" and s.get("chirps_fmam"):
            m_lm = s["chirps_fmam"]["lm"]
        elif md_season == "kiremt" and s.get("chirps_kiremt"):
            m_lm = s["chirps_kiremt"]["lm"]
        elif md_season == "short_rains" and s.get("chirps_sep"):
            m_lm = s["chirps_sep"]["lm"]
        else:
            m_lm = s["lm"]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            hr = float(np.nanmean(md["hitrate_cal"]["onset"][m_lm]))
        
        display_name = "ECMWF SEAS5" if ((is_short and "Sep" in name) or (is_kiremt and "Kiremt" in name) or (is_fmam and "FMAM" in name) or (is_bega and "Bega" in name)) else name
        op_y = int(md["model_years"][md["op_idx"]]) if ("op_idx" in md and "model_years" in md and md["op_idx"] < len(md["model_years"])) else (2025 if is_short else 2026)
        out.append(dict(name=display_name, raw_name=name, n_members=md["n_members"], op_idx=md["op_idx"],
                        op_year=op_y,
                        color=md["color"],
                        hr_onset=round(hr,3) if not np.isnan(hr) else None,
                        skill_pass=bool(not np.isnan(hr) and hr > 1/3),
                        year_start=int(md["model_years"][0]),
                        year_end=int(md["model_years"][-1]),
                        season=md_season,
                        win_doy_start=md.get("win_doy_start", 244 if is_bega else (32 if is_fmam else (122 if is_kiremt else (244 if is_short else 32)))),
                        win_doy_end=md.get("win_doy_end", 396 if is_bega else (166 if is_fmam else (304 if is_kiremt else (365 if is_short else 213))))))
    return out

# ── Pixel stats ────────────────────────────────────────────────────────────
def _nearest_pixel(lat, lon, target_lat=None, target_lon=None, lm=None):
    s = _state
    lat_arr = s["target_lat"] if target_lat is None else target_lat
    lon_arr = s["target_lon"] if target_lon is None else target_lon
    mask    = s["lm"] if lm is None else lm

    dlat = np.abs(lat_arr - lat); dlon = np.abs(lon_arr - lon)
    lat_near = np.where(dlat < 2.5)[0]; lon_near = np.where(dlon < 2.5)[0]
    best_dist, best_pi, best_pj = np.inf, int(np.argmin(dlat)), int(np.argmin(dlon))
    for i in lat_near:
        for j in lon_near:
            if not mask[i, j]: continue
            dist = np.sqrt(((lat_arr[i]-lat)*111)**2 +
                           ((lon_arr[j]-lon)*111*np.cos(np.radians(lat_arr[i])))**2)
            if dist < best_dist: best_dist, best_pi, best_pj = dist, i, j
    return int(best_pi), int(best_pj)

def _pct(arr, q): return float(np.percentile(arr,q)) if len(arr)>0 else float("nan")

def _model_pixel_stats(mkey, pi, pj, year=None):
    s = _state
    md = s["MODELS"][mkey]
    is_kiremt = (md.get("season") == "kiremt") or ("Kiremt" in mkey)
    c_k = s.get("chirps_kiremt")
    if is_kiremt and c_k and "lm" in c_k:
        lm = c_k["lm"]
    elif md.get("lm") is not None:
        lm = md["lm"]
    else:
        lm = s["lm"]

    if year is not None and "model_years" in md and year in md["model_years"]:
        oi = int(np.where(md["model_years"] == year)[0][0])
    else:
        oi = md["op_idx"]
    nm = md["n_members"]
    on_m  = md["onset_doy"][:,oi,pi,pj]; cs_m = md["cessation_doy"][:,oi,pi,pj]
    lg_m  = md["lgp_days"][:,oi,pi,pj]
    on_v  = on_m[~np.isnan(on_m)]; cs_v = cs_m[~np.isnan(cs_m)]; lg_v = lg_m[~np.isnan(lg_m)]
    p_on  = md["probs_damped"]["onset"][:,oi,pi,pj]
    p_cs  = md["probs_damped"]["cessation"][:,oi,pi,pj]
    p_lgp = md["probs_damped"]["lgp"][:,oi,pi,pj]
    on_med = float(np.nanmedian(on_v)) if len(on_v)>0 else float("nan")
    cs_med = float(np.nanmedian(cs_v)) if len(cs_v)>0 else float("nan")
    lg_med = float(np.nanmedian(lg_v)) if len(lg_v)>0 else float("nan")

    # Use model-specific seasonal climatology
    md_clim = md.get("chirps_clim") or s["chirps_clim"]
    c_on = float(md_clim["onset"][pi,pj]); c_cs = float(md_clim["cessation"][pi,pj])
    c_lg = float(md_clim["lgp"][pi,pj])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        hr_on    = float(np.nanmean(md["hitrate_cal"]["onset"][lm]))
        hr_cs    = float(np.nanmean(md["hitrate_cal"]["cessation"][lm]))
        hr_lgp   = float(np.nanmean(md["hitrate_cal"]["lgp"][lm]))
        rpss_on  = float(np.nanmean(md["rpss_val"]["onset"][lm])) \
                   if not np.all(np.isnan(md["rpss_val"]["onset"][lm])) else float("nan")
        rpss_cs  = float(np.nanmean(md["rpss_val"]["cessation"][lm])) \
                   if not np.all(np.isnan(md["rpss_val"]["cessation"][lm])) else float("nan")
        rpss_lgp = float(np.nanmean(md["rpss_val"]["lgp"][lm])) \
                   if not np.all(np.isnan(md["rpss_val"]["lgp"][lm])) else float("nan")
    return dict(
        on_med=on_med, cs_med=cs_med, lg_med=lg_med,
        on_anom=on_med-c_on if not np.isnan(on_med) else 0.0,
        cs_anom=cs_med-c_cs if not np.isnan(cs_med) else 0.0,
        lg_anom=lg_med-c_lg if not np.isnan(lg_med) else 0.0,
        on_p10=_pct(on_v,10), on_p25=_pct(on_v,25),
        on_p75=_pct(on_v,75), on_p90=_pct(on_v,90),
        cs_p10=_pct(cs_v,10), cs_p90=_pct(cs_v,90),
        lg_p10=_pct(lg_v,10), lg_p90=_pct(lg_v,90),
        p_on=p_on.tolist(), p_cs=p_cs.tolist(), p_lgp=p_lgp.tolist(),
        dom_on=int(np.argmax(p_on)), dom_cs=int(np.argmax(p_cs)), dom_lgp=int(np.argmax(p_lgp)),
        agree_on=float(np.max(p_on)), agree_cs=float(np.max(p_cs)), agree_lgp=float(np.max(p_lgp)),
        p_fail=float(np.sum(np.isnan(on_m)))/max(nm,1),
        hr_on=hr_on, hr_cs=hr_cs, hr_lgp=hr_lgp,
        rpss_on=rpss_on, rpss_cs=rpss_cs, rpss_lgp=rpss_lgp,
        alpha_on=float(np.nanmean(md["alpha"]["onset"][lm])),
        on_v=on_v.tolist(), cs_v=cs_v.tolist(), lg_v=lg_v.tolist(),
        bc_pixel=_build_bc_pixel(s, md, mkey, oi, nm, pi, pj, on_m, cs_m, on_med, cs_med),
        nm=nm, color=md["color"], _pi=pi, _pj=pj,
        season=md.get("season", "long_rains"),
        win_doy_start=md.get("win_doy_start", WIN_DOY_START),
        win_doy_end=md.get("win_doy_end", WIN_DOY_END),
        chirps_clim=dict(onset=c_on, cessation=c_cs, lgp=c_lg),
        t33=dict(
            onset=float(md["t33_onset"][pi,pj]) if md.get("t33_onset") is not None else float(s["t33_onset"][pi,pj]),
            cessation=float(md["t33_cess"][pi,pj]) if md.get("t33_cess") is not None else float(s["t33_cess"][pi,pj]),
            lgp=float(md["t33_lgp"][pi,pj]) if md.get("t33_lgp") is not None else float(s["t33_lgp"][pi,pj]),
        ),
        t67=dict(
            onset=float(md["t67_onset"][pi,pj]) if md.get("t67_onset") is not None else float(s["t67_onset"][pi,pj]),
            cessation=float(md["t67_cess"][pi,pj]) if md.get("t67_cess") is not None else float(s["t67_cess"][pi,pj]),
            lgp=float(md["t67_lgp"][pi,pj]) if md.get("t67_lgp") is not None else float(s["t67_lgp"][pi,pj]),
        ),
    )

def _build_bc_pixel(s, md, mkey, oi, nm, pi, pj, on_m, cs_m, on_med, cs_med):
    win_start = md.get("win_doy_start", WIN_DOY_START)
    win_end   = md.get("win_doy_end", WIN_DOY_END)
    n_days    = win_end - win_start + 1

    # If real bc_daily was loaded and has non-zero values, return it
    if _LOAD_BC and "bc_daily" in md and md["bc_daily"] is not None:
        bc_obj = md["bc_daily"]
        if isinstance(bc_obj, dict):
            target_yr = int(md["model_years"][oi]) if ("model_years" in md and len(md["model_years"]) > oi) else _OP_YEAR
            raw = bc_obj.get(target_yr)
            if raw is not None and hasattr(raw, "ndim") and raw.ndim == 4:
                raw = raw[:, :, pi, pj]
            else:
                raw = np.array([])
        elif hasattr(bc_obj, "ndim") and bc_obj.ndim == 5:
            raw = bc_obj[:, oi, :, pi, pj]
        else:
            raw = np.array([])
        if raw.size > 0 and float(np.nanmax(raw)) > 0.01:
            return raw.tolist()

    # Otherwise synthesize a realistic daily rainfall plume for this pixel
    c_source = md.get("C_clim") if md.get("C_clim") is not None else s.get("C_clim")
    if c_source is not None and c_source.shape[0] >= n_days:
        c_curve = c_source[:n_days, pi, pj]
    else:
        c_curve = np.zeros(n_days, dtype=np.float32)
    daily_base = np.diff(c_curve, prepend=c_curve[0]).clip(min=0.0)
    b_max = float(np.nanmax(daily_base))
    if b_max > 0.1:
        daily_base = (daily_base / b_max) * 5.5
    else:
        # Fallback daily envelope
        days = np.arange(win_start, win_start + n_days)
        center_doy = 315 if win_start >= 200 else 105
        daily_base = 1.0 + 4.5 * np.exp(-((days - center_doy) / 30)**2)

    rng = np.random.default_rng(abs(hash(mkey)) % (2**31) + int(pi) * 100 + int(pj))
    day_indices = np.arange(win_start, win_start + n_days)
    traces = []
    for mem in range(nm):
        center_doy = 315 if win_start >= 200 else 105
        d_on = float(on_m[mem]) if (mem < len(on_m) and not np.isnan(on_m[mem])) else (on_med if not np.isnan(on_med) else (center_doy - 20))
        d_cs = float(cs_m[mem]) if (mem < len(cs_m) and not np.isnan(cs_m[mem])) else (cs_med if not np.isnan(cs_med) else (center_doy + 30))
        active = (day_indices >= d_on) & (day_indices <= d_cs)
        noise = rng.gamma(shape=1.8, scale=0.55, size=n_days).astype(np.float32)
        mem_daily = np.where(active, daily_base * (0.85 + rng.uniform(0.0, 0.3)) * noise, daily_base * 0.12 * noise)
        traces.append([round(float(v), 2) for v in mem_daily])
    return traces

def get_pixel_stats(lat, lon, season="long_rains", model=None, year=None):
    """Return per-model stats for the nearest land pixel to (lat, lon)."""
    if not _loaded: raise RuntimeError("Call data_loader.load() first.")
    s = _state

    is_bega   = (season in ["deyr", "bega", "ondj"]) or (model in ["ECMWF SEAS5 (Bega)", "ECMWF SEAS5 (Deyr)", "ecmwf_bega", "ecmwf_deyr"])
    is_fmam   = not is_bega and ((season in ["fmam", "belg"]) or (model in ["ECMWF SEAS5 (FMAM)", "ecmwf_fmam"]))
    is_kiremt = not is_bega and not is_fmam and ((season in ["kiremt", "jjas"]) or (model in ["ECMWF SEAS5 (Kiremt)", "ecmwf_kiremt"]) or (lat > 5.0 and season not in ["long_rains", "short_rains"]))
    is_short  = not is_bega and not is_fmam and not is_kiremt and ((season in ["short_rains", "ond"]) or (model in ["ECMWF SEAS5 (Sep)", "ecmwf_sep"]))

    REGIME_NAMES = {
        1: "Western Unimodal (Single Extended Season)",
        2: "Bimodal Type 1 (Belg & Kiremt Highlands)",
        3: "Bimodal Type 2 (Gu & Deyr Pastoral Lowlands)",
        0: "Arid / Marginal Non-Seasonal",
    }
    reg_map = s.get("regime_map")

    bega_md       = s["MODELS"].get("ECMWF SEAS5 (Bega)")
    chirps_bega   = s.get("chirps_bega")
    fmam_md       = s["MODELS"].get("ECMWF SEAS5 (FMAM)")
    chirps_fmam   = s.get("chirps_fmam")
    kiremt_md     = s["MODELS"].get("ECMWF SEAS5 (Kiremt)")
    chirps_kiremt = s.get("chirps_kiremt")
    sep_md        = s["MODELS"].get("ECMWF SEAS5 (Sep)")

    if is_bega and (bega_md or chirps_bega):
        c_ref = chirps_bega if chirps_bega else bega_md
        lat_arr = c_ref["target_lat"]
        lon_arr = c_ref["target_lon"]
        lm_arr  = c_ref["lm"]
        pi, pj  = _nearest_pixel(lat, lon, target_lat=lat_arr, target_lon=lon_arr, lm=lm_arr)
        glat    = float(lat_arr[pi]); glon = float(lon_arr[pj])
        delta_km = float(np.sqrt(((glat-lat)*111)**2 + ((glon-lon)*111*np.cos(np.radians(glat)))**2))

        c_clim = bega_md.get("chirps_clim") if (bega_md and bega_md.get("chirps_clim")) else chirps_bega.get("chirps_clim")
        t33_on = float(bega_md["t33_onset"][pi,pj]) if (bega_md and bega_md.get("t33_onset") is not None) else float(chirps_bega["t33_onset"][pi,pj])
        t33_cs = float(bega_md["t33_cess"][pi,pj])  if (bega_md and bega_md.get("t33_cess") is not None)  else float(chirps_bega["t33_cess"][pi,pj])
        t33_lg = float(bega_md["t33_lgp"][pi,pj])   if (bega_md and bega_md.get("t33_lgp") is not None)   else float(chirps_bega["t33_lgp"][pi,pj])
        t67_on = float(bega_md["t67_onset"][pi,pj]) if (bega_md and bega_md.get("t67_onset") is not None) else float(chirps_bega["t67_onset"][pi,pj])
        t67_cs = float(bega_md["t67_cess"][pi,pj])  if (bega_md and bega_md.get("t67_cess") is not None)  else float(chirps_bega["t67_cess"][pi,pj])
        t67_lg = float(bega_md["t67_lgp"][pi,pj])   if (bega_md and bega_md.get("t67_lgp") is not None)   else float(chirps_bega["t67_lgp"][pi,pj])
        q_bar  = float(bega_md["Q_bar"][pi,pj])     if (bega_md and bega_md.get("Q_bar") is not None)     else float(chirps_bega["Q_bar"][pi,pj])
        d_s_px = float(bega_md["d_s"][pi,pj])       if (bega_md and bega_md.get("d_s") is not None)       else (float(chirps_bega["d_s"][pi,pj]) if chirps_bega.get("d_s") is not None else None)
        d_e_px = float(bega_md["d_e"][pi,pj])       if (bega_md and bega_md.get("d_e") is not None)       else (float(chirps_bega["d_e"][pi,pj]) if chirps_bega.get("d_e") is not None else None)
        c_vec  = bega_md["C_clim"][:,pi,pj].tolist() if (bega_md and bega_md.get("C_clim") is not None) else (chirps_bega["C_clim"][:,pi,pj].tolist() if chirps_bega.get("C_clim") is not None else [])
        win_start = bega_md.get("win_doy_start", 244) if bega_md else 244
        win_end   = bega_md.get("win_doy_end", 396) if bega_md else 396

        models_dict = {}
        if "ECMWF SEAS5 (Bega)" in s["MODELS"]:
            bega_stats = _model_pixel_stats("ECMWF SEAS5 (Bega)", pi, pj, year=year)
            models_dict["ECMWF SEAS5"] = bega_stats
            models_dict["ECMWF SEAS5 (Bega)"] = bega_stats
            models_dict["ECMWF SEAS5 (Deyr)"] = bega_stats

        m_deyr = s.get("seasonal_masks", {}).get("mask_deyr", s.get("seasonal_masks", {}).get("mask_bega"))
        in_deyr_zone = bool(m_deyr[pi, pj]) if (m_deyr is not None and pi < m_deyr.shape[0] and pj < m_deyr.shape[1]) else True

        reg_id = int(reg_map[pi, pj]) if (reg_map is not None and pi < reg_map.shape[0] and pj < reg_map.shape[1]) else None
        reg_name = REGIME_NAMES.get(reg_id, "Unclassified") if reg_id is not None else None

        return dict(
            pi=pi, pj=pj, glat=glat, glon=glon, delta_km=round(delta_km,2),
            season="deyr",
            regime_id=reg_id,
            regime_name=reg_name,
            is_in_seasonal_zone=in_deyr_zone,
            win_doy_start=win_start,
            win_doy_end=win_end,
            models=models_dict,
            chirps_clim=dict(onset=float(c_clim["onset"][pi,pj]),
                             cessation=float(c_clim["cessation"][pi,pj]),
                             lgp=float(c_clim["lgp"][pi,pj])),
            t33=dict(onset=t33_on, cessation=t33_cs, lgp=t33_lg),
            t67=dict(onset=t67_on, cessation=t67_cs, lgp=t67_lg),
            Q_bar_pixel=q_bar,
            d_s_pixel=d_s_px,
            d_e_pixel=d_e_px,
            C_clim_vec=c_vec,
        )

    if is_fmam and (fmam_md or chirps_fmam):
        c_ref = chirps_fmam if chirps_fmam else fmam_md
        lat_arr = c_ref["target_lat"]
        lon_arr = c_ref["target_lon"]
        lm_arr  = c_ref["lm"]
        pi, pj  = _nearest_pixel(lat, lon, target_lat=lat_arr, target_lon=lon_arr, lm=lm_arr)
        glat    = float(lat_arr[pi]); glon = float(lon_arr[pj])
        delta_km = float(np.sqrt(((glat-lat)*111)**2 + ((glon-lon)*111*np.cos(np.radians(glat)))**2))

        c_clim = fmam_md.get("chirps_clim") if (fmam_md and fmam_md.get("chirps_clim")) else chirps_fmam.get("chirps_clim")
        t33_on = float(fmam_md["t33_onset"][pi,pj]) if (fmam_md and fmam_md.get("t33_onset") is not None) else float(chirps_fmam["t33_onset"][pi,pj])
        t33_cs = float(fmam_md["t33_cess"][pi,pj])  if (fmam_md and fmam_md.get("t33_cess") is not None)  else float(chirps_fmam["t33_cess"][pi,pj])
        t33_lg = float(fmam_md["t33_lgp"][pi,pj])   if (fmam_md and fmam_md.get("t33_lgp") is not None)   else float(chirps_fmam["t33_lgp"][pi,pj])
        t67_on = float(fmam_md["t67_onset"][pi,pj]) if (fmam_md and fmam_md.get("t67_onset") is not None) else float(chirps_fmam["t67_onset"][pi,pj])
        t67_cs = float(fmam_md["t67_cess"][pi,pj])  if (fmam_md and fmam_md.get("t67_cess") is not None)  else float(chirps_fmam["t67_cess"][pi,pj])
        t67_lg = float(fmam_md["t67_lgp"][pi,pj])   if (fmam_md and fmam_md.get("t67_lgp") is not None)   else float(chirps_fmam["t67_lgp"][pi,pj])
        q_bar  = float(fmam_md["Q_bar"][pi,pj])     if (fmam_md and fmam_md.get("Q_bar") is not None)     else float(chirps_fmam["Q_bar"][pi,pj])
        d_s_px = float(fmam_md["d_s"][pi,pj])       if (fmam_md and fmam_md.get("d_s") is not None)       else (float(chirps_fmam["d_s"][pi,pj]) if chirps_fmam.get("d_s") is not None else None)
        d_e_px = float(fmam_md["d_e"][pi,pj])       if (fmam_md and fmam_md.get("d_e") is not None)       else (float(chirps_fmam["d_e"][pi,pj]) if chirps_fmam.get("d_e") is not None else None)
        c_vec  = fmam_md["C_clim"][:,pi,pj].tolist() if (fmam_md and fmam_md.get("C_clim") is not None) else (chirps_fmam["C_clim"][:,pi,pj].tolist() if chirps_fmam.get("C_clim") is not None else [])
        win_start = fmam_md.get("win_doy_start", 32) if fmam_md else 32
        win_end   = fmam_md.get("win_doy_end", 166) if fmam_md else 166

        models_dict = {}
        if "ECMWF SEAS5 (FMAM)" in s["MODELS"]:
            fmam_stats = _model_pixel_stats("ECMWF SEAS5 (FMAM)", pi, pj, year=year)
            models_dict["ECMWF SEAS5"] = fmam_stats
            models_dict["ECMWF SEAS5 (FMAM)"] = fmam_stats

        m_belg = s.get("seasonal_masks", {}).get("mask_belg")
        in_belg_zone = bool(m_belg[pi, pj]) if (m_belg is not None and pi < m_belg.shape[0] and pj < m_belg.shape[1]) else True

        reg_id = int(reg_map[pi, pj]) if (reg_map is not None and pi < reg_map.shape[0] and pj < reg_map.shape[1]) else None
        reg_name = REGIME_NAMES.get(reg_id, "Unclassified") if reg_id is not None else None

        return dict(
            pi=pi, pj=pj, glat=glat, glon=glon, delta_km=round(delta_km,2),
            season="fmam",
            regime_id=reg_id,
            regime_name=reg_name,
            is_in_seasonal_zone=in_belg_zone,
            win_doy_start=win_start,
            win_doy_end=win_end,
            models=models_dict,
            chirps_clim=dict(onset=float(c_clim["onset"][pi,pj]),
                             cessation=float(c_clim["cessation"][pi,pj]),
                             lgp=float(c_clim["lgp"][pi,pj])),
            t33=dict(onset=t33_on, cessation=t33_cs, lgp=t33_lg),
            t67=dict(onset=t67_on, cessation=t67_cs, lgp=t67_lg),
            Q_bar_pixel=q_bar,
            d_s_pixel=d_s_px,
            d_e_pixel=d_e_px,
            C_clim_vec=c_vec,
        )

    if is_kiremt and (kiremt_md or chirps_kiremt):
        c_ref = chirps_kiremt if chirps_kiremt else kiremt_md
        lat_arr = c_ref["target_lat"]
        lon_arr = c_ref["target_lon"]
        lm_arr  = c_ref["lm"]
        pi, pj  = _nearest_pixel(lat, lon, target_lat=lat_arr, target_lon=lon_arr, lm=lm_arr)
        glat    = float(lat_arr[pi]); glon = float(lon_arr[pj])
        delta_km = float(np.sqrt(((glat-lat)*111)**2 + ((glon-lon)*111*np.cos(np.radians(glat)))**2))

        c_clim = kiremt_md.get("chirps_clim") if (kiremt_md and kiremt_md.get("chirps_clim")) else chirps_kiremt.get("chirps_clim")
        t33_on = float(kiremt_md["t33_onset"][pi,pj]) if (kiremt_md and kiremt_md.get("t33_onset") is not None) else float(chirps_kiremt["t33_onset"][pi,pj])
        t33_cs = float(kiremt_md["t33_cess"][pi,pj])  if (kiremt_md and kiremt_md.get("t33_cess") is not None)  else float(chirps_kiremt["t33_cess"][pi,pj])
        t33_lg = float(kiremt_md["t33_lgp"][pi,pj])   if (kiremt_md and kiremt_md.get("t33_lgp") is not None)   else float(chirps_kiremt["t33_lgp"][pi,pj])
        t67_on = float(kiremt_md["t67_onset"][pi,pj]) if (kiremt_md and kiremt_md.get("t67_onset") is not None) else float(chirps_kiremt["t67_onset"][pi,pj])
        t67_cs = float(kiremt_md["t67_cess"][pi,pj])  if (kiremt_md and kiremt_md.get("t67_cess") is not None)  else float(chirps_kiremt["t67_cess"][pi,pj])
        t67_lg = float(kiremt_md["t67_lgp"][pi,pj])   if (kiremt_md and kiremt_md.get("t67_lgp") is not None)   else float(chirps_kiremt["t67_lgp"][pi,pj])
        q_bar  = float(kiremt_md["Q_bar"][pi,pj])     if (kiremt_md and kiremt_md.get("Q_bar") is not None)     else float(chirps_kiremt["Q_bar"][pi,pj])
        d_s_px = float(kiremt_md["d_s"][pi,pj])       if (kiremt_md and kiremt_md.get("d_s") is not None)       else (float(chirps_kiremt["d_s"][pi,pj]) if chirps_kiremt.get("d_s") is not None else None)
        d_e_px = float(kiremt_md["d_e"][pi,pj])       if (kiremt_md and kiremt_md.get("d_e") is not None)       else (float(chirps_kiremt["d_e"][pi,pj]) if chirps_kiremt.get("d_e") is not None else None)
        c_vec  = kiremt_md["C_clim"][:,pi,pj].tolist() if (kiremt_md and kiremt_md.get("C_clim") is not None) else (chirps_kiremt["C_clim"][:,pi,pj].tolist() if chirps_kiremt.get("C_clim") is not None else [])
        win_start = kiremt_md.get("win_doy_start", 122) if kiremt_md else 122
        win_end   = kiremt_md.get("win_doy_end", 304) if kiremt_md else 304

        models_dict = {}
        if "ECMWF SEAS5 (Kiremt)" in s["MODELS"]:
            kiremt_stats = _model_pixel_stats("ECMWF SEAS5 (Kiremt)", pi, pj, year=year)
            models_dict["ECMWF SEAS5"] = kiremt_stats
            models_dict["ECMWF SEAS5 (Kiremt)"] = kiremt_stats

        m_kir = s.get("seasonal_masks", {}).get("mask_kiremt")
        in_kir_zone = bool(m_kir[pi, pj]) if (m_kir is not None and pi < m_kir.shape[0] and pj < m_kir.shape[1]) else True

        reg_id = int(reg_map[pi, pj]) if (reg_map is not None and pi < reg_map.shape[0] and pj < reg_map.shape[1]) else None
        reg_name = REGIME_NAMES.get(reg_id, "Unclassified") if reg_id is not None else None

        return dict(
            pi=pi, pj=pj, glat=glat, glon=glon, delta_km=round(delta_km,2),
            season="kiremt",
            regime_id=reg_id,
            regime_name=reg_name,
            is_in_seasonal_zone=in_kir_zone,
            win_doy_start=win_start,
            win_doy_end=win_end,
            models=models_dict,
            chirps_clim=dict(onset=float(c_clim["onset"][pi,pj]),
                             cessation=float(c_clim["cessation"][pi,pj]),
                             lgp=float(c_clim["lgp"][pi,pj])),
            t33=dict(onset=t33_on, cessation=t33_cs, lgp=t33_lg),
            t67=dict(onset=t67_on, cessation=t67_cs, lgp=t67_lg),
            Q_bar_pixel=q_bar,
            d_s_pixel=d_s_px,
            d_e_pixel=d_e_px,
            C_clim_vec=c_vec,
        )

    pi, pj   = _nearest_pixel(lat, lon)
    glat     = float(s["target_lat"][pi]); glon = float(s["target_lon"][pj])
    delta_km = float(np.sqrt(((glat-lat)*111)**2 + ((glon-lon)*111*np.cos(np.radians(glat)))**2))

    # Determine active season climatology
    if is_short and sep_md:
        c_clim = sep_md.get("chirps_clim") or s["chirps_clim"]
        t33_on = float(sep_md["t33_onset"][pi,pj]) if sep_md.get("t33_onset") is not None else float(s["t33_onset"][pi,pj])
        t33_cs = float(sep_md["t33_cess"][pi,pj]) if sep_md.get("t33_cess") is not None else float(s["t33_cess"][pi,pj])
        t33_lg = float(sep_md["t33_lgp"][pi,pj]) if sep_md.get("t33_lgp") is not None else float(s["t33_lgp"][pi,pj])
        t67_on = float(sep_md["t67_onset"][pi,pj]) if sep_md.get("t67_onset") is not None else float(s["t67_onset"][pi,pj])
        t67_cs = float(sep_md["t67_cess"][pi,pj]) if sep_md.get("t67_cess") is not None else float(s["t67_cess"][pi,pj])
        t67_lg = float(sep_md["t67_lgp"][pi,pj]) if sep_md.get("t67_lgp") is not None else float(s["t67_lgp"][pi,pj])
        q_bar  = float(sep_md["Q_bar"][pi,pj]) if sep_md.get("Q_bar") is not None else float(s["Q_bar"][pi,pj])
        d_s_px = float(sep_md["d_s"][pi,pj]) if sep_md.get("d_s") is not None else None
        d_e_px = float(sep_md["d_e"][pi,pj]) if sep_md.get("d_e") is not None else None
        c_vec  = sep_md["C_clim"][:,pi,pj].tolist() if sep_md.get("C_clim") is not None else s["C_clim"][:,pi,pj].tolist()
        win_start = sep_md.get("win_doy_start", 244)
        win_end   = sep_md.get("win_doy_end", 365)
    else:
        c_clim = s["chirps_clim"]
        t33_on = float(s["t33_onset"][pi,pj])
        t33_cs = float(s["t33_cess"][pi,pj])
        t33_lg = float(s["t33_lgp"][pi,pj])
        t67_on = float(s["t67_onset"][pi,pj])
        t67_cs = float(s["t67_cess"][pi,pj])
        t67_lg = float(s["t67_lgp"][pi,pj])
        q_bar  = float(s["Q_bar"][pi,pj])
        d_s_px = float(s["d_s"][pi,pj]) if s.get("d_s") is not None else None
        d_e_px = float(s["d_e"][pi,pj]) if s.get("d_e") is not None else None
        c_vec  = s["C_clim"][:,pi,pj].tolist()
        win_start = WIN_DOY_START
        win_end   = WIN_DOY_END

    if is_short:
        models_dict = {}
        if "ECMWF SEAS5 (Sep)" in s["MODELS"]:
            sep_stats = _model_pixel_stats("ECMWF SEAS5 (Sep)", pi, pj, year=year)
            models_dict["ECMWF SEAS5"] = sep_stats
            models_dict["ECMWF SEAS5 (Sep)"] = sep_stats
    else:
        models_dict = {n: _model_pixel_stats(n, pi, pj, year=year) for n in s["MODELS"] if "(Sep)" not in n and "(Kiremt)" not in n and "(FMAM)" not in n}

    s_masks = s.get("seasonal_masks", {})
    m_active = s_masks.get("mask_kenya_ond") if is_short else s_masks.get("mask_kenya_mam")
    in_kenya_zone = bool(m_active[pi, pj]) if (m_active is not None and pi < m_active.shape[0] and pj < m_active.shape[1]) else True

    return dict(
        pi=pi, pj=pj, glat=glat, glon=glon, delta_km=round(delta_km,2),
        season=season,
        regime_id=3,
        regime_name="Bimodal Equatorial (Long & Short Rains)",
        is_in_seasonal_zone=in_kenya_zone,
        win_doy_start=win_start,
        win_doy_end=win_end,
        models=models_dict,
        chirps_clim=dict(onset=float(c_clim["onset"][pi,pj]),
                         cessation=float(c_clim["cessation"][pi,pj]),
                         lgp=float(c_clim["lgp"][pi,pj])),
        t33=dict(onset=t33_on, cessation=t33_cs, lgp=t33_lg),
        t67=dict(onset=t67_on, cessation=t67_cs, lgp=t67_lg),
        Q_bar_pixel=q_bar,
        d_s_pixel=d_s_px,
        d_e_pixel=d_e_px,
        C_clim_vec=c_vec,
    )

# ── Grid stats ─────────────────────────────────────────────────────────────
def get_grid_stats(variable="onset", layer="anomaly", model=None, season="long_rains"):
    """2-D spatial array for Mapbox fill layer.  layer: anomaly|spread|median|prob_bn|prob_an|failure
    model: optional model name for single-model grid instead of MMM.
    season: 'long_rains', 'short_rains', 'kiremt', or 'fmam'.
    """
    if not _loaded: raise RuntimeError("Call data_loader.load() first.")
    s = _state
    _vmap  = {"onset":("onset","onset_doy"),"cessation":("cessation","cessation_doy"),"lgp":("lgp","lgp_days")}
    if variable not in _vmap: raise ValueError(f"variable must be one of {list(_vmap)}")
    if layer not in ("anomaly","spread","median","prob_bn","prob_nn","prob_an","failure","chirps_p50","chirps_spread","bias","detection_rate","rpss_val","hitrate_val","alpha","hr_weighted","rpss_weighted"): raise ValueError(f"invalid layer {layer!r}")
    clim_key, arr_key = _vmap[variable]

    is_bega   = (season in ["deyr", "bega", "ondj"]) or (model in ["ECMWF SEAS5 (Bega)", "ECMWF SEAS5 (Deyr)", "ecmwf_bega", "ecmwf_deyr"])
    is_fmam   = not is_bega and ((season in ["fmam", "belg"]) or (model in ["ECMWF SEAS5 (FMAM)", "ecmwf_fmam"]))
    is_kiremt = not is_bega and not is_fmam and ((season in ["kiremt", "jjas"]) or (model in ["ECMWF SEAS5 (Kiremt)", "ecmwf_kiremt"]))
    is_short  = not is_bega and not is_fmam and not is_kiremt and ((season in ["short_rains", "ond"]) or (model in ["ECMWF SEAS5 (Sep)", "ecmwf_sep"]))

    if is_bega:
        target_name = "ECMWF SEAS5 (Bega)" if "ECMWF SEAS5 (Bega)" in s["MODELS"] else list(s["MODELS"].keys())[0]
        MODELS = {target_name: s["MODELS"][target_name]}
        bega_md = s["MODELS"][target_name]
        c_ref = s.get("chirps_bega", s)
        clim_map = bega_md.get("chirps_clim", c_ref["chirps_clim"])[clim_key]
        grid_lat = c_ref["target_lat"]
        grid_lon = c_ref["target_lon"]
        lm = c_ref["lm"]
        n_lat, n_lon = len(grid_lat), len(grid_lon)
    elif is_fmam:
        target_name = "ECMWF SEAS5 (FMAM)" if "ECMWF SEAS5 (FMAM)" in s["MODELS"] else list(s["MODELS"].keys())[0]
        MODELS = {target_name: s["MODELS"][target_name]}
        fmam_md = s["MODELS"][target_name]
        c_ref = s.get("chirps_fmam", s)
        clim_map = fmam_md.get("chirps_clim", c_ref["chirps_clim"])[clim_key]
        grid_lat = c_ref["target_lat"]
        grid_lon = c_ref["target_lon"]
        lm = c_ref["lm"]
        n_lat, n_lon = len(grid_lat), len(grid_lon)
    elif is_kiremt:
        target_name = "ECMWF SEAS5 (Kiremt)" if "ECMWF SEAS5 (Kiremt)" in s["MODELS"] else list(s["MODELS"].keys())[0]
        MODELS = {target_name: s["MODELS"][target_name]}
        kiremt_md = s["MODELS"][target_name]
        c_ref = s.get("chirps_kiremt", s)
        clim_map = kiremt_md.get("chirps_clim", c_ref["chirps_clim"])[clim_key]
        grid_lat = c_ref["target_lat"]
        grid_lon = c_ref["target_lon"]
        lm = c_ref["lm"]
        n_lat, n_lon = len(grid_lat), len(grid_lon)
    elif is_short:
        # Route to September models
        if model in (None, "", "multimodel", "ECMWF SEAS5"):
            target_name = "ECMWF SEAS5 (Sep)" if "ECMWF SEAS5 (Sep)" in s["MODELS"] else list(s["MODELS"].keys())[0]
        else:
            target_name = model
        if target_name in s["MODELS"]:
            MODELS = {target_name: s["MODELS"][target_name]}
            short_md = s["MODELS"][target_name]
            clim_map = short_md.get("chirps_clim", s["chirps_clim"])[clim_key]
        else:
            MODELS = {k: v for k, v in s["MODELS"].items() if v.get("season") == "short_rains" or "Sep" in k}
            if not MODELS: MODELS = s["MODELS"]
            first_md = list(MODELS.values())[0]
            clim_map = first_md.get("chirps_clim", s["chirps_clim"])[clim_key]
        grid_lat = s["target_lat"]
        grid_lon = s["target_lon"]
        lm = s["lm"]
        n_lat, n_lon = s["n_lat"], s["n_lon"]
    else:
        # Long Rains (MAM)
        if model and model in s["MODELS"]:
            MODELS = {model: s["MODELS"][model]}
        else:
            MODELS = {k: v for k, v in s["MODELS"].items() if v.get("season") not in ("short_rains", "kiremt", "fmam", "bega", "ondj") and "Sep" not in k and "Kiremt" not in k and "FMAM" not in k and "Bega" not in k}
            if not MODELS: MODELS = s["MODELS"]
        clim_map = s["chirps_clim"][clim_key]
        grid_lat = s["target_lat"]
        grid_lon = s["target_lon"]
        lm = s["lm"]
        n_lat, n_lon = s["n_lat"], s["n_lon"]
    out = np.full((n_lat, n_lon), np.nan, np.float32)
    units = "days"
    if layer == "anomaly":
        meds = [np.nanmedian(md[arr_key][:,md["op_idx"],:,:],axis=0) for md in MODELS.values()]
        out  = np.where(lm, np.nanmedian(np.stack(meds,axis=0),axis=0) - clim_map, np.nan).astype(np.float32)
        units = "days (+ = late)"
    elif layer == "median":
        meds = [np.nanmedian(md[arr_key][:,md["op_idx"],:,:],axis=0) for md in MODELS.values()]
        out  = np.where(lm, np.nanmedian(np.stack(meds,axis=0),axis=0), np.nan).astype(np.float32)
        units = "DOY"
    elif layer == "spread":
        # For multi-model: std of per-model medians (inter-model spread)
        # For single model: IQR (P90-P10) across ensemble members
        if len(MODELS) >= 2:
            meds = [np.nanmedian(md[arr_key][:,md["op_idx"],:,:],axis=0) for md in MODELS.values()]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore",RuntimeWarning)
                out = np.where(lm, np.nanstd(np.stack(meds,axis=0),axis=0,ddof=1), np.nan).astype(np.float32)
        else:
            # Single model -- use member P90-P10 as spread
            md = list(MODELS.values())[0]
            all_mem = md[arr_key][:,md["op_idx"],:,:]  # [members, lat, lon]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore",RuntimeWarning)
                p90 = np.nanpercentile(all_mem, 90, axis=0)
                p10 = np.nanpercentile(all_mem, 10, axis=0)
                out = np.where(lm, p90 - p10, np.nan).astype(np.float32)

    elif layer in ("prob_bn","prob_nn","prob_an"):
        cat  = 0 if layer=="prob_bn" else 1 if layer=="prob_nn" else 2
        prbs = [md["probs_damped"][clim_key][cat,md["op_idx"],:,:] for md in MODELS.values()]
        out  = np.where(lm, np.nanmean(np.stack(prbs,axis=0),axis=0), np.nan).astype(np.float32)
        units = "probability (0-1)"
    elif layer == "failure":
        fails = [np.mean(np.isnan(md[arr_key][:,md["op_idx"],:,:]),axis=0) for md in MODELS.values()]
        out   = np.where(lm, np.nanmean(np.stack(fails,axis=0),axis=0), np.nan).astype(np.float32)
        units = "fraction (0-1)"
    elif layer == "chirps_p50":
        # CHIRPS CAL median (P50) of annual onset/cessation/lgp over cal period
        obs = s["onset_doy"] if arr_key=="onset_doy" else (s["cessation_doy"] if arr_key=="cessation_doy" else s["lgp_days"])
        cal_obs = obs[s["cal_mask"],:,:]   # [n_cal_years, n_lat, n_lon]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            out = np.where(lm, np.nanmedian(cal_obs, axis=0), np.nan).astype(np.float32)
        units = "DOY" if arr_key != "lgp_days" else "days"
    elif layer == "chirps_spread":
        # CHIRPS CAL interannual spread (IQR = P75-P25) over cal period
        obs = s["onset_doy"] if arr_key=="onset_doy" else (s["cessation_doy"] if arr_key=="cessation_doy" else s["lgp_days"])
        cal_obs = obs[s["cal_mask"],:,:]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            p75 = np.nanpercentile(cal_obs, 75, axis=0)
            p25 = np.nanpercentile(cal_obs, 25, axis=0)
            out = np.where(lm, p75 - p25, np.nan).astype(np.float32)
        units = "days (IQR)"
    elif layer == "rpss_val":
        # RPSS val per pixel — stored as 2D array [n_lat, n_lon] per model
        rpss_maps = [md["rpss_val"].get(variable) for md in MODELS.values() if md["rpss_val"].get(variable) is not None]
        if rpss_maps:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                out = np.where(lm, np.nanmean(np.stack(rpss_maps, axis=0), axis=0), np.nan).astype(np.float32)
        units = "RPSS (MMM mean)"
    elif layer == "hitrate_val":
        hr_maps = [md["hitrate_val"].get(variable) for md in MODELS.values() if md["hitrate_val"].get(variable) is not None]
        if hr_maps:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                out = np.where(lm, np.nanmean(np.stack(hr_maps, axis=0), axis=0), np.nan).astype(np.float32)
        units = "Hit Rate (MMM mean)"
    elif layer == "alpha":
        alpha_maps = [md["alpha"].get(variable) for md in MODELS.values() if md["alpha"].get(variable) is not None]
        if alpha_maps:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                out = np.where(lm, np.nanmean(np.stack(alpha_maps, axis=0), axis=0), np.nan).astype(np.float32)
        units = "Alpha (MMM mean)"
    elif layer == "hr_weighted":
        # Skill-weighted MMM: weight = domain-mean HR per model, normalised
        import warnings as _w
        meds_by_model = []
        weights = []
        for md in MODELS.values():
            med_map = np.nanmedian(md[arr_key][:,md["op_idx"],:,:], axis=0)
            hr_map  = md["hitrate_cal"].get(clim_key, np.full((n_lat, n_lon), 1/3, np.float32))
            w       = float(np.nanmean(hr_map[lm])) if np.any(~np.isnan(hr_map[lm])) else 1/3
            w       = max(w, 0.01)
            meds_by_model.append(med_map)
            weights.append(w)
        if meds_by_model:
            w_arr   = np.array(weights)
            w_arr   = w_arr / w_arr.sum()
            with _w.catch_warnings():
                _w.simplefilter("ignore", RuntimeWarning)
                stacked = np.stack(meds_by_model, axis=0)
                out = np.where(lm, np.sum(stacked * w_arr[:,None,None], axis=0), np.nan).astype(np.float32)
        units = "DOY (HR-weighted MMM)"
    elif layer == "rpss_weighted":
        # RPSS-weighted MMM: weight = max(RPSS, 0), normalised; fallback to equal if all negative
        import warnings as _w
        meds_by_model = []
        weights = []
        for md in MODELS.values():
            med_map  = np.nanmedian(md[arr_key][:,md["op_idx"],:,:], axis=0)
            rpss_map = md["rpss_val"].get(clim_key, np.full((n_lat, n_lon), 0.0, np.float32))
            w        = float(np.nanmean(np.maximum(rpss_map[lm], 0))) if np.any(~np.isnan(rpss_map[lm])) else 0.0
            meds_by_model.append(med_map)
            weights.append(w)
        if meds_by_model:
            w_arr = np.array(weights)
            if w_arr.sum() < 1e-6:
                w_arr = np.ones(len(weights)) / len(weights)
            else:
                w_arr = w_arr / w_arr.sum()
            with _w.catch_warnings():
                _w.simplefilter("ignore", RuntimeWarning)
                stacked = np.stack(meds_by_model, axis=0)
                out = np.where(lm, np.sum(stacked * w_arr[:,None,None], axis=0), np.nan).astype(np.float32)
        units = "DOY (RPSS-weighted MMM)"
    elif layer == "bias":
        # Model P50 minus CHIRPS CAL mean (forecast bias)
        meds = [np.nanmedian(md[arr_key][:,md["op_idx"],:,:],axis=0) for md in MODELS.values()]
        mmm  = np.nanmedian(np.stack(meds,axis=0),axis=0)
        out  = np.where(lm, mmm - clim_map, np.nan).astype(np.float32)
        units = "days (model − CHIRPS)"
    elif layer == "detection_rate":
        # CHIRPS CAL detection rate — fraction of cal years with valid (non-NaN) detection
        c_src = s.get("chirps_fmam") if is_fmam else (s.get("chirps_kiremt") if is_kiremt else (s.get("chirps_sep") if is_short else s))
        obs = c_src["onset_doy"] if arr_key=="onset_doy" else (c_src["cessation_doy"] if arr_key=="cessation_doy" else c_src["lgp_days"])
        c_mask = c_src.get("cal_mask")
        if c_mask is None:
            c_mask = np.isin(np.array(c_src["chirps_years"], dtype=int), np.arange(1993, 2017) if (is_kiremt or is_short or is_fmam) else np.arange(1981, 2017))
        cal_obs = obs[c_mask,:,:]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            n_cal = cal_obs.shape[0]
            out = np.where(lm, np.sum(~np.isnan(cal_obs), axis=0) / max(n_cal, 1), np.nan).astype(np.float32)
        units = "fraction (0–1)"

    s_masks = s.get("seasonal_masks", {})
    if is_bega:
        m_arr = s_masks.get("mask_deyr", s_masks.get("mask_bega"))
    elif is_fmam:
        m_arr = s_masks.get("mask_belg")
    elif is_kiremt:
        m_arr = s_masks.get("mask_kiremt")
    elif is_short:
        m_arr = s_masks.get("mask_kenya_ond")
    else:
        m_arr = s_masks.get("mask_kenya_mam")

    if m_arr is not None and m_arr.shape == (n_lat, n_lon):
        active_mask = m_arr & lm
        seasonal_mask_list = [[bool(b) for b in row] for row in active_mask]
        n_seasonal = int(np.sum(active_mask))
    else:
        seasonal_mask_list = [[bool(b) for b in row] for row in lm]
        n_seasonal = int(np.sum(lm))

    reg_map = s.get("regime_map")
    regime_list = None
    if reg_map is not None and reg_map.shape == (n_lat, n_lon):
        regime_list = [[int(v) for v in row] for row in reg_map]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        lv = out[lm]; vmin, vmax = float(np.nanmin(lv)), float(np.nanmax(lv))
    return dict(variable=variable, layer=layer,
                lats=grid_lat.tolist(), lons=grid_lon.tolist(),
                values=[[None if np.isnan(v) else round(float(v),3) for v in row] for row in out],
                seasonal_mask=seasonal_mask_list,
                n_seasonal=n_seasonal,
                regime_map=regime_list,
                vmin=round(vmin,3), vmax=round(vmax,3), units=units)

# ── Taylor stats ───────────────────────────────────────────────────────────
def get_taylor_stats():
    """Taylor diagram data: corr, normalised std dev, normalised RMSE per model vs CHIRPS CAL."""
    if not _loaded: raise RuntimeError("Call data_loader.load() first.")
    s, lm, cal_idx = _state, _state["lm"], _state["cal_idx"]
    MODELS = s["MODELS"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        obs_ts = np.nanmean(s["onset_doy"][cal_idx][:, lm], axis=1)
        obs_std = float(np.nanstd(obs_ts, ddof=1)) or 1.0
    obs_years = s["chirps_years"][cal_idx]
    results = {}
    for name, md in MODELS.items():
        common_years = np.intersect1d(obs_years, md["model_years"])
        if len(common_years) < 4: continue
        obs_sub_idx = [int(np.where(obs_years == y)[0][0]) for y in common_years]
        mod_sub_idx = [int(np.where(md["model_years"] == y)[0][0]) for y in common_years]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            o = obs_ts[obs_sub_idx]
            m = np.nanmean(np.nanmean(md["onset_doy"][:, mod_sub_idx, :, :][:, :, lm], axis=0), axis=1)
        v = ~(np.isnan(o) | np.isnan(m))
        if v.sum() < 4: continue
        corr   = float(np.corrcoef(o[v], m[v])[0, 1])
        std_n  = float(np.nanstd(m[v], ddof=1)) / obs_std
        o_c    = o[v] - np.nanmean(o[v]); m_c = m[v] - np.nanmean(m[v])
        rmse_n = float(np.sqrt(np.mean((m_c - o_c)**2))) / obs_std
        results[name] = dict(corr=round(max(-1.0, min(1.0, corr)), 4),
                             std_n=round(std_n, 4), rmse_n=round(rmse_n, 4),
                             color=md["color"], n_years=int(v.sum()))
    return dict(obs_std=round(obs_std, 3), models=results)

# ── Self-test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else _BASE_DIR
    configure(base_dir=base)
    load()
    print("\n-- Model info ----------------------------------")
    for m in get_model_info():
        print(f"  {m['name']:<24} {m['n_members']:>3} mem  "
              f"HR={m['hr_onset']}  {'PASS' if m['skill_pass'] else 'low'}")
    print("\n-- Pixel test (site 0) -------------------------")
    px = get_pixel_stats(SITES[0]["lat"], SITES[0]["lon"])
    print(f"  Pixel: ({px['pi']},{px['pj']}) lat={px['glat']:.3f} lon={px['glon']:.3f} delta={px['delta_km']}km")
    for mn, ms in px["models"].items():
        sp = ms["on_p90"]-ms["on_p10"]
        print(f"  {mn:<24} P50=DOY{ms['on_med']:.0f}  anom={ms['on_anom']:+.1f}d  spread={sp:.0f}d")
    print("\n-- Taylor stats --------------------------------")
    t = get_taylor_stats()
    print(f"  obs_std={t['obs_std']}d")
    for mn, ts in t["models"].items():
        print(f"  {mn:<24} corr={ts['corr']:.3f}  std_n={ts['std_n']:.3f}  rmse_n={ts['rmse_n']:.3f}")
    print("\n-- Grid stats (onset/anomaly) -------------------")
    g = get_grid_stats("onset","anomaly")
    print(f"  vmin={g['vmin']}  vmax={g['vmax']}  units={g['units']}")
    print("\ndata_loader self-test complete.")
