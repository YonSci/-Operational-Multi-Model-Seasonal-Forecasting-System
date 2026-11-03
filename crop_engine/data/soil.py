"""
Soil profile at a site's grid cell from the platform's SoilGrids 2.0 file (data/soilgrids/soil_hydraulics_kenya_p25.nc:
six layers to 200 cm, sand, clay, organic matter, coarse fragments, and field capacity / wilting point from the
Saxton & Rawls (2006) pedotransfer functions, as used by the FAO water balance).

These are 0.25° (≈ 28 km) averages of 250 m SoilGrids estimates, not field measurements: the crop results carry
that uncertainty. Coarse fragments are reported but not yet used to reduce water-holding capacity.
"""
from dataclasses import dataclass

import numpy as np
import xarray as xr

from crop_engine.config import BASE

SOIL_FILE = BASE / "data" / "soilgrids" / "soil_hydraulics_kenya_p25.nc"


@dataclass
class Layer:
    top_cm: float
    bottom_cm: float
    sand: float           # %
    clay: float           # %
    om: float             # organic matter, %
    cfvo: float           # coarse fragments, % volume
    theta_fc: float       # m3 m-3
    theta_wp: float

    @property
    def thickness_m(self):
        return (self.bottom_cm - self.top_cm) / 100.0


def profile(site, path=SOIL_FILE):
    """The site's layers (top to bottom); raises if the cell has no soil data."""
    with xr.open_dataset(path) as ds:
        c = ds.sel(lat=site.cell_lat, lon=site.cell_lon, method="nearest")
        layers = [Layer(float(c.depth_top[k]), float(c.depth_bottom[k]), float(c.sand[k]), float(c.clay[k]),
                        float(c.om_pct[k]), float(c.cfvo[k]), float(c.theta_fc[k]), float(c.theta_wp[k]))
                  for k in range(ds.sizes["depth"])]
    check(layers, site.name)
    return layers


def check(layers, where=""):
    problems = []
    for L in layers:
        vals = (L.sand, L.clay, L.om, L.theta_fc, L.theta_wp)
        if not all(np.isfinite(v) for v in vals):
            problems.append(f"{L.top_cm:.0f}-{L.bottom_cm:.0f} cm: missing values")
        elif not (0 <= L.sand <= 100 and 0 <= L.clay <= 100 and L.sand + L.clay <= 100.5 and 0 <= L.om <= 30):
            problems.append(f"{L.top_cm:.0f}-{L.bottom_cm:.0f} cm: texture out of range")
        elif not (0 < L.theta_wp < L.theta_fc < 0.7):
            problems.append(f"{L.top_cm:.0f}-{L.bottom_cm:.0f} cm: wilting point / field capacity out of order")
    if layers and abs(layers[-1].bottom_cm - 200) > 1:
        problems.append("profile does not reach 200 cm")
    if problems:
        raise ValueError(f"soil profile {where}: " + "; ".join(problems))


def taw_mm(layers, depth_m=1.0):
    """Total available water (FC − WP) in the top depth_m (mm), for reporting."""
    out, top = 0.0, 0.0
    for L in layers:
        lo, hi = max(top, L.top_cm / 100), min(depth_m, L.bottom_cm / 100)
        if hi > lo:
            out += (L.theta_fc - L.theta_wp) * (hi - lo) * 1000
    return out
