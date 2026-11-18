"""Field reports: what farmers, extension staff and researchers observe (sowing, rain, emergence, crop stage, water
stress, harvest) and whether an advisory was understandable and feasible.

Every report keeps its verification status (unverified until a reviewer marks it) and its kind of evidence: a
farmer's estimate, a gauge reading and a satellite estimate are all useful but not the same. Contact details are
optional, kept only with consent, and shown only to reviewers (ASSISTANT_ADMIN_TOKEN). A photo may be attached;
Claude gives a first description for the reviewer, marked as not a diagnosis.
"""
import base64
import datetime as dt
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import defaultdict, deque

from . import narrate, store

log = logging.getLogger("assistant")
TABLE, BUCKET = "field_reports", "field-photos"
RADIUS_KM = 25.0
MAX_PHOTO = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
ROLES = ("farmer", "extension", "researcher", "other")

# report type -> (label, fields: name -> (kind, required, limits or choices))
TYPES = {
    "sowing": ("Sowing", {"sown_on": ("date", True, None), "variety_note": ("text", False, 120), "area_ha": ("number", False, (0, 1000))}),
    "rainfall": ("Rainfall", {"observed_on": ("date", True, None), "rain_mm": ("number", True, (0, 500)),
                              "measured_by": ("choice", True, ("rain gauge", "estimate"))}),
    "emergence": ("Emergence", {"observed_on": ("date", True, None), "established_pct": ("number", True, (0, 100)),
                                "note": ("text", False, 300)}),
    "crop_stage": ("Crop stage", {"observed_on": ("date", True, None),
                                  "stage": ("choice", True, ("emerged", "vegetative", "flowering", "grain filling", "mature"))}),
    "water_stress": ("Water stress", {"observed_on": ("date", True, None),
                                      "severity": ("choice", True, ("none", "mild", "moderate", "severe")), "note": ("text", False, 300)}),
    "harvest": ("Harvest", {"harvested_on": ("date", True, None), "yield_t_ha": ("number", False, (0, 20)),
                            "area_ha": ("number", False, (0, 1000)), "note": ("text", False, 300)}),
    "advisory_feedback": ("Advisory feedback", {"advisory_id": ("text", False, 40),
                                                "understandable": ("choice", True, ("yes", "partly", "no")),
                                                "feasible": ("choice", True, ("yes", "partly", "no")),
                                                "followed": ("choice", False, ("yes", "partly", "no")), "comment": ("text", False, 500)}),
}


def schema():
    return {k: {"label": lab, "fields": {f: {"kind": kd, "required": rq,
                                             **({"choices": list(lim)} if kd == "choice" else {"limits": lim} if lim else {})}
                                         for f, (kd, rq, lim) in fs.items()}}
            for k, (lab, fs) in TYPES.items()}


# ---------------------------------------------------------------------------- validation
def _date(v, name):
    try:
        d = dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError(f"{name}: not a date (YYYY-MM-DD)")
    if d > dt.date.today() + dt.timedelta(days=1) or d.year < 2000:
        raise ValueError(f"{name}: date out of range")
    return d.isoformat()


def validate(r: dict) -> dict:
    t = r.get("report_type")
    if t not in TYPES:
        raise ValueError(f"report_type must be one of {sorted(TYPES)}")
    _, fields = TYPES[t]
    payload = {}
    src = r.get("payload") or {}
    for name, (kind, required, lim) in fields.items():
        v = src.get(name)
        if v in (None, ""):
            if required:
                raise ValueError(f"{name} is required")
            continue
        if kind == "date":
            payload[name] = _date(v, name)
        elif kind == "number":
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name}: not a number")
            if not math.isfinite(x) or (lim and not lim[0] <= x <= lim[1]):
                raise ValueError(f"{name}: must be between {lim[0]} and {lim[1]}")
            payload[name] = x
        elif kind == "choice":
            if v not in lim:
                raise ValueError(f"{name} must be one of {list(lim)}")
            payload[name] = v
        else:
            payload[name] = str(v)[: lim or 300]
    try:
        lat, lon = float(r.get("lat")), float(r.get("lon"))
    except (TypeError, ValueError):
        raise ValueError("lat and lon are required")
    if not (-12 <= lat <= 16 and 32 <= lon <= 49):
        raise ValueError("The place is outside Kenya and Ethiopia")
    role = r.get("reporter_role") if r.get("reporter_role") in ROLES else "other"
    consent = bool(r.get("consent"))
    observed = payload.get("observed_on") or payload.get("sown_on") or payload.get("harvested_on")
    return {"report_type": t, "observed_on": observed, "lat": round(lat, 4), "lon": round(lon, 4),
            "place_name": (r.get("place_name") or "")[:120] or None, "country": (r.get("country") or "")[:20] or None,
            "season": (r.get("season") or "")[:20] or None, "crop": (r.get("crop") or "")[:20] or None,
            "payload": payload, "reporter_role": role, "consent": consent,
            "reporter_contact": (r.get("reporter_contact") or "")[:120] or None if consent else None,
            "verification": "unverified"}


def evidence_kind(row) -> str:
    """What kind of evidence a report is, for whoever reads it."""
    if row["report_type"] == "rainfall":
        return "gauge reading" if (row.get("payload") or {}).get("measured_by") == "rain gauge" else "rainfall estimate"
    return {"farmer": "farmer's observation", "extension": "extension officer's observation",
            "researcher": "researcher's measurement"}.get(row.get("reporter_role"), "observation")


# ---------------------------------------------------------------------------- limits (public endpoint)
class _Rate:
    def __init__(self):
        self.lock = threading.Lock()
        self.by = defaultdict(deque)

    def allow(self, key, per_hour):
        now = time.time()
        with self.lock:
            q = self.by[key]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= per_hour:
                return False
            q.append(now)
            return True


_rate = _Rate()


def allow(ip: str) -> bool:
    return _rate.allow("ip:" + (ip or "?"), int(os.environ.get("FEEDBACK_PER_IP_PER_HOUR", "20"))) and \
        _rate.allow("all", int(os.environ.get("FEEDBACK_PER_HOUR", "500")))


# ---------------------------------------------------------------------------- photo
TRIAGE_SCHEMA = {"type": "object", "additionalProperties": False,
                 "required": ["visible_crop", "growth_stage", "visible_signs", "image_usable", "note"],
                 "properties": {"visible_crop": {"type": "string"}, "growth_stage": {"type": "string"},
                                "visible_signs": {"type": "array", "items": {"type": "string"}},
                                "image_usable": {"type": "boolean"}, "note": {"type": "string"}}}


def triage_photo(data: bytes, content_type: str, report: dict):
    """A first description of the photo for the reviewer (not a diagnosis), or None without Claude."""
    if not narrate.llm_status()["llm_enabled"] or not narrate._limiter.allow(int(os.environ.get("ASSISTANT_MAX_CALLS_PER_HOUR", "200"))):
        return None
    try:
        client = narrate._get_client()
        resp = client.messages.create(
            model=os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5"), max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
            system="You describe field photos sent with crop reports so a reviewer can check them. Describe only what is "
                   "visible: the crop if recognisable, its growth stage, and visible signs such as wilting, leaf rolling, "
                   "yellowing, bare soil, poor stand or standing water. Do not diagnose pests or diseases and do not "
                   "give advice. Say when the image is unclear. Plain English, short.",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": base64.standard_b64encode(data).decode()}},
                {"type": "text", "text": f"Report type: {report['report_type']}; crop stated: {report.get('crop') or 'not stated'}."}]}])
        if resp.stop_reason != "end_turn":
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        out = json.loads(text) if text else None
        if out:
            out.update(status="needs review", model=resp.model, disclaimer="A first description by an AI model, not a diagnosis.")
        return out
    except Exception as e:
        log.warning("feedback: photo triage failed: %s: %s", type(e).__name__, e)
        return None


# ---------------------------------------------------------------------------- operations
def submit(report: dict, photo: bytes = None, photo_type: str = None) -> dict:
    row = validate(report)
    if photo:
        if photo_type not in PHOTO_TYPES:
            raise ValueError("Photo must be JPEG, PNG or WebP")
        if len(photo) > MAX_PHOTO:
            raise ValueError("Photo larger than 5 MB")
        name = f"{dt.date.today():%Y/%m}/{uuid.uuid4().hex}.{PHOTO_TYPES[photo_type]}"
        row["photo_path"] = store.upload(BUCKET, name, photo, photo_type)
        row["photo_triage"] = triage_photo(photo, photo_type, row)
    saved = store.insert(TABLE, row)
    return {"id": saved["id"], "verification": saved.get("verification", "unverified"),
            "evidence_kind": evidence_kind(saved), "photo_described": bool(row.get("photo_triage")),
            "storage": store.status()}


def _km(a, b, c, d):
    return math.hypot((c - a) * 111.0, (d - b) * 111.0 * math.cos(math.radians((a + c) / 2)))


def nearby(lat, lon, radius_km=RADIUS_KM, limit=500) -> dict:
    """Counts of reports near a place by type, with the latest observation date: no names or contacts."""
    try:
        rows = store.select(TABLE, limit=limit)
    except Exception as e:
        log.warning("feedback: could not read reports: %s", e)
        return None
    near = [r for r in rows if r.get("lat") is not None and r.get("verification") != "rejected"
            and _km(float(lat), float(lon), float(r["lat"]), float(r["lon"])) <= radius_km]
    if not near:
        return None
    by = {}
    for r in near:
        b = by.setdefault(r["report_type"], {"label": TYPES.get(r["report_type"], (r["report_type"],))[0],
                                             "reports": 0, "verified": 0, "latest_observed": None})
        b["reports"] += 1
        b["verified"] += r.get("verification") == "verified"
        if r.get("observed_on") and (not b["latest_observed"] or str(r["observed_on"]) > b["latest_observed"]):
            b["latest_observed"] = str(r["observed_on"])[:10]
    sow = sorted(str(r["payload"].get("sown_on")) for r in near if r["report_type"] == "sowing" and (r.get("payload") or {}).get("sown_on"))
    out = {"radius_km": radius_km, "reports": len(near), "by_type": by}
    if sow:
        out["sowing_dates_reported"] = {"earliest": sow[0], "latest": sow[-1], "reports": len(sow)}
    return out


def review(report_id: str, verification: str, reviewer: str, note: str = None) -> dict:
    if verification not in ("verified", "rejected", "unverified"):
        raise ValueError("verification must be verified, rejected or unverified")
    return store.update(TABLE, report_id, {"verification": verification, "reviewed_by": (reviewer or "")[:80] or None,
                                           "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                           "review_note": (note or "")[:500] or None})


def for_review(status: str = None, limit: int = 100) -> list:
    rows = store.select(TABLE, eq={"verification": status} if status else None, limit=limit)
    for r in rows:
        r["evidence_kind"] = evidence_kind(r)
        r["photo_url"] = store.signed_url(BUCKET, r.get("photo_path")) if r.get("photo_path") else None
    return rows
