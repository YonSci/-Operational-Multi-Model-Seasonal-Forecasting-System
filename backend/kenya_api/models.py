"""GET /models  —  list all loaded models."""
from fastapi import APIRouter, HTTPException, Query
import mam_loader as dl

router = APIRouter()

@router.get("")
def get_models(season: str = Query(None, description="Optional season filter: 'long_rains' or 'short_rains'")):
    """Return metadata for loaded models, filtered by season if provided."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    info = dl.get_model_info(season=season)   # returns list of dicts
    is_short = (season == "short_rains")
    return {
        "models"       : {m["name"]: m for m in info},
        "op_year"      : int(dl._OP_YEAR),
        "win_doy_start": 244 if is_short else int(dl.WIN_DOY_START),
        "win_doy_end"  : 365 if is_short else int(dl.WIN_DOY_END),
    }
