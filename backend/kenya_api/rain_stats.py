"""GET /rain_stats -- seasonal rainfall statistics for one location (scripts/rainfall_stats.py)"""
import json
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Query

from kenya_api.pixel import _json

router = APIRouter()

_NPZ = Path(__file__).resolve().parent.parent / "rain_stats.npz"
STATS = ["total", "wet_days", "dry_days", "intensity", "wet_spells", "dry_spells"]
FIELDS = ["fc_med", "fc_p10", "fc_p90", "clim_med", "clim_t33", "clim_t67", "p_bn", "p_nn", "p_an"]
_cache = {}


def _runs():
    """{model: {"lat", "lon", "meta", stat: (9, lat, lon)}}, loaded once (about 3 MB in memory)."""
    if "runs" not in _cache:
        runs = {}
        if _NPZ.is_file():
            z = np.load(_NPZ)
            for key in z.files:
                model, part = key.split("|", 1)
                runs.setdefault(model, {})[part] = json.loads(str(z[key])) if part == "meta" else z[key]
        _cache["runs"] = runs
    return _cache["runs"]


@router.get("/rain_stats")
def get_rain_stats(
    lat: float = Query(..., description="Latitude (decimal degrees N)"),
    lon: float = Query(..., description="Longitude (decimal degrees E)"),
    model: str = Query(..., description="Model name as served by /models; a ' - <method>' suffix is ignored"),
):
    """Total rainfall, wet and dry days, rainfall intensity and wet / dry spells at the nearest grid cell:
    forecast median and 10-90% range, CHIRPS 1993-2016 normal and terciles, and the share of members below,
    near and above normal. Statistics a run cannot support are null (see meta.available)."""
    base = model.split(" - ")[0]
    run = _runs().get(base)
    if run is None:
        return _json({"model": base, "available": False})
    i = int(np.abs(run["lat"] - lat).argmin())
    j = int(np.abs(run["lon"] - lon).argmin())
    stats = {st: dict(zip(FIELDS, run[st][:, i, j])) for st in STATS}
    in_grid = abs(run["lat"][i] - lat) <= 0.13 and abs(run["lon"][j] - lon) <= 0.13
    return _json({
        "model": base, "available": in_grid and not np.isnan(run["total"][3, i, j]),
        "lat": run["lat"][i], "lon": run["lon"][j], "meta": run["meta"], "stats": stats,
    })
