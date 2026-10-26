#!/usr/bin/env python3
"""
model_onsets.py
───────────────
Seasonal onset (Dunning) and planting onset (20 mm rule) implied by each short-range model run, per station.

A model run covers only 7–16 days, while the onset definitions need the whole season (Dunning: DOY 244–365)
or a 21-day dry-spell check (planting rule). For each station and model the series is built as
  observed rainfall (CHIRPS to its last day, then the mean of ARC2/TAMSAT/PDIR-Now for later days)
  + that model's daily forecast (data/nwp/nwp_<date>.csv)
  + the 25 bias-corrected SEAS5 members after the model's last day (outputs/ecmwf_oct_obs_latest, 2026)
and both onset rules are applied to the 25 composite series → median and P25–P75 per model.
Rows "SEAS5 only" use the seasonal members from the first unobserved day (no short-range model).

Output: outputs/model_onsets_<date>.csv (and a printed table)
"""
import datetime as dt
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, str(BASE / "notebook"))
sys.path.insert(0, str(BASE / "backend"))
import agro_onset as ao  # noqa: E402
import dunning_lib as dl  # noqa: E402
import realtime_rain as rr  # noqa: E402

SEAS = BASE / "outputs" / "ecmwf_oct_obs_latest"
YEAR, WIN0, WIN1 = 2026, 244, 365
LABELS = {"ecmwf_ifs025": "ECMWF IFS", "ecmwf_ens_median": "ECMWF ENS median", "gfs_global": "GFS (NOAA)",
          "gem_global": "GDPS (ECCC)", "icon_global": "ICON (DWD)", "ukmo_global_deterministic_10km": "UKMO (Met Office)"}


def doy(d):
    return pd.Timestamp(d).dayofyear


def d2s(x):
    return (dt.date(YEAR, 1, 1) + dt.timedelta(days=int(round(x)) - 1)).strftime("%d %b") if np.isfinite(x) else "none"


def observed(lat, lon):
    """Daily observed rain from 1 Sep: CHIRPS where available, then the mean of the other products."""
    df = rr.site_series(lat, lon, f"{YEAR}-09-01", products=("chirps", "arc2", "tamsat", "pdirnow"))
    s = df["chirps"].copy() if "chirps" in df else pd.Series(dtype=float)
    others = df.drop(columns=["chirps"], errors="ignore").mean(axis=1)
    s = s.combine_first(others).dropna()
    return s[s.index >= f"{YEAR}-09-01"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    nwp_f = sorted(glob.glob(str(BASE / "data" / "nwp" / "nwp_*.csv")))[-1]
    nwp = pd.read_csv(nwp_f)
    nwp = nwp[nwp.kind == "station"]
    bc = xr.open_dataarray(SEAS / "ECMWF_bc_daily_all_years.nc").sel(year=YEAR)      # member, day(0=DOY 244), lat, lon
    clim = {k: xr.open_dataarray(SEAS / f"chirps_{k}.nc") for k in ("Q_bar", "d_s", "d_e")}
    import mam_loader as ml
    stations = [(s["site_name"], s["lat"], s["lon"]) for s in ml.SITES if s["country"] == "kenya"]
    rule = {k: v for k, v in ao.RULE.items() if k != "search_start_doy"}
    rows = []
    for site, lat, lon in stations:
        sel = dict(lat=lat, lon=lon, method="nearest")
        members = bc.sel(**sel).values                                   # (25, 122)
        q = float(clim["Q_bar"].sel(**sel)); ds_ = float(clim["d_s"].sel(**sel)); de_ = float(clim["d_e"].sel(**sel))
        obs = observed(lat, lon)
        obs_end = doy(obs.index.max())
        runs = [("SEAS5 only", None)] + [(LABELS.get(m, m), g) for m, g in nwp[nwp.site == site].groupby("model")]
        for name, g in runs:
            series = np.array(members, dtype=np.float32)                 # start from the seasonal members
            idx = lambda d: d - WIN0
            series[:, :idx(obs_end) + 1] = obs.reindex(pd.date_range(f"{YEAR}-09-01", obs.index.max())).values[None, :]
            last = obs_end
            src = "direct"
            if g is not None:
                g = g.sort_values("date")
                for d, v in zip(g.date, g.rain_mm):
                    k = doy(d)
                    if k > obs_end and k <= WIN1:
                        series[:, idx(k)] = v                            # model day replaces every member's value
                        last = max(last, k)
                src = g["source"].iloc[0] if "source" in g else "open-meteo"
            series = np.nan_to_num(series, nan=0.0)
            res = dl.detect_season_batch(precip=series, Q_bar=np.full(len(series), q), d_s=np.full(len(series), ds_),
                                         d_e=np.full(len(series), de_), doy_axis=np.arange(WIN0, WIN1 + 1),
                                         win_doy_start=WIN0, win_doy_end=WIN1, buffer_days=30, min_lgp_days=20)
            dun = np.asarray(res["onset_doy"], dtype=float)
            ag_idx, _ = ao.detect(series, ao.RULE["search_start_doy"] - WIN0, **rule)
            agro = np.asarray(ag_idx, dtype=float) + WIN0
            # A planting onset inside the model's own forecast days is decided by that model alone
            within = np.isfinite(agro) & (agro <= last)
            pct = lambda a, p: np.nanpercentile(a, p) if np.isfinite(a).any() else np.nan
            rows.append({"site": site, "run": name, "source": src if g is not None else "seasonal",
                         "model_last_day": d2s(last), "dunning_median": d2s(pct(dun, 50)),
                         "dunning_range": f"{d2s(pct(dun, 25))} – {d2s(pct(dun, 75))}",
                         "planting_median": d2s(pct(agro, 50)), "planting_range": f"{d2s(pct(agro, 25))} – {d2s(pct(agro, 75))}",
                         "planting_within_model_days": f"{within.mean():.0%}" if g is not None else "",
                         "dunning_median_doy": round(pct(dun, 50), 1), "planting_median_doy": round(pct(agro, 50), 1)})
    df = pd.DataFrame(rows)
    out = BASE / "outputs" / f"model_onsets_{Path(nwp_f).stem.split('_')[1]}.csv"
    df.to_csv(out, index=False)
    for site, g in df.groupby("site", sort=False):
        print(f"\n{site}")
        print(g[["run", "source", "model_last_day", "dunning_median", "dunning_range", "planting_median", "planting_range",
                 "planting_within_model_days"]].to_string(index=False))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
