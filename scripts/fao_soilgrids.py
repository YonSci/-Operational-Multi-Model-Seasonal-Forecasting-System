#!/usr/bin/env python3
"""
fao_soilgrids.py
────────────────
Soil water-retention parameters for the FAO water-balance module on the platform's 0.25° Kenya grid.

SoilGrids 2.0 (ISRIC) publishes texture, organic carbon and coarse fragments but not water retention, so field
capacity (−33 kPa) and permanent wilting point (−1500 kPa) are estimated with the Saxton & Rawls (2006) pedotransfer
equations from each layer's sand, clay and organic matter, then reduced for coarse fragments:

  θWP  = θ1500t + (0.14 θ1500t − 0.02)
         θ1500t = −0.024S + 0.487C + 0.006OM + 0.005 S·OM − 0.013 C·OM + 0.068 S·C + 0.031
  θFC  = θ33t + (1.283 θ33t² − 0.374 θ33t − 0.015)
         θ33t   = −0.251S + 0.195C + 0.011OM + 0.006 S·OM − 0.027 C·OM + 0.452 S·C + 0.299
  S, C: sand and clay fractions (0–1); OM: organic matter, % by weight = 1.724 × SOC (capped at 8 %)
  bulk value = θ × (1 − coarse-fragment volume fraction)

Layers 0–5, 5–15, 15–30, 30–60, 60–100 and 100–200 cm are read from the SoilGrids WCS at about 1 km over Kenya
(mean prediction), converted, and averaged onto each 0.25° cell (land pixels only). The module averages θFC and θWP
over the crop's rooting depth Zr (depth-weighted) to get TAW = 1000 (θFC − θWP) Zr.

Output: data/soilgrids/soil_hydraulics_kenya_p25.nc
  theta_fc, theta_wp (depth, lat, lon) volumetric fractions; sand, clay, om_pct, cfvo; depth_top / depth_bottom (m)
Raw layers are cached in data/soilgrids/raw/ (re-runs skip them).

Usage:
  python scripts/fao_soilgrids.py
"""
import datetime as dt
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "soilgrids"
RAW = OUT / "raw"
LAT = np.arange(-4.875, 5.4, 0.25)
LON = np.arange(33.625, 41.9, 0.25)
W, S, E, N = 33.5, -5.0, 42.0, 5.5
NX, NY = 850, 1050                                  # 0.01° (about 1 km); 25 × 25 pixels per 0.25° cell
DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]
TOPS = np.array([0, 5, 15, 30, 60, 100]) / 100.0
BOTS = np.array([5, 15, 30, 60, 100, 200]) / 100.0
VARS = {"sand": 0.1, "clay": 0.1, "soc": 0.01, "cfvo": 0.1}   # mapped units → %: g/kg, g/kg, dg/kg (→ %), cm³/dm³
CRS = "http://www.opengis.net/def/crs/EPSG/0/4326"


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch(var, depth):
    dest = RAW / f"{var}_{depth}_mean.tif"
    if dest.exists():
        return dest
    url = (f"https://maps.isric.org/mapserv?map=/map/{var}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
           f"&COVERAGEID={var}_{depth}_mean&FORMAT=image/tiff&SUBSET=long({W},{E})&SUBSET=lat({S},{N})"
           f"&SUBSETTINGCRS={CRS}&OUTPUTCRS={CRS}&SCALESIZE=long({NX}),lat({NY})")
    for i in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "fao-wb"}), timeout=600).read()
            if b[:2] not in (b"II", b"MM"):
                raise RuntimeError(b[:200])
            tmp = dest.with_suffix(".part"); tmp.write_bytes(b); os.replace(tmp, dest)
            return dest
        except Exception as exc:
            log(f"  retry {i + 1} {dest.name}: {str(exc)[:120]}")
    raise RuntimeError(f"failed: {dest.name}")


def read(var, depth):
    with rasterio.open(RAW / f"{var}_{depth}_mean.tif") as src:
        a = src.read(1).astype(np.float32)
    a[a <= 0 if var in ("sand", "clay") else a < 0] = np.nan     # 0 sand and clay together = no data (water, outside)
    return a[::-1] * VARS[var]                                   # north-up → ascending latitude; percent


def saxton_rawls(sand_pct, clay_pct, om_pct):
    s, c, om = sand_pct / 100.0, clay_pct / 100.0, np.minimum(om_pct, 8.0)
    t1500 = -0.024 * s + 0.487 * c + 0.006 * om + 0.005 * s * om - 0.013 * c * om + 0.068 * s * c + 0.031
    wp = t1500 + (0.14 * t1500 - 0.02)
    t33 = -0.251 * s + 0.195 * c + 0.011 * om + 0.006 * s * om - 0.027 * c * om + 0.452 * s * c + 0.299
    fc = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)
    return np.clip(fc, 0.02, 0.6), np.clip(wp, 0.005, 0.5)


def to_cells(a):
    """1 km → 0.25° cell mean over valid pixels (25 × 25 blocks)."""
    b = a.reshape(len(LAT), NY // len(LAT), len(LON), NX // len(LON))
    with np.errstate(invalid="ignore"):
        return np.nanmean(b, axis=(1, 3))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    RAW.mkdir(parents=True, exist_ok=True)
    pairs = [(v, d) for v in VARS for d in DEPTHS]
    log(f"SoilGrids WCS: {len(pairs)} layers (≈1 km, Kenya)")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda p: fetch(*p), pairs))
    # 1050 × 850 does not split into 42 × 34 blocks of 25: crop to 1050 × 850 = 42·25 × 34·25 ✓
    assert NY == len(LAT) * 25 and NX == len(LON) * 25
    out = {k: [] for k in ("theta_fc", "theta_wp", "sand", "clay", "om_pct", "cfvo")}
    for d in DEPTHS:
        sand, clay, soc, cf = (read(v, d) for v in ("sand", "clay", "soc", "cfvo"))
        om = 1.724 * soc
        fc, wp = saxton_rawls(sand, clay, om)
        frac = 1.0 - np.nan_to_num(cf, nan=0.0) / 100.0
        fc, wp = fc * frac, wp * frac                    # coarse fragments hold no plant water
        for k, a in (("theta_fc", fc), ("theta_wp", wp), ("sand", sand), ("clay", clay), ("om_pct", om), ("cfvo", cf)):
            out[k].append(to_cells(a))
        log(f"  {d}: θFC {np.nanmean(out['theta_fc'][-1]):.3f}, θWP {np.nanmean(out['theta_wp'][-1]):.3f}, "
            f"AWC {np.nanmean(out['theta_fc'][-1] - out['theta_wp'][-1]) * 1000:.0f} mm/m")
    coords = {"depth": [d.replace("cm", " cm") for d in DEPTHS], "lat": LAT, "lon": LON}
    ds = xr.Dataset({k: (("depth", "lat", "lon"), np.stack(v).astype(np.float32)) for k, v in out.items()}, coords=coords)
    ds["depth_top"] = ("depth", TOPS); ds["depth_bottom"] = ("depth", BOTS)
    ds["theta_fc"].attrs.update(units="m3 m-3", long_name="field capacity (-33 kPa), Saxton & Rawls 2006, coarse-fragment corrected")
    ds["theta_wp"].attrs.update(units="m3 m-3", long_name="permanent wilting point (-1500 kPa), Saxton & Rawls 2006, coarse-fragment corrected")
    ds.attrs.update(source="SoilGrids 2.0 (ISRIC) sand, clay, soc, cfvo mean; WCS at 0.01°, averaged to 0.25°",
                    pedotransfer="Saxton & Rawls (2006) Soil Sci. Soc. Am. J. 70:1569-1578; OM = 1.724 SOC (≤ 8 %)")
    dest = OUT / "soil_hydraulics_kenya_p25.nc"
    ds.to_netcdf(dest)
    log(f"wrote {dest}")


if __name__ == "__main__":
    main()
