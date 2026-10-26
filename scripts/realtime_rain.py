#!/usr/bin/env python3
"""
realtime_rain.py
────────────────
Near-real-time satellite rainfall for Kenya on the project's 0.25° grid: download, monitor, verify.

Products (open access unless noted)            latency   native grid
  arc2     NOAA CPC ARC2 Africa daily          ~2 d      0.1°
  tamsat   TAMSAT v3.1 daily RFE (rfe_filled)  ~4–5 d    0.0375°
  pdirnow  UCI CHRS PDIR-Now daily             ~1 d      0.04°
  chirps   CHIRPS-2.0 final p25 + preliminary  ~5 d      0.25° / 0.05°   (data/chirps_2026, data/chirps_prelim_2026)
  imerg    NASA GPM IMERG Late daily V07       ~1–2 d    0.1°   needs a NASA Earthdata login in ~/.netrc (untested here)
Not included: JAXA GSMaP (needs a JAXA account), MSWEP (needs a GloH2O data request).

All products are aggregated to the 0.25° target grid by averaging source pixels whose centres fall in
each cell. Raw files are streamed through a temp folder and deleted after cropping.

Subcommands
  sync    --start 2025-10-01 --end 2026-10-25 [--products arc2 tamsat pdirnow]
          → data/realtime_rain/<product>_kenya_p25.nc (time, lat, lon; incremental)
  verify  --ref chirps|tamsat --periods 2025-10-01:2025-12-31 2026-09-01:2026-10-20
          → outputs/realtime_rain/verification_<ref>.csv (+ .json)
  monitor --since 2026-10-01
          → outputs/realtime_rain/monitor_<date>.json / .nc (totals, % of normal, planting onset per product)
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import io
import json
import netrc
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
DATA = BASE_DIR / "data" / "realtime_rain"
OUT = BASE_DIR / "outputs" / "realtime_rain"
S, N, W, E, RES = -5.0, 5.5, 33.5, 42.0, 0.25
LAT = np.round(np.arange(S + RES / 2, N, RES), 3)
LON = np.round(np.arange(W + RES / 2, E, RES), 3)
CHIRPS_REC = BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
CHIRPS_FINAL = BASE_DIR / "data" / "chirps_2026" / "chirps-v2.0.2026.days_p25.nc"
CHIRPS_PRELIM = BASE_DIR / "data" / "chirps_prelim_2026" / "chirps_prelim_2026_p25_kenya.nc"
OND_MASK = None


# ── grid aggregation ───────────────────────────────────────────────────────
def to_target(lat, lon, data):
    """Mean of source pixels (centres lat×lon, NaN = missing) falling in each 0.25° target cell."""
    lon = np.where(lon > 180, lon - 360, lon)
    i = np.floor((lat - S) / RES).astype(int)
    j = np.floor((lon - W) / RES).astype(int)
    ii, jj = np.meshgrid(i, j, indexing="ij")
    ok = (ii >= 0) & (ii < len(LAT)) & (jj >= 0) & (jj < len(LON)) & np.isfinite(data)
    flat = ii[ok] * len(LON) + jj[ok]
    s = np.bincount(flat, weights=data[ok], minlength=len(LAT) * len(LON))
    n = np.bincount(flat, minlength=len(LAT) * len(LON))
    with np.errstate(invalid="ignore"):
        return (s / n).reshape(len(LAT), len(LON)).astype(np.float32)


def _get(url, session=None, tries=5, timeout=300):
    sess = session or requests
    for k in range(tries):
        try:
            r = sess.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"failed: {url}")


# ── product readers: day -> (42, 34) mm/day or None if not published ──────
def read_arc2(day):
    b = _get(f"https://ftp.cpc.ncep.noaa.gov/fews/fewsdata/africa/arc2/geotiff/africa_arc.{day:%Y%m%d}.tif.zip")
    if b is None:
        return None
    import rasterio
    with zipfile.ZipFile(io.BytesIO(b)) as z, tempfile.TemporaryDirectory() as td:
        z.extractall(td)
        with rasterio.open(next(Path(td).glob("*.tif"))) as r:
            a = r.read(1).astype(np.float32)
            t = r.transform
            lat = t.f + t.e * (np.arange(r.height) + 0.5)
            lon = t.c + t.a * (np.arange(r.width) + 0.5)
    a[(a < 0) | (a > 1000)] = np.nan
    return to_target(lat, lon, a)


def read_tamsat(day):
    b = _get(f"https://gws-access.jasmin.ac.uk/public/tamsat/rfe/data/v3.1/daily/{day:%Y/%m}/rfe{day:%Y_%m_%d}.v3.1.nc")
    if b is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
        f.write(b)
    try:
        with xr.open_dataset(f.name) as ds:
            v = ds["rfe_filled"].squeeze()
            a = v.values.astype(np.float32)
            a[a < 0] = np.nan
            return to_target(v.lat.values, v.lon.values, a)
    finally:
        os.unlink(f.name)


def read_pdirnow(day):
    b = _get(f"https://persiann.eng.uci.edu/CHRSdata/PDIRNow/PDIRNowdaily/pdirnow1d{day:%y%m%d}.bin.gz")
    if b is None:
        return None
    g = np.frombuffer(gzip.decompress(b), "<f4").reshape(3000, 9000)       # 60N→60S, 0→360E, 0.04°
    lat = 60 - 0.02 - 0.04 * np.arange(3000)
    lon = 0.02 + 0.04 * np.arange(9000)
    i = (lat > S - 0.1) & (lat < N + 0.1)
    j = (lon > W - 0.1) & (lon < E + 0.1)
    a = g[np.ix_(i, j)].astype(np.float32)
    a[a < 0] = np.nan
    return to_target(lat[i], lon[j], a)


_IMERG_SESSION = None
# IMERG daily grid: 0.1°, lon −179.95…179.95 (3600), lat −89.95…89.95 (1800); index ranges cover 33.5–42.0°E, 5.0°S–5.5°N
_IMERG_CE = "/precipitation[0:1:0][2135:1:2219][850:1:954];/lat[850:1:954];/lon[2135:1:2219];/time"


def _imerg_opendap_url(day, run):
    """OPeNDAP link of the daily IMERG granule (run 'L' = Late, 'E' = Early), looked up in NASA CMR."""
    r = _get("https://cmr.earthdata.nasa.gov/search/granules.json?short_name=GPM_3IMERGD" + run + "&version=07"
             f"&temporal={day:%Y-%m-%d}T00:00:00Z,{day:%Y-%m-%d}T23:59:59Z&page_size=5")
    entries = json.loads(r)["feed"]["entry"] if r else []
    hits = [e for e in entries if f".{day:%Y%m%d}-S000000" in e["title"]]
    if not hits:
        return None
    links = [lk["href"] for lk in hits[-1].get("links", []) if lk["href"].startswith("https://opendap.earthdata.nasa.gov/")]
    return links[0] if links else None


def read_imerg(day, run="L"):
    """Kenya subset of the daily IMERG file through NASA's cloud OPeNDAP (Hyrax): the server cuts the box, so only
    ~36 KB per day comes down and the GES DISC / CloudFront file hosts are never contacted. The Earthdata login
    comes from ~/.netrc on the redirect to urs.earthdata.nasa.gov (requests rebuilds auth per host from .netrc)."""
    global _IMERG_SESSION
    try:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
    except (FileNotFoundError, netrc.NetrcParseError):
        auth = None
    if not auth:
        raise RuntimeError("IMERG needs a NASA Earthdata login: add 'machine urs.earthdata.nasa.gov login <user> password <pw>' to ~/.netrc")
    url = _imerg_opendap_url(day, run)
    if url is None:
        return None
    _IMERG_SESSION = _IMERG_SESSION or requests.Session()
    from urllib.parse import quote
    b = _get(f"{url}.dap.nc4?dap4.ce={quote(_IMERG_CE, safe='/:;')}", session=_IMERG_SESSION, timeout=180)
    if b is None or b[1:4] != b"HDF":                # HDF5 signature; anything else is an error page
        return None
    with tempfile.NamedTemporaryFile(suffix=".nc4", delete=False) as f:
        f.write(b)
    try:
        with xr.open_dataset(f.name) as ds:
            v = ds["precipitation"].squeeze().transpose("lat", "lon")
            return to_target(v.lat.values, v.lon.values, v.values.astype(np.float32))
    finally:
        os.unlink(f.name)


# ── Google Earth Engine (IMERG and GSMaP without NASA/JAXA servers) ────────
# Needs: `pip install earthengine-api`, a one-time `earthengine authenticate`, and a Google Cloud project
# registered for Earth Engine, given as env var EE_PROJECT or in ~/.config/earthengine/project.txt.
GEE = {  # product -> (collection, band, hours per image, images per complete UTC day)
    "imerg_gee": ("NASA/GPM_L3/IMERG_V07", "precipitation", 0.5, 48),
    "gsmap_gee": ("JAXA/GPM_L3/GSMaP/v8/operational", "hourlyPrecipRateGC", 1.0, 24),
}


def ee_project():
    p = os.environ.get("EE_PROJECT")
    f = Path.home() / ".config" / "earthengine" / "project.txt"
    return p or (f.read_text().strip() if f.exists() else None)


def _ee():
    import ee
    if not getattr(_ee, "ready", False):
        proj = ee_project()
        ee.Initialize(project=proj) if proj else ee.Initialize()
        _ee.ready = True
    return ee


def read_gee(day, product):
    """Daily total (mm) from an Earth Engine rate collection, averaged onto the 0.25° grid server-side."""
    ee = _ee()
    coll, band, hours, need = GEE[product]
    start = ee.Date(day.isoformat())
    col = ee.ImageCollection(coll).filterDate(start, start.advance(1, "day")).select(band)
    if col.size().getInfo() < need:
        return None                                   # day not complete yet in Earth Engine
    img = (col.sum().multiply(hours).rename("p")
           .setDefaultProjection(col.first().projection())
           .reduceResolution(ee.Reducer.mean(), maxPixels=1024)
           .reproject(crs="EPSG:4326", crsTransform=[RES, 0, W, 0, -RES, N]))
    arr = ee.data.computePixels({
        "expression": img, "fileFormat": "NUMPY_NDARRAY",
        "grid": {"dimensions": {"width": len(LON), "height": len(LAT)}, "crsCode": "EPSG:4326",
                 "affineTransform": {"scaleX": RES, "shearX": 0, "translateX": W, "shearY": 0, "scaleY": -RES, "translateY": N}},
    })
    a = np.asarray(arr["p"], dtype=np.float32)[::-1]   # rows north→south → south→north like LAT
    a[a < 0] = np.nan
    return a


READERS = {"arc2": read_arc2, "tamsat": read_tamsat, "pdirnow": read_pdirnow, "imerg": read_imerg,
           "imerg_early": lambda d: read_imerg(d, run="E"),
           "imerg_gee": lambda d: read_gee(d, "imerg_gee"), "gsmap_gee": lambda d: read_gee(d, "gsmap_gee")}
LABELS = {"chirps": "CHIRPS (final+prelim)", "arc2": "ARC2 (NOAA CPC)", "tamsat": "TAMSAT v3.1",
          "pdirnow": "PDIR-Now (UCI CHRS)", "imerg": "IMERG Late (NASA)", "imerg_early": "IMERG Early (NASA)",
          "imerg_gee": "IMERG (Earth Engine)", "gsmap_gee": "GSMaP Gauge (Earth Engine)"}


# ── storage ─────────────────────────────────────────────────────────────────
def path(product):
    return DATA / f"{product}_kenya_p25.nc"


def load(product):
    if product == "chirps":
        return load_chirps()
    p = path(product)
    if not p.exists():
        return None
    with xr.open_dataset(p) as ds:
        return ds["precip"].load()


def load_chirps():
    parts = []
    with xr.open_dataset(CHIRPS_REC) as ds:
        parts.append(ds["precip"].reindex(lat=LAT, lon=LON, method="nearest", tolerance=0.01).load())
    if CHIRPS_FINAL.exists():
        with xr.open_dataset(CHIRPS_FINAL) as ds:
            f = ds["precip"].rename(latitude="lat", longitude="lon")
            parts.append(f.reindex(lat=LAT, lon=LON, method="nearest", tolerance=0.01).load())
    if CHIRPS_PRELIM.exists():
        with xr.open_dataset(CHIRPS_PRELIM) as ds:
            parts.append(ds["precip"].reindex(lat=LAT, lon=LON, method="nearest", tolerance=0.01).load())
    da = xr.concat(parts, "time")
    return da.isel(time=~da.indexes["time"].duplicated(keep="first")).sortby("time")


def sync(products, start, end, workers=3):
    DATA.mkdir(parents=True, exist_ok=True)
    for p in products:
        old = load(p)
        have = set(pd.DatetimeIndex(old.time.values).date) if old is not None else set()
        days = [d.date() for d in pd.date_range(start, end) if d.date() not in have]
        if not days:
            print(f"[{p}] up to date ({len(have)} days)")
            continue
        print(f"[{p}] fetching {len(days)} day(s) {days[0]} .. {days[-1]}", flush=True)
        got, saved = {}, 0

        def save():
            """Merge fetched days into the product file (called every 10 days, so an interruption loses little)."""
            nonlocal old, saved
            t = pd.DatetimeIndex(sorted(got))
            new = xr.DataArray(np.stack([got[d.date()] for d in t]), dims=("time", "lat", "lon"),
                               coords={"time": t, "lat": LAT, "lon": LON}, name="precip")
            da = new if old is None else xr.concat([old, new], "time").sortby("time")
            tmp = path(p).with_suffix(".tmp.nc")
            da.to_dataset().assign_attrs(source=LABELS[p], grid="0.25 deg cell mean of native pixels").to_netcdf(tmp)
            os.replace(tmp, path(p))
            old, saved = da, saved + len(got)
            got.clear()
            return da

        da = old
        fails = 0
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(READERS[p], d): d for d in days}
            for k, fu in enumerate(cf.as_completed(futs), 1):
                d = futs[fu]
                try:
                    a = fu.result()
                    fails = 0
                except Exception as exc:
                    print(f"  [{p}] {d}: {exc}")
                    fails += 1
                    if fails >= 5:          # server down: stop, keep what was saved; the next run fills the gaps
                        print(f"  [{p}] 5 failures in a row; stopping this run")
                        for other in futs:
                            other.cancel()
                        break
                    continue
                if a is not None:
                    got[d] = a
                if len(got) >= 10:
                    da = save()
                if k % 25 == 0:
                    print(f"  [{p}] {k}/{len(days)}", flush=True)
        if got:
            da = save()
        if not saved:
            print(f"[{p}] nothing new")
            continue
        print(f"[{p}] +{saved} day(s); now {str(da.time.values[0])[:10]} .. {str(da.time.values[-1])[:10]}")


# ── verification ────────────────────────────────────────────────────────────
def ond_mask():
    global OND_MASK
    if OND_MASK is None:
        m = np.load(BASE_DIR / "backend" / "demo_data.npz")["mask_kenya_ond"].astype(bool)
        OND_MASK = m if m.shape == (len(LAT), len(LON)) else np.ones((len(LAT), len(LON)), bool)
    return OND_MASK


def scores(f, o):
    """f, o: matching (time, lat, lon) arrays; pixels inside the OND mask."""
    m = ond_mask()[None] & np.isfinite(f) & np.isfinite(o)
    fv, ov = f[m], o[m]
    out = {"n": int(m.sum()), "bias_pct": 100 * (fv.sum() / ov.sum() - 1) if ov.sum() > 0 else np.nan,
           "corr_daily": float(np.corrcoef(fv, ov)[0, 1]) if fv.size > 2 else np.nan,
           "mae_daily": float(np.mean(np.abs(fv - ov))), "rmse_daily": float(np.sqrt(np.mean((fv - ov) ** 2)))}
    for thr in (1.0, 10.0):
        fy, oy = fv >= thr, ov >= thr
        hit, miss, fa = np.sum(fy & oy), np.sum(~fy & oy), np.sum(fy & ~oy)
        out[f"pod_{thr:g}mm"] = hit / (hit + miss) if hit + miss else np.nan
        out[f"far_{thr:g}mm"] = fa / (hit + fa) if hit + fa else np.nan
        out[f"csi_{thr:g}mm"] = hit / (hit + miss + fa) if hit + miss + fa else np.nan
        out[f"freq_bias_{thr:g}mm"] = (hit + fa) / (hit + miss) if hit + miss else np.nan
    # pentad totals (5-day sums), the scale relevant for onset rules
    nt = (f.shape[0] // 5) * 5
    if nt >= 10:
        fp = f[:nt].reshape(-1, 5, *f.shape[1:]).sum(1)
        op = o[:nt].reshape(-1, 5, *o.shape[1:]).sum(1)
        mp = ond_mask()[None] & np.isfinite(fp) & np.isfinite(op)
        out["corr_pentad"] = float(np.corrcoef(fp[mp], op[mp])[0, 1])
    return out


def verify(ref, periods):
    import agro_onset as ao
    OUT.mkdir(parents=True, exist_ok=True)
    R = load(ref)
    rows = []
    for prod in ["arc2", "tamsat", "pdirnow", "imerg", "imerg_early", "imerg_gee", "gsmap_gee", "chirps"]:
        if prod == ref:
            continue
        F = load(prod)
        if F is None:
            continue
        for per in periods:
            a, b = per.split(":")
            t = pd.date_range(a, b)
            ff = F.reindex(time=t).values
            oo = R.reindex(time=t).values
            ok_t = np.isfinite(ff).any((1, 2)) & np.isfinite(oo).any((1, 2))
            if ok_t.sum() < 10:
                continue
            sc = scores(ff[ok_t], oo[ok_t])
            # planting-onset agreement (20 mm rule) when the period starts by 1 Oct and is long enough
            if ok_t.all() and len(t) >= 60 and t[0].month <= 10:
                s_idx = max(0, (pd.Timestamp(f"{t[0].year}-10-01") - t[0]).days)
                rule = {k: v for k, v in ao.RULE.items() if k != "search_start_doy"}
                fo, _ = ao.detect(np.moveaxis(ff, 0, -1), s_idx, **rule)
                oo_, _ = ao.detect(np.moveaxis(oo, 0, -1), s_idx, **rule)
                m = ond_mask() & np.isfinite(fo) & np.isfinite(oo_)
                sc["onset_mad_days"] = float(np.mean(np.abs(fo - oo_)[m])) if m.any() else np.nan
                sc["onset_both_detected_pct"] = float(100 * m.sum() / ond_mask().sum())
            rows.append({"product": prod, "reference": ref, "period": per, "days": int(ok_t.sum()), **sc})
            print(f"  {prod:8s} vs {ref} {per}: bias {sc['bias_pct']:+.0f}%  r(daily) {sc['corr_daily']:.2f}  "
                  f"r(pentad) {sc.get('corr_pentad', np.nan):.2f}  POD/FAR 1mm {sc['pod_1mm']:.2f}/{sc['far_1mm']:.2f}  "
                  f"10mm {sc['pod_10mm']:.2f}/{sc['far_10mm']:.2f}" +
                  (f"  onset MAD {sc['onset_mad_days']:.0f} d" if "onset_mad_days" in sc else ""))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"verification_{ref}.csv", index=False)
    return df


# ── monitoring ──────────────────────────────────────────────────────────────
def monitor(since, products):
    import agro_onset as ao
    OUT.mkdir(parents=True, exist_ok=True)
    since = pd.Timestamp(since)
    rec = load_chirps()
    rule = {k: v for k, v in ao.RULE.items() if k != "search_start_doy"}
    res, grids = {"since": str(since.date()), "products": {}}, {}
    for prod in ["chirps", "arc2", "tamsat", "pdirnow", "imerg", "imerg_early", "imerg_gee", "gsmap_gee"]:
        F = load(prod)
        if F is None:
            continue
        F = F.sel(time=slice(since - pd.Timedelta(days=30), None))
        tt = pd.DatetimeIndex(F.time.values)
        last = tt.max()
        sub = F.sel(time=slice(since, last))
        n = sub.sizes["time"]
        expected = (last - since).days + 1
        total = sub.sum("time", min_count=1).values
        # normal over exactly the calendar days this product has (CHIRPS 1993–2016)
        md = pd.DatetimeIndex(sub.time.values).strftime("%m-%d")
        rec_md = pd.DatetimeIndex(rec.time.values).strftime("%m-%d")
        norm = [rec.isel(time=np.where((rec.time.dt.year.values == y) & np.isin(rec_md, md))[0]).sum("time").values
                for y in range(1993, 2017)]
        normal = np.mean(norm, axis=0)
        # planting onset from `since` within the product's record (provisional when the 21-day check is incomplete)
        full = F.reindex(time=pd.date_range(tt.min(), last)).values
        s_idx = (since - tt.min()).days
        on, prov = ao.detect(np.moveaxis(full, 0, -1), s_idx, **rule)
        on_date = np.where(np.isfinite(on), on - s_idx, np.nan)          # days after `since`
        grids[prod] = dict(total=total, pct=100 * total / normal, onset_day=on_date, provisional=prov.astype(np.int8))
        m = ond_mask()
        res["products"][prod] = {
            "label": LABELS[prod], "last_day": str(last.date()), "days": n, "days_missing": int(expected - n),
            "ond_zone_mean_mm": round(float(np.nanmean(total[m])), 1), "ond_zone_normal_mm": round(float(np.nanmean(normal[m])), 1),
            "ond_zone_pct_normal": round(float(100 * np.nanmean(total[m]) / np.nanmean(normal[m])), 0),
            "ond_zone_pct_onset_detected": round(float(100 * np.mean(np.isfinite(on_date)[m])), 0),
        }
    ds = xr.Dataset({f"{p}_{k}": (("lat", "lon"), v.astype(np.float32)) for p, g in grids.items() for k, v in g.items()},
                    coords={"lat": LAT, "lon": LON}, attrs={"since": str(since.date())})
    stamp = dt.date.today().isoformat()
    ds.to_netcdf(OUT / f"monitor_{stamp}.nc")
    (OUT / f"monitor_{stamp}.json").write_text(json.dumps(res, indent=1))
    for p, r in res["products"].items():
        print(f"  {r['label']:24s} to {r['last_day']}: OND-zone {r['ond_zone_mean_mm']} mm vs normal {r['ond_zone_normal_mm']} "
              f"({r['ond_zone_pct_normal']:.0f}%), planting onset detected in {r['ond_zone_pct_onset_detected']:.0f}% of zone")
    return res


def site_series(lat, lon, start, products=("chirps", "arc2", "tamsat", "pdirnow", "imerg", "imerg_early", "imerg_gee", "gsmap_gee")):
    """Daily rain at the nearest cell for each available product (DataFrame, columns = products)."""
    cols = {}
    for p in products:
        F = load(p)
        if F is None:
            continue
        cols[p] = F.sel(lat=lat, lon=lon, method="nearest").sel(time=slice(start, None)).to_series()
    return pd.DataFrame(cols)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--start", default="2026-09-01")
    s.add_argument("--end", default=dt.date.today().isoformat())
    s.add_argument("--products", nargs="+", default=["arc2", "tamsat", "pdirnow"])
    v = sub.add_parser("verify")
    v.add_argument("--ref", default="chirps", choices=["chirps", "tamsat"])
    v.add_argument("--periods", nargs="+", default=["2025-10-01:2025-12-31", "2026-09-01:2026-09-30"])
    m = sub.add_parser("monitor")
    m.add_argument("--since", default="2026-10-01")
    a = ap.parse_args()
    if a.cmd == "sync":
        sync(a.products, a.start, a.end)
    elif a.cmd == "verify":
        verify(a.ref, a.periods)
    else:
        monitor(a.since, None)
