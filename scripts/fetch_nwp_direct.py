#!/usr/bin/env python3
"""
fetch_nwp_direct.py
───────────────────
Daily precipitation forecasts for Kenya downloaded directly from each producing centre (00 UTC run):

  model id                          source                                                   range
  ecmwf_ifs025                      ECMWF open data, oper fc tp (data.ecmwf.int)             15 d
  ecmwf_ens_median                  ECMWF open data ensemble (fetch_ecmwf_ens.py file)       15 d
  gfs_global                        NOAA NOMADS GRIB filter, APCP 0-to-step, Kenya subregion 16 d
  gem_global                        ECCC MSC Datamart GDPS 15 km Precip-Accum24h             10 d
  icon_global                       DWD open data ICON global TOT_PREC (icosahedral)          7 d
  ukmo_global_deterministic_10km    Met Office global 10 km on AWS Open Data (NetCDF)          7 d

Days are UTC days (00–24 UTC) of the 00 UTC run. Any model whose download fails is filled from
Open-Meteo (fetch_nwp_forecasts.py) so the dashboard always has all six. Output has the same columns
as fetch_nwp_forecasts.py, plus `source`: data/nwp/nwp_<YYYYMMDD>.csv
"""
import argparse
import bz2
import datetime as dt
import glob
import io
import json
import re
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
import fetch_nwp_forecasts as om  # noqa: E402  (points, stations, Open-Meteo fallback)

OUT = BASE / "data" / "nwp"
CACHE = BASE / "data" / "nwp" / "cache"
BOX = dict(s=-6.0, n=6.5, w=32.5, e=43.0)


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def get(url, tries=5, timeout=(20, 180), **kw):
    """GET with retries; (connect, read) timeouts keep a dropped connection from hanging a run."""
    for k in range(tries):
        try:
            r = requests.get(url, timeout=timeout, **kw)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"failed: {url}")


def grib_messages(blob):
    """All GRIB messages in a bytes blob as dicts (values, lats, lons, keys). The blob is split into
    messages using each message's own length (GRIB1: octets 5–7, GRIB2: octets 9–16) and each message is
    decoded in memory — no temporary files (ecCodes keeps files locked on Windows)."""
    import eccodes
    out, pos = [], 0
    while True:
        i = blob.find(b"GRIB", pos)
        if i < 0:
            break
        edition = blob[i + 7]
        length = int.from_bytes(blob[i + 8:i + 16], "big") if edition == 2 else int.from_bytes(blob[i + 4:i + 7], "big")
        h = eccodes.codes_new_from_message(blob[i:i + length])
        try:
            ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
            la0, la1 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
            lo0, lo1 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "longitudeOfLastGridPointInDegrees")
            out.append({"step": eccodes.codes_get(h, "stepRange"), "short": eccodes.codes_get(h, "shortName"),
                        "lat": np.linspace(la0, la1, nj), "lon": np.linspace(lo0, lo1 if lo1 > lo0 else lo1 + 360, ni),
                        "values": eccodes.codes_get_values(h).reshape(nj, ni)})
        finally:
            eccodes.codes_release(h)
        pos = i + length
    return out


def crop(lat, lon, a):
    """Crop a regular lat/lon field to the Kenya box; returns flat lat, lon, values."""
    lon = np.where(lon > 180, lon - 360, lon)
    i = (lat >= BOX["s"]) & (lat <= BOX["n"])
    j = (lon >= BOX["w"]) & (lon <= BOX["e"])
    la, lo = np.meshgrid(lat[i], lon[j], indexing="ij")
    return la.ravel(), lo.ravel(), a[np.ix_(i, j)].ravel()


# ── per-model readers → (dates, lat[n], lon[n], daily[nd, n]) on source points in the Kenya box ──
def ecmwf_ifs(date):
    base = f"https://data.ecmwf.int/forecasts/{date:%Y%m%d}/00z/ifs/0p25/oper/{date:%Y%m%d}000000"
    cum, la, lo = [], None, None
    for step in range(24, 361, 24):
        try:
            idx = get(f"{base}-{step}h-oper-fc.index")
        except RuntimeError:
            log(f"ecmwf_ifs025: step {step} h unavailable; keeping {len(cum)} day(s)")
            break
        if idx is None:
            break
        e = [json.loads(l) for l in idx.text.splitlines() if json.loads(l).get("param") == "tp"][0]
        try:
            blob = get(f"{base}-{step}h-oper-fc.grib2", headers={"Range": f"bytes={e['_offset']}-{e['_offset'] + e['_length'] - 1}"}).content
        except RuntimeError:
            log(f"ecmwf_ifs025: step {step} h unavailable; keeping {len(cum)} day(s)")
            break
        m = grib_messages(blob)[0]
        la, lo, v = crop(m["lat"], m["lon"], m["values"])
        cum.append(v * 1000.0)                        # m → mm, accumulated from run start
    daily = np.diff(np.array(cum), axis=0, prepend=0)
    return [date + dt.timedelta(days=k) for k in range(len(cum))], la, lo, np.clip(daily, 0, None)


def gfs(date):
    cum, la, lo = [], None, None
    for step in range(24, 385, 24):
        url = ("https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?"
               f"dir=%2Fgfs.{date:%Y%m%d}%2F00%2Fatmos&file=gfs.t00z.pgrb2.0p25.f{step:03d}&var_APCP=on&lev_surface=on"
               f"&subregion=&toplat={BOX['n']}&leftlon={BOX['w']}&rightlon={BOX['e']}&bottomlat={BOX['s']}")
        try:
            r = get(url)
        except RuntimeError:
            log(f"gfs_global: f{step:03d} unavailable; keeping {len(cum)} day(s)")
            break
        if r is None or len(r.content) < 100:
            break
        msgs = [m for m in grib_messages(r.content) if m["step"].startswith("0-")]   # accumulation since run start
        if not msgs:
            raise RuntimeError(f"GFS f{step:03d}: no 0-{step} APCP message")
        la, lo, v = crop(msgs[0]["lat"], msgs[0]["lon"], msgs[0]["values"])
        cum.append(v)                                 # kg m-2 = mm
        time.sleep(0.5)
    daily = np.diff(np.array(cum), axis=0, prepend=0)
    return [date + dt.timedelta(days=k) for k in range(len(cum))], la, lo, np.clip(daily, 0, None)


def gdps(date):
    days, la, lo = [], None, None
    for step in range(24, 241, 24):
        url = (f"https://dd.weather.gc.ca/{date:%Y%m%d}/WXO-DD/model_gdps/15km/00/{step:03d}/"
               f"{date:%Y%m%d}T00Z_MSC_GDPS_Precip-Accum24h_Sfc_LatLon0.15_PT{step:03d}H.grib2")
        try:
            r = get(url)
        except RuntimeError:
            log(f"gem_global: PT{step:03d}H unavailable; keeping {len(days)} day(s)")
            break
        if r is None:
            break
        m = grib_messages(r.content)[0]
        la, lo, v = crop(m["lat"], m["lon"], m["values"])
        days.append(v)                                # 24-h accumulation ending at the step (mm)
    return [date + dt.timedelta(days=k) for k in range(len(days))], la, lo, np.clip(np.array(days), 0, None)


def icon(date):
    import eccodes  # noqa: F401
    CACHE.mkdir(parents=True, exist_ok=True)
    gi = CACHE / "icon_R03B07_kenya_cells.npz"
    if not gi.exists():
        # One-off: cell-centre coordinates come from DWD's small per-run time-invariant CLAT/CLON GRIB files
        # (the full grid description is ~940 MB); only Kenya-box cells are kept.
        import eccodes
        log("ICON: fetching CLAT/CLON once (cell centres for the Kenya box)")
        coords = {}
        for var in ("CLAT", "CLON"):
            r = get(f"https://opendata.dwd.de/weather/nwp/icon/grib/00/{var.lower()}/"
                    f"icon_global_icosahedral_time-invariant_{date:%Y%m%d}00_{var}.grib2.bz2")
            if r is None:
                raise RuntimeError(f"ICON {var} file not found for {date}")
            h = eccodes.codes_new_from_message(bz2.decompress(r.content))
            try:
                coords[var] = eccodes.codes_get_values(h)          # degrees
            finally:
                eccodes.codes_release(h)
        clat, clon = coords["CLAT"], coords["CLON"]
        sel = np.where((clat >= BOX["s"]) & (clat <= BOX["n"]) & (clon >= BOX["w"]) & (clon <= BOX["e"]))[0]
        np.savez(gi, idx=sel, lat=clat[sel], lon=clon[sel])
    g = np.load(gi)
    cum = []
    for step in range(24, 181, 24):
        url = (f"https://opendata.dwd.de/weather/nwp/icon/grib/00/tot_prec/"
               f"icon_global_icosahedral_single-level_{date:%Y%m%d}00_{step:03d}_TOT_PREC.grib2.bz2")
        try:
            r = get(url)
        except RuntimeError:
            log(f"icon_global: step {step} h unavailable; keeping {len(cum)} day(s)")
            break
        if r is None:
            break
        import eccodes
        h = eccodes.codes_new_from_message(bz2.decompress(r.content))
        try:
            vals = eccodes.codes_get_values(h)
        finally:
            eccodes.codes_release(h)
        cum.append(vals[g["idx"]])                    # kg m-2 accumulated from run start
    daily = np.diff(np.array(cum), axis=0, prepend=0)
    return [date + dt.timedelta(days=k) for k in range(len(cum))], g["lat"], g["lon"], np.clip(daily, 0, None)


class RangeFile(io.RawIOBase):
    """Read-only file object over HTTP Range requests, cached in 64 KB blocks, so h5py can read the Kenya
    chunks of a remote netCDF-4 file (UKMO: 128×128 gzip chunks → ~5 requests, ~0.3 MB instead of 3–5 MB)."""

    def __init__(self, url, block=64 * 1024):
        self.url, self.block, self.s = url, block, requests.Session()
        r = self.s.head(url, timeout=(20, 60))
        self.size = int(r.headers["Content-Length"]) if r.status_code == 200 else None
        self.pos, self.cache = 0, {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def _blk(self, b):
        if b not in self.cache:
            lo = b * self.block
            r = get(self.url, headers={"Range": f"bytes={lo}-{min(self.size, lo + self.block) - 1}"}, timeout=(20, 60))
            if r is None:
                raise RuntimeError(f"gone: {self.url}")
            self.cache[b] = r.content
        return self.cache[b]

    def readinto(self, buf):
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        out, p = bytearray(), self.pos
        while len(out) < n:
            b, o = divmod(p, self.block)
            part = self._blk(b)[o:o + n - len(out)]
            out += part
            p += len(part)
        buf[:n] = out
        self.pos += n
        return n


# usual forecast range (days) of each model's 00 UTC run
HORIZON = {"ecmwf_ifs025": 15, "ecmwf_ens_median": 15, "gfs_global": 16, "gem_global": 10, "icon_global": 7,
           "ukmo_global_deterministic_10km": 7}
UKMO_BUDGET_S = 900                                    # stop UKMO after this and keep the complete days
UKMO_WORKERS = 8


def _ukmo_subset(url):
    """Kenya box of one UKMO precipitation-accumulation file → (lat[n], lon[n], mm[n]); runs in a worker process."""
    import h5py
    rf = RangeFile(url)                                # only the Kenya chunks are fetched
    if rf.size is None:
        raise RuntimeError("missing")
    with h5py.File(rf, "r") as f:
        lat, lon = f["latitude"][:], f["longitude"][:]
        i = np.where((lat >= BOX["s"]) & (lat <= BOX["n"]))[0]
        j = np.where((lon >= BOX["w"]) & (lon <= BOX["e"]))[0]
        v = f["lwe_thickness_of_precipitation_amount"]
        units = v.attrs.get("units", b"m")
        scale = 1000.0 if (units.decode() if isinstance(units, bytes) else str(units)) == "m" else 1.0
        vals = v[i[0]:i[-1] + 1, j[0]:j[-1] + 1].astype(np.float64) * scale
    la, lo = np.meshgrid(lat[i], lon[j], indexing="ij")
    return la.ravel(), lo.ravel(), vals.ravel()


def ukmo(date):
    t0 = time.time()
    base = "https://met-office-atmospheric-model-data.s3.eu-west-2.amazonaws.com"
    prefix = f"global-deterministic-10km/{date:%Y%m%d}T0000Z/"
    keys, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        x = get(base + "/", params=q).text
        keys += re.findall(r"<Key>([^<]*precipitation_accumulation[^<]*)</Key>", x)
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", x)
        if not m:
            break
        token = m.group(1)
    log(f"ukmo: {len(keys)} precipitation files listed ({time.time() - t0:.0f} s)")
    # one accumulation file per validity time: take the shortest accumulation period offered at each lead
    files = {}
    for k in keys:
        mm = re.search(r"-PT(\d{4})H00M-precipitation_accumulation-PT(\d{2})H\.nc$", k)
        if mm:
            lead, per = int(mm.group(1)), int(mm.group(2))
            if lead not in files or per < files[lead][1]:
                files[lead] = (k, per)
    leads = sorted(files)
    # keep a non-overlapping chain of periods from 0 to the last lead
    chain, t = [], 0
    for lead in leads:
        k, per = files[lead]
        if lead - per == t:
            chain.append((lead, k)); t = lead
    nd = t // 24
    if nd == 0:
        raise RuntimeError("UKMO: no precipitation accumulation chain found")
    # files are read in parallel worker processes (h5py serialises reads within one process); a day counts
    # only when every file in it arrived within the time budget
    import concurrent.futures as cf
    chain = [(lead, k) for lead, k in chain if (lead - 1) // 24 < nd]
    got = {}
    with cf.ProcessPoolExecutor(max_workers=UKMO_WORKERS) as ex:
        futs = {ex.submit(_ukmo_subset, f"{base}/{k}"): lead for lead, k in chain}
        try:
            for fu in cf.as_completed(futs, timeout=max(60, UKMO_BUDGET_S - (time.time() - t0))):
                try:
                    got[futs[fu]] = fu.result()
                except Exception as exc:
                    log(f"ukmo: lead {futs[fu]} h unavailable ({type(exc).__name__})")
        except cf.TimeoutError:
            log(f"ukmo: time budget reached with {len(got)} of {len(chain)} files")
            for fu in futs:
                fu.cancel()
    first_gap = min([(lead - 1) // 24 for lead, _ in chain if lead not in got], default=nd)
    nd = min(nd, first_gap)
    if nd == 0 or not got:
        raise RuntimeError("UKMO: no complete forecast day could be fetched")
    la, lo = next(iter(got.values()))[:2]
    daily = np.zeros((nd, la.size))
    for lead, (_, _, vals) in got.items():
        if (lead - 1) // 24 < nd:
            daily[(lead - 1) // 24] += vals
    return [date + dt.timedelta(days=k) for k in range(nd)], la, lo, np.clip(daily[:nd], 0, None)


def ens_median(date):
    f = sorted(glob.glob(str(BASE / "data" / "ecmwf_ens" / "ens_tp_*_kenya.nc")))
    if not f:
        raise RuntimeError("no ECMWF ENS file (run fetch_ecmwf_ens.py)")
    e = xr.open_dataset(f[-1])["precip"].median("member")
    la, lo = np.meshgrid(e.lat.values, e.lon.values, indexing="ij")
    return [pd.Timestamp(t).date() for t in e.time.values], la.ravel(), lo.ravel(), e.values.reshape(e.sizes["time"], -1)


READERS = {"ecmwf_ifs025": ecmwf_ifs, "ecmwf_ens_median": ens_median, "gfs_global": gfs, "gem_global": gdps,
           "icon_global": icon, "ukmo_global_deterministic_10km": ukmo}


def sample(points, dates, la, lo, daily, model, source):
    """Grid points: mean of source points within the 0.5° cell; stations: nearest source point."""
    rows = []
    for kind, site, plat, plon in points:
        if kind == "grid":
            m = (np.abs(la - plat) <= 0.25) & (np.abs(lo - plon) <= 0.25)
            vals = daily[:, m].mean(axis=1) if m.any() else np.full(len(dates), np.nan)
        else:
            k = int(np.argmin((la - plat) ** 2 + (lo - plon) ** 2))
            vals = daily[:, k]
        for d, v in zip(dates, vals):
            if np.isfinite(v):
                rows.append({"model": model, "kind": kind, "site": site, "lat": plat, "lon": plon,
                             "date": str(d), "rain_mm": round(float(v), 1), "source": source})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"), help="run date YYYYMMDD (00 UTC run)")
    ap.add_argument("--models", nargs="+", default=list(READERS))
    ap.add_argument("--no-fallback", action="store_true")
    ap.add_argument("--only-missing", action="store_true",
                    help="fetch only models that do not yet have direct data in the day's file (for retries)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    date = dt.datetime.strptime(a.date, "%Y%m%d").date()
    if a.only_missing:
        f = OUT / f"nwp_{date:%Y%m%d}.csv"
        have = set(pd.read_csv(f).query("source == 'direct'").model) if f.exists() and "source" in pd.read_csv(f, nrows=1) else set()
        a.models = [m for m in a.models if m not in have]
        if not a.models:
            log("all models already have direct data"); return
        log(f"retrying: {', '.join(a.models)}")
    points = [("grid", "", la, lo) for la, lo in om.kenya_points()] + [("station", n, la, lo) for n, la, lo in om.stations()]
    rows, failed, direct_days = [], [], {}
    for m in a.models:
        t0 = time.time()
        try:
            dates, la, lo, daily = READERS[m](date)
            if not len(dates):
                raise RuntimeError("no forecast days published yet")
            rows += sample(points, dates, la, lo, daily, m, "direct")
            direct_days[m] = len(dates)
            log(f"{m}: {len(dates)} days direct ({time.time() - t0:.0f} s)")
            if len(dates) < 0.6 * HORIZON.get(m, 0):        # a cut-short download: Open-Meteo may have the full range
                failed.append(m)
        except Exception as exc:
            failed.append(m)
            log(f"{m}: direct download failed ({type(exc).__name__}: {str(exc)[:160]})")
    out = OUT / f"nwp_{date:%Y%m%d}.csv"
    write(out, rows)                                   # save direct results before any fallback can fail
    if failed and not a.no_fallback:
        fb = [m for m in failed if m in om.MODELS]
        if fb:
            log(f"Open-Meteo fallback for: {', '.join(fb)}")
            om.MODELS[:] = fb
            fb_rows = []
            try:
                for i in range(0, len(points), om.BATCH):
                    chunk = points[i:i + om.BATCH]
                    res = om.fetch_batch([(p[2], p[3]) for p in chunk])
                    for (kind, site, plat, plon), d in zip(chunk, res):
                        for m in fb:
                            for t, v in zip(d["daily"]["time"], d["daily"].get(f"precipitation_sum_{m}") or []):
                                if v is not None:
                                    fb_rows.append({"model": m, "kind": kind, "site": site, "lat": plat, "lon": plon,
                                                    "date": t, "rain_mm": round(float(v), 1), "source": "open-meteo"})
                    time.sleep(1)
                # a short direct run is replaced only if Open-Meteo has more days for that model
                fb_days = {m: len({r["date"] for r in fb_rows if r["model"] == m}) for m in fb}
                keep = [m for m in fb if fb_days[m] > direct_days.get(m, 0)]
                if set(fb) - set(keep):
                    log(f"keeping direct data for {', '.join(sorted(set(fb) - set(keep)))} (Open-Meteo has no more days)")
                write(out, [r for r in fb_rows if r["model"] in keep])
            except Exception as exc:
                log(f"Open-Meteo fallback failed ({type(exc).__name__}); keeping earlier values for {', '.join(fb)} if any")


def write(out, rows):
    """Merge rows into the day's file: models in `rows` replace their earlier rows, other models are kept."""
    if not rows:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if out.exists():
        prev = pd.read_csv(out)
        if "source" not in prev:
            prev["source"] = "open-meteo"
        df = pd.concat([prev[~prev.model.isin(df.model.unique())], df], ignore_index=True)
    df.to_csv(out, index=False)
    log(f"wrote {out}: {len(df)} rows; " + ", ".join(f"{m}={g.date.nunique()}d/{g.source.iloc[0]}" for m, g in df[df.kind == 'station'].groupby("model")))


if __name__ == "__main__":
    main()
