"""Product identity shared by the bulletins and the dashboard: name, version, date format and method names."""
import datetime as _dt
import json as _json
import re as _re
from pathlib import Path as _Path

PLATFORM = "Seasonal Climate Forecast Dashboard"


def platform_version():
    """The dashboard's version (frontend/package.json), or None when the frontend is not alongside the backend."""
    try:
        pkg = _Path(__file__).resolve().parent.parent / "frontend" / "package.json"
        return _json.loads(pkg.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def platform_label():
    v = platform_version()
    return f"{PLATFORM} v{v}" if v else PLATFORM


def fmt_date(d):
    """'31 Oct 2026', the date format used across the dashboard (accepts a date or an ISO string)."""
    if isinstance(d, str):
        d = _dt.date.fromisoformat(d[:10])
    return f"{d.day} {d.strftime('%b')} {d.year}"


def method_label(onset_definition):
    """Method name as the dashboard's Method selector shows it."""
    od = onset_definition or {}
    if od.get("method") == "icpac":
        return f"Agri rule {od.get('rule', '')}".strip()
    if od.get("method") == "fao":
        return f"FAO water balance ({od.get('definition', 'agricultural')})"
    return "Dunning (rainfall pattern)"


def split_run_label(init_label):
    """'01 October 2026 + obs to 2026-10-25' -> ('1 Oct 2026', '25 Oct 2026'); no observations -> (date, None)."""
    m = _re.search(r"obs to (\d{4}-\d{2}-\d{2})", init_label or "")
    start = (init_label or "").split(" + ")[0].strip()
    try:
        start = fmt_date(_dt.datetime.strptime(start, "%d %B %Y").date())
    except ValueError:
        pass
    return start, (fmt_date(m.group(1)) if m else None)
