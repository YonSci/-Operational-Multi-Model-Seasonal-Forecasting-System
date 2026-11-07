"""
Standard daily crop weather: the platform's forecast rainfall members and observed weather at each site, as one
xarray Dataset per forecast run (or per observed season), with the source of every day.

Dimensions: member, site, time (1 Aug of the season year – config.SEASON_END of the next, 31 Mar: past the FAO
water balance's 28 Feb, its cessation search end, so a medium-maturity crop can mature; 243 days, to 30 Mar when the
next year is a leap year).
  precip_mm (member, site, time)   daily rain
  tmax_c, tmin_c (member, site, time)  2 m temperature (the same in every member where observed)
  et0_mm (member, site, time)      FAO-56 reference evapotranspiration
  precip_source (time)             index into attrs["precip_sources"] (config.PRECIP_SOURCES)
  tmax_source, et0_source (site, time)  index into attrs["met_sources"] (config.MET_SOURCES)

Rain of a forecast run, member k (the members of forecast_runs.py, so the onset dates the dashboard shows belong to
exactly this rain):
  1–31 Aug        observed CHIRPS v2 (final, then preliminary)
  1 Sep – 31 Dec  the run's joined rain: observed to the last observed day, gap days, the weather forecast, SEAS5
  1 Jan – 28 Feb  SEAS5 member k, bias-corrected as the Agri rules' January–February (onset_rules.EXT_CACHE);
                  a 29 Feb repeats 28 Feb
  1–31 Mar        SEAS5 member k, quantile-mapped to CHIRPS (data/seas5.py) when the 182-day SEAS5 files are on
                  disk; otherwise climatological: observed CHIRPS March of 1994 + (k mod 24), the March after
                  calibration year 1993 + (k mod 24)
Observed seasons (the benchmark) are observed CHIRPS throughout, March included.
Temperature: ERA5-Land at the site (Open-Meteo point series) to its last day, then SEAS5 member k bias-corrected to
ERA5-Land (data/seas5.py) to 31 Mar; the 1993–2016 day-of-year climatology where neither is available.
ET0: the platform's ERA5-Land FAO-56 grid to its last day, then its climatology by season day, scaled on SEAS5 days
by member k's Hargreaves ET0 over that of the climatological temperatures (0.7–1.3): a warmer member with a wider
daily range evaporates more. No forecast radiation, humidity or wind is used.
"""
import datetime as dt
import json

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C
from crop_engine.data import era5land
from crop_engine.data import seas5 as s5
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
        self.seas5, self.seas5_note = self._seas5()

    def _seas5(self):
        """The SEAS5 1 Oct run of the season year at the sites (temperature, March rain), or None and why not."""
        why = s5.missing(self.year)
        if why:
            return None, f"no SEAS5 temperature or March rain: {why} ({s5.DIR})"
        try:
            s = s5.Seas5(self.year, [x.id for x in self.sites], self.lat[self.ii], self.lon[self.jj], self.temps, self.hist)
        except Exception as exc:                                           # the climatological fallback stands
            return None, f"no SEAS5 temperature: {type(exc).__name__}: {str(exc)[:160]}"
        return s, s5.describe(s)

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
        mar = dates >= pd.Timestamp(y + 1, 3, 1)                          # March
        S = self.seas5
        cal = np.arange(C.CAL_YEARS[0], C.CAL_YEARS[1] + 1)
        mk = np.arange(n_mem) % (S.n_members if S else 1)                # SEAS5 member of each rain member
        pos = S.march_dates.get_indexer(dates[mar]) if S is not None else None
        if S is not None and (pos >= 0).all():                            # SEAS5 member k, quantile-mapped
            rain[:, :, mar] = np.moveaxis(S.march[mk][:, pos], 1, 2)
            src[mar] = C.PRECIP_SOURCES.index("seasonal")
            attrs = {**attrs, "march_rain": "ECMWF SEAS5 1 Oct, member k, quantile-mapped to CHIRPS"}
        else:                                                             # climatology: CHIRPS of a past March
            for m in range(n_mem):
                cy = int(cal[m % len(cal)])
                md = pd.DatetimeIndex([pd.Timestamp(cy + 1, d.month, min(d.day, 28 if d.month == 2 else 31)) for d in dates[mar]])
                rain[m][:, mar] = self.observed_rain(md)                 # (site, March days)
            src[mar] = C.PRECIP_SOURCES.index("climatology")
            attrs = {**attrs, "march_rain": f"climatology: member k takes CHIRPS March {cal[0] + 1}+(k mod {len(cal)})"}
        tmax, tmin, et0, tsrc, esrc = self.met(y, dates)
        tmax, tmin, et0 = (np.repeat(a[None], n_mem, axis=0) for a in (tmax, tmin, et0))
        if S is not None:                                                 # after ERA5-Land: SEAS5 member k
            p = S.on(dates)
            use = (tsrc == C.MET_SOURCES.index("climatology")) & (p >= 0)[None, :]          # (site, T)
            k = np.where(p >= 0, p, 0)
            fx = np.moveaxis(S.tmax[mk][:, k], 1, 2)                       # (member, site, T)
            fn = np.moveaxis(S.tmin[mk][:, k], 1, 2)
            on_e = use & (esrc == C.MET_SOURCES.index("climatology"))    # ET0 climatology on a SEAS5 day: scaled
            ratio = s5.hargreaves_ratio(fx, fn, tmax, tmin)
            et0 = np.where(on_e[None], et0 * ratio, et0).astype(np.float32)
            tmax = np.where(use[None], fx, tmax).astype(np.float32)
            tmin = np.minimum(np.where(use[None], fn, tmin), tmax).astype(np.float32)
            tsrc = np.where(use, C.MET_SOURCES.index("seasonal"), tsrc).astype(np.int8)
            esrc = np.where(on_e, C.MET_SOURCES.index("seasonal"), esrc).astype(np.int8)
        attrs = {**attrs, "season_year": y, "temperature_forecast": self.seas5_note}
        return to_dataset(rain, tmax, tmin, et0, src, tsrc, esrc, dates, self.sites, attrs)

    # ── an observed season (benchmark) ───────────────────────────────────
    def observed(self, year):
        dates = self.dates(year)
        rain = self.observed_rain(dates)[None]
        src = np.full(len(dates), C.PRECIP_SOURCES.index("obs_final"), np.int8)
        tmax, tmin, et0, tsrc, esrc = self.met(year, dates)
        attrs = {"forecast_source": "observed", "model_label": "Observed weather (CHIRPS v2, ERA5-Land)", "season_year": year,
                 "run_date": "", "obs_end": "", "members_kind": "one observed season"}
        return to_dataset(rain, tmax, tmin, et0, src, tsrc, esrc, dates, self.sites, attrs)


def to_dataset(rain, tmax, tmin, et0, src, tsrc, esrc, dates, sites, attrs):
    """tmax, tmin, et0: (member, site, time), or (site, time) for the same in every member."""
    n = rain.shape[0]
    tmax, tmin, et0 = (np.broadcast_to(a, (n, *a.shape)) if a.ndim == 2 else a for a in (tmax, tmin, et0))
    site_coords = {"site": [s.id for s in sites], "site_name": ("site", [s.name for s in sites]),
                   "lat": ("site", [s.lat for s in sites]), "lon": ("site", [s.lon for s in sites]),
                   "cell_lat": ("site", [s.cell_lat for s in sites]), "cell_lon": ("site", [s.cell_lon for s in sites])}
    ds = xr.Dataset(
        {"precip_mm": (("member", "site", "time"), rain.astype(np.float32)),
         "tmax_c": (("member", "site", "time"), np.ascontiguousarray(tmax, np.float32)),
         "tmin_c": (("member", "site", "time"), np.ascontiguousarray(tmin, np.float32)),
         "et0_mm": (("member", "site", "time"), np.ascontiguousarray(et0, np.float32)),
         "precip_source": (("time",), src), "tmax_source": (("site", "time"), tsrc), "et0_source": (("site", "time"), esrc)},
        coords={"member": np.arange(1, rain.shape[0] + 1), "time": dates, **site_coords})
    ds["precip_mm"].attrs["units"] = "mm/day"
    ds["tmax_c"].attrs["units"] = ds["tmin_c"].attrs["units"] = "degC"
    ds["et0_mm"].attrs["units"] = "mm/day"
    ds.attrs.update({
        "precip_sources": json.dumps(C.PRECIP_SOURCES), "met_sources": json.dumps(C.MET_SOURCES),
        "calibration": "CHIRPS v2 quantile mapping of SEAS5 (1993–2016); weather forecasts as in forecast_runs.py",
        "spatial_resolution": "0.25° analysis-grid cell nearest each site; weather forecasts from their native grids "
                              "(0.25–1.5°) mapped to it; temperature at the site (ERA5-Land 0.1°)",
        "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        **{k: (v if isinstance(v, (str, int, float)) else json.dumps(v)) for k, v in attrs.items()}})
    return ds


REQUIRED = {"precip_mm": ("member", "site", "time"), "tmax_c": ("member", "site", "time"),
            "tmin_c": ("member", "site", "time"), "et0_mm": ("member", "site", "time"), "precip_source": ("time",),
            "tmax_source": ("site", "time"), "et0_source": ("site", "time")}
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
    if (ds.tmin_c.values > ds.tmax_c.values + 1e-6).any():
        p.append("tmin above tmax")
    n_p, n_m = len(json.loads(ds.attrs["precip_sources"])), len(json.loads(ds.attrs["met_sources"]))
    if ds.precip_source.values.min() < 0 or ds.precip_source.values.max() >= n_p:
        p.append("precip_source codes out of range")
    for v in ("tmax_source", "et0_source"):
        if ds[v].values.min() < 0 or ds[v].values.max() >= n_m:
            p.append(f"{v} codes out of range")
    return p
