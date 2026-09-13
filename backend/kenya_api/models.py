"""GET /models  —  list all loaded models."""
from fastapi import APIRouter, HTTPException
import mam_loader as dl

router = APIRouter()

@router.get("")
def get_models():
    """Return metadata for all loaded models."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    info = dl.get_model_info()   # returns list of dicts
    return {
        "models"       : {m["name"]: m for m in info},
        "op_year"      : int(dl._OP_YEAR),
        "win_doy_start": int(dl.WIN_DOY_START),
        "win_doy_end"  : int(dl.WIN_DOY_END),
    }
