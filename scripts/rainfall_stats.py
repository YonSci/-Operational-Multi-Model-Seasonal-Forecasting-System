#!/usr/bin/env python3
"""
rainfall_stats.py
─────────────────
Seasonal rainfall statistics for the dashboard's Rainfall Terciles view, per 0.25° cell:

  total        total rainfall over the season (mm)
  wet_days     days with rain >= WET_MM
  dry_days     days with rain <  WET_MM
  intensity    mean rain on wet days (mm/day; 0 when there are none)
  wet_spells   runs of >= WET_SPELL consecutive wet days
  dry_spells   runs of >= DRY_SPELL consecutive dry days

Forecast: bias-corrected ECMWF SEAS5 daily members for the operational year. Normal: CHIRPS 1993-2016.

Daily bias correction fixes rainfall amounts but not always how often it rains: models drizzle, so counts of
wet days and spells can be far off even when the total is right. Runs whose own hindcasts (1993-2016) are on
disk are therefore calibrated statistic by statistic: each member's value is ranked within the model's
hindcast distribution at that cell, the rank sets the tercile (below / near / above normal), and the value is
mapped to the same rank of the CHIRPS distribution for display. Runs without daily hindcasts get the total
only, compared directly with CHIRPS (the daily correction makes totals comparable); their other statistics
are withheld (NaN). Where the terciles coincide (no spread, common for spell counts) no tercile forecast is
issued (NaN probabilities).

Seasons (fixed calendar windows):
  Kenya Short Rains  OND   Sep run (total only); Oct, Oct+Obs, Oct+Obs latest runs (all statistics)
  Ethiopia Kiremt    JJAS  total only (also used for the Annual wet season view)
  Ethiopia Belg      FMAM  total only (also used for the Gu/Ganna view)
  Ethiopia Bega      ONDJ  total only (also used for the Deyr/Hagaya view)
The Kenya Long Rains have no daily forecast traces on disk, so they are not covered.

Output: backend/rain_stats.npz   keys "<model>|lat", "<model>|lon", "<model>|meta" (JSON),
                                 "<model>|<stat>" float32 (9, lat, lon) in FIELDS order
Usage:  python scripts/rainfall_stats.py [--base <repo holding data/ and outputs/>] [--out backend/rain_stats.npz]
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

WET_MM = 1.0          # wet day: rain >= 1 mm
WET_SPELL = 3         # wet spell: at least 3 consecutive wet days
DRY_SPELL = 7         # dry spell: at least 7 consecutive dry days (as in Agri rules 1-2)
CAL_YEARS = list(range(1993, 2017))
OP_YEAR = 2026
STATS = ["total", "wet_days", "dry_days", "intensity", "wet_spells", "dry_spells"]
FIELDS = ["fc_med", "fc_p10", "fc_p90", "clim_med", "clim_t33", "clim_t67", "p_bn", "p_nn", "p_an"]

# model -> (country, season label, first DOY of the daily traces, window start "MM-DD", window end "MM-DD", source)
# source ("nc", path) holds all years, so the run is calibrated on its hindcasts; ("npz", key) holds 2026 only
RUNS = {
    "ECMWF SEAS5 (Sep)":            ("kenya",    "OND",  244, "10-01", "12-31", ("npz", "sep_ecmwf_bc_daily_{y}")),
    "ECMWF SEAS5 (Oct)":            ("kenya",    "OND",  274, "10-01", "12-31", ("nc", "outputs/ecmwf_oct/ECMWF_bc_daily_all_years.nc")),
    "ECMWF SEAS5 (Oct+Obs)":        ("kenya",    "OND",  244, "10-01", "12-31", ("nc", "outputs/ecmwf_oct_obs/ECMWF_bc_daily_all_years.nc")),
    "ECMWF SEAS5 (Oct+Obs latest)": ("kenya",    "OND",  244, "10-01", "12-31", ("nc", "outputs/ecmwf_oct_obs_latest/ECMWF_bc_daily_all_years.nc")),
    "ECMWF SEAS5 (Kiremt)":         ("ethiopia", "JJAS", 122, "06-01", "09-30", ("npz", "kiremt_ecmwf_bc_daily_{y}")),
    "ECMWF SEAS5 (FMAM)":           ("ethiopia", "FMAM",  32, "02-01", "05-31", ("npz", "fmam_ecmwf_bc_daily_{y}")),
    "ECMWF SEAS5 (Bega)":           ("ethiopia", "ONDJ", 244, "10-01", "01-31", ("npz", "bega_ecmwf_bc_daily_{y}")),
}
GRID_KEYS = {"kenya": ("target_lat", "target_lon"), "ethiopia": ("kiremt_target_lat", "kiremt_target_lon")}


def window_dates(year, start, end):
    """First and last date of the season starting in `year` (the end may fall in the next year)."""
    d0 = pd.Timestamp(f"{year}-{start}")
    d1 = pd.Timestamp(f"{year}-{end}")
    if d1 < d0:
        d1 = pd.Timestamp(f"{year + 1}-{end}")
    return d0, d1


def window_slice(first_doy, year, start, end):
    """Index range of the season inside daily traces that begin on day-of-year `first_doy` of `year`."""
    t0 = pd.Timestamp(dt.date(year, 1, 1)) + pd.Timedelta(days=first_doy - 1)
    d0, d1 = window_dates(year, start, end)
    return slice((d0 - t0).days, (d1 - t0).days + 1)


def count_runs(flag, min_len):
    """Number of runs of >= min_len consecutive True values along axis 0."""
    n = flag.shape[0]
    if n < min_len:
        return np.zeros(flag.shape[1:], np.float32)
    c = np.concatenate([np.zeros((1,) + flag.shape[1:], np.int32), np.cumsum(flag, axis=0, dtype=np.int32)])
    full = (c[min_len:] - c[:-min_len]) == min_len                  # window [t, t+min_len) all True
    prev = np.concatenate([np.zeros((1,) + flag.shape[1:], bool), flag[:n - min_len]])
    return (full & ~prev).sum(axis=0).astype(np.float32)             # count each run once, at its start


def season_stats(rain):
    """rain: (day, ...) mm/day -> dict of statistics with the day axis removed."""
    wet = rain >= WET_MM
    n_wet = wet.sum(axis=0).astype(np.float32)
    wet_rain = np.where(wet, rain, 0).sum(axis=0)
    return {
        "total": rain.sum(axis=0).astype(np.float32),
        "wet_days": n_wet,
        "dry_days": (rain.shape[0] - n_wet).astype(np.float32),
        "intensity": np.divide(wet_rain, n_wet, out=np.zeros_like(n_wet), where=n_wet > 0).astype(np.float32),
        "wet_spells": count_runs(wet, WET_SPELL),
        "dry_spells": count_runs(~wet, DRY_SPELL),
    }


def chirps_kenya(base, lat, lon, start, end):
    out = []
    for y in CAL_YEARS:
        d0, d1 = window_dates(y, start, end)
        parts = [xr.open_dataset(base / "data" / "chirps_pr_ke" / f"chirps-v2.0.{yy}.days_p25_clip.nc")["precip"]
                 .sel(time=slice(d0, d1)) for yy in range(d0.year, d1.year + 1)]
        out.append(xr.concat(parts, "time").reindex(lat=lat, lon=lon, method="nearest", tolerance=0.01).values)
    return out


def chirps_ethiopia(base, lat, lon, start, end):
    pr = xr.open_dataset(base / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc")["precip"]
    pr = pr.reindex(lat=lat, lon=lon, method="nearest", tolerance=0.01)
    return [pr.sel(time=slice(*window_dates(y, start, end))).values for y in CAL_YEARS]


def member_stats(traces):
    """traces: (member, day, lat, lon) -> dict of (member, lat, lon)."""
    return season_stats(np.moveaxis(traces, 1, 0))


def rank_in(h, f):
    """Mid-rank of each forecast value f (M, ...) within the hindcast sample h (N, ...), as a fraction."""
    below = (h[None] < f[:, None]).sum(axis=1)
    ties = (h[None] == f[:, None]).sum(axis=1)
    return (below + 0.5 * ties) / h.shape[0]


def quantile_at(c, q):
    """Linear-interpolated quantile q (M, ...) of sample c (Y, ...), cell by cell."""
    cs = np.sort(c, axis=0)
    pos = q * (cs.shape[0] - 1)
    lo = np.clip(np.floor(pos).astype(int), 0, cs.shape[0] - 1)
    hi = np.clip(lo + 1, 0, cs.shape[0] - 1)
    w = pos - lo
    return np.take_along_axis(cs, lo, 0) * (1 - w) + np.take_along_axis(cs, hi, 0) * w


def run(base, out_path):
    npz = np.load(Path(__file__).resolve().parent.parent / "backend" / "demo_data.npz")
    result = {}
    for model, (country, label, first_doy, start, end, (kind, ref)) in RUNS.items():
        lat = npz[GRID_KEYS[country][0]]
        lon = npz[GRID_KEYS[country][1]]
        sl = window_slice(first_doy, OP_YEAR, start, end)
        d0, d1 = window_dates(OP_YEAR, start, end)
        calibrated = kind == "nc"

        if calibrated:
            da = xr.open_dataarray(base / ref)
            fc = member_stats(da.sel(year=OP_YEAR).values[:, sl])
            hc = [member_stats(da.sel(year=y).values[:, sl]) for y in CAL_YEARS]
            hind = {st: np.concatenate([h[st] for h in hc]) for st in STATS}   # (year x member, lat, lon)
        else:
            fc = member_stats(npz[ref.format(y=OP_YEAR)].astype(np.float32)[:, sl])
        n_mem = fc["total"].shape[0]
        if sl.stop - sl.start != (d1 - d0).days + 1:
            raise RuntimeError(f"{model}: window {sl} does not cover {d0.date()}..{d1.date()}")

        obs = (chirps_kenya if country == "kenya" else chirps_ethiopia)(base, lat, lon, start, end)
        land = ~np.isnan(np.stack([o.sum(axis=0) for o in obs])).any(axis=0)
        obs_stats = [season_stats(o) for o in obs]

        available = STATS if calibrated else ["total"]
        for st in STATS:
            block = np.full((len(FIELDS),) + land.shape, np.nan, np.float32)
            if st in available:
                c = np.stack([o[st] for o in obs_stats])                          # (year, lat, lon)
                with np.errstate(invalid="ignore"):
                    c_med, t33, t67 = (np.nanpercentile(c, q, axis=0) for q in (50, 100 / 3, 200 / 3))
                    if calibrated:
                        h = hind[st]
                        q = rank_in(h, fc[st])                                    # member ranks in the model climate
                        shown = quantile_at(c, q)                                 # same ranks of the CHIRPS climate
                        p_bn, p_an = np.mean(q < 1 / 3, axis=0), np.mean(q > 2 / 3, axis=0)
                        h33, h67 = (np.percentile(h, x, axis=0) for x in (100 / 3, 200 / 3))
                        flat = ~(t67 > t33) | ~(h67 > h33)
                    else:
                        shown = fc[st]
                        p_bn, p_an = np.mean(shown < t33, axis=0), np.mean(shown > t67, axis=0)
                        flat = ~(t67 > t33)
                    p_nn = 1.0 - p_bn - p_an
                    probs = [np.where(flat, np.nan, p) for p in (p_bn, p_nn, p_an)]
                    pct = [np.percentile(shown, x, axis=0) for x in (50, 10, 90)]
                block[:] = np.stack(pct + [c_med, t33, t67] + probs)
                block[:, ~land] = np.nan
            result[f"{model}|{st}"] = block

        meta = dict(country=country, season=label, window=[str(d0.date())[5:], str(d1.date())[5:]], year=OP_YEAR,
                    n_members=n_mem, calibrated=calibrated, available=available,
                    cal_years=[CAL_YEARS[0], CAL_YEARS[-1]], wet_mm=WET_MM, wet_spell=WET_SPELL, dry_spell=DRY_SPELL)
        result[f"{model}|lat"] = lat
        result[f"{model}|lon"] = lon
        result[f"{model}|meta"] = np.array(json.dumps(meta))
        no_terc = {st: int(np.isnan(result[f'{model}|{st}'][6][land]).sum()) for st in available}
        print(f"  {model:<30} {label:<5} {n_mem} members, {int(land.sum())} cells, "
              f"{'calibrated on hindcasts' if calibrated else 'total only'}; cells without terciles: {no_terc}")
    np.savez_compressed(out_path, **result)
    print(f"  -> {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, default=here, help="repository holding data/ and outputs/")
    ap.add_argument("--out", type=Path, default=here / "backend" / "rain_stats.npz")
    a = ap.parse_args()
    run(a.base, a.out)
