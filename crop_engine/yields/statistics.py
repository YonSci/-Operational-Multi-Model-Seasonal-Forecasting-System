"""
Reported and estimated yields of areas, in one table (yields.STAT_COLUMNS), from:

  HarvestStat Africa v1.2   Kenya counties (admin 1) by season: Long Rains, Short Rains or annual, 1970–2024
  FAOSTAT QCL               Kenya national yield, harvested area and production, 1961–2024
  MapSPAM 2020 V2r2         IFPRI gridded yield (5 arc-min) over each monitored site's 0.25° cell, harvested-area
                            weighted, all / rainfed / irrigated technologies

These are area averages over all farmers' fields (and MapSPAM is itself disaggregated from such statistics), so they
validate aggregated or relative yields; they never calibrate a field-scale crop model.
"""
import zipfile

import numpy as np
import pandas as pd

from crop_engine.yields import ASSUMED_MOISTURE, STAT_COLUMNS, YIELD_CACHE, YIELD_DATA, dry

HVSTAT_CROPS = {"Maize": "maize", "Sorghum": "sorghum", "Beans (mixed)": "bean"}
HVSTAT_SEASONS = {"Long": "LR", "Short": "SR", "Annual": "annual"}
HVSTAT_QC = {0: None, 1: "outlier", 2: "low variance"}
FAO_CROPS = {"Maize (corn)": "maize", "Sorghum": "sorghum", "Beans, dry": "bean"}
FAO_YIELD_UNITS = {"kg/ha": 1.0, "hg/ha": 0.1, "100 g/ha": 0.1, "t/ha": 1000.0}
SPAM_CROPS = {"maiz": "maize", "sorg": "sorghum", "bean": "bean"}
SPAM_TECH = {"TA": "all", "TR": "rainfed", "TI": "irrigated"}
CELL = 0.25                                         # the platform's analysis grid (cell centres at .125 / .375 ...)


def _finish(df, source):
    df = df.copy()
    df["source"] = source
    df["moisture_pct"] = df["crop"].map(ASSUMED_MOISTURE)
    df["moisture_assumed"] = True
    df["yield_dry_kg_ha"] = dry(df["yield_kg_ha"], df["moisture_pct"]).round(1)
    for c in STAT_COLUMNS:
        if c not in df:
            df[c] = np.nan
    return df[STAT_COLUMNS]


def harveststat(root=YIELD_DATA):
    h = pd.read_csv(root / "HarvestStat_Africa" / "hvstat_africa_data_v1.2.csv")
    h = h[(h.country_code == "KE") & h["product"].isin(HVSTAT_CROPS)]
    df = pd.DataFrame(dict(
        level="admin1", country="Kenya", admin_1=h.admin_1, crop=h["product"].map(HVSTAT_CROPS),
        season=h.season_name.map(HVSTAT_SEASONS), year=h.planting_year, harvest_year=h.harvest_year,
        technology="all", yield_kg_ha=(h["yield"] * 1000).round(1), area_ha=h.area, production_t=h.production,
        qc_flag=h.qc_flag.map(HVSTAT_QC),
        notes="planted " + h.planting_month.astype(str) + "/" + h.planting_year.astype(str) +
              ", harvested " + h.harvest_month.astype(str) + "/" + h.harvest_year.astype(str)))
    return _finish(df, "HarvestStat Africa v1.2")


def faostat(root=YIELD_DATA):
    f = next((root / "FAOSTAT").glob("FAOSTAT_data_*.csv"))
    f = pd.read_csv(f, encoding="utf-8-sig", usecols=["Area", "Element", "Item", "Year", "Unit", "Value", "Flag Description"])
    f = f[(f.Area == "Kenya") & f.Item.isin(FAO_CROPS) & f.Element.isin(["Yield", "Area harvested", "Production"])]
    y = f[f.Element == "Yield"].copy()
    unknown = set(y.Unit) - set(FAO_YIELD_UNITS)
    if unknown:
        raise ValueError(f"FAOSTAT yield unit(s) not understood: {unknown}")
    y["yield_kg_ha"] = y.Value * y.Unit.map(FAO_YIELD_UNITS)
    key = ["Item", "Year"]
    area = f[f.Element == "Area harvested"].set_index(key).Value.rename("area_ha")
    prod = f[f.Element == "Production"].set_index(key).Value.rename("production_t")
    y = y.set_index(key).join(area).join(prod).reset_index()
    df = pd.DataFrame(dict(
        level="national", country="Kenya", crop=y.Item.map(FAO_CROPS), season="annual", year=y.Year,
        harvest_year=y.Year, technology="all", yield_kg_ha=y.yield_kg_ha.round(1), area_ha=y.area_ha,
        production_t=y.production_t, notes=y["Flag Description"]))
    return _finish(df[df.yield_kg_ha.notna()], "FAOSTAT QCL")


# ── MapSPAM 2020: a Kenya extract of the global CSVs, cached ───────────────
def mapspam_kenya(root=YIELD_DATA, log=print):
    """Kenya pixels of SPAM 2020 (yield kg/ha by technology, harvested area ha), cached in data/crop_engine/yields/."""
    out = YIELD_CACHE / "mapspam2020_kenya.csv"
    if out.exists():
        return pd.read_csv(out)
    d = root / "MAPSPAM-2020" / "Global_CSV"
    keep = ["x", "y", "ADM1_NAME", *SPAM_CROPS]
    parts = {}
    for var, techs in (("yield", SPAM_TECH), ("harvested_area", SPAM_TECH)):
        z = zipfile.ZipFile(d / f"spam2020V2r2_global_{var}.csv.zip")
        for t in techs:
            name = next(n for n in z.namelist() if n.endswith(f"_{t}.csv"))
            log(f"MapSPAM: reading {name} (Kenya rows)")
            with z.open(name) as fh:
                rows = [c[c.ADM0_NAME == "Kenya"][keep] for c in
                        pd.read_csv(fh, usecols=keep + ["ADM0_NAME"], chunksize=250_000)]
            v = pd.concat(rows).set_index(["x", "y", "ADM1_NAME"])
            parts[(var, t)] = v.rename(columns=lambda c: f"{c}_{'Y' if var == 'yield' else 'H'}_{t}")
    k = pd.concat(parts.values(), axis=1).reset_index()
    YIELD_CACHE.mkdir(parents=True, exist_ok=True)
    k.to_csv(out, index=False, float_format="%.2f")
    return k


def cell_of(lat, lon):
    """Centre of the 0.25° analysis-grid cell holding a point."""
    return (np.floor(lat / CELL) * CELL + CELL / 2, np.floor(lon / CELL) * CELL + CELL / 2)


def mapspam_sites(sites, root=YIELD_DATA, log=print):
    """Harvested-area-weighted SPAM yield over each site's 0.25° cell, per crop and technology."""
    k = mapspam_kenya(root, log)
    rows = []
    for s in sites:
        clat, clon = cell_of(s.lat, s.lon)
        box = k[(k.y.sub(clat).abs() < CELL / 2) & (k.x.sub(clon).abs() < CELL / 2)]
        for code, crop in SPAM_CROPS.items():
            for t, tech in SPAM_TECH.items():
                y, h = box[f"{code}_Y_{t}"], box[f"{code}_H_{t}"]
                w = h.where(y > 0, 0).sum()
                rows.append(dict(level="cell 0.25°", country="Kenya", admin_1=", ".join(sorted(box.ADM1_NAME.unique())),
                                 site_id=s.id, crop=crop, season="annual", year=2020, harvest_year=2020,
                                 technology=tech, yield_kg_ha=round(float((y * h).sum() / w), 1) if w > 0 else np.nan,
                                 area_ha=round(float(h.sum()), 1),
                                 notes=f"{len(box)} SPAM pixels in cell ({clat:.3f}, {clon:.3f}); circa 2020"))
    return _finish(pd.DataFrame(rows), "MapSPAM 2020 V2r2 (IFPRI)")


def site_counties(sites, root=YIELD_DATA):
    """The HarvestStat county (admin 1) of each site, by point in polygon."""
    import geopandas as gpd                          # here: only the build needs it
    from shapely.geometry import Point
    b = gpd.read_file(root / "HarvestStat_Africa" / "hvstat_africa_boundary_v1.2.gpkg")
    b = b[b.country_code == "KE"]
    out = {}
    for s in sites:
        hit = b[b.contains(Point(s.lon, s.lat))]
        out[s.id] = hit.admin_1.iloc[0] if len(hit) else None
    return out


def load_all(sites, root=YIELD_DATA, log=print):
    frames = []
    for key, fn in (("harveststat", lambda: harveststat(root)), ("faostat", lambda: faostat(root)),
                    ("mapspam", lambda: mapspam_sites(sites, root, log))):
        try:
            frames.append(fn())
            log(f"statistics: {key}: {len(frames[-1])} rows")
        except (FileNotFoundError, StopIteration) as e:
            log(f"statistics: {key}: skipped ({getattr(e, 'filename', None) or 'file not found'})")
    return pd.concat(frames, ignore_index=True)
