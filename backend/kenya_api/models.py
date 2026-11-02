"""GET /models  —  list all loaded models."""
from fastapi import APIRouter, HTTPException, Query
import mam_loader as dl

router = APIRouter()

@router.get("")
def get_models(season: str = Query(None, description="Optional season filter: 'long_rains', 'short_rains', 'kiremt', or 'fmam'")):
    """Return metadata for loaded models, filtered by season if provided."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    info = dl.get_model_info(season=season)   # returns list of dicts
    is_short = (season == "short_rains" or "short" in str(season).lower() or "sep" in str(season).lower() or "ond" in str(season).lower())
    is_kiremt = (season == "kiremt" or "kiremt" in str(season).lower())
    is_fmam = (season == "fmam" or "fmam" in str(season).lower() or "belg" in str(season).lower())
    
    if is_fmam:
        w_start, w_end = 32, 166
    elif is_kiremt:
        w_start, w_end = 122, 304
    elif is_short:
        w_start, w_end = 244, 365
    else:
        w_start, w_end = int(dl.WIN_DOY_START), int(dl.WIN_DOY_END)

    return {
        "models"       : {m["name"]: m for m in info},
        "op_year"      : int(dl._OP_YEAR),
        "win_doy_start": w_start,
        "win_doy_end"  : w_end,
    }


@router.get("/forecast-runs")
def get_forecast_runs():
    """Forecast runs joining one weather model to the seasonal forecast (Forecast tab: Sub-seasonal and Medium-range
    views): source, kind (s2s | medium), model, run date, where each day's rainfall comes from, and the model name to
    request from /pixel and /grid (append a method suffix such as " - Agri rule 1" for the other methods)."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    return dl.forecast_runs_index()
