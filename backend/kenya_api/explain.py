"""GET /explain/*  --  the forecast assistant's explanations (assistant/).

Each response carries the evidence record it was written from, the explanation (template or Claude) and the
result of the number check, so the dashboard can show the evidence beside the text.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import mam_loader as dl
from pydantic import BaseModel

from assistant import advisory, chat, evidence as ev
from assistant import narrate
from kenya_api.pixel import _clean
import json

router = APIRouter()


def _reply(kind, rec, audience):
    out = {"kind": kind, "evidence": rec, "explanation": narrate.explain(kind, rec, audience)}
    return Response(content=json.dumps(_clean(out)), media_type="application/json")


def _ready():
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")


@router.get("/status")
def status():
    """Whether Claude writes the explanations (else the standard template is used)."""
    return narrate.llm_status()


@router.get("/location")
def explain_location(
    lat: float = Query(...), lon: float = Query(...),
    season: str = Query("short_rains"),
    model: str = Query("", description="Platform model name, as for /pixel"),
    year: int = Query(None),
    audience: str = Query("general", description="general | farmer | extension | technical"),
):
    """What the current outlook means at one place (the forecast grid cell holding lat, lon)."""
    _ready()
    try:
        rec = ev.location(lat, lon, season, model, year)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("location", rec, audience)


@router.get("/changes")
def explain_changes(
    lat: float = Query(...), lon: float = Query(...),
    season: str = Query("short_rains"),
    model: str = Query(..., description="The current run (platform model name)"),
    compare_to: str = Query(..., description="The earlier run, or another method, to compare with"),
    year: int = Query(None),
    audience: str = Query("general"),
):
    """What changed at one place between two runs (or two methods)."""
    _ready()
    if model == compare_to:
        raise HTTPException(400, "Choose two different runs to compare.")
    try:
        rec = ev.changes(lat, lon, season, model, compare_to, year)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("changes", rec, audience)


@router.get("/map")
def explain_map(
    variable: str = Query("onset"), layer: str = Query("median"),
    model: str = Query(""), season: str = Query("short_rains"),
    audience: str = Query("general"),
):
    """What a map layer shows: its distribution, where values are high and low, and the monitored sites."""
    _ready()
    try:
        rec = ev.map_layer(variable, layer, model, season)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _reply("map", rec, audience)


@router.get("/advisory")
def explain_advisory(
    lat: float = Query(...), lon: float = Query(...),
    season: str = Query("short_rains"),
    model: str = Query(""),
    decision: str = Query("", description="sowing | crop_choice | establishment | replanting | water"),
    crop: str = Query("maize_early", description="maize_early | maize_medium | sorghum | bean"),
    planted: str = Query("unknown", description="yes | no | unknown"),
    sowing_date: str = Query("", description="ISO date, when sown"),
    water: str = Query("rainfed", description="rainfed | irrigated"),
    objective: str = Query("maturity", description="maturity | establishment | downside | yield | water"),
    year: int = Query(None),
    audience: str = Query("general"),
):
    """An advisory card (DRAFT rules, not reviewed): the assessment for one decision, the options from the crop
    outlook ranked by the objective, their trade-offs, and what could change the assessment."""
    _ready()
    try:
        rec = advisory.card(lat, lon, season, model, {"decision": decision, "crop": crop, "planted": planted,
                                                      "sowing_date": sowing_date, "water": water,
                                                      "objective": objective}, year)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("advisory", rec, audience)


class ChatIn(BaseModel):
    messages: list = []
    context: dict = {}
    audience: str = "general"


@router.post("/chat")
def chat_reply(body: ChatIn):
    """The forecast assistant's answer to the last user message, from the platform's evidence (assistant/chat.py).
    Context: {lat, lon, season, model, variable, layer, site_name} of the dashboard."""
    _ready()
    out = chat.reply(body.messages, body.context, body.audience)
    return Response(content=json.dumps(_clean(out)), media_type="application/json")
