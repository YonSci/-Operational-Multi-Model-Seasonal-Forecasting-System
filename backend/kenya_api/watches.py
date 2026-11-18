"""/watches/*  --  saved watches ("Did the advice change?") and the decision calendar (assistant/watches.py).

A watch is anonymous: creating one returns its id and a private key; the dashboard keeps both in the browser and
sends the key (header X-Watch-Key) to read, acknowledge, edit or delete it.
"""
import json

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

import mam_loader as dl
from assistant import watches
from kenya_api.pixel import _clean

router = APIRouter()


def _ready():
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")


def _json(x):
    return Response(content=json.dumps(_clean(x)), media_type="application/json")


class WatchIn(BaseModel):
    name: str = ""
    lat: float
    lon: float
    place_name: str = ""
    season: str = "short_rains"
    model: str
    crop: str = "maize_early"
    planted: str = "unknown"
    sowing_date: str | None = None
    decision: str = ""
    objective: str = "maturity"
    thresholds: dict = {}


@router.post("")
def create(body: WatchIn):
    _ready()
    try:
        return watches.create(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


def _call(fn, *a):
    _ready()
    try:
        return fn(*a)
    except PermissionError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{wid}")
def check(wid: str, x_watch_key: str = Header(...)):
    """What changed since the baseline, and the verdict."""
    return _json(_call(watches.check, wid, x_watch_key))


@router.post("/{wid}/acknowledge")
def acknowledge(wid: str, x_watch_key: str = Header(...)):
    """Make today's figures the new baseline."""
    return _call(watches.acknowledge, wid, x_watch_key)


class EditIn(BaseModel):
    patch: dict


@router.post("/{wid}/edit")
def edit(wid: str, body: EditIn, x_watch_key: str = Header(...)):
    return _call(watches.edit, wid, x_watch_key, body.patch)


@router.delete("/{wid}")
def delete(wid: str, x_watch_key: str = Header(...)):
    _call(watches.remove, wid, x_watch_key)
    return {"id": wid, "status": "deleted"}


@router.get("/calendar/for")
def calendar(lat: float = Query(...), lon: float = Query(...), season: str = Query("short_rains"), model: str = Query(...),
             crop: str = Query("maize_early"), planted: str = Query("unknown"), sowing_date: str = Query("")):
    """The decisions and dates ahead for a crop at a place."""
    _ready()
    try:
        return _json(watches.calendar(lat, lon, season, model, crop, planted, sowing_date or None))
    except ValueError as e:
        raise HTTPException(400, str(e))
