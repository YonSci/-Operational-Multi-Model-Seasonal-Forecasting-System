#!/usr/bin/env python3
"""
export_dashboard_data.py
────────────────────────
Flatten the latest Short Rains results into small CSV files for the online tracker dashboard.

Reads: outputs/site_reports/<latest>/*.json, outputs/realtime_rain/monitor_<latest>.{json,nc},
       outputs/realtime_rain/verification_chirps.csv, outputs/ecmwf_ens/ens_outlook_<latest>.nc,
       <seasonal>/agro_onset/*, outputs/site_tracker/Kapiti_Research_Station_Farm/inits_summary.csv
Writes: outputs/dashboard/{sites,seasonal,ens_daily,rain_daily,zone,verification,grid,inits}.csv
"""
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "outputs" / "dashboard"
sys.path.insert(0, str(BASE / "scripts"))


def latest(pattern):
    f = sorted(glob.glob(str(BASE / pattern)))
    return Path(f[-1]) if f else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rep_dir = Path(sorted(glob.glob(str(BASE / "outputs" / "site_reports" / "20*")))[-1])
    reps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(rep_dir.glob("*.json"))]

    sites, seas, ensd, rain = [], [], [], []
    for R in reps:
        o, e, P = R["observed"], R.get("ens") or {}, R.get("products", {})
        a = R["seasonal"].get("agro_onset", {})
        row = {"site": R["site"], "lat": R["lat"], "lon": R["lon"], "issued": R["issued"],
               "obs_through": o["through"], "rain_since_oct1_chirps_mm": o["oct_total_mm"],
               "normal_same_days_mm": o["normal_same_days_mm"], "pct_of_normal": o["pct_of_normal"],
               "products_with_onset": len(o.get("products_with_onset", [])), "products": len(P),
               "ens_init": e.get("init"), "p_event_7d": e.get("p_trigger_7d"), "p_event_15d": e.get("p_trigger_15d"),
               "p_onset_15d": e.get("p_onset_15d"),
               "ens_onset_median": e.get("composite_onset", {}).get("median"),
               "ens_onset_likely": f"{e['composite_onset']['p25']} – {e['composite_onset']['p75']}" if e else None,
               "season_onset_median": a.get("median"), "season_onset_likely": a.get("likely_range"),
               "season_p_early": a.get("p", {}).get("early"), "season_p_normal": a.get("p", {}).get("normal"),
               "season_p_late": a.get("p", {}).get("late"), "season_normal": a.get("normal"),
               "season_skill": a.get("skill", {}).get("category"), "season_mae_days": a.get("skill", {}).get("mae"),
               "condition": R.get("condition") or ""}
        for p, v in P.items():
            row[f"rain_since_oct1_{p}_mm"] = v["oct_total_mm"]
            row[f"through_{p}"] = v["through"]
        sites.append(row)
        for k, v in R["seasonal"].items():
            lr, wr = v["likely_range"].split(" – "), v["wide_range"].split(" – ")
            pv = list(v["p"].values())
            seas.append({"site": R["site"], "variable": k, "label": v["label"], "median": v["median"],
                         "likely_from": lr[0], "likely_to": lr[-1], "wide_from": wr[0], "wide_to": wr[-1],
                         "p_low": pv[0], "p_mid": pv[1], "p_high": pv[2], "normal": v["normal"], "normal_band": v["normal_band"],
                         "skill": v["skill"]["category"], "rpss_val": v["skill"]["rpss_val"], "corr": v["skill"]["corr"],
                         "mae_days": v["skill"]["mae"], "members": v["n_members"], "flags": "; ".join(v["flags"]),
                         "unit": "days" if k == "lgp" else "day of year",
                         **{f"{n}_value": v.get("num", {}).get(n) for n in ("p10", "p25", "p50", "p75", "p90", "normal", "t33", "t67", "obs_min", "obs_max")}})
        for d in e.get("daily", []):
            ensd.append({"site": R["site"], **d})
    import realtime_rain as rr
    for R in reps:
        df = rr.site_series(R["lat"], R["lon"], "2026-09-01")
        for p in df.columns:
            for t, v in df[p].dropna().items():
                rain.append({"site": R["site"], "date": str(t.date()), "product": p, "mm": round(float(v), 2)})

    pd.DataFrame(sites).to_csv(OUT / "sites.csv", index=False)
    pd.DataFrame(seas).to_csv(OUT / "seasonal.csv", index=False)
    pd.DataFrame(ensd).to_csv(OUT / "ens_daily.csv", index=False)
    pd.DataFrame(rain).to_csv(OUT / "rain_daily.csv", index=False)

    # Kenya OND-zone monitoring per product
    mon = latest("outputs/realtime_rain/monitor_*.json")
    zone = [{"product": p, **v} for p, v in json.loads(mon.read_text())["products"].items()] if mon else []
    pd.DataFrame(zone).to_csv(OUT / "zone.csv", index=False)

    ver = BASE / "outputs" / "realtime_rain" / "verification_chirps.csv"
    if ver.exists():
        v = pd.read_csv(ver)
        v.round(3).to_csv(OUT / "verification.csv", index=False)

    # Gridded fields for the maps (one row per 0.25° cell in the Kenya box)
    mnc = latest("outputs/realtime_rain/monitor_*.nc")
    ens = latest("outputs/ecmwf_ens/ens_outlook_*.nc")
    sd = BASE / "outputs" / "ecmwf_oct_obs_latest" / "agro_onset"
    g = xr.open_dataset(mnc)
    lat, lon = g.lat.values, g.lon.values
    zone_mask = rr.ond_mask()
    cols = {"lat": np.repeat(lat, len(lon)), "lon": np.tile(lon, len(lat)), "in_zone": zone_mask.ravel().astype(int)}
    for p in ["chirps", "arc2", "tamsat", "pdirnow", "imerg", "imerg_early", "imerg_gee", "gsmap_gee"]:
        if f"{p}_total" in g:
            cols[f"{p}_total_mm"] = g[f"{p}_total"].values.ravel().round(1)
            cols[f"{p}_pct_normal"] = g[f"{p}_pct"].values.ravel().round(0)
            cols[f"{p}_onset_detected"] = np.isfinite(g[f"{p}_onset_day"].values).ravel().astype(int)
    if ens:
        E = xr.open_dataset(ens)
        cols["ens_p_event_7d"] = E["p_trigger_7d"].values.ravel().round(2)
        cols["ens_p_onset_15d"] = E["p_onset_15d"].values.ravel().round(2)
    if sd.exists():
        p = xr.open_dataarray(sd / "probs_op_2026_agro_onset.nc").values
        cols["season_p_early"], cols["season_p_late"] = p[0].ravel().round(2), p[2].ravel().round(2)
        cols["season_rpss_val"] = xr.open_dataarray(sd / "rpss_val_agro_onset.nc").values.ravel().round(2)
    grid = pd.DataFrame(cols)
    grid = grid[np.isfinite(grid.get("chirps_total_mm", grid["lat"]))]
    grid.to_csv(OUT / "grid.csv", index=False)

    # Day-by-day fields since 1 Oct for the animation: daily rain, rain so far, normal so far (CHIRPS 1993–2016
    # mean of the same calendar days), anomaly (mm) and % of normal, per product and 0.25° cell
    since = pd.Timestamp("2026-10-01")
    rec = rr.load_chirps()
    rec_cal = rec.sel(time=slice("1993-01-01", "2016-12-31"))
    md_all = pd.DatetimeIndex(rec_cal.time.values).strftime("%m-%d")
    keep = np.isfinite(rec.sel(time=slice("1993", "2016")).mean("time").values)        # cells with a CHIRPS record
    anim = []
    end = pd.Timestamp.today().normalize()
    days = pd.date_range(since, end)
    normal_daily = np.stack([rec_cal.isel(time=np.where(md_all == f"{d:%m-%d}")[0]).mean("time").values for d in days])
    normal_cum = np.cumsum(normal_daily, axis=0)
    ii, jj = np.where(keep)
    for p in ["chirps", "arc2", "tamsat", "pdirnow", "imerg", "imerg_early", "imerg_gee", "gsmap_gee"]:
        F = rr.load(p)
        if F is None:
            continue
        F = F.reindex(time=days)
        v = F.values
        have = np.isfinite(v).any(axis=(1, 2))
        cum = np.cumsum(np.nan_to_num(v), axis=0)
        for k, d in enumerate(days):
            if not have[k] or not have[: k + 1].all():          # stop at the first missing day of this product
                break
            r, c, n = v[k, ii, jj], cum[k, ii, jj], normal_cum[k, ii, jj]
            with np.errstate(invalid="ignore", divide="ignore"):
                pct = np.where(n > 0.5, 100 * c / n, np.nan)
            anim.append(pd.DataFrame({"date": str(d.date()), "product": p, "lat": rr.LAT[ii], "lon": rr.LON[jj],
                                      "rain_mm": np.round(r, 1), "rain_since_oct1_mm": np.round(c, 1),
                                      "normal_since_oct1_mm": np.round(n, 1), "anomaly_mm": np.round(c - n, 1),
                                      "pct_of_normal": np.round(pct, 0)}))
    if anim:
        a = pd.concat(anim)
        a = a[np.isfinite(a.rain_mm)]
        a.to_csv(OUT / "anim.csv", index=False)

    # Multi-model 10–16 day forecasts (fetch_nwp_forecasts.py): grid maps, station series, planting-rain summary
    nwp_f = latest("data/nwp/nwp_*.csv")
    if nwp_f:
        labels = {"ecmwf_ifs025": "ECMWF IFS", "ecmwf_ens_median": "ECMWF ENS median", "gfs_global": "GFS (NOAA)",
                  "icon_global": "ICON (DWD)", "gem_global": "GDPS (ECCC)", "ukmo_global_deterministic_10km": "UKMO (Met Office)"}
        nw = pd.read_csv(nwp_f).sort_values(["model", "kind", "site", "lat", "lon", "date"])
        nw["model_label"] = nw.model.map(labels).fillna(nw.model)
        nw["cum_mm"] = nw.groupby(["model", "kind", "site", "lat", "lon"]).rain_mm.cumsum().round(1)
        nw[nw.kind == "grid"][["model", "model_label", "date", "lat", "lon", "rain_mm", "cum_mm"]].to_csv(OUT / "forecast.csv", index=False)
        st = nw[nw.kind == "station"].copy()
        short = {r["site"]: r["short_name"] for r in pd.read_csv(OUT / "stations.csv").to_dict("records")} if (OUT / "stations.csv").exists() else {}
        st["short_name"] = st.site.map(short).fillna(st.site)
        st[["model", "model_label", "site", "short_name", "date", "rain_mm", "cum_mm"]].to_csv(OUT / "forecast_sites.csv", index=False)
        ev = []
        for (m, site), g in st.groupby(["model", "site"]):
            r = g.rain_mm.values
            acc = np.array([r[k:k + 3].sum() for k in range(len(r))])
            trig = np.where((r >= 1.0) & (acc >= 20.0))[0]
            first = g.date.values[trig[0]] if len(trig) else ""
            src = g["source"].iloc[0] if "source" in g else "open-meteo"
            ev.append({"model": m, "model_label": labels.get(m, m), "source": "direct" if src == "direct" else "Open-Meteo",
                       "site": site, "short_name": short.get(site, site),
                       "horizon_days": len(r), "total_7d_mm": round(float(r[:7].sum()), 1), "total_all_mm": round(float(r.sum()), 1),
                       "first_planting_rain": first, "planting_rain_within_7d": int(len(trig) > 0 and trig[0] < 7)})
        pd.DataFrame(ev).to_csv(OUT / "forecast_events.csv", index=False)

    # Forecast-run (initialization) comparison for every station (track_site_inits.py)
    site_by_slug = {re.sub(r"[^A-Za-z0-9]+", "_", R["site"]).strip("_"): R["site"] for R in reps}
    parts = []
    for f in sorted((BASE / "outputs" / "site_tracker").glob("*/inits_summary.csv")):
        d = pd.read_csv(f)
        d.insert(0, "site", site_by_slug.get(f.parent.name, f.parent.name.replace("_", " ")))
        parts.append(d)
    if parts:
        pd.concat(parts).to_csv(OUT / "inits.csv", index=False)
    for f in sorted(OUT.glob("*.csv")):
        print(f"  {f.name:18s} {f.stat().st_size / 1024:7.1f} KB  {len(pd.read_csv(f))} rows")


if __name__ == "__main__":
    main()
