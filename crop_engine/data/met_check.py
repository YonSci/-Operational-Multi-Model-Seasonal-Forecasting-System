#!/usr/bin/env python3
"""
Check of the site radiation, humidity and wind (crop_engine.data.era5land.site_met): FAO-56 Penman-Monteith ET0
computed from them (with the site's ERA5-Land temperature) against the platform's ERA5-Land ET0 at the site's 0.25°
cell (outputs/fao_wb/et0, the ET0 the crop outlook uses). Close agreement (correlation near 1, a small bias from
the point vs the cell mean) shows the units, the dates and the sampling are right; a large bias would show an error.

Usage: python -m crop_engine.data.met_check [--years 1993 2025]
"""
import argparse
import sys

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C
from crop_engine.data import era5land
from crop_engine.data.sites import registered_sites

import fao_water_balance as fw  # noqa: E402


def dewpoint(vap_hpa):
    """Inverse of FAO-56 Eq. 14 (°C)."""
    x = np.log(vap_hpa / 6.108)
    return 237.3 * x / (17.27 - x)


def site_et0(t, m, lat):
    """FAO-56 ET0 (mm/day) from the site temperature t (tmax, tmin) and site_met m, on their common days."""
    d = t.join(m, how="inner").dropna()
    p = float(d.sp_kpa.mean())
    et0 = fw.et0_fao56(d.tmax.values, d.tmin.values, dewpoint(d.vap_hpa.values), d.wind2_ms.values, d.rad_mj_m2.values,
                       p, lat, d.index.dayofyear.values, fw.elevation_from_pressure(p))
    return pd.Series(et0, index=d.index)


def platform_et0(site, years):
    out = []
    for y in range(years[0], years[1] + 1):
        f = fw.ET0_DIR / f"et0_{y}.nc"
        if f.exists():
            with xr.open_dataset(f) as ds:
                a = ds["ET0"].sel(lat=site.lat, lon=site.lon, method="nearest")
                out.append(pd.Series(a.values, index=pd.DatetimeIndex(a.time.values)))
    return pd.concat(out).dropna() if out else pd.Series(dtype=float)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs=2, type=int, default=[C.CAL_YEARS[0], 2025])
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sites = registered_sites()
    met = era5land.site_met(sites, refresh=False)
    print(f"{'site':36s} {'days':>5s} {'r':>5s} {'site ET0':>8s} {'platform':>8s} {'bias':>6s}  rad  vap wind2 elev")
    worst = 0.0
    for s in sites:
        m = met[s.id]
        m = m[(m.index.year >= a.years[0]) & (m.index.year <= a.years[1])]
        mine = site_et0(era5land.site_temperature(s, refresh=False), m, s.lat)
        ref = platform_et0(s, a.years)
        both = pd.concat([mine.rename("site"), ref.rename("platform")], axis=1).dropna()
        r = np.corrcoef(both.site, both.platform)[0, 1]
        bias = float((both.site - both.platform).mean())
        worst = max(worst, abs(bias))
        print(f"{s.id[:36]:36s} {len(both):5d} {r:5.2f} {both.site.mean():8.2f} {both.platform.mean():8.2f} {bias:+6.2f}  "
              f"{m.rad_mj_m2.mean():4.1f} {m.vap_hpa.mean():4.1f} {m.wind2_ms.mean():5.2f} "
              f"{fw.elevation_from_pressure(float(m.sp_kpa.mean())):4.0f}")
    print(f"largest mean difference {worst:.2f} mm/day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
