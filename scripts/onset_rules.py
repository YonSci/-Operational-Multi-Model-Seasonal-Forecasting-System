#!/usr/bin/env python3
"""
onset_rules.py
──────────────
ICPAC operational (agricultural) onset and cessation rules for the OND Short Rains, applied to CHIRPS
(1993–2025) and to every member / year of a seasonal run, next to the Dunning (cumulative anomaly) method:

  Rule 1  onset: day d wet (>= 1 mm) and rain over d..d+2 > 20 mm; no dry spell of >= 7 days in the next 21 days
          cessation: water balance (below)
  Rule 2  onset: rain over d..d+4 >= 20 mm with at least 3 rainy days (>= 1 mm); no dry spell longer than 7 days
          (>= 8) in the next 21 days
          cessation: water balance (below)
  Rule 3  onset: rain over d..d+2 > 20 mm; no dry spell longer than 10 days (>= 11) in the next 30 days
          cessation: first day d of a 10-day period with rain(d..d+9) < 0.5 × PET(d..d+9)

  Dry day < 1 mm. Onset = first day of the triggering window.
  Water-balance cessation (rules 1 and 2): after a 10-day period with rain < 0.5 × PET, the season ends on the
  first day the soil store is empty — a bucket of SWHC mm (default 100) filled by rain and emptied by PET from
  the onset day on.
  Cessation is searched from the end of the onset look-ahead (onset + 21 or 30 days): the onset test has already
  required the rains to hold through it.
  PET: modified Hargreaves daily climatology (pet_hargreaves.py).

  Search window: ICPAC uses 15 Aug – 15 Jan for OND. Days before the forecast start are observed CHIRPS (also for
  the hindcast years), so every run is searched from 15 Aug. Onset is searched to 15 Jan and cessation to 28 Feb
  (DOY 366–424 = 1 Jan – 28 Feb of the next year). The 1 Oct runs get 1 Jan – 28 Feb from SEAS5 lead days 93–151,
  bias-corrected here with the EQM of process_ecmwf_september.py (CHIRPS pool: CAL years' next Jan–Feb, ±7 days);
  the observed CHIRPS of the next Jan–Feb is used for the CHIRPS climatology. Runs without those lead days (the
  Sep 01 demo) stop at 31 Dec. "No onset" / "no cessation" mean none by the search end. For terciles and
  probabilities no onset counts as late, no cessation as late, and the season length is 0 without onset and
  "to the search end or later" without cessation.

Usage:
  python scripts/onset_rules.py outputs/ecmwf_oct_obs_latest              # rules 1–3 → <run>/icpac_rule<k>/
  python scripts/onset_rules.py --sep-demo                                # Sep 01 run (2025/2026 members in demo_data.npz)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
import agro_onset as ao  # noqa: E402

RULES = {
    1: dict(label="Agri rule 1: >20 mm in 3 days (first day wet), no 7-day dry spell in 21 days; water-balance cessation",
            onset=dict(rain_mm=20.0, acc_days=3, strict=True, first_day_wet=True, min_wet_days=0, dry_spell=7, lookahead=21),
            cessation="water_balance"),
    2: dict(label="Agri rule 2: >=20 mm in 5 days with 3 rainy days, no dry spell >7 days in 21 days; water-balance cessation",
            onset=dict(rain_mm=20.0, acc_days=5, strict=False, first_day_wet=False, min_wet_days=3, dry_spell=8, lookahead=21),
            cessation="water_balance"),
    3: dict(label="Agri rule 3: >20 mm in 3 days, no dry spell >10 days in 30 days; cessation 10-day rain <0.5 PET",
            onset=dict(rain_mm=20.0, acc_days=3, strict=True, first_day_wet=False, min_wet_days=0, dry_spell=11, lookahead=30),
            cessation="ratio"),
}
SEARCH_START_DOY = 227          # 15 Aug
SEARCH_END_DOY = 380            # 15 Jan (next year): last onset day
BC_END_DOY = 365                # the run's bias-corrected daily file ends on 31 Dec
EXT_DAYS = 59                   # 1 Jan – 28 Feb appended for the 1 Oct runs (cessation searched to DOY 424)
EXT_LEAD0 = 92                  # forecast day index of 1 Jan for a 1 Oct start (day 0 = 1 Oct)
EXT_QM_WINDOW = 7               # EQM CHIRPS pool ±days for 1 Jan – 28 Feb (±15 pulls in wetter Dec / Mar days)
DRY_DAY_MM = 1.0
CESS = dict(window=10, ratio=0.5, swhc=100.0)
LATE = 500.0                    # sentinel DOY for "none by the search end" (late) in terciles
RAW_OCT = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_oct"
EXT_CACHE = BASE_DIR / "outputs" / "ecmwf_oct" / "ECMWF_bc_daily_janfeb.nc"
PET_PATH = BASE_DIR / "data" / "worldclim" / "pet_mhargreaves_clim_kenya.nc"
FINAL_2026 = BASE_DIR / "data" / "chirps_2026" / "chirps-v2.0.2026.days_p25.nc"
PRELIM_2026 = BASE_DIR / "data" / "chirps_prelim_2026" / "chirps_prelim_2026_p25_kenya.nc"


# ── Cessation ───────────────────────────────────────────────────────────────
def cessation(x, pet, onset, start_after, mode, window=10, ratio=0.5, swhc=100.0):
    """
    x, pet : (S, n) daily rain (NaN = unknown) and PET; onset : (S,) day index (NaN = none).
    Trigger: first day d >= onset + start_after with all of d..d+window-1 known and
    rain(d..d+window-1) < ratio × PET(d..d+window-1). mode "ratio": cessation = trigger day.
    mode "water_balance": cessation = first day >= trigger day with an empty soil store
    (store from the onset day: min(swhc, max(0, store + rain - PET))). Returns (S,) day index, NaN = none.
    """
    S, n = x.shape
    known = np.isfinite(x)
    xz = np.where(known, x, 0.0).astype(np.float32)
    cs = lambda a: np.concatenate([np.zeros((S, 1), np.float32), np.cumsum(a, axis=1, dtype=np.float32)], axis=1)
    m = n - window + 1
    r10 = cs(xz)[:, window:] - cs(xz)[:, :m]
    p10 = cs(pet)[:, window:] - cs(pet)[:, :m]
    k10 = cs(known.astype(np.float32))[:, window:] - cs(known.astype(np.float32))[:, :m]
    trig = np.zeros((S, n), bool)
    trig[:, :m] = (k10 == window) & (r10 < ratio * p10)
    has_on = np.isfinite(onset)
    first = np.where(has_on, onset + start_after, n + 1)
    trig &= np.arange(n)[None, :] >= first[:, None]
    t0 = np.where(trig.any(axis=1), np.argmax(trig, axis=1), np.nan).astype(np.float32)
    if mode == "ratio":
        return t0
    on = np.where(has_on, onset, n + 1)
    store = np.zeros(S, np.float32)
    out = np.full(S, np.nan, np.float32)
    for t in range(n):
        active = t >= on
        store = np.where(active, np.clip(store + xz[:, t] - pet[:, t], 0, swhc), 0)
        hit = active & np.isfinite(t0) & (t >= t0) & (store <= 0) & known[:, t] & np.isnan(out)
        out[hit] = t
    return out


def apply_rule(daily, pet, rule):
    """daily (S, n) from SEARCH_START_DOY, pet (S, n) → onset, cessation (DOY, NaN = none by the data end), lgp (days)."""
    o = rule["onset"]
    end_doy = SEARCH_START_DOY + daily.shape[1] - 1
    idx, _ = ao.detect(daily, 0, dry_day_mm=DRY_DAY_MM, end_idx=min(SEARCH_END_DOY, end_doy) - SEARCH_START_DOY, **o)
    c = cessation(daily, pet, idx, o["lookahead"], rule["cessation"], **CESS)
    return idx + SEARCH_START_DOY, c + SEARCH_START_DOY, c - idx


def for_terciles(on, cs, lg, valid):
    """Map "none by 31 Dec" to sentinels (valid = cells/years with data): onset/cessation late, LGP 0 without
    onset and LATE - onset without cessation; cessation stays NaN without onset (excluded)."""
    has_on = np.isfinite(on)
    on_f = np.where(valid & ~has_on, LATE, on)
    cs_f = np.where(valid & has_on & np.isnan(cs), LATE, cs)
    lg_f = np.where(valid & ~has_on, 0.0, np.where(valid & has_on & np.isnan(cs), LATE - on, lg))
    return on_f, cs_f, lg_f


def by_label(end_doy):
    """'31 Dec' / '28 Feb' for the last searched DOY (DOY > 365 = next year)."""
    d = pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(end_doy) - 1)
    return f"{d.day} {d:%b}"


# ── Data ────────────────────────────────────────────────────────────────────
def obs_2026(lat, lon):
    """CHIRPS 2026 by DOY (final, then preliminary) on the grid → (366, lat, lon), NaN where not yet observed."""
    arr = np.full((366, len(lat), len(lon)), np.nan, np.float32)
    for path in (FINAL_2026, PRELIM_2026):
        if not path.exists():
            continue
        with xr.open_dataset(path) as ds:
            ds = ds.rename({k: v for k, v in {"latitude": "lat", "longitude": "lon"}.items() if k in ds.dims})
            ds = ds.reindex(lat=lat, lon=lon, method="nearest")
            t = pd.DatetimeIndex(ds.time.values)
            m = t.year == 2026
            d = t[m].dayofyear.values - 1
            arr[d] = np.where(np.isnan(arr[d]), ds["precip"].values[m], arr[d])
    return arr


def load_pet(lat, lon, ext_days=0):
    """PET climatology from SEARCH_START_DOY to 31 Dec, then ext_days of the next January–February: (n, lat, lon)."""
    with xr.open_dataset(PET_PATH) as ds:
        v = ds["pet"].sel(lat=lat, lon=lon, method="nearest").values
    return np.concatenate([v[SEARCH_START_DOY - 1:BC_END_DOY], v[:ext_days]])


def next_year_obs(c_years, c_daily, o26, y, n):
    """Observed CHIRPS for the first n days of year y+1 (NaN where missing)."""
    if y + 1 in c_years:
        return c_daily[int(np.where(c_years == y + 1)[0][0]), :n]
    return o26[:n] if y + 1 == 2026 else np.full((n, *c_daily.shape[2:]), np.nan, np.float32)


def jan_feb(seasonal_dir, m_years, lat, lon, lm, c_years, c_daily, o26):
    """(member, year, EXT_DAYS, lat, lon) bias-corrected 1 Jan – 28 Feb rain for the 1 Oct runs, from SEAS5 lead
    days 93–151 in RAW_OCT; None for other runs or when a year's file has fewer lead days. Cached in EXT_CACHE
    (shared by the three 1 Oct runs; rebuilt when a raw file is newer)."""
    if seasonal_dir == "sep-demo" or not Path(seasonal_dir).name.startswith("ecmwf_oct"):
        return None
    files = [RAW_OCT / f"ecmwf_{y}10_d01.nc" for y in m_years]
    if not all(f.exists() for f in files):
        return None
    if EXT_CACHE.exists() and EXT_CACHE.stat().st_mtime > max(f.stat().st_mtime for f in files):
        with xr.open_dataarray(EXT_CACHE) as da:
            if np.array_equal(da.year.values, m_years) and da.attrs.get("qm_window") == EXT_QM_WINDOW:
                print(f"[rules] 1 Jan – 28 Feb members from {EXT_CACHE.name}")
                return da.values.astype(np.float32)
    import process_ecmwf_september as pes
    n_mem = pes.N_MEMBERS_COMMON
    raw = np.full((n_mem, len(m_years), EXT_DAYS, len(lat), len(lon)), np.nan, np.float32)
    for yi, f in enumerate(files):
        with xr.open_dataset(f) as ds:
            tp = ds["tp"].squeeze("forecast_reference_time", drop=True) if "forecast_reference_time" in ds["tp"].dims else ds["tp"]
            if tp.sizes["forecast_period"] < EXT_LEAD0 + EXT_DAYS:
                print(f"[rules] {f.name}: {tp.sizes['forecast_period']} lead days (< {EXT_LEAD0 + EXT_DAYS}); "
                      "searching to 31 Dec only")
                return None
            v = tp.reindex(latitude=lat, longitude=lon, method="nearest").values[:n_mem, EXT_LEAD0 - 1:EXT_LEAD0 + EXT_DAYS]
        raw[:v.shape[0], yi] = np.clip(np.diff(v, axis=1), 0, None) * 1000.0           # accumulated m → mm/day
    # EQM per land pixel and day: CHIRPS pool = CAL years' days (end of Dec of y, Jan–Mar of y+1) within ±EXT_QM_WINDOW
    w = EXT_QM_WINDOW
    cal = [y for y in pes.CAL_YEARS if y in c_years]
    cont = np.stack([np.concatenate([c_daily[int(np.where(c_years == y)[0][0]), BC_END_DOY - w:BC_END_DOY],
                                     next_year_obs(c_years, c_daily, o26, y, EXT_DAYS + w)]) for y in cal])
    cal_e = np.isin(m_years, pes.CAL_YEARS)
    bc = raw.copy()
    for pi, pj in np.argwhere(lm):
        for d in range(EXT_DAYS):
            c_pool = cont[:, d:d + 2 * w + 1, pi, pj].ravel()
            s_pool = raw[:, cal_e, d, pi, pj].ravel()
            bc[:, :, d, pi, pj] = pes._build_qm_transfer(c_pool[np.isfinite(c_pool)], s_pool[np.isfinite(s_pool)])(raw[:, :, d, pi, pj])
    bc[:, :, :, ~lm] = np.nan
    EXT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    da = xr.DataArray(bc, dims=["member", "year", "day", "lat", "lon"], name="pr",
                      coords={"member": np.arange(1, n_mem + 1), "year": m_years, "day": np.arange(EXT_DAYS), "lat": lat, "lon": lon},
                      attrs={"units": "mm/day", "long_name": "Bias-corrected daily precipitation 1 Jan – 28 Feb (EQM), 1 Oct init",
                             "qm_window": EXT_QM_WINDOW})
    da.to_netcdf(EXT_CACHE, encoding={"pr": {"zlib": True, "complevel": 4}})
    print(f"[rules] 1 Jan – 28 Feb members bias-corrected → {EXT_CACHE}")
    return bc


def member_daily(seasonal_dir):
    """(member, year, day, lat, lon) bias-corrected daily rain from the run's first day to 31 Dec, its first DOY,
    model years and grid, from <run>/ECMWF_bc_daily_all_years.nc, or the Sep 01 run in demo_data.npz."""
    if seasonal_dir == "sep-demo":
        demo = np.load(BASE_DIR / "backend" / "demo_data.npz")
        years = demo["sep_ecmwf_years"].astype(int)
        lat, lon = demo["target_lat"].astype(float), demo["target_lon"].astype(float)
        n_day = demo["sep_ecmwf_bc_daily_2026"].shape[1]
        arr = np.full((25, len(years), n_day, len(lat), len(lon)), np.nan, np.float32)
        for y in (2025, 2026):
            k = f"sep_ecmwf_bc_daily_{y}"
            if k in demo.files:
                arr[:, int(np.where(years == y)[0][0])] = demo[k].astype(np.float32)
        return arr, BC_END_DOY - n_day + 1, years, lat, lon
    bc = xr.open_dataarray(Path(seasonal_dir) / "ECMWF_bc_daily_all_years.nc")
    return (bc.values.astype(np.float32), BC_END_DOY - bc.sizes["day"] + 1, bc.year.values.astype(int),
            bc.lat.values, bc.lon.values)


def _save(vals, dims, coords, path):
    xr.DataArray(vals, dims=dims, coords=coords).to_netcdf(path)


# ── Pipeline ────────────────────────────────────────────────────────────────
def run(seasonal_dir, rules=(1, 2, 3)):
    out_root = BASE_DIR / "outputs" / "ecmwf_sep_demo" if seasonal_dir == "sep-demo" else Path(seasonal_dir)
    mem, win0, m_years, lat, lon = member_daily(seasonal_dir)
    grid = xr.open_dataarray(BASE_DIR / "outputs" / "ecmwf_oct_obs_latest" / "chirps_Q_bar.nc")
    assert np.allclose(grid.lat.values, lat) and np.allclose(grid.lon.values, lon), "grid differs from the Oct runs"
    lm = np.isfinite(grid.values)
    c_years, c_daily = ao._chirps_daily(lat, lon)
    o26 = obs_2026(lat, lon)
    has_year = np.isfinite(mem[:, :, -1]).any(axis=(0, 2, 3))                       # member years with data
    ext = jan_feb(seasonal_dir, m_years, lat, lon, lm, c_years, c_daily, o26)
    n_ext = 0 if ext is None else EXT_DAYS
    if n_ext:
        mem = np.concatenate([mem, ext[:mem.shape[0]]], axis=2)
    end_doy = BC_END_DOY + n_ext
    s0, n = SEARCH_START_DOY - 1, end_doy - SEARCH_START_DOY + 1
    pet = load_pet(lat, lon, n_ext)[:, lm].T                                       # (S, n)
    n_mem = mem.shape[0]
    by = by_label(end_doy)
    print(f"[rules] {out_root.name}: members from DOY {win0}, CHIRPS before it; onset search DOY {SEARCH_START_DOY}–"
          f"{min(SEARCH_END_DOY, end_doy)}, cessation to DOY {end_doy} ({by}); {int(has_year.sum())} member years")

    for k in rules:
        rule = RULES[k]
        out = out_root / f"icpac_rule{k}"
        out.mkdir(parents=True, exist_ok=True)
        # CHIRPS
        c = {v: np.full((len(c_years), *lm.shape), np.nan, np.float32) for v in ("onset", "cessation", "lgp")}
        for i, y in enumerate(c_years):
            obs = np.concatenate([c_daily[i, s0:BC_END_DOY], next_year_obs(c_years, c_daily, o26, y, n_ext)])
            on, cs, lg = apply_rule(obs[:, lm].T, pet, rule)
            c["onset"][i, lm], c["cessation"][i, lm], c["lgp"][i, lm] = on, cs, lg
        # Members: observed CHIRPS from 15 Aug to the day before the run starts, then the members
        e = {v: np.full((n_mem, len(m_years), *lm.shape), np.nan, np.float32) for v in ("onset", "cessation", "lgp")}
        for yi, y in enumerate(m_years):
            if not has_year[yi]:
                continue
            obs = c_daily[int(np.where(c_years == y)[0][0])] if y in c_years else o26
            pre = obs[s0:win0 - 1][:, lm]                                             # (n_pre, S)
            if np.isnan(pre).any():
                raise RuntimeError(f"CHIRPS gaps for {y} DOY {SEARCH_START_DOY}–{win0 - 1}")
            d = np.concatenate([np.broadcast_to(pre, (n_mem, *pre.shape)), mem[:, yi][:, :, lm]], axis=1)  # (m, n, S)
            d = np.moveaxis(d, 1, -1).reshape(-1, n)
            on, cs, lg = apply_rule(d, np.tile(pet, (n_mem, 1)), rule)
            for v, a in (("onset", on), ("cessation", cs), ("lgp", lg)):
                e[v][:, yi][:, lm] = a.reshape(n_mem, -1)

        # Terciles, calibrated probabilities and skill per variable
        c_valid = lm[None]
        e_valid = lm[None, None] & has_year[None, :, None, None]
        c_f = dict(zip(("onset", "cessation", "lgp"), for_terciles(c["onset"], c["cessation"], c["lgp"], c_valid)))
        e_f = dict(zip(("onset", "cessation", "lgp"), for_terciles(e["onset"], e["cessation"], e["lgp"], e_valid)))
        g = {"lat": lat, "lon": lon}
        summary = {}
        for v in ("onset", "cessation", "lgp"):
            t33, t67, p_d, alpha, skill, corr, mae = ao.tercile_probs_skill(c_f[v], e_f[v], c_years, m_years, lm)
            for name, a in {"t33": t33, "t67": t67, "alpha": alpha, "corr_median": corr, "mae_median": mae, **skill}.items():
                _save(a, ["lat", "lon"], g, out / f"{name}_{v}.nc")
            _save(p_d, ["category", "year", "lat", "lon"], {"year": m_years, **g}, out / f"probs_damped_{v}.nc")
            _save(c[v], ["year", "lat", "lon"], {"year": c_years, **g}, out / f"CHIRPS_{v}.nc")
            _save(e[v], ["member", "year", "lat", "lon"], {"member": np.arange(1, n_mem + 1), "year": m_years, **g},
                  out / f"ECMWF_{v}_all_years.nc")
            op = int(np.where(has_year)[0][-1])
            summary[v] = (np.nanmean(p_d[:, op][:, lm], axis=1), np.nanmean(skill["rpss_val"][lm]))
        (out / "rule.json").write_text(json.dumps({
            "rule": k, "label": rule["label"], "onset": rule["onset"], "cessation": rule["cessation"], **CESS,
            "dry_day_mm": DRY_DAY_MM, "search_doy": [SEARCH_START_DOY, min(SEARCH_END_DOY, end_doy)],
            "icpac_search_doy": [SEARCH_START_DOY, SEARCH_END_DOY], "data_end_doy": int(end_doy), "none_by": by, "onset_by": by_label(min(SEARCH_END_DOY, end_doy)),
            "member_start_doy": int(win0),
            "late_sentinel_doy": LATE, "pet": "modified Hargreaves climatology (WorldClim 2.1 + CHIRPS)",
            "skill": bool(np.isfinite(summary["onset"][1]))}, indent=1))
        lmed = lambda a: np.nanmedian(a[:, op][:, lm])
        print(f"[rules] rule {k} → {out}: {m_years[op]} domain median onset DOY {lmed(e['onset']):.0f}, cessation "
              f"{lmed(e['cessation']):.0f}, LGP {lmed(e['lgp']):.0f} d; CHIRPS clim onset "
              f"{np.nanmedian(c['onset'][np.isin(c_years, ao.CAL_YEARS)][:, lm]):.0f}; "
              + "; ".join(f"{v} P(BN/NN/AN) {'/'.join(f'{x:.2f}' for x in p)} RPSS val {r:+.2f}" for v, (p, r) in summary.items()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seasonal_dir", nargs="?")
    ap.add_argument("--sep-demo", action="store_true", help="the Sep 01 run from backend/demo_data.npz")
    ap.add_argument("--rules", type=int, nargs="+", default=[1, 2, 3])
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run("sep-demo" if a.sep_demo else a.seasonal_dir, tuple(a.rules))
