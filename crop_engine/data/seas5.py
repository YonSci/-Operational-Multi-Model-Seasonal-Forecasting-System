"""
ECMWF SEAS5 from its 1 Oct runs for the crop weather: daily maximum and minimum temperature per member at the sites,
bias-corrected to the sites' ERA5-Land series, and bias-corrected March rain.

Files (one per year, 1993–2026; not committed): data/seasonal_downloads_ke/ecmwf_oct_182d/ecmwf_<year>10_d01.nc,
with mx2t24, mn2t24 (K, the 24 hours to the lead time) and tp (m, accumulated) for 182 lead days, 1 Oct – 31 Mar
(30 Mar in a leap year), over 5.5 N – 5.5 S, 33 – 42.5 E (1°), downloaded with

  python scripts/download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --months 10
      --year-start 1993 --year-end 2026 --leadtime-days 182 --north 5.5 --west 33 --south -5.5 --east 42.5
      --variables maximum_2m_temperature_in_the_last_24_hours minimum_2m_temperature_in_the_last_24_hours
                  total_precipitation --outdir data/seasonal_downloads_ke/ecmwf_oct_182d

Each site takes the 1° cell nearest its 0.25° analysis cell (as onset_rules.jan_feb maps SEAS5 to the grid).

Calibration years: those of 1993–2016 whose file is on disk, at least MIN_CAL_YEARS of them (the run's year is
always needed); the corrections say how many they used. A past run (the hindcast verification) leaves its own
year out of them (exclude=year), so its correction never sees the season it forecasts.

Temperature: mean-bias (delta) correction by lead day. For each site and lead day, the bias is the calibration
years' member mean minus the ERA5-Land site series on the same days, ±15-day smoothed; every member of the run has
that bias subtracted. The forecast's anomaly and its member spread are kept; tmin is capped at tmax.

March rain: empirical quantile mapping per site and day, as the Agri rules' 1 Jan – 28 Feb (onset_rules.jan_feb):
the CHIRPS pool is the calibration years' observed days within ±EXT_QM_WINDOW of the day, the SEAS5 pool the
calibration years' members on that lead day.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C

DIR = C.BASE / "data" / "seasonal_downloads_ke" / "ecmwf_oct_182d"
LEAD_DAYS = 182
SMOOTH = 15                     # ± days of the temperature bias's running mean
MIN_CAL_YEARS = 10              # calibration years needed (of 1993–2016) for the corrections
NAMES = {"tmax": ("mx2t24", "tasmax", "maximum_2m_temperature_in_the_last_24_hours"),
         "tmin": ("mn2t24", "tasmin", "minimum_2m_temperature_in_the_last_24_hours"),
         "tp": ("tp", "total_precipitation")}


def path(year):
    return DIR / f"ecmwf_{year}10_d01.nc"


def calibration_years():
    """The calibration years (config.CAL_YEARS) whose file is on disk."""
    return [y for y in range(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1) if path(y).exists()]


def missing(year):
    """Why the run of `year` cannot be corrected (None when it can): its file, or too few calibration years."""
    if not path(year).exists():
        return f"the 182-day 1 Oct {year} file is missing"
    n = len(calibration_years())
    if n < MIN_CAL_YEARS:
        return f"{n} of the calibration years' files on disk (at least {MIN_CAL_YEARS} needed)"
    return None


def _var(ds, key):
    for n in NAMES[key]:
        if n in ds:
            return ds[n]
    raise KeyError(f"{key}: none of {NAMES[key]} in {list(ds.data_vars)}")


def lead_dates(year, n=LEAD_DAYS):
    """The day each lead day's value belongs to: lead hour 24 k covers day k − 1 from 1 Oct."""
    return pd.date_range(f"{year}-10-01", periods=n)


def load(year, lats, lons):
    """(member, lead day, site) tmax, tmin (°C) and daily rain (mm) of one 1 Oct run at the sites' cells."""
    with xr.open_dataset(path(year)) as ds:
        out = {}
        for key in ("tmax", "tmin", "tp"):
            v = _var(ds, key)
            if "forecast_reference_time" in v.dims:
                v = v.isel(forecast_reference_time=0, drop=True)
            v = v.sel(latitude=xr.DataArray(lats, dims="site"), longitude=xr.DataArray(lons, dims="site"),
                      method="nearest").transpose("number", "forecast_period", "site")
            out[key] = v.values.astype(np.float64)
    n = out["tp"].shape[1]
    if n < LEAD_DAYS:
        raise ValueError(f"{path(year).name}: {n} lead days (< {LEAD_DAYS})")
    rain = np.diff(out["tp"], axis=1, prepend=0.0) * 1000.0          # accumulated m → mm/day
    return {"tmax": out["tmax"][:, :LEAD_DAYS] - 273.15, "tmin": out["tmin"][:, :LEAD_DAYS] - 273.15,
            "rain": np.clip(rain[:, :LEAD_DAYS], 0, None)}


def _load(year, lats, lons):
    """load() of a year at the sites, kept while its file is unchanged: every hindcast year reads the same
    calibration files. The arrays are shared: read them, never write to them."""
    f = path(year)
    return _load_kept(year, str(f), f.stat().st_mtime_ns, tuple(float(x) for x in lats), tuple(float(x) for x in lons))


@lru_cache(maxsize=48)
def _load_kept(year, where, mtime, lats, lons):
    out = load(year, np.array(lats), np.array(lons))
    for a in out.values():
        a.flags.writeable = False
    return out


def _smooth(a, k=SMOOTH):
    """Running mean ±k days along axis 0, NaN-aware, shorter at the ends."""
    out = np.full_like(a, np.nan)
    for i in range(a.shape[0]):
        with np.errstate(invalid="ignore"):
            out[i] = np.nanmean(a[max(0, i - k):i + k + 1], axis=0)
    return out


class Seas5:
    """The run of `year` at the sites: bias-corrected tmax, tmin (member, lead day, site) and March rain."""

    def __init__(self, year, sites, lats, lons, temps, hist, exclude=None):
        """sites: ids; lats, lons: the sites' analysis cells; temps: {site id: ERA5-Land DataFrame tmax, tmin};
        hist: DataFrame (date, site id) of observed CHIRPS v2 (weather.Inputs.hist); exclude: a calibration year
        left out of the corrections (a past run's own year)."""
        import onset_rules as orl  # noqa: E402  (scripts/, on sys.path via config)
        import process_ecmwf_september as pes  # noqa: E402
        self.year, self.dates = year, lead_dates(year)
        self.cal_years = cal = [y for y in calibration_years() if y != exclude]
        if len(cal) < MIN_CAL_YEARS:
            raise ValueError(f"{len(cal)} calibration years (at least {MIN_CAL_YEARS} needed)")
        hind = {y: _load(y, lats, lons) for y in cal}
        run = _load(year, lats, lons)
        # temperature: hindcast member mean minus ERA5-Land on the same days, per lead day and site
        self.bias = {}
        for key in ("tmax", "tmin"):
            model = np.stack([hind[y][key].mean(axis=0) for y in cal])                       # (year, lead, site)
            obs = np.stack([np.stack([temps[s][key].reindex(lead_dates(y)).values for s in sites], axis=1)
                            for y in cal])                                                    # (year, lead, site)
            with np.errstate(invalid="ignore"):
                diff = np.nanmean(model - obs, axis=0)
            self.bias[key] = _smooth(diff)
        self.tmax = (run["tmax"] - self.bias["tmax"][None]).astype(np.float32)
        self.tmin = np.minimum(run["tmin"] - self.bias["tmin"][None], self.tmax).astype(np.float32)
        # March rain: quantile mapping per site and lead day
        mar = np.where(self.dates.month == 3)[0]
        w = orl.EXT_QM_WINDOW
        self.march_dates = self.dates[mar]
        self.march = np.empty((run["rain"].shape[0], len(mar), len(sites)), np.float32)
        for j, s in enumerate(sites):
            h = hist[s]
            for i, d in enumerate(mar):
                day = self.dates[d]
                c_pool = np.concatenate([h.reindex(pd.date_range(
                    pd.Timestamp(y + 1, 3, day.day) - pd.Timedelta(days=w), periods=2 * w + 1)).values for y in cal])
                s_pool = np.concatenate([hind[y]["rain"][:, d, j] for y in cal])
                f = pes._build_qm_transfer(c_pool[np.isfinite(c_pool)], s_pool[np.isfinite(s_pool)])
                self.march[:, i, j] = f(run["rain"][:, d, j])
        self.n_members = run["tmax"].shape[0]

    def on(self, dates):
        """Positions of `dates` among the run's lead days (−1 where the run has no value)."""
        return self.dates.get_indexer(pd.DatetimeIndex(dates))


def hargreaves_ratio(tmax, tmin, tmax_ref, tmin_ref, lo=0.7, hi=1.3):
    """ET0 of (tmax, tmin) over ET0 of (tmax_ref, tmin_ref) on the same day, by the Hargreaves equation
    (0.0023 Ra (Tmean + 17.8) sqrt(Tmax − Tmin): the radiation cancels), clipped to [lo, hi]."""
    def hg(x, n):
        return ((x + n) / 2 + 17.8) * np.sqrt(np.maximum(x - n, 0.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        r = hg(tmax, tmin) / hg(tmax_ref, tmin_ref)
    return np.clip(np.where(np.isfinite(r), r, 1.0), lo, hi)


def describe(s, year=None):
    """One line for the logs and attrs."""
    n, all_ = len(s.cal_years), C.CAL_YEARS[1] - C.CAL_YEARS[0] + 1
    return (f"ECMWF SEAS5 1 Oct {year or s.year} ({s.n_members} members), temperature bias-corrected to ERA5-Land by "
            f"lead day and March rain quantile-mapped to CHIRPS, from {n} of the {all_} calibration years "
            f"{C.CAL_YEARS[0]}–{C.CAL_YEARS[1]}")


