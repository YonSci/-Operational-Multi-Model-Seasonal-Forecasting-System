"""
regions.py
----------
The forecast regions the observation and forecast-input scripts can build: each region's 0.25 deg grid (cell
centres on the CHIRPS p25 lattice, x.125 / x.375 / ...), its edges, and where its files go.

  kenya          the platform's Kenya grid (42 x 34 cells); every path is the one the scripts always used
  ethiopia_deyr  southern Ethiopia's Deyr/Hagaya (OND) regime: the cells over
                 frontend/public/shapefiles/mask_deyr_autumn_rains.geojson (3.5-9.0 N, 35.25-47.75 E), 22 x 50 cells;
                 its outputs go under outputs/ethiopia_deyr/ and its data files carry the tag "ethiopia_deyr"

A script picks its region with --region, else the FORECAST_REGION environment variable, else kenya
(get(None) reads the variable when called, not when this module is imported).

CHIRPS record: v3 (default) or v2, from the CHIRPS_VERSION environment variable (read when called). CHC ends CHIRPS v2
production after December 2026.
  v3  CHIRPS v3.0 daily "sat" (each pentad split into days with IMERG timing; final from 1998, preliminary after it),
      with "rnl" (ERA5 timing) for 1981-1997, which "sat" does not cover; one full-year file per year on the region's
      grid (data/chirps_v3_daily, fao_download_chirps_v3.py) and the 1993-2025 history built from them
  v2  CHIRPS v2.0: the 1993-2025 history (data/chirps_pr_<cc>), the year's final p25 file and its preliminary days;
      the FAO water balance's own v3 "rnl" files (data/chirps_v3). Every path as before the switch, for comparison
      and rollback.
"""
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
ENV = "FORECAST_REGION"
DEFAULT = "kenya"
CHIRPS_ENV = "CHIRPS_VERSION"
CHIRPS_VERSIONS = ("v3", "v2")
HIST_YEARS = (1993, 2025)                        # the CHIRPS history file's years
V3_SAT_FROM = 1998                               # first year of CHIRPS v3 daily "sat" (IMERG); "rnl" before it


def chirps_version():
    """The CHIRPS record in use: CHIRPS_VERSION (v3 or v2), else v3."""
    v = (os.environ.get(CHIRPS_ENV) or CHIRPS_VERSIONS[0]).lower()
    if v not in CHIRPS_VERSIONS:
        raise ValueError(f"{CHIRPS_ENV}={v!r}; known: {', '.join(CHIRPS_VERSIONS)}")
    return v


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    lat_range: tuple            # first and last cell centre, deg N
    lon_range: tuple            # first and last cell centre, deg E
    outputs: Path               # this region's outputs root (Kenya: outputs/)
    border: str                 # admin-0 name (outlines, masks)
    cc: str                     # short country code of the download folders (seasonal_pr_downloads_<cc>)
    mask: Path = None           # polygon(s) a cell must overlap to be in the forecast (None: Kenya's border mask)

    @property
    def tag(self):
        """File-name tag: chirps_v3_p25_<tag>_<year>.nc, soil_hydraulics_<tag>_p25.nc, ..."""
        return self.key

    @property
    def lat(self):
        return np.arange(self.lat_range[0], self.lat_range[1] + 0.125, 0.25)

    @property
    def lon(self):
        return np.arange(self.lon_range[0], self.lon_range[1] + 0.125, 0.25)

    @property
    def bounds(self):
        """W, S, E, N cell edges."""
        return (self.lon_range[0] - 0.125, self.lat_range[0] - 0.125, self.lon_range[1] + 0.125, self.lat_range[1] + 0.125)

    @property
    def obs_run(self):
        """The SEAS5 1 Oct + latest observations run (chirps_Q_bar.nc, the bias-corrected daily forecast, ...)."""
        return self.outputs / "ecmwf_oct_obs_latest"

    @property
    def fao_wb(self):
        return self.outputs / "fao_wb"

    def chirps_v3(self, year):
        """The FAO water balance's CHIRPS v3 days of a year: with v3, the platform's record (chirps_daily); with v2, its
        own "rnl" files (Jan-Mar, Aug-Dec)."""
        if chirps_version() == "v3":
            return self.chirps_daily(year)
        return BASE_DIR / "data" / "chirps_v3" / f"chirps_v3_p25_{self.tag}_{year}.nc"

    def chirps_daily(self, year):
        """CHIRPS v3 daily, every day of a year on the region's grid (final, then preliminary; variable "source")."""
        return BASE_DIR / "data" / "chirps_v3_daily" / f"chirps_v3_p25_{self.tag}_{year}.nc"

    def chirps_obs(self, year):
        """The files holding a year's observed days after the history (later files fill days the earlier lack):
        v3, the year's file; v2, the final p25 file and the preliminary days."""
        if chirps_version() == "v3":
            return [self.chirps_daily(year)]
        return [self.chirps_final(year), self.chirps_prelim(year)]

    @property
    def soil(self):
        return BASE_DIR / "data" / "soilgrids" / f"soil_hydraulics_{self.tag}_p25.nc"

    @property
    def soil_raw(self):
        """SoilGrids layers as downloaded (each region's own window)."""
        return BASE_DIR / "data" / "soilgrids" / ("raw" if self.key == DEFAULT else f"raw_{self.tag}")

    @property
    def chirps_hist(self):
        """CHIRPS daily on the region's 0.25° grid, 1993-2025 (v3: built from chirps_daily; v2: CHIRPS v2.0)."""
        y0, y1 = HIST_YEARS
        if chirps_version() == "v3":
            return BASE_DIR / "data" / "chirps_v3_daily" / f"chirps_v3_p25_{self.tag}_{y0}_{y1}.nc"
        return BASE_DIR / "data" / f"chirps_pr_{self.cc}" / f"{self.cc}_chirps_pr_r25_{y0}_{y1}.nc"

    @property
    def chirps_label(self):
        return "CHIRPS v3" if chirps_version() == "v3" else "CHIRPS v2"

    @staticmethod
    def chirps_final(year):
        """CHIRPS v2.0 final days of a year (the global p25 file: every region)."""
        return BASE_DIR / "data" / f"chirps_{year}" / f"chirps-v2.0.{year}.days_p25.nc"

    def chirps_prelim(self, year):
        """CHIRPS v2.0 preliminary days after the final ones, on the region's grid (chirps_prelim_to_p25.py)."""
        return BASE_DIR / "data" / f"chirps_prelim_{year}" / f"chirps_prelim_{year}_p25_{self.tag}.nc"

    @property
    def pet_clim(self):
        """Modified-Hargreaves PET climatology (pet_hargreaves.py)."""
        return BASE_DIR / "data" / "worldclim" / f"pet_mhargreaves_clim_{self.tag}.nc"

    @property
    def janfeb_cache(self):
        """Bias-corrected 1 Jan - 28 Feb of the 1 Oct members (onset_rules.jan_feb)."""
        return self.outputs / "ecmwf_oct" / "ECMWF_bc_daily_janfeb.nc"

    @property
    def seas5_rain(self):
        """SEAS5 1 Oct total precipitation, 215 lead days (download_seasonal_forecasts_daily_c3s.py)."""
        return BASE_DIR / "data" / f"seasonal_pr_downloads_{self.cc}" / "ecmwf_oct"

    @property
    def era5land(self):
        """ERA5-Land files of the CDS route (fao_download_era5land.py)."""
        return BASE_DIR / "data" / ("era5land" if self.key == DEFAULT else f"era5land_{self.tag}")


REGIONS = {
    "kenya": Region("kenya", "Kenya", (-4.875, 5.375), (33.625, 41.875), BASE_DIR / "outputs", "Kenya", "ke"),
    "ethiopia_deyr": Region("ethiopia_deyr", "southern Ethiopia, Deyr/Hagaya regime", (3.625, 8.875), (35.375, 47.625),
                            BASE_DIR / "outputs" / "ethiopia_deyr", "Ethiopia", "et",
                            BASE_DIR / "frontend" / "public" / "shapefiles" / "mask_deyr_autumn_rains.geojson"),
}


def get(key=None):
    """The region named key, else FORECAST_REGION, else kenya."""
    key = key or os.environ.get(ENV) or DEFAULT
    if key not in REGIONS:
        raise ValueError(f"unknown region {key!r}; known: {', '.join(REGIONS)}")
    return REGIONS[key]


def cell_mask(region):
    """(lat, lon) bool: the cells of a region with a mask polygon that overlap it (a cell is in when any part of it
    is: the crop map keeps a cell when any of its MapSPAM pixels is inside). None for a region without one."""
    if region.mask is None:
        return None
    import geopandas as gpd
    from shapely.geometry import box
    g = gpd.read_file(region.mask).to_crs(4326).geometry
    poly = g.union_all() if hasattr(g, "union_all") else g.unary_union
    return np.array([[poly.intersects(box(x - 0.125, y - 0.125, x + 0.125, y + 0.125)) for x in region.lon]
                     for y in region.lat])


def add_argument(parser):
    """--region on a script's argument parser (default: FORECAST_REGION, else kenya)."""
    parser.add_argument("--region", choices=list(REGIONS), default=None,
                        help=f"forecast region (default: ${ENV}, else {DEFAULT})")


def activate(key):
    """Make key the region for this process and the processes it starts; returns the Region."""
    r = get(key)
    os.environ[ENV] = r.key
    return r
