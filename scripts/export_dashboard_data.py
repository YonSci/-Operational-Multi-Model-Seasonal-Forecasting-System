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


# Product catalogue for the tracker's "Data sources" section: static facts here, latest data read from the files.
# kind: obs = observed/estimated rainfall, nwp = 1–16 day forecast, seasonal = SEAS5
PRODUCTS = [
    dict(id="chirps", kind="obs", name="CHIRPS 2.0", provider="UC Santa Barbara Climate Hazards Center",
         resolution="0.05° (used at 0.25°)", typical_latency="final ~3 weeks after the month; preliminary ~2–5 days",
         link="https://www.chc.ucsb.edu/data/chirps",
         about="Satellite infrared rainfall blended with rain-gauge reports, 1981 to present. The reference for this "
               "tracker: climatology (1993–2016), bias correction and verification all use CHIRPS. The final record "
               "ends with the last complete month; preliminary daily files fill the days after it."),
    dict(id="arc2", kind="obs", name="ARC2", provider="NOAA Climate Prediction Center (FEWS NET)",
         resolution="0.1°", typical_latency="~1–2 days", link="https://www.cpc.ncep.noaa.gov/products/fews/",
         about="Africa Rainfall Climatology v2: Meteosat infrared cloud-top temperatures merged with daily GTS rain-gauge "
               "reports. Quick and long record; tends to miss light rain and shows occasional single-cell spikes."),
    dict(id="tamsat", kind="obs", name="TAMSAT v3.1", provider="University of Reading",
         resolution="0.0375°", typical_latency="~2–5 days", link="https://www.tamsat.org.uk/",
         about="Africa-only rainfall from Meteosat thermal-infrared cold-cloud duration, calibrated against "
               "historical gauges. Good at telling rain from no rain; weaker for heavy amounts."),
    dict(id="pdirnow", kind="obs", name="PDIR-Now", provider="UC Irvine CHRS",
         resolution="0.04°", typical_latency="~1 day", link="https://chrsdata.eng.uci.edu/",
         about="Precipitation from infrared imagery by a neural network (PERSIANN family), near-global, quasi-real-time. "
               "Fastest product here; no gauge correction."),
    dict(id="imerg", kind="obs", name="IMERG Late (V07)", provider="NASA GPM",
         resolution="0.1°", typical_latency="~14 hours (daily file ~1–2 days)", link="https://gpm.nasa.gov/data/imerg",
         about="Integrated Multi-satellitE Retrievals for GPM: passive-microwave rainfall from the GPM constellation, "
               "gaps filled with infrared; the Late run has more microwave overpasses than Early. Fetched as a Kenya "
               "subset through NASA's cloud OPeNDAP (Earthdata login)."),
    dict(id="imerg_early", kind="obs", name="IMERG Early (V07)", provider="NASA GPM",
         resolution="0.1°", typical_latency="~4 hours (daily file ~1 day)", link="https://gpm.nasa.gov/data/imerg",
         about="Same algorithm as IMERG Late, issued sooner with fewer satellite overpasses; for monitoring when speed matters."),
    dict(id="imerg_gee", kind="obs", name="IMERG via Earth Engine", provider="NASA GPM / Google Earth Engine",
         resolution="0.1°", typical_latency="as IMERG",
         link="https://developers.google.com/earth-engine/datasets/catalog/NASA_GPM_L3_IMERG_V07",
         about="Half-hourly IMERG summed to daily in Google Earth Engine; an alternative route when NASA servers are unreachable."),
    dict(id="gsmap_gee", kind="obs", name="GSMaP Gauge (operational v8)", provider="JAXA / Google Earth Engine",
         resolution="0.1°", typical_latency="~3 days (gauge-adjusted)",
         link="https://developers.google.com/earth-engine/datasets/catalog/JAXA_GPM_L3_GSMaP_v8_operational",
         about="Global Satellite Mapping of Precipitation: microwave + infrared rainfall adjusted to the CPC gauge analysis. "
               "Needs an Earth Engine project (or a JAXA G-Portal account) before it can be downloaded."),
    dict(id="ecmwf_ifs025", kind="nwp", name="ECMWF IFS (HRES)", provider="ECMWF", resolution="0.25° open data",
         typical_latency="00 UTC run published ~7–9 h later", link="https://www.ecmwf.int/en/forecasts/datasets/open-data",
         about="ECMWF's deterministic global forecast, 15 days."),
    dict(id="ecmwf_ens_median", kind="nwp", name="ECMWF ensemble (ENS)", provider="ECMWF", resolution="0.25° open data",
         typical_latency="00 UTC run published ~8–10 h later", link="https://www.ecmwf.int/en/forecasts/datasets/open-data",
         about="51-member ensemble, 15 days. The maps show the member median; the planting-rain chances use all 50 perturbed members."),
    dict(id="gfs_global", kind="nwp", name="GFS", provider="NOAA NCEP", resolution="0.25°",
         typical_latency="00 UTC run published ~3.5–5 h later", link="https://nomads.ncep.noaa.gov/",
         about="NOAA's Global Forecast System, 16 days."),
    dict(id="gem_global", kind="nwp", name="GDPS", provider="Environment and Climate Change Canada", resolution="15 km",
         typical_latency="00 UTC run published ~4–6 h later", link="https://dd.weather.gc.ca/",
         about="Canada's Global Deterministic Prediction System (GEM model), 10 days."),
    dict(id="icon_global", kind="nwp", name="ICON", provider="Deutscher Wetterdienst (DWD)", resolution="13 km icosahedral",
         typical_latency="00 UTC run published ~3–4 h later", link="https://opendata.dwd.de/weather/nwp/icon/",
         about="Germany's ICOsahedral Nonhydrostatic global model, 7.5 days on the open-data server."),
    dict(id="ukmo_global_deterministic_10km", kind="nwp", name="UKMO Global", provider="Met Office", resolution="10 km",
         typical_latency="00 UTC run published ~5–6 h later",
         link="https://registry.opendata.aws/met-office-global-deterministic/",
         about="Met Office Unified Model global deterministic forecast on AWS open data, 7 days used here."),
    dict(id="seas5", kind="seasonal", name="ECMWF SEAS5", provider="ECMWF / Copernicus C3S",
         resolution="1° (bias-corrected to 0.25°)", typical_latency="new start every month, published on the 5th",
         link="https://cds.climate.copernicus.eu/",
         about="Seasonal ensemble (25 members for the forecast, hindcasts 1993–2016), bias-corrected against CHIRPS; observed "
               "CHIRPS replaces the forecast up to the latest observed day."),
]


def product_status(today):
    """Latest data per product from the files on disk → one row per catalogue entry."""
    rows, last_obs = [], {}
    for p in ["arc2", "tamsat", "pdirnow", "imerg", "imerg_early", "imerg_gee", "gsmap_gee"]:
        f = BASE / "data" / "realtime_rain" / f"{p}_kenya_p25.nc"
        if f.exists():
            with xr.open_dataset(f) as ds:
                last_obs[p] = pd.Timestamp(ds.time.values.max()).date()
    ends = []
    for f in (BASE / "data" / "chirps_2026" / "chirps-v2.0.2026.days_p25.nc",
              BASE / "data" / "chirps_prelim_2026" / "chirps_prelim_2026_p25_kenya.nc"):
        if f.exists():
            with xr.open_dataset(f) as ds:
                ends.append(pd.Timestamp(ds.time.values.max()).date())
    if ends:
        last_obs["chirps"] = max(ends)
    nwp = {}
    nwp_f = latest("data/nwp/nwp_*.csv")
    if nwp_f:
        n = pd.read_csv(nwp_f)
        for m, g in n.groupby("model"):
            # day 1 of a 00 UTC run is the run date itself
            nwp[m] = (pd.Timestamp(g.date.min()).date(), pd.Timestamp(g.date.max()).date(),
                      g["source"].iloc[0] if "source" in g else "open-meteo")
    meta_p = BASE / "outputs" / "ecmwf_oct_obs_latest" / "run_meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    init = meta.get("init", "2026-10-01")
    for P in PRODUCTS:
        r = {k: P[k] for k in ("id", "kind", "name", "provider", "resolution", "typical_latency", "about", "link")}
        r.update(latest_data="", days_behind=None, run_date="", forecast_to="", note="")
        if P["kind"] == "obs":
            if P["id"] in last_obs:
                d = last_obs[P["id"]]
                r.update(latest_data=str(d), days_behind=(today - d).days)
                if P["id"] == "chirps" and len(ends) == 2:
                    r["note"] = f"final record to {ends[0]}, preliminary days after"
            else:
                r["note"] = "not downloaded yet (needs an account or project)"
        elif P["kind"] == "nwp":
            if P["id"] in nwp:
                run, to, src = nwp[P["id"]]
                r.update(latest_data=f"{run} 00 UTC run", run_date=str(run), forecast_to=str(to), days_behind=(today - run).days,
                         note="direct from the provider" if src == "direct" else "through Open-Meteo")
        else:
            r.update(latest_data=f"{init} start", run_date=init, forecast_to="2026-12-31",
                     days_behind=(today - pd.Timestamp(init).date()).days,
                     note=f"observations spliced in to {meta.get('obs_end', '')}; next start 1 Nov, published 5 Nov")
        r["checked"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
        rows.append(r)
    return pd.DataFrame(rows)


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
        # 5- and 10-day totals ending on each day use the days before 1 Oct as well
        full = F.reindex(time=pd.date_range(since - pd.Timedelta(days=9), end))
        roll5 = full.rolling(time=5, min_periods=5).sum().reindex(time=days).values
        roll10 = full.rolling(time=10, min_periods=10).sum().reindex(time=days).values
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
                                      "rain_mm": np.round(r, 1), "rain_5d_mm": np.round(roll5[k, ii, jj], 1),
                                      "rain_10d_mm": np.round(roll10[k, ii, jj], 1), "rain_since_oct1_mm": np.round(c, 1),
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
        nw = pd.read_csv(nwp_f)
        nw["site"] = nw["site"].fillna("")          # grid points have no site; NaN keys would be dropped by groupby
        # a model from an older run (e.g. yesterday's ENS when today's download failed) starts on the newest
        # run's first day, so every model's "next 5/10 days" covers the same dates
        nw = nw[nw.date >= nw.groupby("model").date.min().max()]
        nw = nw.sort_values(["model", "kind", "site", "lat", "lon", "date"])
        nw["model_label"] = nw.model.map(labels).fillna(nw.model)
        keys = ["model", "kind", "site", "lat", "lon"]
        nw["cum_mm"] = nw.groupby(keys, dropna=False).rain_mm.cumsum().round(1)
        nw[nw.kind == "grid"][["model", "model_label", "date", "lat", "lon", "rain_mm", "cum_mm"]].to_csv(OUT / "forecast.csv", index=False)
        # Totals over the next 5 days, next 10 days and the model's whole range, per grid point (maps)
        gr = nw[nw.kind == "grid"].copy()
        gr["k"] = gr.groupby(keys, dropna=False).cumcount()                  # day index within each model's run
        gr["r5"], gr["r10"] = gr.rain_mm.where(gr.k < 5), gr.rain_mm.where(gr.k < 10)
        tot = gr.groupby(["model", "model_label", "lat", "lon"]).agg(horizon_days=("rain_mm", "size"), total_5d_mm=("r5", "sum"),
                                                                    total_10d_mm=("r10", "sum"), total_all_mm=("rain_mm", "sum")).round(1).reset_index()
        tot["first_day"] = nw.date.min()
        tot.to_csv(OUT / "forecast_totals.csv", index=False)
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
                       "horizon_days": len(r), "total_5d_mm": round(float(r[:5].sum()), 1), "total_7d_mm": round(float(r[:7].sum()), 1),
                       "total_10d_mm": round(float(r[:10].sum()), 1), "total_all_mm": round(float(r.sum()), 1),
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
    # every member's value per run / definition (Season outlook member dots)
    mem = []
    for f in sorted((BASE / "outputs" / "site_tracker").glob("*/inits_members.csv")):
        d = pd.read_csv(f)
        d.insert(0, "site", site_by_slug.get(f.parent.name, f.parent.name.replace("_", " ")))
        mem.append(d)
    if mem:
        m = pd.concat(mem)
        if "definition" not in m:
            m["definition"] = ""
        m["value"] = m["value"].round(1)
        m.to_csv(OUT / "inits_members.csv", index=False)
    product_status(pd.Timestamp.today().date()).to_csv(OUT / "products.csv", index=False)
    for f in sorted(OUT.glob("*.csv")):
        print(f"  {f.name:18s} {f.stat().st_size / 1024:7.1f} KB  {len(pd.read_csv(f))} rows")


if __name__ == "__main__":
    main()
