"""GET /pixel, /chirps, /taylor"""
import warnings, math, json
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
import mam_loader as dl

router = APIRouter()


# ── JSON serializer: handles numpy types + NaN/Inf ────────────────────────
def _clean(obj):
    """Recursively convert numpy types and NaN/Inf to JSON-safe values."""
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
    return obj

def _json(data):
    return Response(content=json.dumps(_clean(data)), media_type="application/json")


@router.get("/pixel")
def get_pixel(
    lat: float = Query(..., description="Latitude (decimal degrees N)"),
    lon: float = Query(..., description="Longitude (decimal degrees E)"),
    season: str = Query("long_rains", description="Season: 'long_rains' or 'short_rains'"),
    model: str = Query("", description="Optional active model name"),
    year: int = Query(None, description="Optional forecast year"),
):
    """All model stats for the nearest land pixel to (lat, lon)."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    is_kiremt = (season == "kiremt" or "kiremt" in str(season).lower() or lat > 5.0 or lon > 42.5)
    if is_kiremt:
        if not (3.0 <= lat <= 15.0 and 33.0 <= lon <= 48.0):
            raise HTTPException(400, f"({lat},{lon}) is outside the Ethiopia domain.")
    else:
        if not (-5.0 <= lat <= 5.0 and 33.0 <= lon <= 42.5):
            raise HTTPException(400, f"({lat},{lon}) is outside the Kenya domain.")
    return _json(dl.get_pixel_stats(lat, lon, season=season, model=model, year=year))


@router.get("/chirps")
def get_chirps(
    season: str = Query("long_rains", description="Season: 'long_rains', 'short_rains', or 'kiremt'"),
):
    """CHIRPS CAL domain-mean climatology and grid metadata."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    s  = dl.get_state()
    is_kiremt = (season == "kiremt" or "kiremt" in str(season).lower())
    is_short = (season == "short_rains" or "short" in str(season).lower() or "sep" in str(season).lower() or "ond" in str(season).lower())
    if is_kiremt and s.get("chirps_kiremt"):
        c_source = s["chirps_kiremt"]
    elif is_short and s.get("chirps_sep"):
        c_source = s["chirps_sep"]
    else:
        c_source = s
    lm = c_source.get("lm", s["lm"])
    clim = c_source.get("chirps_clim", s["chirps_clim"])
    target_lat = c_source.get("target_lat", s["target_lat"])
    target_lon = c_source.get("target_lon", s["target_lon"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {
            "on_clim" : round(float(np.nanmean(clim["onset"][lm])),    1),
            "cs_clim" : round(float(np.nanmean(clim["cessation"][lm])),1),
            "lgp_clim": round(float(np.nanmean(clim["lgp"][lm])),      1),
            "n_land"  : int(lm.sum()),
            "n_lat"   : int(c_source.get("n_lat", s["n_lat"])),
            "n_lon"   : int(c_source.get("n_lon", s["n_lon"])),
            "lat_range": [round(float(target_lat.min()), 3),
                          round(float(target_lat.max()), 3)],
            "lon_range": [round(float(target_lon.min()), 3),
                          round(float(target_lon.max()), 3)],
        }


@router.get("/taylor")
def get_taylor():
    """Taylor diagram data per model vs CHIRPS CAL onset."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    return _json(dl.get_taylor_stats())

@router.get("/chirps_historical")
def get_chirps_historical(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    season: str = Query("long_rains", description="Season: 'long_rains', 'short_rains', or 'kiremt'"),
):
    """Full CHIRPS time series (onset, cessation, LGP) for the nearest pixel."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    is_kiremt = (season == "kiremt" or "kiremt" in str(season).lower() or lat > 5.0 or lon > 42.5)
    if is_kiremt:
        if not (3.0 <= lat <= 15.0 and 33.0 <= lon <= 48.0):
            raise HTTPException(400, f"({lat},{lon}) is outside the Ethiopia domain.")
    else:
        if not (-5.0 <= lat <= 5.0 and 33.0 <= lon <= 42.5):
            raise HTTPException(400, f"({lat},{lon}) is outside the Kenya domain.")

    import numpy as np
    import warnings

    s = dl.get_state()
    is_short = (season == "short_rains" or "short" in str(season).lower() or "sep" in str(season).lower() or "ond" in str(season).lower())
    if is_kiremt and s.get("chirps_kiremt"):
        c_source = s["chirps_kiremt"]
    elif is_short and s.get("chirps_sep"):
        c_source = s["chirps_sep"]
    else:
        c_source = s

    # Nearest pixel
    lat_arr = np.array(c_source.get("target_lat", s["target_lat"]))
    lon_arr = np.array(c_source.get("target_lon", s["target_lon"]))
    pi = int(np.argmin(np.abs(lat_arr - lat)))
    pj = int(np.argmin(np.abs(lon_arr - lon)))

    years    = [int(y) for y in c_source["chirps_years"]]
    cal_mask = c_source.get("cal_mask")
    if cal_mask is None:
        cal_mask = np.isin(np.array(years), np.arange(1981, 2017))

    on_ts  = [float(v) if not np.isnan(v) else None for v in c_source["onset_doy"][:, pi, pj]]
    cs_ts  = [float(v) if not np.isnan(v) else None for v in c_source["cessation_doy"][:, pi, pj]]
    lgp_ts = [float(v) if not np.isnan(v) else None for v in c_source["lgp_days"][:, pi, pj]]

    def compute_stats(ts_raw):
        ts = np.array([v if v is not None else np.nan for v in ts_raw], dtype=float)
        cal = ts[cal_mask]
        cal_valid = cal[~np.isnan(cal)]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_val = float(np.nanmean(cal)) if len(cal_valid) else None
            sd_val   = float(np.nanstd(cal, ddof=1)) if len(cal_valid) > 1 else None
            cv_val   = round(sd_val / mean_val * 100, 1) if (mean_val and sd_val and mean_val != 0) else None

            # Trend: linear slope over all non-nan years
            valid_mask = ~np.isnan(ts)
            if np.sum(valid_mask) > 5:
                xs = np.where(valid_mask)[0].astype(float)
                ys = ts[valid_mask]
                slope = float(np.polyfit(xs, ys, 1)[0])
                trend = round(slope, 3)
            else:
                trend = None

            # Latest non-nan value
            last_idx = np.where(valid_mask)[0]
            latest_val = float(ts[last_idx[-1]]) if len(last_idx) else None
            anom  = round(latest_val - mean_val, 1) if (latest_val is not None and mean_val) else None
            prank = int(round(np.sum(cal_valid <= latest_val) / len(cal_valid) * 100))                     if (latest_val is not None and len(cal_valid)) else None
            det   = round(float(np.sum(~np.isnan(cal))) / max(len(cal), 1), 3) if len(cal) else None

        return {
            "mean"             : round(mean_val, 1) if mean_val is not None else None,
            "sd"               : round(sd_val, 1)   if sd_val   is not None else None,
            "cv"               : cv_val,
            "trend_day_per_yr" : trend,
            "latest_val"       : round(latest_val, 1) if latest_val is not None else None,
            "latest_anom"      : anom,
            "latest_prank"     : prank,
            "detect_rate"      : det,
        }

    cal_years_list = [int(y) for y in np.array(c_source["chirps_years"])[cal_mask]]
    latest_year    = int(c_source["chirps_years"][-1])

    return _json({
        "years"      : years,
        "cal_years"  : cal_years_list,
        "latest_year": latest_year,
        "onset"      : {"ts": on_ts,  **compute_stats(on_ts)},
        "cessation"  : {"ts": cs_ts,  **compute_stats(cs_ts)},
        "lgp"        : {"ts": lgp_ts, **compute_stats(lgp_ts)},
    })

@router.get("/validation")
def get_validation():
    """Domain-mean probabilities per VAL year per model."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    import numpy as np, warnings

    s   = dl.get_state()
    lm  = s["lm"]
    op  = int(s["OP_YEAR"])
    cal = set(int(y) for y in s["chirps_years"][s["cal_mask"]])

    result = {}
    for name, md in s["MODELS"].items():
        my = md.get("model_years")
        if my is None:
            continue
        years_list = [int(y) for y in my]
        val_idx = [i for i, y in enumerate(years_list) if y != op and y not in cal]
        val_years = [years_list[i] for i in val_idx]

        probs_out = {}
        for var in ["onset", "cessation", "lgp"]:
            pd_arr = md.get("probs_damped", {}).get(var)
            if pd_arr is None or not hasattr(pd_arr, "shape") or pd_arr.ndim < 2:
                probs_out[var] = {"bn": [], "nn": [], "an": [], "years": val_years}
                continue
            bn_vals, nn_vals, an_vals = [], [], []
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                for yi in val_idx:
                    if yi >= pd_arr.shape[1]:
                        continue
                    bn_vals.append(round(float(np.nanmean(pd_arr[0, yi][lm])), 3))
                    nn_vals.append(round(float(np.nanmean(pd_arr[1, yi][lm])), 3))
                    an_vals.append(round(float(np.nanmean(pd_arr[2, yi][lm])), 3))
            probs_out[var] = {
                "bn": bn_vals, "nn": nn_vals, "an": an_vals,
                "years": val_years[:len(bn_vals)],
            }
        result[name] = {"probs": probs_out}

    return _json(result)
