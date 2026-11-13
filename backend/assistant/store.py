"""Permanent storage for the assistant: Supabase (Postgres tables over its REST API, and Storage for photos).

Settings (Render environment variables; keep the key secret):
  SUPABASE_URL           https://<project>.supabase.co
  SUPABASE_SERVICE_KEY   the project's service-role key (server only: it bypasses row-level security)
Without them, rows and files go to local files under ASSISTANT_STORE_DIR (default outputs/assistant_store): fine
for development and tests, but NOT permanent on Render, whose disk is wiped on every deploy. status() says which.

Tables and the bucket are created by backend/assistant/supabase_schema.sql (run once in the Supabase SQL editor).
"""
import datetime as dt
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

_lock = threading.Lock()


def _cfg():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return (url, key) if url and key else (None, None)


def status() -> dict:
    url, _ = _cfg()
    return {"backend": "supabase" if url else "local", "permanent": bool(url),
            "note": None if url else "Reports are kept in local files on this server and are lost on redeploy; "
                                     "set SUPABASE_URL and SUPABASE_SERVICE_KEY to keep them."}


def _local_dir() -> Path:
    d = Path(os.environ.get("ASSISTANT_STORE_DIR") or Path(__file__).resolve().parents[2] / "outputs" / "assistant_store")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _req(method, path, body=None, headers=None, raw=None, content_type="application/json"):
    url, key = _cfg()
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": content_type}
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode("utf-8")
            return json.loads(txt) if txt else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"storage {method} {path.split('?')[0]}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}")


# ---------------------------------------------------------------------------- rows
def insert(table: str, row: dict) -> dict:
    row = dict(row)
    row.setdefault("id", str(uuid.uuid4()))
    row.setdefault("created_at", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    url, _ = _cfg()
    if url:
        out = _req("POST", f"/rest/v1/{table}", row, {"Prefer": "return=representation"})
        return out[0] if isinstance(out, list) and out else row
    with _lock:
        with open(_local_dir() / f"{table}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    return row


def _local_rows(table):
    p = _local_dir() / f"{table}.jsonl"
    if not p.exists():
        return []
    rows = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("_deleted"):
                rows.pop(r["id"], None)
            else:
                rows[r["id"]] = {**rows.get(r["id"], {}), **r}       # later lines update earlier ones
    return list(rows.values())


def select(table: str, eq: dict = None, order: str = "created_at.desc", limit: int = 200) -> list:
    """Rows where every eq field equals its value, newest first."""
    url, _ = _cfg()
    if url:
        q = [f"{k}=eq.{urllib.parse.quote(str(v))}" for k, v in (eq or {}).items()] + [f"order={order}", f"limit={int(limit)}"]
        return _req("GET", f"/rest/v1/{table}?" + "&".join(q)) or []
    rows = [r for r in _local_rows(table) if all(str(r.get(k)) == str(v) for k, v in (eq or {}).items())]
    field, _, direction = order.partition(".")
    rows.sort(key=lambda r: str(r.get(field) or ""), reverse=direction == "desc")
    return rows[:limit]


def update(table: str, row_id: str, patch: dict) -> dict:
    url, _ = _cfg()
    if url:
        out = _req("PATCH", f"/rest/v1/{table}?id=eq.{urllib.parse.quote(row_id)}", patch, {"Prefer": "return=representation"})
        return out[0] if out else {}
    with _lock:
        with open(_local_dir() / f"{table}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": row_id, **patch}, default=str) + "\n")
    return next((r for r in _local_rows(table) if r["id"] == row_id), {})


def delete(table: str, row_id: str) -> None:
    url, _ = _cfg()
    if url:
        _req("DELETE", f"/rest/v1/{table}?id=eq.{urllib.parse.quote(row_id)}")
        return
    with _lock:
        with open(_local_dir() / f"{table}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": row_id, "_deleted": True}) + "\n")


# ---------------------------------------------------------------------------- files (photos)
def upload(bucket: str, name: str, data: bytes, content_type: str) -> str:
    """Store a file privately; returns its path in the bucket."""
    url, _ = _cfg()
    if url:
        _req("POST", f"/storage/v1/object/{bucket}/{urllib.parse.quote(name)}", raw=data, content_type=content_type,
             headers={"x-upsert": "false"})
        return name
    f = _local_dir() / bucket / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return name


def signed_url(bucket: str, name: str, seconds: int = 3600):
    """A temporary link to a private file (Supabase only), or None."""
    url, _ = _cfg()
    if not url or not name:
        return None
    out = _req("POST", f"/storage/v1/object/sign/{bucket}/{urllib.parse.quote(name)}", {"expiresIn": seconds})
    return url + "/storage/v1" + out["signedURL"] if out and out.get("signedURL") else None
