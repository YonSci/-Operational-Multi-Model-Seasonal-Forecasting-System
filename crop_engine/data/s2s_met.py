"""
Daily solar radiation, vapour pressure and 2 m wind from the sub-seasonal forecasts at the crop sites, ratio-corrected
to their ERA5-Land series (crop_engine.data.era5land.site_met), for the crop weather of the s2s-ecmwf and s2s-gefs
runs beside their temperature (data/s2s_temperature.py: the same archives, members, training runs and files' layout).

Daily values by UTC valid day, at the archive's nearest cell to each site:
  ecmwf (ECMWF IFS extended range, daily leads; lead L covers the 24 hours before it → day L − 1)
    rad    the 24-hour mean downward short-wave flux × 0.0864 (W m-2 → MJ m-2 day-1)
    vap    at the 24-hour mean 2 m dewpoint, FAO-56 Eq. 14 (hPa)
    wind2  the mean speed of the 10 m wind at the day's two 00 UTC instants (its start and end) × 0.748 (Eq. 47)
  gefs (NOAA GEFS 35-day, 3-hourly to day 10, then 6-hourly)
    rad    the mean of the four 6-hour mean fluxes ending 06, 12, 18 and 24 UTC (the 6-hourly steps; the 3-hourly ones
           in between average only from the last 6-hour mark) × 0.0864
    vap    the mean over the day's instants of RH × e°(T) (2 m relative humidity and temperature)
    wind2  the mean over the day's instants of the 10 m speed × 0.748
The dewpoint, the 00 UTC winds and GEFS's instants are not ERA5-Land's daily means: the correction absorbs that offset
with each model's own bias.

Correction: as SEAS5's radiation, humidity and wind (data/seas5.py), a ratio per site and lead day: the training
runs' ERA5-Land site mean over their member mean on the same valid days, each ±SMOOTH smoothed along the lead,
clipped to RATIO; every member is multiplied by it, so the anomaly and the spread are kept as fractions.

Files: data/ecmwf_ext/ext_met_<YYYYMMDD>_sites.nc, data/gefs/gefs_met_<YYYYMMDD>_sites.nc (rad, vap, wind2: member,
time, site; written by the daily fetches with the temperature) and outputs/crop_engine/s2s_temperature/
<source>_met_training.nc (member means, run × lead × site).

  python -m crop_engine.data.s2s_met --build ecmwf gefs      # the training runs (network, not CDS)
  python -m crop_engine.data.s2s_met --ratios                # print the ratios at the sites
"""
import argparse
import sys
import time

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine.data import era5land
from crop_engine.data import s2s_temperature as s2t
from crop_engine.data import sites as sites_mod

RUN_PREFIX = {"ecmwf": "ext_met", "gefs": "gefs_met"}
KEYS = {"rad": "rad_mj_m2", "vap": "vap_hpa", "wind2": "wind2_ms"}      # file variable → ERA5-Land site column
RATIO = (0.5, 2.0)
SMOOTH = 3
W_TO_MJ = 0.0864
WIND_10_TO_2 = 0.748
VARS = {"ecmwf": ("downward_short_wave_radiation_flux_surface", "average_dew_point_temperature_2m", "wind_u_10m",
                  "wind_v_10m"),
        "gefs": ("downward_short_wave_radiation_flux_surface", "relative_humidity_2m", "temperature_2m", "wind_u_10m",
                 "wind_v_10m")}


def es_hpa(t):
    """Saturation vapour pressure (hPa) at t °C (FAO-56 Eq. 11)."""
    return 6.108 * np.exp(17.27 * t / (t + 237.3))


def _day_mean(vals, day, n_day):
    """Mean over the steps of each day (vals (member, step, point), day (step,) with −1 for none) → (member, n_day,
    point); a day with no finite step is NaN."""
    out = np.full((vals.shape[0], n_day, vals.shape[2]), np.nan, np.float32)
    for d in range(n_day):
        k = np.where(day == d)[0]
        if len(k):
            v = vals[:, k]
            ok = np.isfinite(v).all(axis=(0, 2))
            if ok.any():
                out[:, d] = v[:, ok].mean(axis=1)
    return out


def daily_met(source, arrays, leads, init):
    """{archive variable: (member, step, point)} of one run → {rad, vap, wind2: (member, day, point)}, the dates."""
    hours = np.asarray((pd.to_timedelta(leads) / pd.Timedelta(hours=1)).astype(int))
    n_day = int(hours[-1] // 24)
    u, v = arrays["wind_u_10m"], arrays["wind_v_10m"]
    speed = np.sqrt(u ** 2 + v ** 2)
    if source == "ecmwf":
        prev = np.where(hours > 0, (hours - 24) // 24, -1)                # lead L (hours 24 L) → day L − 1
        rad = _day_mean(arrays["downward_short_wave_radiation_flux_surface"] * W_TO_MJ, prev, n_day)
        vap = _day_mean(es_hpa(arrays["average_dew_point_temperature_2m"]), prev, n_day)
        # the day's start and end instants: the 00 UTC steps of day d and d + 1
        inst = np.where(hours % 24 == 0, hours // 24, -1)
        w = np.full((speed.shape[0], n_day, speed.shape[2]), np.nan, np.float32)
        for d in range(n_day):
            a, b = np.where(inst == d)[0], np.where(inst == d + 1)[0]
            if len(a) and len(b):
                w[:, d] = (speed[:, a[0]] + speed[:, b[0]]) / 2
        wind = w
    else:
        six = np.where((hours > 0) & (hours % 6 == 0), (hours - 6) // 24, -1)  # 6-hour mean ending at h → its day
        rad = _day_mean(arrays["downward_short_wave_radiation_flux_surface"] * W_TO_MJ, six, n_day)
        inst = np.where(hours < n_day * 24, hours // 24, -1)
        vap = _day_mean(arrays["relative_humidity_2m"] / 100.0 * es_hpa(arrays["temperature_2m"]), inst, n_day)
        wind = _day_mean(speed, inst, n_day)
    dates = pd.date_range(pd.Timestamp(init).normalize(), periods=n_day, freq="D")
    return {"rad": rad, "vap": vap, "wind2": (wind * WIND_10_TO_2).astype(np.float32)}, dates


def at_points(source, ds, init, lats, lons):
    sel = dict(init_time=init, latitude=xr.DataArray(lats, dims="point"), longitude=xr.DataArray(lons, dims="point"))
    arrays = {v: ds[v].sel(**sel, method="nearest").transpose("ensemble_member", "lead_time", "point").values.astype(np.float32)
              for v in VARS[source]}
    return daily_met(source, arrays, ds.lead_time.values, init)


def save_run(source, ds, init, sites, out_dir=None):
    """The run's daily rad, vap, wind2 at the crop sites → <out_dir>/<prefix>_<YYYYMMDD>_sites.nc (the daily fetch)."""
    out_dir = out_dir or s2t.RUN_DIRS[source]
    out = out_dir / f"{RUN_PREFIX[source]}_{pd.Timestamp(init):%Y%m%d}_sites.nc"
    if out.exists():
        return out
    met, dates = at_points(source, ds, init, np.array([s.lat for s in sites]), np.array([s.lon for s in sites]))
    full = np.all([np.isfinite(a).all(axis=(0, 2)) for a in met.values()], axis=0)
    if not full.all():                                   # still being ingested: saved on a later day's fetch
        raise RuntimeError(f"run {pd.Timestamp(init):%Y-%m-%d} has {int(full.sum())} of {len(full)} days so far")
    ds_out = xr.Dataset({k: (("member", "time", "site"), a) for k, a in met.items()},
                        coords={"member": ds.ensemble_member.values.astype(int), "time": dates,
                                "site": [s.id for s in sites]})
    for k, u in (("rad", "MJ m-2 day-1"), ("vap", "hPa"), ("wind2", "m/s")):
        ds_out[k].attrs["units"] = u
    out_dir.mkdir(parents=True, exist_ok=True)
    ds_out.assign_attrs(source=f"{s2t.LABEL[source]} via dynamical.org", init=f"{pd.Timestamp(init):%Y%m%d}00",
                        note="daily solar radiation, vapour pressure, 2 m wind by UTC valid day (crop_engine/data/"
                             "s2s_met.py), nearest cell to each crop site; uncorrected").to_netcdf(out)
    return out


def fetch_runs(source, ds, inits, log_=print):
    """As s2s_temperature.fetch_runs, for radiation, humidity and wind; never raises."""
    try:
        sites = sites_mod.registered_sites()
    except Exception as exc:
        log_(f"  radiation, humidity, wind at the crop sites: skipped ({type(exc).__name__}: {str(exc)[:160]})")
        return
    for init in inits:
        try:
            p = save_run(source, ds, init, sites)
            log_(f"  {p.name}: radiation, humidity and wind at {len(sites)} crop sites")
        except Exception as exc:
            log_(f"  {pd.Timestamp(init):%Y-%m-%d} radiation, humidity, wind: skipped ({type(exc).__name__}: {str(exc)[:120]})")


# ── training: the ratios by lead day ────────────────────────────────────────
def training_path(source):
    return s2t.TRAIN_DIR / f"{source}_met_training.nc"


def build(source, limit=None):
    """Member means of the training runs (s2s_temperature.training_inits) → <source>_met_training.nc; resumable."""
    s2t.TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    path = training_path(source)
    sites = sites_mod.registered_sites()
    lats, lons = np.array([s.lat for s in sites]), np.array([s.lon for s in sites])
    have = {}
    if path.exists():
        with xr.open_dataset(path) as old:
            old.load()
            for i, init in enumerate(pd.DatetimeIndex(old.init.values)):
                have[init] = {k: old[k].values[i] for k in KEYS}
    ds = s2t.open_archive(source)
    todo = [i for i in s2t.training_inits(source, ds) if i not in have]
    if limit:
        todo = todo[:limit]
    s2t.log(f"{source} radiation, humidity, wind: {len(have)} training runs on disk, {len(todo)} to read")
    for k, init in enumerate(todo):
        t0 = time.time()
        try:
            met, _ = at_points(source, ds, init, lats, lons)
        except Exception as exc:
            s2t.log(f"  {init:%Y-%m-%d}: skipped ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        with np.errstate(invalid="ignore"):
            have[init] = {key: np.nanmean(a, axis=0) for key, a in met.items()}           # (day, site)
        s2t.log(f"  {init:%Y-%m-%d}: {time.time() - t0:.0f} s ({k + 1}/{len(todo)})")
        if (k + 1) % 10 == 0:
            _write(path, have, sites, source)
    if have:
        _write(path, have, sites, source)
    return path


def _write(path, have, sites, source):
    inits = sorted(have)
    n = max(have[i]["rad"].shape[0] for i in inits)

    def pad(a):
        return np.concatenate([a, np.full((n - a.shape[0], a.shape[1]), np.nan, np.float32)]) if a.shape[0] < n else a
    ds = xr.Dataset({k: (("init", "lead", "site"), np.stack([pad(have[i][k]) for i in inits])) for k in KEYS},
                    coords={"init": inits, "lead": np.arange(n), "site": [s.id for s in sites]},
                    attrs={"source": f"{s2t.LABEL[source]} via dynamical.org: member means of daily radiation, vapour "
                                     "pressure, 2 m wind at the crop sites", "lead": "day 0 = the run's start day (UTC)"})
    tmp = path.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp)
    tmp.replace(path)


def ratios(source, met, site_ids, exclude_after=None):
    """{rad, vap, wind2: (lead, site)} ERA5-Land over the model, smoothed and clipped, and the number of training runs;
    None without enough. met: {site id: ERA5-Land DataFrame (era5land.site_met)}."""
    path = training_path(source)
    if not path.exists():
        return None, 0
    with xr.open_dataset(path) as tr:
        tr = tr.sel(site=list(site_ids)).load()
    inits = pd.DatetimeIndex(tr.init.values)
    if exclude_after is not None:
        keep = inits < pd.Timestamp(exclude_after)
        tr, inits = tr.isel(init=np.where(keep)[0]), inits[keep]
    if len(inits) < s2t.MIN_RUNS:
        return None, len(inits)
    n_lead = tr.sizes["lead"]
    out = {}
    for key, col in KEYS.items():
        obs = np.stack([np.stack([met[s][col].reindex(pd.date_range(i, periods=n_lead, freq="D")).values
                                  for s in site_ids], axis=1) for i in inits])          # (run, lead, site)
        model = tr[key].values.copy()
        model[~np.isfinite(obs)] = np.nan                                              # the same days on both sides
        obs[~np.isfinite(tr[key].values)] = np.nan
        with np.errstate(invalid="ignore", divide="ignore"):
            r = s2t._smooth(np.nanmean(obs, axis=0), SMOOTH) / s2t._smooth(np.nanmean(model, axis=0), SMOOTH)
        out[key] = np.clip(np.where(np.isfinite(r), r, 1.0), *RATIO)
    return out, len(inits)


class RunMet:
    """A forecast run's corrected radiation, vapour pressure and wind at the sites: (member, day, site) by valid date,
    as s2s_temperature.RunTemperature (the same member order)."""

    def __init__(self, source, init, site_ids, met):
        f = s2t.RUN_DIRS[source] / f"{RUN_PREFIX[source]}_{pd.Timestamp(init):%Y%m%d}_sites.nc"
        if not f.exists():
            raise FileNotFoundError(f"{f.name} not on disk")
        r, n = ratios(source, met, site_ids)
        if r is None:
            raise ValueError(f"{n} training runs of radiation, humidity and wind (at least {s2t.MIN_RUNS} needed; "
                             f"python -m crop_engine.data.s2s_met --build {source})")
        with xr.open_dataset(f) as ds:
            ds = ds.sel(site=list(site_ids)).load()
        self.source, self.init, self.n_train = source, pd.Timestamp(init), n
        dates = pd.DatetimeIndex(ds.time.values)
        lead = (dates - self.init.normalize()).days.values
        ok = lead < r["rad"].shape[0]
        self.dates, lead = dates[ok], lead[ok]
        self.values = {k: (ds[k].values[:, ok] * r[k][lead][None]).astype(np.float32) for k in KEYS}
        self.ratio = {k: v[lead] for k, v in r.items()}

    def on(self, dates):
        return self.dates.get_indexer(pd.DatetimeIndex(dates))

    def describe(self):
        return (f"{s2t.LABEL[self.source]} run {self.init:%Y-%m-%d} radiation, humidity and wind, ratio-corrected to "
                f"ERA5-Land by lead day ({self.n_train} training runs)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", nargs="+", choices=list(s2t.SOURCES))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ratios", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for s in a.build or []:
        build(s, a.limit)
    if a.ratios:
        sites = sites_mod.registered_sites()
        met = era5land.site_met(sites, refresh=False)
        for src in s2t.SOURCES:
            r, n = ratios(src, met, [s.id for s in sites])
            if r is None:
                s2t.log(f"{src}: {n} training runs of radiation, humidity, wind: not enough")
                continue
            s2t.log(f"{src}: {n} training runs; ERA5-Land / model at lead days 1, 14, last (rad, vap, wind2)")
            for j, s in enumerate(sites):
                pick = [1, 14, r["rad"].shape[0] - 2]
                s2t.log(f"  {s.name:30s} " + "   ".join(
                    k + " " + " ".join(f"{r[k][i, j]:.2f}" for i in pick) for k in KEYS))


if __name__ == "__main__":
    main()
