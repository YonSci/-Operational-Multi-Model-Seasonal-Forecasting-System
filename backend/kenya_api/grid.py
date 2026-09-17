"""GET /grid  —  GeoJSON map layer."""
import math, json
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from functools import lru_cache
import mam_loader as dl

router = APIRouter()


# ── Numpy-safe serialiser (same as pixel.py) ──────────────────────────────
def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


@lru_cache(maxsize=64)
def _build_geojson(variable: str, layer: str, model: str = "", season: str = "long_rains"):
    """Build and cache GeoJSON FeatureCollection for a variable+layer combo."""
    try:
        grid = dl.get_grid_stats(variable=variable, layer=layer, model=model if model else None, season=season)
    except Exception as e:
        raise ValueError(f"get_grid_stats failed for {variable}/{layer}: {e}")

    lats   = grid["lats"]
    lons   = grid["lons"]
    values = grid["values"]
    half   = 0.125
    features = []

    for ii, lat in enumerate(lats):
        for jj, lon in enumerate(lons):
            try:
                val = values[ii][jj]
            except (IndexError, TypeError):
                continue
            if val is None:
                continue
            # Clean val
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                continue

            coords = [[[lon-half, lat-half], [lon+half, lat-half],
                        [lon+half, lat+half], [lon-half, lat+half],
                        [lon-half, lat-half]]]
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": coords},
                "properties": {
                    "lat"    : round(float(lat), 3),
                    "lon"    : round(float(lon), 3),
                    "pi"     : ii,
                    "pj"     : jj,
                    "map_val": round(float(val), 3),
                    # Tooltip fields - derived fresh per-pixel
                    "label"  : grid.get("variable", ""),
                    "layer"  : grid.get("layer", ""),
                    "units"  : grid.get("units", ""),
                },
            })

    # Enrich features with tooltip data using appropriate season CHIRPS clim
    try:
        import numpy as np
        is_fmam = (season in ["fmam", "belg"]) or (model in ["ECMWF SEAS5 (FMAM)", "ecmwf_fmam"])
        is_kiremt = not is_fmam and ((season == "kiremt") or (model in ["ECMWF SEAS5 (Kiremt)", "ecmwf_kiremt"]))
        is_short = not is_fmam and not is_kiremt and ((season == "short_rains") or (model in ["ECMWF SEAS5 (Sep)", "ecmwf_sep"]))
        fmam_md = dl.get_state().get("MODELS", {}).get("ECMWF SEAS5 (FMAM)")
        kiremt_md = dl.get_state().get("MODELS", {}).get("ECMWF SEAS5 (Kiremt)")
        sep_md = dl.get_state().get("MODELS", {}).get("ECMWF SEAS5 (Sep)")
        if is_fmam and fmam_md and "chirps_clim" in fmam_md:
            c_clim = fmam_md["chirps_clim"]
        elif is_fmam and dl.get_state().get("chirps_fmam"):
            c_clim = dl.get_state()["chirps_fmam"]["chirps_clim"]
        elif is_kiremt and kiremt_md and "chirps_clim" in kiremt_md:
            c_clim = kiremt_md["chirps_clim"]
        elif is_kiremt and dl.get_state().get("chirps_kiremt"):
            c_clim = dl.get_state()["chirps_kiremt"]["chirps_clim"]
        elif is_short and sep_md and "chirps_clim" in sep_md:
            c_clim = sep_md["chirps_clim"]
        else:
            c_clim = dl.get_state().get("chirps_clim", {})

        chirps_on  = c_clim.get("onset")
        chirps_cs  = c_clim.get("cessation")
        chirps_lgp = c_clim.get("lgp")
        for feat in features:
            p = feat["properties"]
            ii, jj = p["pi"], p["pj"]
            mv = p["map_val"]
            if chirps_on is not None:
                c_on = float(chirps_on[ii, jj]) if not np.isnan(chirps_on[ii, jj]) else None
                p["chirps_on"]  = round(c_on, 1) if c_on else None
                if variable == "onset":
                    p["on_anom"] = round(mv, 1) if layer == "anomaly" else (round(mv - c_on, 1) if (layer == "median" and c_on) else None)
            if chirps_cs is not None:
                c_cs = float(chirps_cs[ii, jj]) if not np.isnan(chirps_cs[ii, jj]) else None
                p["chirps_cs"]  = round(c_cs, 1) if c_cs else None
                if variable == "cessation":
                    p["cs_anom"] = round(mv, 1) if layer == "anomaly" else (round(mv - c_cs, 1) if (layer == "median" and c_cs) else None)
            if chirps_lgp is not None:
                c_lgp = float(chirps_lgp[ii, jj]) if not np.isnan(chirps_lgp[ii, jj]) else None
                p["chirps_lgp"] = round(c_lgp, 1) if c_lgp else None
                if variable == "lgp":
                    p["lg_anom"] = round(mv, 1) if layer == "anomaly" else (round(mv - c_lgp, 1) if (layer == "median" and c_lgp) else None)
    except Exception:
        pass  # tooltip enrichment is best-effort

    return {
        "type"    : "FeatureCollection",
        "features": features,
        "meta"    : {
            "variable": variable,
            "layer"   : layer,
            "n_pixels": len(features),
            "vmin"    : round(float(grid["vmin"]), 3) if grid["vmin"] is not None else None,
            "vmax"    : round(float(grid["vmax"]), 3) if grid["vmax"] is not None else None,
            "units"   : grid["units"],
        },
    }


@router.get("")
def get_grid(
    variable: str  = Query("onset",        description="onset | cessation | lgp"),
    layer   : str  = Query("anomaly",      description="anomaly | spread | prob_bn | prob_an | failure"),
    bust    : bool = Query(False,          description="Clear cache and rebuild"),
    model   : str  = Query("",            description="Optional: single model name for per-model grid"),
    season  : str  = Query("long_rains",  description="long_rains | short_rains"),
):
    """
    Return a GeoJSON FeatureCollection for the requested map layer.
    Cached in memory — first call takes a few seconds.
    """
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")

    valid_vars   = {"onset", "cessation", "lgp"}
    valid_layers = {"anomaly", "spread", "median", "prob_bn", "prob_nn", "prob_an", "failure", "chirps_p50", "chirps_spread", "bias", "detection_rate", "rpss_val", "hitrate_val", "alpha", "hr_weighted", "rpss_weighted"}

    if variable not in valid_vars:
        raise HTTPException(400, f"variable must be one of {sorted(valid_vars)}")
    if layer not in valid_layers:
        raise HTTPException(400, f"layer must be one of {sorted(valid_layers)}")

    if bust:
        _build_geojson.cache_clear()

    try:
        data = _build_geojson(variable, layer, model or "", season or "long_rains")
    except ValueError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        raise HTTPException(500, f"Unexpected error building grid: {e}")

    # Serialise via _clean to strip any residual numpy types
    return Response(
        content=json.dumps(_clean(data)),
        media_type="application/json",
    )


@router.get("/cache-info")
def cache_info():
    i = _build_geojson.cache_info()
    return {"hits": i.hits, "misses": i.misses, "currsize": i.currsize}
