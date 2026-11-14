"""/extras/*  --  analogues, end-of-season review, guided learning, scenario planning and official outlooks
(assistant/extras.py). Uploading an official outlook needs the reviewer token (X-Admin-Token)."""
import json

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

import mam_loader as dl
from assistant import extras, narrate, translate
from kenya_api.feedback import _admin
from kenya_api.pixel import _clean

router = APIRouter()


def _json(x):
    return Response(content=json.dumps(_clean(x)), media_type="application/json")


def _ready():
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")


def _explained(kind, fn, audience, language, *a):
    _ready()
    try:
        rec = fn(*a)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _json({"kind": kind, "evidence": rec,
                  "explanation": translate.localise(narrate.explain(kind, rec, audience), language)})


@router.get("/analogues")
def analogues(lat: float = Query(...), lon: float = Query(...), season: str = Query("short_rains"), model: str = Query(...),
              audience: str = Query("general"), language: str = Query("en")):
    """Past seasons (CHIRPS) most like this season's forecast at a place."""
    return _explained("analogues", extras.analogues, audience, language, lat, lon, season, model)


@router.get("/season-review")
def season_review(lat: float = Query(...), lon: float = Query(...), season: str = Query("short_rains"), model: str = Query(...),
                  years: int = Query(5, ge=1, le=20), audience: str = Query("general"), language: str = Query("en")):
    """End-of-season review: past seasons' hindcasts against what was observed."""
    return _explained("season_review", extras.season_review, audience, language, lat, lon, season, model, years)


@router.get("/lessons")
def lessons(lat: float = Query(...), lon: float = Query(...), season: str = Query("short_rains"), model: str = Query(...),
            language: str = Query("en")):
    """Guided learning: how to read each figure, with this forecast's own numbers and a check question."""
    _ready()
    try:
        rec = extras.lessons(lat, lon, season, model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if language != "en":
        tr, err = translate.translate(rec["lessons"], language)
        if tr:
            rec = {**rec, "lessons": tr, "language": language, "translation_notice": translate.NOTICE.get(language)}
        if err:
            rec = {**rec, "translation_note": err}
    return _json(rec)


@router.get("/scenario-plan")
def scenario_plan(lat: float = Query(...), lon: float = Query(...), season: str = Query("short_rains"), model: str = Query(...),
                  crop: str = Query("maize_early")):
    """Participatory scenario planning: outcomes with their chances, the crop by season rain, discussion questions."""
    _ready()
    try:
        return _json(extras.scenario_plan(lat, lon, season, model, crop))
    except ValueError as e:
        raise HTTPException(400, str(e))


class OutlookIn(BaseModel):
    source: str
    season: str
    year: int
    issued_on: str | None = None
    variable: str = "rainfall"
    regions: list = []
    geojson: dict | None = None
    uploaded_by: str = ""


@router.post("/outlooks")
def upload(body: OutlookIn, x_admin_token: str = Header(None)):
    """Upload an official outlook by hand: chances by county/region name, or as GeoJSON polygons."""
    _admin(x_admin_token)
    try:
        return extras.upload(body.model_dump())
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@router.get("/outlooks")
def list_outlooks(season: str = Query("")):
    return {"outlooks": extras.outlooks(season or None)}


@router.get("/outlooks/{outlook_id}/compare")
def compare(outlook_id: str, model: str = Query(...), audience: str = Query("general"), language: str = Query("en")):
    """The official outlook against the platform's chances, area by area."""
    return _explained("outlook_comparison", extras.compare_official, audience, language, outlook_id, model)
