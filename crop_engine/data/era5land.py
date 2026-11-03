"""
Daily maximum and minimum 2 m temperature at each site from ERA5-Land (0.1°), via the Open-Meteo historical weather
API (https://open-meteo.com, CC-BY 4.0), which serves ERA5-Land at the point. Cached per site in data/crop_engine/
and topped up each run (ERA5-Land runs about 5 days behind real time). Days without ERA5-Land use the 1993–2016
day-of-year climatology (crop_engine.data.weather marks them).

ET0 is not taken from here: the engine uses the platform's own ERA5-Land FAO-56 ET0 (scripts/fao_water_balance.py),
so the crop model and the FAO water balance see the same evaporative demand.
"""
import datetime as dt
import time

import numpy as np
import pandas as pd
import requests

from crop_engine.config import CACHE, CAL_YEARS

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
    path = CACHE / f"era5land_t2m_{site.id}.csv"
    today = today or dt.date.today()
    df = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
    if df is None or df.empty:
        df = _fetch(site.lat, site.lon, FIRST, today)
    elif refresh:
        last = df.date.max().date()
        if (today - last).days > 2:
            new = _fetch(site.lat, site.lon, last - dt.timedelta(days=7), today)
            df = pd.concat([df[df.date < pd.Timestamp(last - dt.timedelta(days=7))], new], ignore_index=True)
    df = df.drop_duplicates("date", keep="last").sort_values("date")
    df.to_csv(path, index=False, float_format="%.2f")
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
