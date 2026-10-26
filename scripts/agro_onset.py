#!/usr/bin/env python3
"""
agro_onset.py
─────────────
Agronomic (planting) onset of the Short Rains — a rule-based alternative to the Dunning onset:

  onset = first day d on/after SEARCH_START with
            rain(d) >= DRY_DAY_MM  and  rain(d .. d+ACC_DAYS-1) >= RAIN_MM            (trigger)
          and no run of >= DRY_SPELL consecutive days with rain < DRY_DAY_MM
          within days d+1 .. d+LOOKAHEAD                                               (no false start)

Defaults: 20 mm in 3 days, dry spell 10 days, lookahead 21 days, dry day < 1 mm, search from 01 Oct.
When the lookahead runs past the end of the data the onset is accepted as *provisional*.

Subcommands
  seasonal  : apply the rule to CHIRPS (1993–2025) and to every member/year of a seasonal output folder
              (ECMWF_bc_daily_all_years.nc), then terciles, calibrated probabilities and skill
              → <seasonal_dir>/agro_onset/
  ens       : 1–15 day outlook from an ECMWF ENS file (fetch_ecmwf_ens.py): daily rain probabilities,
              trigger probabilities, and a composite onset date (ENS days 1–15 + seasonal members after)
              → outputs/ecmwf_ens/ens_outlook_<init>.nc
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "notebook"))
import dunning_lib as dl  # noqa: E402

RULE = dict(rain_mm=20.0, acc_days=3, dry_spell=10, dry_day_mm=1.0, lookahead=21, search_start_doy=274)
NO_ONSET = 400.0          # sentinel DOY for "no onset by 31 Dec" when forming terciles (counts as late)
CAL_YEARS = np.arange(1993, 2017)
VAL_YEARS = np.arange(2017, 2025)
ALPHA_GRID = np.round(np.arange(0.0, 1.01, 0.02), 2)
CHIRPS_PATH = BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"


# ── Core rule ───────────────────────────────────────────────────────────────
def detect(daily, start_idx, rain_mm=20.0, acc_days=3, dry_spell=10, dry_day_mm=1.0, lookahead=21, **_):
    """
    daily : (..., n_days) mm/day; NaN = unknown day (e.g. beyond the observed record).
    Returns (onset_idx, provisional): float index into the day axis (NaN = none), bool.
    Unknown days never trigger, and count as 'not dry' in the dry-spell check (→ provisional).
    """
    x = np.asarray(daily, dtype=np.float32)
    n = x.shape[-1]
    known = np.isfinite(x)
    xz = np.where(known, x, 0.0)
    pad = lookahead + acc_days
    xz = np.concatenate([xz, np.zeros(x.shape[:-1] + (pad,), np.float32)], axis=-1)
    kn = np.concatenate([known, np.zeros(x.shape[:-1] + (pad,), bool)], axis=-1)

    csum = np.concatenate([np.zeros(x.shape[:-1] + (1,), np.float32), np.cumsum(xz, axis=-1)], axis=-1)
    acc = csum[..., acc_days:acc_days + n] - csum[..., :n]                       # rain over d..d+acc-1
    trig = kn[..., :n] & (xz[..., :n] >= dry_day_mm) & (acc >= rain_mm)
    trig[..., :start_idx] = False

    dry = kn & (xz < dry_day_mm)                                                  # unknown days are not dry
    run = np.zeros_like(xz, dtype=np.int16)                                      # dry run length ending at t
    for t in range(xz.shape[-1]):
        run[..., t] = np.where(dry[..., t], (run[..., t - 1] if t else 0) + 1, 0)
    # longest dry run fully inside window d+1 .. d+lookahead
    longest = np.zeros(x.shape[:-1] + (n,), np.int16)
    for k in range(lookahead):
        longest = np.maximum(longest, np.minimum(run[..., 1 + k:1 + k + n], k + 1))
    ok = trig & (longest < dry_spell)

    has = ok.any(axis=-1)
    idx = np.where(has, np.argmax(ok, axis=-1), np.nan).astype(np.float32)
    # provisional when the lookahead window is not fully observed/forecast
    last_known = n - 1 - np.argmax(known[..., ::-1], axis=-1)
    prov = has & (np.nan_to_num(idx, nan=0) + lookahead > last_known)
    return idx, prov


# ── Seasonal pipeline ──────────────────────────────────────────────────────
def _target_grid(seasonal_dir):
    q = xr.open_dataarray(seasonal_dir / "chirps_Q_bar.nc")
    lat, lon = q.lat.values, q.lon.values
    return lat, lon, np.isfinite(q.values)


def _chirps_daily(lat, lon):
    with xr.open_dataset(CHIRPS_PATH) as ds:
        ds = ds.reindex(lat=lat, lon=lon, method="nearest")
        t = pd.DatetimeIndex(ds.time.values)
        years = np.unique(t.year)
        arr = np.full((len(years), 366, len(lat), len(lon)), np.nan, np.float32)
        v = ds["precip"].values
        for i, y in enumerate(years):
            m = t.year == y
            arr[i, t[m].dayofyear.values - 1] = v[m]
    return years, arr


def _save(da_vals, dims, coords, path):
    xr.DataArray(da_vals, dims=dims, coords=coords).to_netcdf(path)


def run_seasonal(seasonal_dir, rule, out_name="agro_onset"):
    seasonal_dir = Path(seasonal_dir)
    out = seasonal_dir / out_name
    out.mkdir(exist_ok=True)
    lat, lon, lm = _target_grid(seasonal_dir)
    bc = xr.open_dataarray(seasonal_dir / "ECMWF_bc_daily_all_years.nc")
    n_days = bc.sizes["day"]
    win0 = 365 - n_days + 1
    s_idx = rule["search_start_doy"] - win0
    m_years = bc.year.values.astype(int)
    print(f"[agro] {seasonal_dir.name}: window DOY {win0}-365, search from DOY {rule['search_start_doy']}, rule {rule}")

    # CHIRPS observed agronomic onset
    c_years, c_daily = _chirps_daily(lat, lon)
    c_on = np.full((len(c_years), len(lat), len(lon)), np.nan, np.float32)
    for i in range(len(c_years)):
        idx, _ = detect(np.moveaxis(c_daily[i, win0 - 1:365][:, lm], 0, -1), s_idx, **rule)
        c_on[i, lm] = idx + win0
    # ECMWF members (per year to keep memory small)
    n_mem = bc.sizes["member"]
    e_on = np.full((n_mem, len(m_years), len(lat), len(lon)), np.nan, np.float32)
    e_prov = np.zeros((n_mem, len(m_years), len(lat), len(lon)), bool)
    for yi in range(len(m_years)):
        d = bc.isel(year=yi).values                                   # (member, day, lat, lon)
        idx, prov = detect(np.moveaxis(d[:, :, lm], 1, -1), s_idx, **rule)
        e_on[:, yi][:, lm] = idx + win0
        e_prov[:, yi][:, lm] = prov

    # Terciles / probabilities / calibration with "no onset" counted as late
    fill = lambda a: np.where(lm & np.isnan(a), NO_ONSET, a)
    c_f, e_f = fill(c_on), fill(e_on)
    cal_c = np.isin(c_years, CAL_YEARS)
    t33, t67, _ = dl.estimate_terciles(c_f[cal_c], lm, 12)
    p_raw = dl.estimate_probs(e_f, t33, t67)
    ov = np.intersect1d(m_years, c_years)
    e_idx = np.where(np.isin(m_years, ov))[0]
    c_idx = np.where(np.isin(c_years, ov))[0]
    obs_cat = np.where(c_f[c_idx] < t33, 0, np.where(c_f[c_idx] < t67, 1, 2)).astype(np.int8)
    obs_cat[np.isnan(c_f[c_idx])] = -1
    cal_ov, val_ov = np.isin(ov, CAL_YEARS), np.isin(ov, VAL_YEARS)
    alpha = dl.optimise_alpha(p_raw[:, e_idx[cal_ov]], obs_cat[cal_ov], ALPHA_GRID)
    p_d = dl.apply_pooling(p_raw, alpha)
    skill = {}
    for tag, msk in (("cal", cal_ov), ("val", val_ov)):
        rps = np.nanmean(dl.rps_batch(p_d[:, e_idx[msk]], obs_cat[msk]), axis=0)
        rps_c = np.nanmean(dl.rps_clim_batch(obs_cat[msk]), axis=0)
        skill[f"rpss_{tag}"] = dl.compute_rpss(rps, rps_c)
        skill[f"hitrate_{tag}"] = dl.compute_hitrate(p_d[:, e_idx[msk]], obs_cat[msk])
    # Deterministic agreement of the ensemble median with observations (all overlap years)
    med = np.nanmedian(e_f[:, e_idx], axis=0)
    obs = c_f[c_idx]
    with np.errstate(invalid="ignore"):
        ma, oa = med - np.nanmean(med, 0), obs - np.nanmean(obs, 0)
        corr = np.nansum(ma * oa, 0) / np.sqrt(np.nansum(ma ** 2, 0) * np.nansum(oa ** 2, 0))
        mae = np.nanmean(np.abs(med - obs), 0)
    corr[~lm] = np.nan
    mae[~lm] = np.nan

    g = {"lat": lat, "lon": lon}
    _save(c_on, ["year", "lat", "lon"], {"year": c_years, **g}, out / "CHIRPS_agro_onset_doy.nc")
    _save(e_on, ["member", "year", "lat", "lon"], {"member": np.arange(1, n_mem + 1), "year": m_years, **g},
          out / "ECMWF_agro_onset_doy_all_years.nc")
    _save(e_prov.astype(np.int8), ["member", "year", "lat", "lon"], {"member": np.arange(1, n_mem + 1), "year": m_years, **g},
          out / "ECMWF_agro_onset_provisional.nc")
    for k, v in {"t33": t33, "t67": t67, "alpha": alpha, "corr_median": corr, "mae_median": mae, **skill}.items():
        _save(v, ["lat", "lon"], g, out / f"{k}_agro_onset.nc")
    _save(p_d, ["category", "year", "lat", "lon"], {"year": m_years, **g}, out / "probs_damped_agro_onset.nc")
    op = len(m_years) - 1
    _save(p_d[:, op], ["category", "lat", "lon"], g, out / f"probs_op_{m_years[op]}_agro_onset.nc")
    (out / "rule.json").write_text(json.dumps({**rule, "no_onset_sentinel_doy": NO_ONSET, "window_doy": [win0, 365]}, indent=1))
    print(f"[agro] wrote {out}  (OP {m_years[op]}: domain-mean P(early/normal/late) = "
          f"{np.nanmean(p_d[0, op][lm]):.2f}/{np.nanmean(p_d[1, op][lm]):.2f}/{np.nanmean(p_d[2, op][lm]):.2f}; "
          f"RPSS val {np.nanmean(skill['rpss_val'][lm]):+.3f})")
    return out


# ── Medium-range (ENS) outlook ─────────────────────────────────────────────
def run_ens(ens_file, seasonal_dir, rule):
    ens_file, seasonal_dir = Path(ens_file), Path(seasonal_dir)
    ens = xr.open_dataset(ens_file)["precip"]                         # member, time, lat, lon
    lat, lon, lm = _target_grid(seasonal_dir)
    ens = ens.reindex(lat=lat, lon=lon, method="nearest")
    times = pd.DatetimeIndex(ens.time.values)
    e = ens.values.astype(np.float32)                                 # (m, 15, lat, lon)
    n_m, n_t = e.shape[:2]
    year = times[0].year

    # Daily probabilities and trigger probabilities from ENS alone
    p_wet = np.mean(e >= rule["dry_day_mm"], axis=0)
    p_10 = np.mean(e >= 10.0, axis=0)
    med = np.median(e, axis=0)
    acc = sum(np.pad(e, ((0, 0), (0, rule["acc_days"]), (0, 0), (0, 0)))[:, k:k + n_t] for k in range(rule["acc_days"]))
    trig = (e >= rule["dry_day_mm"]) & (acc >= rule["rain_mm"])
    p_trig_day = np.mean(trig, axis=0)
    p_trig_7 = np.mean(trig[:, :7].any(axis=1), axis=0)
    p_trig_15 = np.mean(trig.any(axis=1), axis=0)

    # Composite onset: ENS days 1–15 then the paired seasonal member (2026, bias-corrected) to 31 Dec
    bc = xr.open_dataarray(seasonal_dir / "ECMWF_bc_daily_all_years.nc").sel(year=year)
    win0 = 365 - bc.sizes["day"] + 1
    d0 = times[0].dayofyear
    tail = bc.values[:, d0 + n_t - win0:]                             # seasonal days after the ENS horizon
    comp = np.concatenate([e, tail[np.arange(n_m) % tail.shape[0]]], axis=1)   # (m, days from ENS day 1, lat, lon)
    idx, prov = detect(np.moveaxis(comp[:, :, lm], 1, -1), 0, **rule)
    on = np.full((n_m, len(lat), len(lon)), np.nan, np.float32)
    on[:, lm] = idx + d0
    p_onset_15 = np.mean(on <= d0 + n_t - 1, axis=0)
    p_onset_15[~lm] = np.nan

    ds = xr.Dataset(
        {"p_wet": (("time", "lat", "lon"), p_wet), "p_ge10mm": (("time", "lat", "lon"), p_10),
         "median_mm": (("time", "lat", "lon"), med), "p_trigger_start": (("time", "lat", "lon"), p_trig_day),
         "p_trigger_7d": (("lat", "lon"), p_trig_7), "p_trigger_15d": (("lat", "lon"), p_trig_15),
         "p_onset_15d": (("lat", "lon"), p_onset_15),
         "composite_onset_doy": (("member", "lat", "lon"), on)},
        coords={"time": times, "lat": lat, "lon": lon, "member": ens.member.values},
        attrs={"ens_init": ens_file.stem, "seasonal_tail": seasonal_dir.name, "rule": json.dumps(rule),
               "note": "ENS precipitation is not bias-corrected; seasonal tail is EQM bias-corrected"})
    out_dir = BASE_DIR / "outputs" / "ecmwf_ens"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ens_outlook_{ens.attrs.get('init', ens_file.stem.split('_')[2])}.nc"
    ds.to_netcdf(out)
    print(f"[ens] wrote {out}  (domain-mean P(trigger in 7 d) {np.nanmean(p_trig_7[lm]):.2f}, "
          f"P(onset within 15 d) {np.nanmean(p_onset_15[lm]):.2f})")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seasonal"); s.add_argument("seasonal_dir")
    s.add_argument("--out-name", default="agro_onset", help="output folder inside seasonal_dir (one per rule preset)")
    e = sub.add_parser("ens"); e.add_argument("ens_file"); e.add_argument("seasonal_dir")
    for p in (s, e):
        p.add_argument("--rain-mm", type=float, default=RULE["rain_mm"])
        p.add_argument("--acc-days", type=int, default=RULE["acc_days"])
        p.add_argument("--dry-spell", type=int, default=RULE["dry_spell"], help="7–10 days typical")
        p.add_argument("--lookahead", type=int, default=RULE["lookahead"])
        p.add_argument("--search-start-doy", type=int, default=RULE["search_start_doy"])
    a = ap.parse_args()
    rule = dict(RULE, rain_mm=a.rain_mm, acc_days=a.acc_days, dry_spell=a.dry_spell,
                lookahead=a.lookahead, search_start_doy=a.search_start_doy)
    if a.cmd == "seasonal":
        run_seasonal(a.seasonal_dir, rule, a.out_name)
    else:
        run_ens(a.ens_file, a.seasonal_dir, rule)
