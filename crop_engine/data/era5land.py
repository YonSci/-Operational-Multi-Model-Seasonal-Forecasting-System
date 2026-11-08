"""
Daily maximum and minimum 2 m temperature at each site from ERA5-Land (0.1°), via the Open-Meteo historical weather
API (https://open-meteo.com, CC-BY 4.0), which serves ERA5-Land at the point. Cached per site in data/crop_engine/
and topped up each run (ERA5-Land runs about 5 days behind real time). Days without ERA5-Land use the 1993–2016
day-of-year climatology (crop_engine.data.weather marks them).

ET0 is not taken from here: the engine uses the platform's own ERA5-Land FAO-56 ET0 (scripts/fao_water_balance.py),
so the crop model and the FAO water balance see the same evaporative demand.

Solar radiation, humidity and wind (site_met), for engines that compute their own evaporation (WOFOST): the same
ERA5-Land fields the platform's ET0 is built from (scripts/fao_era5land_gee.py), from Google Earth Engine at the
ERA5-Land 0.1° cell of each site (Open-Meteo serves no ERA5-Land radiation or wind):
  surface_solar_radiation_downwards_sum (DAILY_AGGR, UTC day)  → rad_mj_m2
  dewpoint_temperature_2m (DAILY_AGGR, daily mean)            → vap_hpa, FAO-56 Eq. 14 at the dewpoint
  10 m wind speed at 00, 06, 12, 18 UTC (HOURLY), the mean     → wind2_ms, FAO-56 Eq. 47 (as the platform's ET0)
  surface_pressure (DAILY_AGGR)                                → sp_kpa (the site elevation, as the platform's ET0)
Cached per site in data/crop_engine/ and topped up as the temperature.
"""
import datetime as dt
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from crop_engine.config import CACHE, CAL_YEARS

import fao_water_balance as fw  # noqa: E402  (scripts/, on sys.path via config)

API = "https://archive-api.open-meteo.com/v1/archive"
FIRST = dt.date(1993, 1, 1)


def _fetch(lat, lon, start, end):
    q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "start_date": f"{start}", "end_date": f"{end}",
         "daily": "temperature_2m_max,temperature_2m_min", "models": "era5_land", "timezone": "GMT"}
    for k in range(5):
        try:
            r = requests.get(API, params=q, timeout=180)
            if r.status_code == 429:
                time.sleep(30 * (k + 1))
                continue
            if 400 <= r.status_code < 500:                              # a bad request is not retried
                raise RuntimeError(f"ERA5-Land temperature for {lat}, {lon}: HTTP {r.status_code} "
                                   f"{r.json().get('reason', '') if 'json' in r.headers.get('content-type', '') else ''}")
            r.raise_for_status()
            d = r.json()["daily"]
            df = pd.DataFrame({"date": pd.to_datetime(d["time"]), "tmax": d["temperature_2m_max"], "tmin": d["temperature_2m_min"]})
            return df.dropna()
        except requests.RequestException:
            time.sleep(10 * (k + 1))
    raise RuntimeError(f"ERA5-Land temperature download failed for {lat}, {lon}")


def site_temperature(site, today=None, refresh=True):
    """DataFrame indexed by date: tmax, tmin (°C), ERA5-Land, 1 Jan 1993 to the last available day."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"era5land_t2m_{site.id}_{site.lat:.4f}_{site.lon:.4f}.csv"      # a moved site is fetched again
    # the archive's dates are UTC: between midnight and 03:00 in Kenya, the local date is a day past its last allowed one
    today = today or dt.datetime.now(dt.timezone.utc).date()
    df = pd.read_csv(path, parse_dates=["date"]) if path.exists() and path.stat().st_size else None
    fetched = False
    if df is None or df.empty:
        df, fetched = _fetch(site.lat, site.lon, FIRST, today), True
    elif refresh:
        last = df.date.max().date()
        if (today - last).days > 2:
            new = _fetch(site.lat, site.lon, last - dt.timedelta(days=7), today)
            df, fetched = pd.concat([df[df.date < pd.Timestamp(last - dt.timedelta(days=7))], new], ignore_index=True), True
    df = df.drop_duplicates("date", keep="last").sort_values("date")
    if fetched:                       # written only when it changed, and whole: parallel runs read the same cache
        tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
        df.to_csv(tmp, index=False, float_format="%.2f")
        os.replace(tmp, path)
    return df.set_index("date")


def climatology(series, years=CAL_YEARS, half_window=7):
    """Day-of-year mean (366 values, no-leap numbering with 29 Feb = 28 Feb) over `years`, ±half_window smoothed."""
    s = series[(series.index.year >= years[0]) & (series.index.year <= years[1])]
    doy = np.minimum(s.index.dayofyear.values - ((s.index.is_leap_year) & (s.index.month > 2)).astype(int), 365)
    raw = pd.Series(s.values).groupby(doy).mean().reindex(range(1, 366)).interpolate(limit_direction="both").values
    pad = np.concatenate([raw[-half_window:], raw, raw[:half_window]])
    k = 2 * half_window + 1
    smooth = np.convolve(pad, np.ones(k) / k, mode="valid")
    return np.append(smooth, smooth[-1])             # index doy-1; 366th for safety


def doy_noleap(dates):
    d = pd.DatetimeIndex(dates)
    return np.minimum(d.dayofyear.values - ((d.is_leap_year) & (d.month > 2)).astype(int), 365)


# ── solar radiation, humidity and wind (ERA5-Land, Earth Engine) ─────────────
EE_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"
EE_HOURLY = "ECMWF/ERA5_LAND/HOURLY"
EE_GRID = [0.1, 0, -180.05, 0, -0.1, 90.05]              # ERA5-Land's native 0.1° cells: sampled at their centres
RAW = ["rad_mj_m2", "dewpoint_c", "wind10_ms", "sp_kpa"]   # cached
MET = ["rad_mj_m2", "vap_hpa", "wind2_ms"]                 # served (with sp_kpa)


def _log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] era5land: {m}", flush=True)


def cell_of(lat, lon):
    """Centre (lat, lon) of the ERA5-Land 0.1° cell holding a point."""
    return round(round(lat * 10) / 10, 1), round(round(lon * 10) / 10, 1)


def met_path(site):
    return CACHE / f"era5land_met_{site.id}_{site.lat:.4f}_{site.lon:.4f}.csv"   # a moved site is fetched again


def rows_to_frames(daily, wind, sites):
    """Earth Engine getRegion rows (header first) of the daily fields and of the 6-hourly wind speed → {site id:
    DataFrame of RAW by date}. Rows are matched to sites by their 0.1° cell (sites in one cell share it)."""
    def frame(rows):
        df = pd.DataFrame(rows[1:], columns=rows[0])
        df["cell"] = [cell_of(a, o) for a, o in zip(df.latitude, df.longitude)]
        df["date"] = pd.to_datetime(df.time, unit="ms").dt.normalize()
        return df
    d, w = frame(daily), frame(wind)
    d = d.assign(rad_mj_m2=d.surface_solar_radiation_downwards_sum / 1e6, dewpoint_c=d.dewpoint_temperature_2m - 273.15,
                 sp_kpa=d.surface_pressure / 1000.0)
    w = w.groupby(["cell", "date"]).wind.mean().rename("wind10_ms").reset_index()
    both = d.merge(w, on=["cell", "date"], how="left")
    return {s.id: both[both.cell == cell_of(s.lat, s.lon)].set_index("date")[RAW].sort_index() for s in sites}


def _ee_fetch(sites, start, end):
    """RAW of the sites from start to end (dates, inclusive), one calendar year per Earth Engine request."""
    import fao_era5land_gee as gee  # noqa: E402  (Earth Engine: imported only when fetching)
    ee = gee.init_ee()
    pts = ee.Geometry.MultiPoint([[lo, la] for la, lo in sorted({cell_of(s.lat, s.lon) for s in sites})])
    daily = ee.ImageCollection(EE_DAILY).select(["dewpoint_temperature_2m", "surface_solar_radiation_downwards_sum",
                                                 "surface_pressure"])
    uv = ee.ImageCollection(EE_HOURLY).select(["u_component_of_wind_10m", "v_component_of_wind_10m"]).filter(gee.SYNOPTIC)

    def span(a, b):
        e = (b + dt.timedelta(days=1)).isoformat()
        speed = uv.filterDate(a.isoformat(), e).map(lambda im: im.expression(
            "sqrt(u*u + v*v)", {"u": im.select(0), "v": im.select(1)}).rename("wind").copyProperties(im, ["system:time_start"]))
        for k in range(5):
            try:
                return (daily.filterDate(a.isoformat(), e).getRegion(pts, None, "EPSG:4326", EE_GRID).getInfo(),
                        speed.getRegion(pts, None, "EPSG:4326", EE_GRID).getInfo())
            except Exception as exc:                                     # rate limits, network drops
                if k == 4:
                    raise
                _log(f"retry {a}–{b} ({k + 1}): {str(exc)[:100]}")
                time.sleep(30 * (k + 1))

    spans = [(max(start, dt.date(y, 1, 1)), min(end, dt.date(y, 12, 31))) for y in range(start.year, end.year + 1)]
    with ThreadPoolExecutor(4) as ex:
        parts = [p for p in ex.map(lambda ab: span(*ab), spans) if len(p[0]) > 1 and len(p[1]) > 1]
    frames = [rows_to_frames(d, w, sites) for d, w in parts]
    return {s.id: pd.concat([f[s.id] for f in frames]) if frames else pd.DataFrame(columns=RAW) for s in sites}


def derive(raw):
    """RAW → MET and sp_kpa: vapour pressure at the dewpoint (FAO-56 Eq. 14, in hPa), wind at 2 m (Eq. 47)."""
    td = raw.dewpoint_c
    return pd.DataFrame({"rad_mj_m2": raw.rad_mj_m2, "vap_hpa": 6.108 * np.exp(17.27 * td / (td + 237.3)),
                         "wind2_ms": fw.u2_from_u10(raw.wind10_ms), "sp_kpa": raw.sp_kpa}, index=raw.index)


def site_met(sites, today=None, refresh=True, fetch=None):
    """{site id: DataFrame indexed by date of rad_mj_m2 (MJ m-2 day-1), vap_hpa, wind2_ms, sp_kpa}: ERA5-Land from
    1 Jan 1993 to its last day. A site without a cache is fetched whole (an error if that fails); stale caches are
    topped up when refresh, and used as they are (with a warning) when Earth Engine cannot be reached."""
    fetch = fetch or _ee_fetch
    today = today or dt.datetime.now(dt.timezone.utc).date()
    have, new = {}, {}
    for s in sites:
        p = met_path(s)
        if p.exists() and p.stat().st_size:
            df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
            if not df.empty:
                have[s.id] = df
    missing = [s for s in sites if s.id not in have]
    if missing:
        _log(f"radiation, humidity and wind: fetching {FIRST}–{today} for {len(missing)} sites (Earth Engine)")
        new.update(fetch(missing, FIRST, today))
    stale = [s for s in sites if s.id in have and (today - have[s.id].index.max().date()).days > 2] if refresh else []
    if stale:
        start = min(have[s.id].index.max().date() for s in stale) - dt.timedelta(days=7)
        try:
            top = fetch(stale, start, today)
            for s in stale:
                old = have[s.id]
                if len(top[s.id]):
                    new[s.id] = pd.concat([old[old.index < pd.Timestamp(start)], top[s.id]])
        except Exception as exc:
            _log(f"radiation, humidity and wind not topped up ({str(exc)[:120]}); the cache is used as it is")
    if new:
        CACHE.mkdir(parents=True, exist_ok=True)
    for s in sites:
        if s.id not in new:
            continue
        df = new[s.id].astype(float)
        df = df[~df.index.duplicated(keep="last")].sort_index().dropna()
        if df.empty:
            raise RuntimeError(f"ERA5-Land radiation, humidity and wind: no days for {s.id}")
        have[s.id] = df
        tmp = met_path(s).with_name(f"{met_path(s).stem}.{os.getpid()}.tmp")      # whole, as the temperature cache
        df.rename_axis("date").to_csv(tmp, float_format="%.4f")
        os.replace(tmp, met_path(s))
    return {s.id: derive(have[s.id]) for s in sites}
