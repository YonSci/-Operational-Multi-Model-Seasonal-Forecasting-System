"""
Standard daily crop weather: the platform's forecast rainfall members and observed weather at each site, as one
xarray Dataset per forecast run (or per observed season), with the source of every day.

Dimensions: member, site, time (1 Aug of the season year – config.SEASON_END of the next, 31 Mar: past the FAO
water balance's 28 Feb, its cessation search end, so a medium-maturity crop can mature; 243 days, to 30 Mar when the
next year is a leap year).
  precip_mm (member, site, time)   daily rain
  tmax_c, tmin_c (site, time)      2 m temperature
  et0_mm (site, time)              FAO-56 reference evapotranspiration
  precip_source (time)             index into attrs["precip_sources"] (config.PRECIP_SOURCES)
  tmax_source, et0_source (site, time)  index into attrs["met_sources"] (config.MET_SOURCES)
and, when the ERA5-Land site series are available (crop_engine.data.era5land.site_met; for WOFOST, not AquaCrop):
  rad_mj_m2, vap_hpa, wind2_ms (site, time)  solar radiation, vapour pressure, 2 m wind speed
  rad_source (site, time)          their source (one for the three), as tmax_source
  elev_m (site)                    the elevation of the ERA5-Land cell (from its mean surface pressure)

Rain of a forecast run, member k (the members of forecast_runs.py, so the onset dates the dashboard shows belong to
exactly this rain):
  1–31 Aug        observed CHIRPS v2 (final, then preliminary)
  1 Sep – 31 Dec  the run's joined rain: observed to the last observed day, gap days, the weather forecast, SEAS5
  1 Jan – 28 Feb  SEAS5 member k, bias-corrected as the Agri rules' January–February (onset_rules.EXT_CACHE);
                  a 29 Feb repeats 28 Feb
  1–31 Mar        climatological: observed CHIRPS March of year 1994 + (k mod 24), the March after calibration
                  year 1993 + (k mod 24), since the SEAS5 October runs on disk end on 28 Feb (and SEAS5 has little
                  skill five months ahead)
Observed seasons (the benchmark) are observed CHIRPS throughout, March included.
Temperature and ET0: ERA5-Land to its last day (temperature: Open-Meteo point series; ET0: the platform's ERA5-Land
FAO-56 grid), then the 1993–2016 day-of-year climatology (ET0: by season day, to SEASON_END); radiation, vapour
pressure and wind likewise (ERA5-Land from Earth Engine, then their day-of-year climatology); no forecast
temperature or radiation is used yet.
"""
import datetime as dt
import json

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C
from crop_engine.data import era5land
from crop_engine.data import sites as sites_mod

import blend_subseasonal as bs  # noqa: E402  (scripts/, on sys.path via config)
import fao_water_balance as fw  # noqa: E402
import onset_rules as orl  # noqa: E402

KIND_TO_SOURCE = {"obs": "obs_final", "gap": "gap", "ens": "forecast", "ext": "forecast", "fc": "forecast", "seas": "seasonal"}
CHIRPS_HIST = C.BASE / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"


def season_length(t0, end=C.SEASON_END):
    """Days from the season start (DOY t0, 2025 numbering) to `end` (month, day) of the next year, counted in a
    non-leap year pair as the FAO water balance counts its days."""
    start = dt.date(2025, 1, 1) + dt.timedelta(days=int(t0) - 1)
    return (dt.date(2026, *end) - start).days + 1


def jan_feb_index(dates, y):
    """Day index into the SEAS5 1 Jan – 28 Feb members (0–58) of each date in Jan–Feb of y+1: 29 Feb takes 28 Feb's."""
    return np.minimum((dates - pd.Timestamp(y + 1, 1, 1)).days.values, orl.EXT_DAYS - 1)


def _last_time(path):
    with xr.open_dataset(path) as ds:
        return pd.Timestamp(ds.time.values[-1]).date()


class Inputs:
    """What every run shares: the grid, the sites' cells, observed rain, ET0, temperatures, the SEAS5 Jan–Feb members."""

    def __init__(self, sites=None, refresh=True, blender=None):
        self.b = blender or bs.Blender(C.BASE)
        self.year, self.lat, self.lon = self.b.year, self.b.lat, self.b.lon
        self.cfg = fw.load_config()
        self.t0 = fw.season_days(self.cfg)[0]                               # 1 Aug
        self.T = season_length(self.t0)                                     # to SEASON_END (31 Mar: 243 days)
        self.sites = sites_mod.on_grid(sites or sites_mod.registered_sites(), self.lat, self.lon, self.b.lm)
        self.ii = np.array([s.i for s in self.sites])
        self.jj = np.array([s.j for s in self.sites])
        self.temps = {s.id: era5land.site_temperature(s, refresh=refresh) for s in self.sites}
        self.tclim = {s.id: (era5land.climatology(t.tmax), era5land.climatology(t.tmin)) for s, t in
                      ((s, self.temps[s.id]) for s in self.sites)}
        try:                                                              # radiation, humidity, wind: optional
            self.met2 = era5land.site_met(self.sites, refresh=refresh)
            self.met2_clim = {sid: {v: era5land.climatology(df[v]) for v in era5land.MET} for sid, df in self.met2.items()}
            self.met2_note = ""
        except Exception as exc:
            self.met2, self.met2_clim = None, None
            self.met2_note = f"not available: {str(exc)[:200]}"
            print(f"[{dt.datetime.now():%H:%M:%S}] crop weather: radiation, humidity and wind {self.met2_note}", flush=True)
        self.et0_clim = fw.et0_climatology(self.cfg, self.lat, self.lon, self.T)[:, self.ii, self.jj]  # (T, site)
        self.o26 = orl.obs_2026(self.lat, self.lon)[:, self.ii, self.jj]                           # (366, site)
        self.final_end = _last_time(orl.FINAL_2026) if orl.FINAL_2026.exists() else dt.date(self.year, 1, 1)
        with xr.open_dataarray(orl.EXT_CACHE) as da:                      # (member, 59, site)
            self.janfeb = da.sel(year=self.year).values[:, :, self.ii, self.jj].astype(np.float32)
        with xr.open_dataset(CHIRPS_HIST) as ds:                          # (day, site) observed CHIRPS v2, 1993–2025
            p = ds["precip"].sel(lat=xr.DataArray(self.lat[self.ii], dims="site"),
                                 lon=xr.DataArray(self.lon[self.jj], dims="site"), method="nearest")
            self.hist = pd.DataFrame(p.values.astype(np.float32), index=pd.DatetimeIndex(ds.time.values),
                                     columns=[s.id for s in self.sites])
        taw, _, _ = fw.taw_mm(self.cfg["crop_params"]["rooting_depth_m"])
        self.taw = taw

    # ── shared pieces ─────────────────────────────────────────────────────
    def dates(self, year):
        return fw.season_dates(year, self.t0, self.T)

    def observed_rain(self, dates):
        """(site, len(dates)) observed CHIRPS v2: the 1993–2025 file, then 2026 final / preliminary; NaN if missing."""
        out = self.hist.reindex(dates).values.T.copy()
        in26 = dates.year == 2026
        if in26.any():
            d = dates[in26].dayofyear.values - 1
            out[:, in26] = self.o26[d].T
        return out.astype(np.float32)

    def met(self, year, dates):
        """tmax, tmin, et0 (site, T) and their sources (site, T): ERA5-Land where available, else climatology."""
        ns, T = len(self.sites), len(dates)
        tmax, tmin = np.empty((ns, T), np.float32), np.empty((ns, T), np.float32)
        tsrc = np.zeros((ns, T), np.int8)
        doy = era5land.doy_noleap(dates) - 1
        for k, s in enumerate(self.sites):
            t = self.temps[s.id].reindex(dates)
            cx, cn = self.tclim[s.id]
            miss = t.tmax.isna().values | t.tmin.isna().values
            tmax[k] = np.where(miss, cx[doy], t.tmax.values)
            tmin[k] = np.where(miss, cn[doy], t.tmin.values)
            tsrc[k] = np.where(miss, C.MET_SOURCES.index("climatology"), C.MET_SOURCES.index("era5land"))
        tmin = np.minimum(tmin, tmax)
        e = fw.era5_season(year, self.t0, self.T, self.lat, self.lon)[:, self.ii, self.jj].T        # (site, T)
        clim = self.et0_clim.T
        esrc = np.where(np.isfinite(e), C.MET_SOURCES.index("era5land"), C.MET_SOURCES.index("climatology")).astype(np.int8)
        return tmax, tmin, np.where(np.isfinite(e), e, clim).astype(np.float32), tsrc, esrc

    def radiation(self, dates):
        """{rad_mj_m2, vap_hpa, wind2_ms: (site, T)}, their source (site, T) and the cells' elevation (site,): ERA5-Land
        where available, else the day-of-year climatology; None without the site series."""
        if self.met2 is None:
            return None
        ns, T = len(self.sites), len(dates)
        out = {v: np.empty((ns, T), np.float32) for v in era5land.MET}
        src = np.zeros((ns, T), np.int8)
        doy = era5land.doy_noleap(dates) - 1
        elev = np.empty(ns, np.float32)
        for k, s in enumerate(self.sites):
            df = self.met2[s.id]
            m = df.reindex(dates)
            miss = m[era5land.MET].isna().any(axis=1).values
            for v in era5land.MET:
                out[v][k] = np.where(miss, self.met2_clim[s.id][v][doy], m[v].values)
            src[k] = np.where(miss, C.MET_SOURCES.index("climatology"), C.MET_SOURCES.index("era5land"))
            cal = df[(df.index.year >= C.CAL_YEARS[0]) & (df.index.year <= C.CAL_YEARS[1])]
            elev[k] = fw.elevation_from_pressure(float(cal.sp_kpa.mean()))
        return out, src, elev

    def _extra(self, dates):
        r = self.radiation(dates)
        return r if r is not None else self.met2_note

    def initial_water(self, year):
        """Plant-available water on 1 Aug as a fraction of the FAO bucket's TAW (ERA5-Land root-zone soil moisture,
        as the FAO water balance starts), per site."""
        paw = fw.initial_storage(self.cfg, year, self.t0, self.lat, self.lon, self.taw)[self.ii, self.jj]
        taw = self.taw[self.ii, self.jj]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.clip(np.where(taw > 0, paw / taw, 0.0), 0, 1)

    # ── a forecast run ────────────────────────────────────────────────────
    def forecast(self, P, segments, attrs):
        """Dataset of one forecast run: P (member, 1 Sep – 31 Dec, lat, lon) its joined rain, segments its sources."""
        y = self.year
        dates = self.dates(y)
        n_mem, ns, T = P.shape[0], len(self.sites), len(dates)
        rain = np.full((n_mem, ns, T), np.nan, np.float32)
        src = np.full(T, C.PRECIP_SOURCES.index("seasonal"), np.int8)
        win0, last = pd.Timestamp(self.b.win0), pd.Timestamp(self.b.last)
        obs = self.observed_rain(dates)
        aug = dates < win0                                                # 1–31 Aug: observed
        rain[:, :, aug] = obs[None, :, aug]
        sd = (dates >= win0) & (dates <= last)                            # 1 Sep – 31 Dec: the run
        k0 = np.where(sd)[0]
        rain[:, :, k0] = np.moveaxis(P[:, (dates[sd] - win0).days, :, :][:, :, self.ii, self.jj], 1, 2)
        for s in segments:
            m = (dates >= pd.Timestamp(s["start"])) & (dates <= pd.Timestamp(s["end"])) & sd
            src[m] = C.PRECIP_SOURCES.index(KIND_TO_SOURCE.get(s["kind"], "seasonal"))
        is_obs = src == C.PRECIP_SOURCES.index("obs_final")
        is_obs |= aug
        src[is_obs] = np.where(dates[is_obs].date > self.final_end, C.PRECIP_SOURCES.index("obs_prelim"),
                               C.PRECIP_SOURCES.index("obs_final"))
        jf = (dates > last) & (dates < pd.Timestamp(y + 1, 3, 1))         # 1 Jan – 28 Feb: SEAS5 member k
        rain[:, :, jf] = np.moveaxis(self.janfeb[:n_mem, jan_feb_index(dates[jf], y)], 1, 2)
        src[jf] = C.PRECIP_SOURCES.index("seasonal")
        mar = dates >= pd.Timestamp(y + 1, 3, 1)                          # March: climatology (CHIRPS of a past March)
        cal = np.arange(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1)
        for m in range(n_mem):
            cy = int(cal[m % len(cal)])
            md = pd.DatetimeIndex([pd.Timestamp(cy + 1, d.month, min(d.day, 28 if d.month == 2 else 31)) for d in dates[mar]])
            rain[m][:, mar] = self.observed_rain(md)                     # (site, March days)
        src[mar] = C.PRECIP_SOURCES.index("climatology")
        tmax, tmin, et0, tsrc, esrc = self.met(y, dates)
        attrs = {**attrs, "season_year": y, "climatological_march_years": f"member k: CHIRPS March {cal[0] + 1}+(k mod {len(cal)})"}
        return to_dataset(rain, tmax, tmin, et0, src, tsrc, esrc, dates, self.sites, attrs, self._extra(dates))

    # ── an observed season (benchmark) ───────────────────────────────────
    def observed(self, year):
        dates = self.dates(year)
        rain = self.observed_rain(dates)[None]
        src = np.full(len(dates), C.PRECIP_SOURCES.index("obs_final"), np.int8)
        tmax, tmin, et0, tsrc, esrc = self.met(year, dates)
        attrs = {"forecast_source": "observed", "model_label": "Observed weather (CHIRPS v2, ERA5-Land)", "season_year": year,
                 "run_date": "", "obs_end": "", "members_kind": "one observed season"}
        return to_dataset(rain, tmax, tmin, et0, src, tsrc, esrc, dates, self.sites, attrs, self._extra(dates))


def to_dataset(rain, tmax, tmin, et0, src, tsrc, esrc, dates, sites, attrs, extra=None):
    """The crop-weather Dataset. extra: Inputs.radiation's (values, source, elevation), or a note why there are none."""
    site_coords = {"site": [s.id for s in sites], "site_name": ("site", [s.name for s in sites]),
                   "lat": ("site", [s.lat for s in sites]), "lon": ("site", [s.lon for s in sites]),
                   "cell_lat": ("site", [s.cell_lat for s in sites]), "cell_lon": ("site", [s.cell_lon for s in sites])}
    ds = xr.Dataset(
        {"precip_mm": (("member", "site", "time"), rain.astype(np.float32)),
         "tmax_c": (("site", "time"), tmax), "tmin_c": (("site", "time"), tmin), "et0_mm": (("site", "time"), et0),
         "precip_source": (("time",), src), "tmax_source": (("site", "time"), tsrc), "et0_source": (("site", "time"), esrc)},
        coords={"member": np.arange(1, rain.shape[0] + 1), "time": dates, **site_coords})
    ds["precip_mm"].attrs["units"] = "mm/day"
    ds["tmax_c"].attrs["units"] = ds["tmin_c"].attrs["units"] = "degC"
    ds["et0_mm"].attrs["units"] = "mm/day"
    if isinstance(extra, tuple):
        vals, rsrc, elev = extra
        for v, units in (("rad_mj_m2", "MJ m-2 day-1"), ("vap_hpa", "hPa"), ("wind2_ms", "m/s")):
            ds[v] = (("site", "time"), vals[v].astype(np.float32))
            ds[v].attrs["units"] = units
        ds["rad_source"] = (("site", "time"), rsrc)
        ds = ds.assign_coords(elev_m=("site", np.asarray(elev, np.float32)))
        attrs = {**attrs, "radiation": "ERA5-Land 0.1° cell of each site (Google Earth Engine): solar radiation, vapour "
                                       "pressure at the dewpoint, 2 m wind (FAO-56 Eq. 47); rad_source per day"}
    else:
        attrs = {**attrs, "radiation": extra or "not available"}
    ds.attrs.update({
        "precip_sources": json.dumps(C.PRECIP_SOURCES), "met_sources": json.dumps(C.MET_SOURCES),
        "calibration": "CHIRPS v2 quantile mapping of SEAS5 (1993–2016); weather forecasts as in forecast_runs.py",
        "spatial_resolution": "0.25° analysis-grid cell nearest each site; weather forecasts from their native grids "
                              "(0.25–1.5°) mapped to it; temperature at the site (ERA5-Land 0.1°)",
        "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        **{k: (v if isinstance(v, (str, int, float)) else json.dumps(v)) for k, v in attrs.items()}})
    return ds


REQUIRED = {"precip_mm": ("member", "site", "time"), "tmax_c": ("site", "time"), "tmin_c": ("site", "time"),
            "et0_mm": ("site", "time"), "precip_source": ("time",), "tmax_source": ("site", "time"), "et0_source": ("site", "time")}
OPTIONAL = {"rad_mj_m2": (0, 40), "vap_hpa": (0, 50), "wind2_ms": (0, 20)}     # all or none, with rad_source
REQUIRED_ATTRS = ("forecast_source", "season_year", "precip_sources", "met_sources", "calibration", "spatial_resolution")


def validate(ds):
    """Problems with a crop-weather Dataset (empty list = valid): structure, completeness, ranges, provenance."""
    p = []
    for v, dims in REQUIRED.items():
        if v not in ds:
            p.append(f"missing {v}")
        elif ds[v].dims != dims:
            p.append(f"{v} dims {ds[v].dims} != {dims}")
    for a in REQUIRED_ATTRS:
        if a not in ds.attrs:
            p.append(f"missing attribute {a}")
    if p:
        return p
    t = pd.DatetimeIndex(ds.time.values)
    if len(t) < 2 or not (np.diff(t.values) == np.timedelta64(1, "D")).all():
        p.append("time is not a contiguous daily axis")
    for v, lo, hi in (("precip_mm", 0, 400), ("tmax_c", -10, 50), ("tmin_c", -15, 40), ("et0_mm", 0, 15)):
        a = ds[v].values
        if np.isnan(a).any():
            p.append(f"{v}: {int(np.isnan(a).sum())} missing values")
        elif a.min() < lo or a.max() > hi:
            p.append(f"{v}: values outside {lo}–{hi} ({a.min():.1f}–{a.max():.1f})")
    got = [v for v in (*OPTIONAL, "rad_source") if v in ds]
    if got and len(got) < len(OPTIONAL) + 1:
        p.append(f"radiation, humidity and wind incomplete: only {', '.join(got)}")
    elif got:
        for v, (lo, hi) in OPTIONAL.items():
            a = ds[v].values
            if ds[v].dims != ("site", "time"):
                p.append(f"{v} dims {ds[v].dims} != ('site', 'time')")
            elif np.isnan(a).any():
                p.append(f"{v}: {int(np.isnan(a).sum())} missing values")
            elif a.min() < lo or a.max() > hi:
                p.append(f"{v}: values outside {lo}–{hi} ({a.min():.1f}–{a.max():.1f})")
    if (ds.tmin_c.values > ds.tmax_c.values + 1e-6).any():
        p.append("tmin above tmax")
    n_p, n_m = len(json.loads(ds.attrs["precip_sources"])), len(json.loads(ds.attrs["met_sources"]))
    if ds.precip_source.values.min() < 0 or ds.precip_source.values.max() >= n_p:
        p.append("precip_source codes out of range")
    for v in ("tmax_source", "et0_source") + (("rad_source",) if "rad_source" in ds else ()):
        if ds[v].values.min() < 0 or ds[v].values.max() >= n_m:
            p.append(f"{v} codes out of range")
    return p
