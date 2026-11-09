"""
Daily maximum and minimum temperature from the sub-seasonal forecasts at the crop sites, bias-corrected to their
ERA5-Land series, for the crop weather of the s2s-ecmwf and s2s-gefs forecast runs (crop_engine/data/weather.py).

Sources (dynamical.org archives of the real-time products, the same as their rain; CC-BY-4.0, ECMWF terms of use):
  ecmwf  ECMWF IFS extended range: 101 members, daily to day 46, 1.5° (the extended-range run the rain of the
         s2s-ecmwf run used; ECMWF ENS days 1–15 have no temperature on disk, so those days also take it)
  gefs   NOAA GEFS 35-day: 31 members, 3-hourly to day 10, then 6-hourly, 0.25°
Each step's maximum (minimum) over its period goes to the UTC day the period starts, as the archives' rain does;
a day's maximum is the highest of its steps, its minimum the lowest. Each site takes the archive's nearest cell.

Per-run files (the daily fetch: scripts/fetch_ecmwf_extended.py, scripts/fetch_gefs_35day.py, beside the rain):
  data/ecmwf_ext/ext_t2m_<YYYYMMDD>_sites.nc, data/gefs/gefs_t2m_<YYYYMMDD>_sites.nc
      tmax, tmin (member, time, site) in °C at the crop sites

Bias correction: the delta method of the SEAS5 temperature (data/seas5.py), by lead day: for each site and lead day,
the bias is the member mean of past runs minus the ERA5-Land site series on the same valid days, averaged over the
training runs and ±SMOOTH-day smoothed along the lead; every member of a run has it subtracted, so its anomaly and
spread are kept; tmin is capped at tmax. Training runs (`build`, run once and refreshed as runs accumulate):
  ecmwf  the archive's runs every EVERY["ecmwf"] days (the archive starts on 1 Jan 2026)
  gefs   the runs every EVERY["gefs"] days from 1 Aug to 31 Dec of 2020–2025 (the season's months)
  → outputs/crop_engine/s2s_temperature/<source>_training.nc   tmax, tmin member means (run, lead, site)

  python -m crop_engine.data.s2s_temperature --build ecmwf gefs     # the training runs (network; a few GB read)
  python -m crop_engine.data.s2s_temperature --bias                 # print the biases at the sites
"""
import argparse
import datetime as dt
import sys
import time
import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C
from crop_engine.data import era5land
from crop_engine.data import sites as sites_mod

SOURCES = {"ecmwf": "ecmwf-ifs-ens-forecast-46-day-daily-1-5-degree", "gefs": "noaa-gefs-forecast-35-day"}
RUN_DIRS = {"ecmwf": C.BASE / "data" / "ecmwf_ext", "gefs": C.BASE / "data" / "gefs"}
RUN_PREFIX = {"ecmwf": "ext_t2m", "gefs": "gefs_t2m"}
TRAIN_DIR = C.OUT / "s2s_temperature"
EVERY = {"ecmwf": 2, "gefs": 5}
SMOOTH = 3                       # ± lead days of the bias's running mean
MIN_RUNS = 20                    # training runs needed for a correction
LABEL = {"ecmwf": "ECMWF extended range", "gefs": "NOAA GEFS 35-day"}


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] s2s temperature: {m}", flush=True)


def open_archive(source):
    import icechunk
    import pystac
    col = pystac.Catalog.from_file("https://stac.dynamical.org/catalog.json").get_child(SOURCES[source])
    repo = icechunk.Repository.open(icechunk.http_storage(col.assets["icechunk-https"].href))
    return xr.open_zarr(repo.readonly_session("main").store, chunks=None)


def daily_extremes(tx, tn, leads, init):
    """tx, tn (member, step, ...) the steps' maximum and minimum over the period ending at each lead → daily
    (member, day, ...) maximum and minimum by UTC valid day, and the valid dates. Days missing a step are NaN."""
    hours = (pd.to_timedelta(leads) / pd.Timedelta(hours=1)).astype(int)
    hours = np.asarray(hours)
    n_day = int(hours[-1] // 24)
    shape = (tx.shape[0], n_day) + tx.shape[2:]
    dmax, dmin = np.full(shape, -np.inf, np.float32), np.full(shape, np.inf, np.float32)
    seen, need = np.zeros(n_day, int), np.zeros(n_day, int)
    for k in range(1, len(hours)):                       # step k: the period (hours[k-1], hours[k]]
        d = hours[k - 1] // 24
        if d >= n_day:
            continue
        need[d] += 1
        x, n = tx[:, k], tn[:, k]
        if np.isfinite(x).all() and np.isfinite(n).all():
            seen[d] += 1
            dmax[:, d] = np.maximum(dmax[:, d], x)
            dmin[:, d] = np.minimum(dmin[:, d], n)
    bad = seen < need
    dmax[:, bad], dmin[:, bad] = np.nan, np.nan
    dates = pd.date_range(pd.Timestamp(init).normalize(), periods=n_day, freq="D")
    return dmax, dmin, dates


def at_points(ds, init, lats, lons):
    """Daily tmax, tmin (member, day, point) of one run at the points' nearest cells, and the valid dates."""
    sel = dict(init_time=init, latitude=xr.DataArray(lats, dims="point"), longitude=xr.DataArray(lons, dims="point"))
    out = []
    for v in ("maximum_temperature_2m", "minimum_temperature_2m"):
        a = ds[v].sel(**sel, method="nearest").transpose("ensemble_member", "lead_time", "point")
        out.append(a.values.astype(np.float32))
    leads = ds.lead_time.values
    return daily_extremes(out[0], out[1], leads, init)


def save_run(source, ds, init, sites, out_dir=None):
    """The run's daily tmax, tmin at the crop sites → <out_dir>/<prefix>_<YYYYMMDD>_sites.nc (the daily fetch)."""
    out_dir = out_dir or RUN_DIRS[source]
    out = out_dir / f"{RUN_PREFIX[source]}_{pd.Timestamp(init):%Y%m%d}_sites.nc"
    if out.exists():
        return out
    tx, tn, dates = at_points(ds, init, np.array([s.lat for s in sites]), np.array([s.lon for s in sites]))
    if np.isnan(tx).all():
        raise RuntimeError(f"run {pd.Timestamp(init):%Y-%m-%d} has no temperature yet")
    full = np.isfinite(tx).all(axis=(0, 2)) & np.isfinite(tn).all(axis=(0, 2))
    if not full.all():                                   # still being ingested: saved on a later day's fetch
        raise RuntimeError(f"run {pd.Timestamp(init):%Y-%m-%d} has {int(full.sum())} of {len(full)} days so far")
    n = len(full)
    ds_out = xr.Dataset({"tmax": (("member", "time", "site"), tx[:, :n]), "tmin": (("member", "time", "site"), tn[:, :n])},
                        coords={"member": ds.ensemble_member.values.astype(int), "time": dates[:n],
                                "site": [s.id for s in sites]})
    ds_out["tmax"].attrs["units"] = ds_out["tmin"].attrs["units"] = "degC"
    out_dir.mkdir(parents=True, exist_ok=True)
    ds_out.assign_attrs(source=f"{LABEL[source]} via dynamical.org", init=f"{pd.Timestamp(init):%Y%m%d}00",
                        note="daily max/min of the steps by UTC valid day, nearest cell to each crop site; uncorrected"
                        ).to_netcdf(out)
    return out


def fetch_runs(source, ds, inits, log_=print):
    """Save the sites' temperature of the given runs of the open archive ds (the daily fetch scripts call this);
    a failure is logged, never raised: the rain must not depend on it."""
    try:
        sites = sites_mod.registered_sites()
    except Exception as exc:
        log_(f"  temperature at the crop sites: skipped ({type(exc).__name__}: {str(exc)[:160]})")
        return
    for init in inits:
        try:
            p = save_run(source, ds, init, sites)
            log_(f"  {p.name}: temperature at {len(sites)} crop sites")
        except Exception as exc:
            log_(f"  {pd.Timestamp(init):%Y-%m-%d} temperature: skipped ({type(exc).__name__}: {str(exc)[:120]})")


# ── training: the bias by lead day ─────────────────────────────────────────
def training_inits(source, ds):
    inits = pd.DatetimeIndex(ds.init_time.values)
    if source == "ecmwf":
        return inits[::EVERY[source]]
    keep = inits[(inits.month >= 8) & (inits.year <= 2025)]
    return keep[::EVERY[source]]


def build(source, limit=None):
    """Member means of the training runs at the sites → TRAIN_DIR/<source>_training.nc; runs already there are kept,
    so an interrupted build continues."""
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    path = TRAIN_DIR / f"{source}_training.nc"
    sites = sites_mod.registered_sites()
    lats, lons = np.array([s.lat for s in sites]), np.array([s.lon for s in sites])
    have = {}
    if path.exists():
        with xr.open_dataset(path) as old:
            old.load()
            for i, init in enumerate(pd.DatetimeIndex(old.init.values)):
                have[init] = (old.tmax.values[i], old.tmin.values[i])
    ds = open_archive(source)
    todo = [i for i in training_inits(source, ds) if i not in have]
    if limit:
        todo = todo[:limit]
    log(f"{source}: {len(have)} training runs on disk, {len(todo)} to read")
    n_lead = None
    for k, init in enumerate(todo):
        t0 = time.time()
        try:
            tx, tn, _ = at_points(ds, init, lats, lons)
        except Exception as exc:
            log(f"  {init:%Y-%m-%d}: skipped ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        with np.errstate(invalid="ignore"):
            have[init] = (np.nanmean(tx, axis=0), np.nanmean(tn, axis=0))      # (day, site)
        log(f"  {init:%Y-%m-%d}: {tx.shape[0]} members, {tx.shape[1]} days in {time.time() - t0:.0f} s ({k + 1}/{len(todo)})")
        if (k + 1) % 10 == 0 or k + 1 == len(todo):
            _write(path, have, sites, source)
    if have:
        _write(path, have, sites, source)
    return path


def _write(path, have, sites, source):
    inits = sorted(have)
    n = max(have[i][0].shape[0] for i in inits)
    pad = lambda a: np.concatenate([a, np.full((n - a.shape[0], a.shape[1]), np.nan, np.float32)]) if a.shape[0] < n else a  # noqa: E731
    ds = xr.Dataset({"tmax": (("init", "lead", "site"), np.stack([pad(have[i][0]) for i in inits])),
                     "tmin": (("init", "lead", "site"), np.stack([pad(have[i][1]) for i in inits]))},
                    coords={"init": inits, "lead": np.arange(n), "site": [s.id for s in sites]},
                    attrs={"source": f"{LABEL[source]} via dynamical.org: member means of daily max/min at the crop sites",
                           "lead": "day 0 = the run's start day (UTC)"})
    tmp = path.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp)
    tmp.replace(path)


def _smooth(a, k=SMOOTH):
    out = np.full_like(a, np.nan)
    for i in range(a.shape[0]):
        with np.errstate(invalid="ignore"):
            out[i] = np.nanmean(a[max(0, i - k):i + k + 1], axis=0)
    return out


def bias(source, temps, site_ids, exclude_after=None):
    """{'tmax', 'tmin': (lead, site)} model minus ERA5-Land, ±SMOOTH smoothed, and the number of training runs; None
    without enough runs. temps: {site id: ERA5-Land DataFrame}. exclude_after: only runs started before this date
    (a past run is corrected with runs before it)."""
    path = TRAIN_DIR / f"{source}_training.nc"
    if not path.exists():
        return None, 0
    with xr.open_dataset(path) as tr:
        tr = tr.sel(site=list(site_ids)).load()
    inits = pd.DatetimeIndex(tr.init.values)
    if exclude_after is not None:
        keep = inits < pd.Timestamp(exclude_after)
        tr, inits = tr.isel(init=np.where(keep)[0]), inits[keep]
    if len(inits) < MIN_RUNS:
        return None, len(inits)
    n_lead = tr.sizes["lead"]
    out = {}
    for key in ("tmax", "tmin"):
        obs = np.stack([np.stack([temps[s][key].reindex(pd.date_range(i, periods=n_lead, freq="D")).values
                                  for s in site_ids], axis=1) for i in inits])          # (run, lead, site)
        with np.errstate(invalid="ignore"):
            d = np.nanmean(tr[key].values - obs, axis=0)
        out[key] = _smooth(d)
    return out, len(inits)


class RunTemperature:
    """A forecast run's corrected temperature at the sites: tmax, tmin (member, day, site) by valid date."""

    def __init__(self, source, init, site_ids, temps):
        f = RUN_DIRS[source] / f"{RUN_PREFIX[source]}_{pd.Timestamp(init):%Y%m%d}_sites.nc"
        if not f.exists():
            raise FileNotFoundError(f"{f.name} not on disk")
        b, n = bias(source, temps, site_ids)
        if b is None:
            raise ValueError(f"{n} training runs (at least {MIN_RUNS} needed; "
                             f"python -m crop_engine.data.s2s_temperature --build {source})")
        with xr.open_dataset(f) as ds:
            ds = ds.sel(site=list(site_ids)).load()
        self.source, self.init, self.n_train = source, pd.Timestamp(init), n
        self.dates = pd.DatetimeIndex(ds.time.values)
        self.members = ds.member.values
        lead = (self.dates - self.init.normalize()).days.values
        ok = lead < b["tmax"].shape[0]
        self.dates, lead = self.dates[ok], lead[ok]
        self.tmax = (ds.tmax.values[:, ok] - b["tmax"][lead][None]).astype(np.float32)
        self.tmin = np.minimum(ds.tmin.values[:, ok] - b["tmin"][lead][None], self.tmax).astype(np.float32)
        self.bias = {k: v[lead] for k, v in b.items()}

    def on(self, dates):
        return self.dates.get_indexer(pd.DatetimeIndex(dates))

    def member_index(self, member_ids):
        """Positions of archive member ids (as the rain join reports them) in this file."""
        pos = {int(m): i for i, m in enumerate(self.members)}
        return np.array([pos[int(m)] for m in member_ids])

    def describe(self):
        return (f"{LABEL[self.source]} run {self.init:%Y-%m-%d}, member paired with the rain, delta-corrected to ERA5-Land "
                f"by lead day ({self.n_train} training runs), {self.dates[0]:%d %b} – {self.dates[-1]:%d %b}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", nargs="+", choices=list(SOURCES), help="read the training runs of these sources")
    ap.add_argument("--limit", type=int, help="read at most this many new training runs (a test)")
    ap.add_argument("--bias", action="store_true", help="print the biases at the sites")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for s in a.build or []:
        build(s, a.limit)
    if a.bias:
        sites = sites_mod.registered_sites()
        temps = {s.id: era5land.site_temperature(s, refresh=False) for s in sites}
        for src in SOURCES:
            b, n = bias(src, temps, [s.id for s in sites])
            if b is None:
                log(f"{src}: {n} training runs, not enough")
                continue
            log(f"{src}: {n} training runs; bias (model − ERA5-Land, °C) at lead days 1, 7, 14, 28, last")
            for j, s in enumerate(sites):
                pick = [1, 7, 14, 28, b["tmax"].shape[0] - 2]
                log(f"  {s.name:28s} tmax " + " ".join(f"{b['tmax'][i, j]:+.1f}" for i in pick)
                    + "   tmin " + " ".join(f"{b['tmin'][i, j]:+.1f}" for i in pick))


if __name__ == "__main__":
    main()
