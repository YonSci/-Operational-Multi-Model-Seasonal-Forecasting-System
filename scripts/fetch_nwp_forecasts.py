#!/usr/bin/env python3
"""
fetch_nwp_forecasts.py
──────────────────────
10–16 day daily precipitation forecasts from several global models for Kenya (0.5° points inside
Kenya + the monitored stations), via the Open-Meteo forecast API (https://open-meteo.com, CC-BY 4.0,
free for non-commercial use), which serves each centre's own model output:

  ecmwf_ifs025                     ECMWF IFS (deterministic, 0.25°)   15 days
  gfs_global                       NOAA GFS                           16 days
  icon_global                      DWD ICON                           ~7 days
  gem_global                       ECCC GDPS (GEM)                    10 days
  ukmo_global_deterministic_10km   UK Met Office global               ~7 days
plus the ECMWF ensemble median from our own ENS download (data/ecmwf_ens, fetch_ecmwf_ens.py).

Days are local (Africa/Nairobi). Output: data/nwp/nwp_<YYYYMMDD>.csv
  columns: model, kind (grid|station), site, lat, lon, date, rain_mm
"""
import datetime as dt
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "nwp"
MODELS = ["ecmwf_ifs025", "gfs_global", "icon_global", "gem_global", "ukmo_global_deterministic_10km"]
API = "https://api.open-meteo.com/v1/forecast"
SINGLE_RUNS_API = "https://single-runs-api.open-meteo.com/v1/forecast"   # past runs, each as issued
BATCH = 50


def kenya_points():
    from shapely.geometry import Point, shape
    rows = json.loads((BASE / "outputs" / "dashboard" / "boundaries.json").read_text())
    ke = [shape(r["geometry"]) for r in rows if r["level"] == "country"][0].buffer(0.3)
    lats = np.round(np.arange(-4.75, 5.26, 0.5), 2)
    lons = np.round(np.arange(33.75, 41.76, 0.5), 2)
    return [(la, lo) for la in lats for lo in lons if ke.contains(Point(lo, la))]


def stations():
    sys.path.insert(0, str(BASE / "backend"))
    import mam_loader as ml
    return [(s["site_name"], s["lat"], s["lon"]) for s in ml.SITES if s["country"] == "kenya"]


def fetch_batch(points, run=None):
    """Daily rain per point and model; with `run` (a date), that day's 00 UTC run from Open-Meteo's archive of past runs."""
    q = {"latitude": ",".join(f"{p[0]:.3f}" for p in points), "longitude": ",".join(f"{p[1]:.3f}" for p in points),
         "daily": "precipitation_sum", "models": ",".join(MODELS), "forecast_days": 16, "timezone": "Africa/Nairobi"}
    api = API
    if run is not None:
        # the archive gives daily sums only in UTC, and leaves the run's first day empty (no rain at hour 0), so
        # sum the hourly rain instead: hours 01–24 UTC make the day, as in the direct downloads
        api = SINGLE_RUNS_API
        del q["daily"]
        q.update(hourly="precipitation", timezone="GMT", run=f"{run:%Y-%m-%d}T00:00")
    for k in range(6):
        try:
            r = requests.get(api, params=q, timeout=120)
            if r.status_code == 429:
                time.sleep(30 * (k + 1)); continue
            r.raise_for_status()
            d = r.json()
            d = d if isinstance(d, list) else [d]
            return [_hourly_to_daily(x) for x in d] if run is not None else d
        except requests.RequestException:
            time.sleep(10 * (k + 1))
    raise RuntimeError("Open-Meteo request failed")


def _hourly_to_daily(d):
    """Open-Meteo hourly rain → {"daily": {"time", "precipitation_sum[_<model>]"}}; days with a missing hour are None."""
    t = pd.DatetimeIndex(d["hourly"]["time"]) - pd.Timedelta(hours=1)     # rain at hh:00 fell in the hour before
    out = {}
    for key, vals in d["hourly"].items():
        if key == "time":
            continue
        s = pd.Series(np.array(vals, dtype=float), index=t)
        g = s.groupby(s.index.normalize())
        day = g.sum().where(g.count() == 24)
        out[key.replace("precipitation", "precipitation_sum", 1)] = [None if np.isnan(v) else round(float(v), 2) for v in day.values]
    out["time"] = [f"{x:%Y-%m-%d}" for x in day.index]
    return {"daily": out}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    pts = [("grid", "", la, lo) for la, lo in kenya_points()] + [("station", n, la, lo) for n, la, lo in stations()]
    rows = []
    for i in range(0, len(pts), BATCH):
        chunk = pts[i:i + BATCH]
        res = fetch_batch([(p[2], p[3]) for p in chunk])
        for (kind, site, la, lo), d in zip(chunk, res):
            daily = d["daily"]
            for m in MODELS:
                vals = daily.get(f"precipitation_sum_{m}")
                if vals is None:
                    continue
                for t, v in zip(daily["time"], vals):
                    if v is not None:
                        rows.append({"model": m, "kind": kind, "site": site, "lat": la, "lon": lo, "date": t, "rain_mm": round(float(v), 1)})
        print(f"  Open-Meteo {min(i + BATCH, len(pts))}/{len(pts)} points", flush=True)
        time.sleep(1)

    # ECMWF ensemble median (our own ENS download), on the same points
    ens_f = sorted(glob.glob(str(BASE / "data" / "ecmwf_ens" / "ens_tp_*_kenya.nc")))
    if ens_f:
        e = xr.open_dataset(ens_f[-1])["precip"].median("member")
        for kind, site, la, lo in pts:
            sub = e.sel(lat=slice(la - 0.25, la + 0.25), lon=slice(lo - 0.25, lo + 0.25)) if kind == "grid" else \
                  e.sel(lat=la, lon=lo, method="nearest")
            s = sub.mean(("lat", "lon")) if kind == "grid" else sub
            for t, v in zip(pd.DatetimeIndex(s.time.values), s.values):
                if np.isfinite(v):
                    rows.append({"model": "ecmwf_ens_median", "kind": kind, "site": site, "lat": la, "lon": lo,
                                 "date": str(t.date()), "rain_mm": round(float(v), 1)})
    df = pd.DataFrame(rows)
    out = OUT / f"nwp_{dt.date.today():%Y%m%d}.csv"
    df.to_csv(out, index=False)
    print(f"wrote {out}: {len(df)} rows; days per model:",
          df[df.kind == "station"].groupby("model").date.nunique().to_dict())


if __name__ == "__main__":
    main()
