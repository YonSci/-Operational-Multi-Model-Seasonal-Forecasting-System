"""
Soil water on 1 Aug from the SMAP satellite mission, beside the ERA5-Land value the outlook starts from.

The outlook's soil water on 1 Aug (weather.Inputs.initial_water) is ERA5-Land's root-zone soil moisture through the
FAO water balance's bucket; establishment is very sensitive to it and no site measures it. SMAP Level 4 (NASA
SPL4SMGP, 9 km, from April 2015) assimilates SMAP's brightness temperatures into a land model: an independent estimate.
Its root-zone soil moisture (sm_rootzone, 0-100 cm, m3/m3), the mean of 29 Jul to 3 Aug, is turned into the same
measure as the outlook's: plant-available water as a fraction of the site's own available water over 0-100 cm,
(theta - theta_wp) / (theta_fc - theta_wp) with the site's SoilGrids layers, clipped to 0-1. SMAP's land model has
its own soil, so the two can differ by the soils as much as by the water; the comparison says how far apart they are.

  python -m crop_engine.data.smap --fetch            # 2015 to this season, every registered site (Earth Engine)
  python -m crop_engine.data.smap --compare          # ERA5-Land against SMAP, per site (log and verification file)

Used by the management scenario "soil_smap" (Soil water on 1 Aug from SMAP), when the season's values are on disk.
"""
import argparse
import datetime as dt
import json

import numpy as np

from crop_engine import config as C

CACHE_FILE = C.CACHE / "smap_rootzone_1aug.json"
COLLECTIONS = ("NASA/SMAP/SPL4SMGP/008", "NASA/SMAP/SPL4SMGP/007")
FIRST_YEAR = 2015
WINDOW = ("07-29", "08-04")                     # 29 Jul to 3 Aug (end exclusive)


def load(path=CACHE_FILE):
    """{site id: {year (str): volumetric root-zone soil moisture, m3/m3}}."""
    return json.loads(path.read_text(encoding="utf-8")).get("sites", {}) if path.exists() else {}


def available(year, path=CACHE_FILE):
    return any(str(year) in v for v in load(path).values())


def available_fraction(theta, layers, depth_cm=100.0):
    """Volumetric soil moisture over 0-depth_cm as a fraction of the layers' plant-available water there."""
    fc = wp = w = 0.0
    for L in layers:
        d = max(0.0, min(depth_cm, L.bottom_cm) - max(0.0, L.top_cm))
        fc, wp, w = fc + L.theta_fc * d, wp + L.theta_wp * d, w + d
    if w <= 0 or fc <= wp:
        return None
    fc, wp = fc / w, wp / w
    return float(np.clip((float(theta) - wp) / (fc - wp), 0.0, 1.0))


def initial_fraction(site_id, year, layers, path=CACHE_FILE):
    """SMAP's plant-available fraction on 1 Aug of `year` at the site, or None without a value."""
    v = (load(path).get(site_id) or {}).get(str(year))
    return None if v is None else available_fraction(v, layers)


def fetch(sites, years, path=CACHE_FILE, log=print):
    """Fetch SMAP L4 sm_rootzone (29 Jul to 3 Aug mean) at the sites' points for `years` (Earth Engine)."""
    import sys
    sys.path.insert(0, str(C.BASE / "scripts"))
    import fao_era5land_gee as gee  # noqa: E402  (Earth Engine: imported only when fetching)
    ee = gee.init_ee()
    col = None
    for cid in COLLECTIONS:
        try:
            c = ee.ImageCollection(cid)
            c.limit(1).size().getInfo()
            col = c
            break
        except Exception:                                           # an older or newer version on Earth Engine
            continue
    if col is None:
        raise RuntimeError("SMAP L4 is not available on Earth Engine")
    pts = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([s.lon, s.lat]), {"id": s.id}) for s in sites])
    out = load(path)
    for y in years:
        img = col.filterDate(f"{y}-{WINDOW[0]}", f"{y}-{WINDOW[1]}").select(["sm_rootzone"]).mean()
        for f in img.reduceRegions(pts, ee.Reducer.mean(), 9000).getInfo()["features"]:
            v = f["properties"].get("mean")
            if v is not None:
                out.setdefault(f["properties"]["id"], {})[str(y)] = round(float(v), 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": "NASA SMAP L4 (SPL4SMGP) sm_rootzone, 29 Jul to 3 Aug mean",
                                "fetched": dt.date.today().isoformat(), "sites": out}, indent=1), encoding="utf-8")
    log(f"SMAP: {len(sites)} sites, {len(years)} years -> {path}")
    return out


def compare(pairs):
    """pairs: {site: [(year, era5_fraction, smap_fraction)]} → per site: years, mean of each, mean difference
    (SMAP minus ERA5-Land) and their correlation across years."""
    out = {}
    for sid, rows in pairs.items():
        rows = [r for r in rows if r[1] is not None and r[2] is not None]
        if not rows:
            continue
        e, s = np.array([r[1] for r in rows]), np.array([r[2] for r in rows])
        out[sid] = {"years": [r[0] for r in rows], "era5land_mean": round(float(e.mean()), 3),
                    "smap_mean": round(float(s.mean()), 3), "mean_difference": round(float((s - e).mean()), 3),
                    "correlation": round(float(np.corrcoef(e, s)[0, 1]), 2) if len(rows) > 2 and e.std() > 0 and s.std() > 0 else None}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    from crop_engine.data.sites import registered_sites
    sites = registered_sites()
    year = dt.date.today().year if dt.date.today().month >= 8 else dt.date.today().year - 1
    if a.fetch:
        fetch(sites, range(FIRST_YEAR, year + 1))
    if a.compare:
        from crop_engine.data import soil as soil_mod
        from crop_engine.data.weather import Inputs
        inp = Inputs(refresh=False, with_met=False)
        layers = {s.id: soil_mod.profile(s) for s in inp.sites}
        pairs = {}
        for y in range(FIRST_YEAR, year + 1):
            try:
                frac = inp.initial_water(y)
            except Exception as e:                                      # a year without the ERA5-Land soil water
                print(f"{y}: no ERA5-Land soil water ({type(e).__name__})")
                continue
            for k, s in enumerate(inp.sites):
                pairs.setdefault(s.id, []).append((y, round(float(frac[k]), 3), initial_fraction(s.id, y, layers[s.id])))
        res = compare(pairs)
        dest = C.OUT / "verification" / "initial_water_smap.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(res, indent=1), encoding="utf-8")
        for sid, r in res.items():
            print(f"{sid:34s} ERA5-Land {r['era5land_mean']:.2f}  SMAP {r['smap_mean']:.2f}  difference "
                  f"{r['mean_difference']:+.2f}  correlation {r['correlation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
