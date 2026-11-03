"""The platform's monitored sites (backend/mam_loader.py SITES) and the 0.25° analysis-grid cell of each."""
import ast
import re
from dataclasses import dataclass

from crop_engine.config import BASE


@dataclass(frozen=True)
class Site:
    id: str            # slug of the name
    name: str
    lat: float
    lon: float
    country: str
    i: int = -1        # grid cell (row, column) on the analysis grid
    j: int = -1
    cell_lat: float = float("nan")
    cell_lon: float = float("nan")

    @property
    def cell(self):
        return self.i, self.j


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def registered_sites(country="kenya"):
    """SITES from backend/mam_loader.py, read without importing the backend (a literal list)."""
    tree = ast.parse((BASE / "backend" / "mam_loader.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "SITES":
            rows = ast.literal_eval(node.value)
            break
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SITES" for t in node.targets):
            rows = ast.literal_eval(node.value)
            break
    else:
        raise RuntimeError("SITES not found in backend/mam_loader.py")
    return [Site(slug(r["site_name"]), r["site_name"], float(r["lat"]), float(r["lon"]), r["country"])
            for r in rows if country is None or r["country"] == country]


def on_grid(sites, lat, lon, land=None):
    """Each site with its nearest grid cell (a land cell when `land` (lat, lon) bool is given)."""
    import numpy as np                    # here, so listing the sites stays light (crop_engine.run_all)
    out = []
    for s in sites:
        d = (lat[:, None] - s.lat) ** 2 + (lon[None, :] - s.lon) ** 2
        if land is not None:
            d = np.where(land, d, np.inf)
        i, j = np.unravel_index(int(np.argmin(d)), d.shape)
        out.append(Site(s.id, s.name, s.lat, s.lon, s.country, int(i), int(j), float(lat[i]), float(lon[j])))
    return out
