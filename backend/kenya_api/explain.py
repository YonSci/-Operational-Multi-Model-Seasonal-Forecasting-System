"""GET /explain/*  --  the forecast assistant's explanations (assistant/).

Each response carries the evidence record it was written from, the explanation (template or Claude) and the
result of the number check, so the dashboard can show the evidence beside the text.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import mam_loader as dl
from pydantic import BaseModel

from assistant import advisory, areas, charts, chat, evidence as ev, tracker
from assistant import narrate, translate
from kenya_api.pixel import _clean
import json

router = APIRouter()


def _reply(kind, rec, audience, language="en"):
    out = {"kind": kind, "evidence": rec,
           "explanation": translate.localise(narrate.explain(kind, rec, audience), language)}
    return Response(content=json.dumps(_clean(out)), media_type="application/json")


def _ready():
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")


@router.get("/languages")
def languages():
    """The assistant's languages, with the review status of each glossary."""
    return {"languages": translate.languages()}


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
    language: str = Query("en", description="en | sw | am"),
):
    """What the current outlook means at one place (the forecast grid cell holding lat, lon)."""
    _ready()
    try:
        rec = ev.location(lat, lon, season, model, year)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("location", rec, audience, language)


@router.get("/changes")
def explain_changes(
    lat: float = Query(...), lon: float = Query(...),
    season: str = Query("short_rains"),
    model: str = Query(..., description="The current run (platform model name)"),
    compare_to: str = Query(..., description="The earlier run, or another method, to compare with"),
    year: int = Query(None),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """What changed at one place between two runs (or two methods)."""
    _ready()
    if model == compare_to:
        raise HTTPException(400, "Choose two different runs to compare.")
    try:
        rec = ev.changes(lat, lon, season, model, compare_to, year)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("changes", rec, audience, language)


@router.get("/map")
def explain_map(
    variable: str = Query("onset"), layer: str = Query("median"),
    model: str = Query(""), season: str = Query("short_rains"),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """What a map layer shows: its distribution, where values are high and low, and the monitored sites."""
    _ready()
    try:
        rec = ev.map_layer(variable, layer, model, season)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _reply("map", rec, audience, language)


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
    language: str = Query("en", description="en | sw | am"),
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
    return _reply("advisory", rec, audience, language)


class ChatIn(BaseModel):
    messages: list = []
    context: dict = {}
    audience: str = "general"
    language: str = "en"


@router.post("/chat")
def chat_reply(body: ChatIn):
    """The forecast assistant's answer to the last user message, from the platform's evidence (assistant/chat.py).
    Context: {lat, lon, season, model, variable, layer, site_name} of the dashboard."""
    _ready()
    out = chat.reply(body.messages, body.context, body.audience, body.language)
    return Response(content=json.dumps(_clean(out)), media_type="application/json")


@router.get("/regions")
def list_regions(season: str = Query("short_rains")):
    """The counties (Kenya) or regions (Ethiopia) an area explanation can name."""
    country = areas.country_of(season)
    return {"country": country, "kind": areas.ADMIN[country][1], "names": sorted(n for n, _ in areas.regions(country) if n)}


@router.get("/area")
def explain_area(
    season: str = Query("short_rains"), model: str = Query(...),
    name: str = Query("", description="county (Kenya) or region (Ethiopia)"),
    bbox: str = Query("", description="drawn rectangle: west,south,east,north"),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """The outlook over a county/region or a drawn rectangle: cell spread, area-wide event chances (members) and the
    average of the cells' skill-weighted chances."""
    _ready()
    try:
        box = [float(x) for x in bbox.split(",")] if bbox else None
        rec = areas.area(season, model, name=name or None, bbox=box)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _reply("area", rec, audience, language)


@router.get("/attention")
def explain_attention(
    season: str = Query("short_rains"), model: str = Query(...),
    criterion: str = Query("late_onset", description=", ".join(areas.CRITERIA)),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """Areas needing attention on one criterion: counties/regions ranked by the share of their cells that meet it."""
    _ready()
    try:
        rec = areas.attention(season, model, criterion)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _reply("attention", rec, audience, language)


@router.get("/chart")
def explain_chart(
    chart_kind: str = Query(..., alias="chart", description=", ".join(charts.KINDS)),
    lat: float = Query(...), lon: float = Query(...),
    season: str = Query("short_rains"), model: str = Query(""),
    quantity: str = Query("onset"), crop: str = Query("maize_early"),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """What a chart shows: member dates, crop outcomes, or the rainfall plume (illustrative where the server has no
    daily members)."""
    _ready()
    try:
        rec = charts.chart(chart_kind, lat, lon, season, model, quantity=quantity, crop=crop)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _reply("chart", rec, audience, language)


@router.get("/tracker/sites")
def tracker_sites():
    """The monitoring sites of the near real-time rainfall tracking page."""
    try:
        return {"sites": tracker.sites()}
    except ValueError as e:
        raise HTTPException(503, str(e))


@router.get("/tracker")
def explain_tracker(
    site: str = Query("", description="tracking site name (whole or part), or give lat/lon"),
    lat: float = Query(None), lon: float = Query(None),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """How the season is going at a rainfall tracking site: rain so far, planting onset in the satellite products,
    days since the last wet day, the weather models' next days and the seasonal outlook. Needs no forecast data."""
    try:
        rec = tracker.status(site or None, lat, lon)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("tracker", rec, audience, language)


@router.get("/tracker/changes")
def explain_tracker_changes(
    site: str = Query(""), lat: float = Query(None), lon: float = Query(None),
    audience: str = Query("general"),
    language: str = Query("en", description="en | sw | am"),
):
    """What changed between the two latest weather-model runs at a tracking site, and the rain of the last days."""
    try:
        rec = tracker.changes(site or None, lat, lon)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _reply("tracker_changes", rec, audience, language)
