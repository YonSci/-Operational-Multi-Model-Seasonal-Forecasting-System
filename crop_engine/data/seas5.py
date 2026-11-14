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

Solar radiation, vapour pressure and wind (when their files are on disk: MET_DIR, the same 1 Oct runs with
surface_solar_radiation_downwards, 2m_dewpoint_temperature and the 10 m wind components at 24-hour lead steps;
`python -m crop_engine.data.seas5_download --kind met`): daily radiation from the accumulation, vapour pressure at
the dewpoint (FAO-56 Eq. 14) and the 10 m wind speed taken to 2 m (Eq. 47). The dewpoint and wind are the 00 UTC
values, not daily means; the correction absorbs that offset with the models' own. Each is corrected by a ratio per
site and lead day: the ±15-day smoothed calibration years' ERA5-Land site mean (crop_engine.data.era5land.site_met)
over the smoothed member mean of the same days, clipped to RATIO, so values stay positive and the forecast's
anomaly and spread are kept as fractions. With them the forecast's ET0 is FAO-56 Penman-Monteith's ratio of each
member's weather to the climatological weather (pm_ratio), in place of the Hargreaves ratio of temperature alone.
"""

import os
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
         "tp": ("tp", "total_precipitation"),
         "ssrd": ("ssrd", "surface_solar_radiation_downwards"),
         "d2m": ("d2m", "2m_dewpoint_temperature"),
         "u10": ("u10", "10m_u_component_of_wind"),
         "v10": ("v10", "10m_v_component_of_wind")}
VARIABLES = {"temperature": ["maximum_2m_temperature_in_the_last_24_hours", "minimum_2m_temperature_in_the_last_24_hours",
                             "total_precipitation"],
             "met": ["surface_solar_radiation_downwards", "2m_dewpoint_temperature", "10m_u_component_of_wind",
                     "10m_v_component_of_wind"]}
MET_DIR = C.BASE / "data" / "seasonal_downloads_ke" / "ecmwf_oct_182d_met"
MET = {"rad": "rad_mj_m2", "vap": "vap_hpa", "wind2": "wind2_ms"}   # SEAS5 key → ERA5-Land site series column
RATIO = (0.5, 2.0)                                                 # bounds of the radiation, humidity, wind ratios


def path(year, kind="temperature"):
    return (DIR if kind == "temperature" else MET_DIR) / f"ecmwf_{year}10_d01.nc"


def calibration_years(kind="temperature"):
    """The calibration years (config.CAL_YEARS) whose file is on disk."""
    return [y for y in range(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1) if path(y, kind).exists()]


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


def _read(f, keys, lats, lons):
    """(member, lead day, site) arrays of keys at the sites' cells, at least LEAD_DAYS long."""
    with xr.open_dataset(f) as ds:
        out = {}
        for key in keys:
            v = _var(ds, key)
            if "forecast_reference_time" in v.dims:
                v = v.isel(forecast_reference_time=0, drop=True)
            v = v.sel(latitude=xr.DataArray(lats, dims="site"), longitude=xr.DataArray(lons, dims="site"),
                      method="nearest").transpose("number", "forecast_period", "site")
            out[key] = v.values.astype(np.float64)
    n = out[keys[0]].shape[1]
    if n < LEAD_DAYS:
        raise ValueError(f"{f.name}: {n} lead days (< {LEAD_DAYS})")
    return out


def load(year, lats, lons):
    """(member, lead day, site) tmax, tmin (°C) and daily rain (mm) of one 1 Oct run at the sites' cells."""
    out = _read(path(year), ("tmax", "tmin", "tp"), lats, lons)
    rain = np.diff(out["tp"], axis=1, prepend=0.0) * 1000.0          # accumulated m → mm/day
    return {"tmax": out["tmax"][:, :LEAD_DAYS] - 273.15, "tmin": out["tmin"][:, :LEAD_DAYS] - 273.15,
            "rain": np.clip(rain[:, :LEAD_DAYS], 0, None)}


def load_met(year, lats, lons):
    """(member, lead day, site) solar radiation (MJ m-2 day-1), vapour pressure (hPa) and 2 m wind (m/s) of one 1 Oct
    run: the day's radiation from the accumulation (lead hour 24 k covers day k − 1), dewpoint and wind at the step."""
    import fao_water_balance as fw  # noqa: E402  (scripts/, on sys.path via config)
    out = _read(path(year, "met"), ("ssrd", "d2m", "u10", "v10"), lats, lons)
    rad = np.clip(np.diff(out["ssrd"], axis=1, prepend=0.0) / 1e6, 0, None)
    td = out["d2m"] - 273.15
    return {"rad": rad[:, :LEAD_DAYS], "vap": (6.108 * np.exp(17.27 * td / (td + 237.3)))[:, :LEAD_DAYS],
            "wind2": fw.u2_from_u10(np.hypot(out["u10"], out["v10"]))[:, :LEAD_DAYS]}


def _load(year, lats, lons, kind="temperature"):
    """load() (or load_met()) of a year at the sites, kept while its file is unchanged: every hindcast year reads the
    same calibration files. The arrays are shared: read them, never write to them."""
    f = path(year, kind)
    return _load_kept(kind, year, str(f), f.stat().st_mtime_ns, tuple(float(x) for x in lats),
                      tuple(float(x) for x in lons))


@lru_cache(maxsize=96)
def _load_kept(kind, year, where, mtime, lats, lons):
    out = (load if kind == "temperature" else load_met)(year, np.array(lats), np.array(lons))
    for a in out.values():
        a.flags.writeable = False
    return out


# Temperature spread (variance) correction, off by default: CROP_TEMPERATURE_SPREAD=1 scales each member's anomaly
# about the members' smoothed mean by spread_ratio, so the forecast's day-to-day spread matches ERA5-Land's over the
# calibration years (mean-and-variance adjustment); with a ratio of 1 it is the mean-bias correction alone. Off until
# the hindcast shows it helps (python -m crop_engine.hindcast with and without CROP_TEMPERATURE_SPREAD=1).
TEMPERATURE_SPREAD = os.environ.get("CROP_TEMPERATURE_SPREAD", "0") == "1"
SPREAD_RATIO = (0.5, 2.0)


def spread_ratio(hind, temps, sites, cal, key):
    """ERA5-Land's over the members' standard deviation of daily `key` about their ±SMOOTH-day smoothed means, per
    lead day and site (variances ±SMOOTH-day smoothed), clipped to SPREAD_RATIO; 1 where either is missing."""
    model_mean = _smooth(np.nanmean(np.stack([hind[y][key].mean(axis=0) for y in cal]), axis=0))
    var_m = _smooth(np.nanmean(np.stack([np.nanmean((hind[y][key] - model_mean[None]) ** 2, axis=0) for y in cal]), axis=0))
    obs = np.stack([np.stack([temps[s][key].reindex(lead_dates(y)).values for s in sites], axis=1) for y in cal])
    with np.errstate(invalid="ignore"):
        obs_mean = _smooth(np.nanmean(obs, axis=0))
        var_o = _smooth(np.nanmean((obs - obs_mean[None]) ** 2, axis=0))
        r = np.sqrt(var_o / var_m)
    return np.clip(np.where(np.isfinite(r), r, 1.0), *SPREAD_RATIO).astype(np.float32)


def _smooth(a, k=SMOOTH):
    """Running mean ±k days along axis 0, NaN-aware, shorter at the ends."""
    out = np.full_like(a, np.nan)
    for i in range(a.shape[0]):
        with np.errstate(invalid="ignore"):
            out[i] = np.nanmean(a[max(0, i - k):i + k + 1], axis=0)
    return out


class Seas5:
    """The run of `year` at the sites: bias-corrected tmax, tmin (member, lead day, site) and March rain."""

    def __init__(self, year, sites, lats, lons, temps, hist, exclude=None, met=None):
        """sites: ids; lats, lons: the sites' analysis cells; temps: {site id: ERA5-Land DataFrame tmax, tmin};
        hist: DataFrame (date, site id) of observed CHIRPS v2 (weather.Inputs.hist); exclude: a calibration year
        left out of the corrections (a past run's own year); met: {site id: ERA5-Land DataFrame rad_mj_m2, vap_hpa,
        wind2_ms} (era5land.site_met) for the radiation, humidity and wind, when their files are on disk."""
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
        # the spread: the ratio of ERA5-Land's to the members' day-to-day standard deviation about their own
        # (smoothed) means, per lead day and site; applied only with CROP_TEMPERATURE_SPREAD=1 (module doc)
        self.spread_ratio = {k: spread_ratio(hind, temps, sites, cal, k) for k in ("tmax", "tmin")}
        self.spread_applied = TEMPERATURE_SPREAD
        adj = {k: self.spread_ratio[k] if TEMPERATURE_SPREAD else np.ones_like(self.bias[k]) for k in ("tmax", "tmin")}
        mean = {k: _smooth(np.nanmean(np.stack([hind[y][k].mean(axis=0) for y in cal]), axis=0)) for k in ("tmax", "tmin")}
        self.tmax = ((run["tmax"] - mean["tmax"][None]) * adj["tmax"][None] + mean["tmax"][None]
                     - self.bias["tmax"][None]).astype(np.float32)
        self.tmin = np.minimum((run["tmin"] - mean["tmin"][None]) * adj["tmin"][None] + mean["tmin"][None]
                               - self.bias["tmin"][None], self.tmax).astype(np.float32)
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
        self.met, self.met_cal_years = None, []
        self.met_note = self._met(year, sites, lats, lons, exclude, met)          # sets self.met when it can

    def _met(self, year, sites, lats, lons, exclude, met):
        """Corrected radiation, vapour pressure, wind (member, lead day, site) into self.met; a note why not."""
        if met is None:
            return "no ERA5-Land radiation, humidity or wind at the sites"
        if not path(year, "met").exists():
            return f"the radiation, humidity and wind file of {year} is missing ({MET_DIR})"
        cal = [y for y in calibration_years("met") if y != exclude]
        if len(cal) < MIN_CAL_YEARS:
            return f"{len(cal)} calibration years of radiation, humidity and wind (at least {MIN_CAL_YEARS} needed)"
        hind = {y: _load(y, lats, lons, "met") for y in cal}
        run = _load(year, lats, lons, "met")
        self.met, self.met_ratio, self.met_cal_years = {}, {}, cal
        for key, col in MET.items():
            model = np.stack([hind[y][key].mean(axis=0) for y in cal])                       # (year, lead, site)
            obs = np.stack([np.stack([met[s][col].reindex(lead_dates(y)).values for s in sites], axis=1)
                            for y in cal])
            with np.errstate(invalid="ignore", divide="ignore"):
                r = _smooth(np.nanmean(obs, axis=0)) / _smooth(np.nanmean(model, axis=0))
            r = np.clip(np.where(np.isfinite(r), r, 1.0), *RATIO)
            self.met_ratio[key] = r
            self.met[key] = (run[key][:, :LEAD_DAYS] * r[None]).astype(np.float32)
        return None

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


def pm_ratio(member, ref, p_kpa, lat, doy, elev, lo=0.5, hi=1.5):
    """FAO-56 Penman-Monteith ET0 of each member's weather over that of the reference (climatological) weather on the
    same day, clipped to [lo, hi]. member, ref: dicts of tmax, tmin (°C), vap (hPa), wind2 (m/s), rad (MJ m-2 day-1),
    broadcastable; p_kpa, lat, elev per site (broadcastable), doy per day."""
    import fao_water_balance as fw  # noqa: E402

    def et0(w):
        x = np.log(np.maximum(w["vap"], 0.1) / 6.108)
        return fw.et0_fao56(w["tmax"], w["tmin"], 237.3 * x / (17.27 - x), w["wind2"], w["rad"], p_kpa, lat, doy, elev)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = et0(member) / et0(ref)
    return np.clip(np.where(np.isfinite(r), r, 1.0), lo, hi)


def describe(s, year=None):
    """One line for the logs and attrs."""
    n, all_ = len(s.cal_years), C.CAL_YEARS[1] - C.CAL_YEARS[0] + 1
    met = (f"; radiation, humidity and wind corrected to ERA5-Land from {len(s.met_cal_years)} calibration years, ET0 "
           f"by Penman-Monteith" if s.met is not None else f"; ET0 scaled by temperature ({s.met_note})")
    spread = ("its day-to-day spread scaled to ERA5-Land's (median ratio tmax "
              f"{float(np.median(s.spread_ratio['tmax'])):.2f}, tmin {float(np.median(s.spread_ratio['tmin'])):.2f}), "
              if getattr(s, "spread_applied", False) else "")
    return (f"ECMWF SEAS5 1 Oct {year or s.year} ({s.n_members} members), temperature bias-corrected to ERA5-Land by "
            f"lead day, {spread}and March rain quantile-mapped to CHIRPS, from {n} of the {all_} calibration years "
            f"{C.CAL_YEARS[0]}–{C.CAL_YEARS[1]}{met}")


