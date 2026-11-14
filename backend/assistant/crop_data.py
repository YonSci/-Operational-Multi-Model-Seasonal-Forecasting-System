"""The published crop outlook (frontend/public/tracker/data/crop): index.json and scenarios.json.

Read from the repository copy when the backend runs beside it, else from the dashboard's published site
(CROP_DATA_URL), and kept for 30 minutes. The files are public; nothing about the user is sent.
"""
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

LOCAL = Path(__file__).resolve().parents[2] / "frontend" / "public" / "tracker" / "data" / "crop"
DEFAULT_URL = "https://yonsci.github.io/-Operational-Multi-Model-Seasonal-Forecasting-System/tracker/data/crop/"
TTL = 1800

_cache = {}
_lock = threading.Lock()


def load(name: str):
    """A crop outlook file as JSON, or None when it cannot be read."""
    now = time.time()
    with _lock:
        hit = _cache.get(name)
        if hit and now - hit[0] < TTL:
            return hit[1]
    data = None
    path = LOCAL / name
    try:
        if path.exists() and os.environ.get("CROP_DATA_SOURCE", "auto") != "url":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            url = os.environ.get("CROP_DATA_URL", DEFAULT_URL).rstrip("/") + "/" + name
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
    except Exception:
        data = None
    with _lock:                                   # a failed read is retried after a minute, not after 30
        _cache[name] = (now if data is not None else now - TTL + 60, data)
    return data


PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public"
SITE_URL = "https://yonsci.github.io/-Operational-Multi-Model-Seasonal-Forecasting-System/"


def load_tracker(name: str):
    """A file of the rainfall tracking page's data (tracker/data/<name>): a CSV as a list of row dicts, a JSON file
    as JSON; None when it cannot be read. The repository copy, else the published site's. Cached as load()."""
    import csv
    import io
    key = "tracker:" + name
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    data = None
    try:
        path = PUBLIC / "tracker" / "data" / name
        if path.exists() and os.environ.get("CROP_DATA_SOURCE", "auto") != "url":
            text = path.read_text(encoding="utf-8")
        else:
            url = os.environ.get("SITE_URL", SITE_URL).rstrip("/") + "/tracker/data/" + name
            with urllib.request.urlopen(url, timeout=30) as r:
                text = r.read().decode("utf-8")
        data = json.loads(text) if name.endswith(".json") else list(csv.DictReader(io.StringIO(text)))
    except Exception:
        data = None
    with _lock:
        _cache[key] = (now if data is not None else now - TTL + 60, data)
    return data


def load_public(rel: str):
    """A JSON file of the dashboard's public folder (e.g. boundaries/ke_admin1.geojson): the repository copy, or
    the published site's (SITE_URL). Cached as load()."""
    key = "public:" + rel
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    data = None
    try:
        path = PUBLIC / rel
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            with urllib.request.urlopen(os.environ.get("SITE_URL", SITE_URL).rstrip("/") + "/" + rel, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
    except Exception:
        data = None
    with _lock:
        _cache[key] = (now if data is not None else now - TTL + 60, data)
    return data
