#!/usr/bin/env python3
"""
build_tracker_page.py
─────────────────────
Build the platform's "Short Rains Tracker" page (frontend/public/tracker/) from the shared page source
frontend/tracker/page.html — the same page as the online dashboard — plus a local `dash` stand-in
(frontend/tracker/dash-shim.js), theme tokens (theme.css), d3 (vendor/) and the latest data files
from outputs/dashboard/ (export_dashboard_data.py).

The React app shows it in the "Short Rains Tracker" tab (iframe → tracker/index.html).
"""
import json
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "frontend" / "tracker"
DST = BASE / "frontend" / "public" / "tracker"
DATA = BASE / "outputs" / "dashboard"

# dataset id → file in outputs/dashboard (the local platform uses the site table with coordinates)
DATASETS = {
    "sites": "sites.csv", "seasonal": "seasonal.csv", "ens_daily": "ens_daily.csv", "rain_daily": "rain_daily.csv",
    "zone": "zone.csv", "verification": "verification.csv", "grid": "grid.csv", "inits": "inits.csv",
    "anim": "anim.csv", "boundaries": "boundaries.json", "stations": "stations.csv",
    "forecast": "forecast.csv", "forecast_sites": "forecast_sites.csv", "forecast_events": "forecast_events.csv",
}


def main():
    (DST / "data").mkdir(parents=True, exist_ok=True)
    present = {}
    for ds_id, name in DATASETS.items():
        f = DATA / name
        if f.exists():
            shutil.copy2(f, DST / "data" / name)
            present[ds_id] = f"data/{name}"
    for name in ("dash-shim.js", "theme.css"):
        shutil.copy2(SRC / name, DST / name)
    page = (SRC / "page.html").read_text(encoding="utf-8")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kenya Short Rains 2026 Tracker</title>
<link rel="stylesheet" href="theme.css">
</head>
<body>
<script src="vendor/d3.v7.min.js"></script>
<script>window.TRACKER_DATASETS = {json.dumps(present)}; window.TRACKER_PARAMS = {{"site": "Kapiti Research Station Farm"}};</script>
<script src="dash-shim.js"></script>
<div id="dash-root">
{page}
</div>
</body>
</html>
"""
    (DST / "index.html").write_text(html, encoding="utf-8")
    missing = sorted(set(DATASETS) - set(present))
    print(f"wrote {DST / 'index.html'} with {len(present)} datasets" + (f"; missing: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()
