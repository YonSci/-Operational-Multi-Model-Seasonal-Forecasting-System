"""/studio/*  --  Bulletin Studio (assistant/bulletins.py): compose, check, export and keep bulletins.

Composing, checking and exporting are open (nothing is stored). Saving versions and listing saved bulletins need
the header X-Admin-Token (ASSISTANT_ADMIN_TOKEN); published bulletins are listed for everyone.
"""
import json

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

import mam_loader as dl
from assistant import bulletins, store
from kenya_api.feedback import _admin
from kenya_api.pixel import _clean

router = APIRouter()


def _json(x):
    return Response(content=json.dumps(_clean(x)), media_type="application/json")


@router.get("/formats")
def formats():
    return {"formats": bulletins.FORMATS, "sections": [{"id": k, "label": v} for k, v in bulletins.SECTIONS],
            "lengths": list(bulletins.LENGTHS), "storage": store.status()}


class ComposeIn(BaseModel):
    format: str
    season: str = "short_rains"
    model: str
    lat: float | None = None
    lon: float | None = None
    area: str | None = None
    crop: str = "maize_early"
    planted: str = "unknown"
    sowing_date: str | None = None
    audience: str = "general"
    length: str = "standard"
    language: str = "en"


@router.post("/compose")
def compose(body: ComposeIn):
    """Gather the evidence snapshot and write the bulletin (template, or Claude under the number check)."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    try:
        snap = bulletins.snapshot(body.format, body.season, body.model, body.lat, body.lon, body.area, body.crop,
                                  body.planted, body.sowing_date)
    except ValueError as e:
        raise HTTPException(400, str(e))
    b = bulletins.compose(snap, body.audience, body.length)
    if body.language and body.language != "en":
        from assistant import translate
        tr, err = translate.translate({k: b[k] for k in ("title", "sections", "sms", "audio_script")}, body.language)
        if tr:
            b.update(tr, language=body.language, translation_notice=translate.NOTICE.get(body.language))
        if err:
            b["translation_note"] = err
    return _json({"bulletin": b, "snapshot": snap, "quality": bulletins.check(b, snap)})


class CheckIn(BaseModel):
    bulletin: dict
    snapshot: dict


@router.post("/check")
def check(body: CheckIn):
    """The quality check of an edited bulletin against its snapshot."""
    return _json({"quality": bulletins.check(body.bulletin, body.snapshot)})


@router.post("/export")
def export(body: CheckIn, fmt: str = Query("docx", description="docx | md | sms | audio")):
    b = body.bulletin
    name = "".join(c if c.isalnum() else "_" for c in (b.get("title") or "bulletin"))[:60]
    if fmt == "docx":
        return Response(bulletins.docx_bytes(b), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})
    if fmt in ("md", "sms", "audio"):
        txt = bulletins.markdown(b) if fmt == "md" else (b.get("sms") if fmt == "sms" else b.get("audio_script")) or ""
        ext = "md" if fmt == "md" else "txt"
        return Response(txt, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}_{fmt}.{ext}"'})
    raise HTTPException(400, "fmt must be docx, md, sms or audio")


class SaveIn(BaseModel):
    bulletin: dict
    snapshot: dict
    status: str = "draft"
    author: str = ""
    parent_id: str | None = None


@router.post("/save")
def save(body: SaveIn, x_admin_token: str = Header(None)):
    """Keep a version (draft, reviewed or published) with its evidence snapshot and quality check."""
    _admin(x_admin_token)
    issues = bulletins.check(body.bulletin, body.snapshot)
    try:
        return bulletins.save(body.bulletin, body.snapshot, issues, body.author, body.parent_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/saved")
def saved(status: str = Query(""), x_admin_token: str = Header(None)):
    _admin(x_admin_token)
    return {"bulletins": bulletins.saved(status=status or None)}


@router.get("/published")
def published():
    return {"bulletins": bulletins.saved(status="published")}


@router.get("/saved/{row_id}")
def saved_one(row_id: str, x_admin_token: str = Header(None)):
    row = bulletins.get(row_id)
    if not row:
        raise HTTPException(404, "No such bulletin")
    if row.get("status") != "published":
        _admin(x_admin_token)
    return _json(row)
