#!/usr/bin/env python3
"""
pet_hargreaves.py
─────────────────
Daily potential evapotranspiration climatology on the Kenya 0.25° forecast grid with the modified Hargreaves
method (Droogers & Allen 2002), for the ICPAC cessation rule (10-day rain < 0.5 × PET; onset_rules.py):

  PET = 0.0013 × 0.408 Ra × (Tmean + 17.0) × (Tmax − Tmin − 0.0123 P)^0.76      [mm/day]

  Ra          extraterrestrial radiation (FAO-56 eq. 21) from latitude and day of year, MJ m-2 day-1
  Tmax, Tmin  WorldClim 2.1 monthly climatology (1970–2000, station-based, 10 arc-min; downloaded on first
              run to data/worldclim/), interpolated to the grid and from mid-month to daily
  P           CHIRPS 1993–2022 mean monthly rainfall, mm/month (same mid-month interpolation)

The same climatology is used for every year, for CHIRPS and for the forecast members (PET varies far less
from year to year than rainfall, and SEAS5 temperature is not downloaded).
(ERA5's monthly-mean diurnal cycle was tried first: its day–night range is about half the observed one,
which halves PET.)

Usage: python scripts/pet_hargreaves.py → data/worldclim/pet_mhargreaves_clim_kenya.nc (pet, tmax, tmin by doy)
"""
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
import xarray as xr
from rasterio.windows import from_bounds

BASE_DIR = Path(__file__).resolve().parent.parent
WC_DIR = BASE_DIR / "data" / "worldclim"
WC_URL = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_{v}.zip"
GRID = BASE_DIR / "outputs" / "ecmwf_oct_obs_latest" / "chirps_Q_bar.nc"
CHIRPS = BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
OUT = WC_DIR / "pet_mhargreaves_clim_kenya.nc"
YEARS = (1993, 2022)


def extraterrestrial_radiation(lat_deg, doy):
    """FAO-56 eq. 21, MJ m-2 day-1; lat_deg (n_lat,), doy (n_day,) → (n_day, n_lat)."""
    phi = np.deg2rad(lat_deg)[None, :]
    j = np.asarray(doy, float)[:, None]
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    delta = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    return 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def monthly_to_daily(m12):
    """(12, ...) mid-month values → (366, ...) daily by cyclic linear interpolation."""
    mid = np.array([pd.Timestamp(2001, m, 15).dayofyear for m in range(1, 13)], float)
    x = np.concatenate([mid - 365, mid, mid + 365])
    y = np.concatenate([m12, m12, m12], axis=0)
    doy = np.arange(1, 367)
    flat = y.reshape(36, -1)
    out = np.stack([np.interp(doy, x, flat[:, k]) for k in range(flat.shape[1])], axis=1)
    return out.reshape((366,) + m12.shape[1:]).astype(np.float32)


def worldclim(var, lat, lon):
    """WorldClim 2.1 monthly mean (°C) of var (tmax / tmin) interpolated to lat / lon → (12, lat, lon)."""
    z = WC_DIR / f"wc2.1_10m_{var}.zip"
    if not z.exists():
        WC_DIR.mkdir(parents=True, exist_ok=True)
        r = requests.get(WC_URL.format(v=var), timeout=600)
        r.raise_for_status()
        z.write_bytes(r.content)
    out = []
    for m in range(1, 13):
        with rasterio.open(f"zip://{z.as_posix()}!wc2.1_10m_{var}_{m:02d}.tif") as src:
            w = from_bounds(lon.min() - 0.5, lat.min() - 0.5, lon.max() + 0.5, lat.max() + 0.5, src.transform)
            a = src.read(1, window=w).astype(np.float32)
            a[a == src.nodata] = np.nan
            tr = src.window_transform(w)
        ys = tr.f + tr.e * (np.arange(a.shape[0]) + 0.5)
        xs = tr.c + tr.a * (np.arange(a.shape[1]) + 0.5)
        da = xr.DataArray(a, dims=("lat", "lon"), coords={"lat": ys, "lon": xs}).sortby("lat")
        da = da.ffill("lon").bfill("lon").ffill("lat").bfill("lat")      # sea cells from the nearest land (coast)
        out.append(da.interp(lat=lat, lon=lon).values)
    return np.stack(out)


def main():
    grid = xr.open_dataarray(GRID)
    lat, lon = grid.lat.values, grid.lon.values

    tmax_m, tmin_m = worldclim("tmax", lat, lon), worldclim("tmin", lat, lon)                    # (12, lat, lon)

    # CHIRPS mean monthly rainfall
    with xr.open_dataset(CHIRPS) as ds:
        pr = ds["precip"].sel(time=slice(f"{YEARS[0]}", f"{YEARS[1]}")).reindex(lat=lat, lon=lon, method="nearest")
        p_m = (pr.resample(time="MS").sum().groupby("time.month").mean()).values                  # (12, lat, lon)

    tmax, tmin, p = monthly_to_daily(tmax_m), monthly_to_daily(tmin_m), monthly_to_daily(p_m)
    ra = extraterrestrial_radiation(lat, np.arange(1, 367))[:, :, None]                         # (366, lat, 1)
    td = np.clip(tmax - tmin - 0.0123 * p, 0, None)
    pet = (0.0013 * 0.408 * ra * ((tmax + tmin) / 2 + 17.0) * td ** 0.76).astype(np.float32)
    pet[:, ~np.isfinite(grid.values)] = np.nan

    coords = {"doy": np.arange(1, 367), "lat": lat, "lon": lon}
    xr.Dataset({"pet": (("doy", "lat", "lon"), pet, {"units": "mm/day"}),
                "tmax": (("doy", "lat", "lon"), tmax, {"units": "degC"}),
                "tmin": (("doy", "lat", "lon"), tmin, {"units": "degC"})}, coords=coords,
               attrs={"method": "modified Hargreaves (Droogers & Allen 2002)",
                      "sources": f"WorldClim 2.1 Tmax/Tmin (1970-2000) and CHIRPS monthly rainfall {YEARS[0]}-{YEARS[1]}"}
               ).to_netcdf(OUT)
    lm = np.isfinite(grid.values)
    oct_nov = pet[273:334][:, lm]
    print(f"wrote {OUT}: Oct–Nov PET over land {np.nanmin(oct_nov):.1f}–{np.nanmax(oct_nov):.1f} "
          f"mm/day (mean {np.nanmean(oct_nov):.1f})")


if __name__ == "__main__":
    main()
