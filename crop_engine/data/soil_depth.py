"""
Rootable soil depth per site or grid cell (crop_engine/data/soil_depth.yaml): where a restrictive layer (bedrock, a
hardpan) lies within the 2 m profile, the crop's roots stop there. Every engine applies it (soil.profile carries it):
AquaCrop's maximum rooting depth (Zmax; AquaCrop-OSPy stores but never uses its own z_res, so the limit is applied to
the crop as FAO AquaCrop does), DSSAT's root depth and WOFOST's soil rooting depth (RDMSOL).

The table holds, per site id (or grid cell id, "g-<lat>_<lon>"), depth_cm and its source:
  isda      iSDAsoil v1 depth to bedrock (30 m, Africa; Google Earth Engine ISDASOIL/Africa/v1/bedrock_depth, band
            mean_0_200), the median over the site's 0.25 deg cell at 250 m. iSDAsoil stops at 200 cm: 200 means 2 m or
            deeper, no restriction. In November 2026 every site and grid cell was 200: public data show no shallow soils
            here, which may be because the model rarely predicts them
  measured  a depth reported by the site (the partners' questionnaire): kept when the table is refetched
A depth of 199 cm or more is no restriction.

  python -m crop_engine.data.soil_depth --fetch              # the registered sites
  python -m crop_engine.data.soil_depth --fetch --grid       # and the regional grid's cells (outputs/crop_engine/grid)
"""
import argparse
import datetime as dt
import json
import math
from pathlib import Path

import yaml

DEPTH_FILE = Path(__file__).with_name("soil_depth.yaml")
EE_IMAGE, EE_BAND = "ISDASOIL/Africa/v1/bedrock_depth", "mean_0_200"
NO_LIMIT_CM = 199.0
CELL = 0.25


def _table(path=DEPTH_FILE):
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("sites") or {}


def restrictive_cm(site_id, path=DEPTH_FILE):
    """The rootable depth (cm) of a site or grid cell, or None when nothing restricts the roots within 2 m."""
    e = _table(path).get(site_id) or {}
    d = e.get("depth_cm")
    return float(d) if d is not None and float(d) < NO_LIMIT_CM else None


def restrictions(path=DEPTH_FILE):
    """The restrictions in effect, for the engines' configuration hashes: unchanged (empty) while no site is shallow,
    so recording iSDAsoil's 200 cm rebuilds nothing."""
    return sorted((k, float(e["depth_cm"])) for k, e in _table(path).items()
                  if e.get("depth_cm") is not None and float(e["depth_cm"]) < NO_LIMIT_CM)


def _cell(v):
    return math.floor(v / CELL) * CELL + CELL / 2


def fetch(targets, path=DEPTH_FILE, log=print):
    """iSDAsoil's depth for targets [(id, cell_lat, cell_lon)]; entries with another source (measured) are kept."""
    import sys
    from crop_engine.config import BASE
    sys.path.insert(0, str(BASE / "scripts"))
    import fao_era5land_gee as gee  # noqa: E402  (Earth Engine: imported only when fetching)
    ee = gee.init_ee()
    feats = [ee.Feature(ee.Geometry.Rectangle([lo - CELL / 2, la - CELL / 2, lo + CELL / 2, la + CELL / 2]), {"id": i})
             for i, la, lo in targets]
    img = ee.Image(EE_IMAGE).select(EE_BAND)
    got = img.reduceRegions(ee.FeatureCollection(feats), ee.Reducer.median(), 250).getInfo()["features"]
    old = _table(path)
    today = dt.date.today().isoformat()
    for f in got:
        i, v = f["properties"]["id"], f["properties"].get("median")
        if (old.get(i) or {}).get("source", "isda") != "isda" or v is None:
            continue
        old[i] = {"depth_cm": round(float(v)), "source": "isda", "fetched": today}
    head = [ln for ln in __doc__.strip().splitlines()]
    text = "# " + "\n# ".join(head) + "\n" + yaml.safe_dump({"sites": dict(sorted(old.items()))}, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    shallow = [k for k, e in old.items() if e.get("depth_cm") is not None and e["depth_cm"] < NO_LIMIT_CM]
    log(f"soil depth: {len(got)} fetched; {len(shallow)} shallower than 2 m{': ' + ', '.join(shallow) if shallow else ''}")
    return old


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--grid", action="store_true", help="also the regional grid's cells")
    a = ap.parse_args()
    if not a.fetch:
        print(json.dumps(restrictions()))
        return 0
    from crop_engine.data.sites import registered_sites
    targets = [(s.id, _cell(s.lat), _cell(s.lon)) for s in registered_sites()]
    if a.grid:
        from crop_engine.config import OUT
        runs = sorted((OUT / "grid").glob("seasonal_*.json"))
        if runs:
            for cid in json.loads(runs[-1].read_text(encoding="utf-8"))["members"]:
                la, lo = map(float, cid[1:].split("_"))
                targets.append((cid, la, lo))
    fetch(targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
