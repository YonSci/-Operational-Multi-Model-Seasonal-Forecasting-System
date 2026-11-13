"""/feedback/*  --  field reports (assistant/feedback.py, stored by assistant/store.py).

Public: the report form's schema, submitting a report (rate-limited), and counts near a place (no names or
contacts). Reviewers: the reports in full, with photos, and setting their verification; these need the header
X-Admin-Token equal to the ASSISTANT_ADMIN_TOKEN environment variable.
"""
import hmac
import json
import os

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from assistant import feedback, store

router = APIRouter()


def _admin(token):
    want = os.environ.get("ASSISTANT_ADMIN_TOKEN", "")
    if not want or not token or not hmac.compare_digest(str(token), want):
        raise HTTPException(401, "Reviewer token required")


@router.get("/status")
def status():
    """Where reports are stored, and the fields of each report type."""
    return {"storage": store.status(), "types": feedback.schema(), "roles": list(feedback.ROLES),
            "review_enabled": bool(os.environ.get("ASSISTANT_ADMIN_TOKEN"))}


@router.post("/report")
async def submit_report(request: Request, report: str = Form(..., description="the report as JSON"),
                        photo: UploadFile | None = File(None)):
    """Submit a field report (JSON in the 'report' form field) with an optional photo (JPEG/PNG/WebP, 5 MB)."""
    if not feedback.allow(request.client.host if request.client else "?"):
        raise HTTPException(429, "Too many reports from here; try again later.")
    try:
        r = json.loads(report)
    except json.JSONDecodeError:
        raise HTTPException(400, "report must be JSON")
    data = await photo.read(feedback.MAX_PHOTO + 1) if photo is not None else None
    try:
        return feedback.submit(r, data or None, photo.content_type if photo is not None else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, f"The report could not be stored: {e}")


@router.get("/nearby")
def nearby(lat: float = Query(...), lon: float = Query(...), radius_km: float = Query(feedback.RADIUS_KM, le=100)):
    """Counts of field reports near a place by type (no names or contacts)."""
    return feedback.nearby(lat, lon, radius_km) or {"radius_km": radius_km, "reports": 0, "by_type": {}}


@router.get("/reports")
def reports(status: str = Query("", description="unverified | verified | rejected"), limit: int = Query(100, le=500),
            x_admin_token: str = Header(None)):
    """Reports in full for reviewers, newest first, with temporary photo links."""
    _admin(x_admin_token)
    return {"reports": feedback.for_review(status or None, limit), "storage": store.status()}


class ReviewIn(BaseModel):
    verification: str
    reviewer: str = ""
    note: str = ""


@router.post("/reports/{report_id}/review")
def review(report_id: str, body: ReviewIn, x_admin_token: str = Header(None)):
    _admin(x_admin_token)
    try:
        return feedback.review(report_id, body.verification, body.reviewer, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
