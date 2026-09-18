"""
export_regime_shapefiles.py
---------------------------
Exports standard ESRI Shapefiles (.shp, .shx, .dbf, .prj) and GeoJSON (.geojson)
for the Four Objective Climate Regimes of Ethiopia and Operational Seasonal Masks.

Coordinate Reference System: WGS 84 (EPSG:4326)

Outputs in outputs/shapefiles/:
  - ethiopia_climate_regimes (.shp, .geojson): All 4 Ethiopian Climate Regimes (Regimes 0, 1, 2, 3)
  - mask_kiremt_jjas (.shp, .geojson): National JJAS Monsoon Rainfall Domain (832 px)
  - mask_kiremt_onset (.shp, .geojson): Highlands Type-1 Bimodal Kiremt Onset Domain (416 px)
  - mask_belg_early_rains (.shp, .geojson): Highlands Type-1 Belg Early Rains Domain (416 px)
  - mask_gu_spring_rains (.shp, .geojson): Pastoral Lowlands Gu Spring Rains Domain (578 px)
  - mask_deyr_autumn_rains (.shp, .geojson): Pastoral Lowlands Deyr Autumn Rains Domain (578 px)
  - mask_western_annual (.shp, .geojson): Western Ethiopia Extended Annual Wet Season (426 px)
"""
import os
import json
import numpy as np
import xarray as xr
import shapefile  # pyshp
from shapely.geometry import box, shape, mapping
from shapely.ops import unary_union

WGS84_PRJ = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'

def mask_to_multipolygon(mask, lats, lons):
    """Converts a 2D boolean grid into a dissolved Shapely MultiPolygon."""
    boxes = []
    dlat = 0.25 / 2.0
    dlon = 0.25 / 2.0
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            if mask[i, j]:
                b = box(lon - dlon, lat - dlat, lon + dlon, lat + dlat)
                boxes.append(b)
    if not boxes:
        return None
    merged = unary_union(boxes)
    return merged

def write_shapefile_and_geojson(base_path, features_data):
    """
    Writes shapefile (.shp, .shx, .dbf, .prj) and GeoJSON using pyshp and Shapely.
    features_data: list of dicts with:
      - 'geometry': Shapely geometry
      - 'properties': dict of attribute values
    """
    shp_path = base_path + ".shp"
    geojson_path = base_path + ".geojson"
    prj_path = base_path + ".prj"

    # 1. Write Shapefile
    w = shapefile.Writer(base_path, shapeType=shapefile.POLYGON)
    
    # Fields definition from first record
    first_props = features_data[0]["properties"]
    field_names = list(first_props.keys())
    for f in field_names:
        val = first_props[f]
        if isinstance(val, int):
            w.field(f[:10], 'N', 10, 0)
        elif isinstance(val, float):
            w.field(f[:10], 'F', 12, 3)
        else:
            w.field(f[:10], 'C', 254)

    for item in features_data:
        geom = item["geometry"]
        props = item["properties"]
        if geom is None:
            continue
        
        # Convert shapely geometry to pyshp parts
        if geom.geom_type == "Polygon":
            exterior = list(geom.exterior.coords)
            holes = [list(h.coords) for h in geom.interiors]
            w.poly([exterior] + holes)
        elif geom.geom_type == "MultiPolygon":
            all_parts = []
            for poly in geom.geoms:
                all_parts.append(list(poly.exterior.coords))
                for h in poly.interiors:
                    all_parts.append(list(h.coords))
            w.poly(all_parts)
        else:
            continue
            
        w.record(*[props[f] for f in field_names])

    w.close()

    # Write PRJ
    with open(prj_path, "w", encoding="utf-8") as f:
        f.write(WGS84_PRJ)

    # 2. Write GeoJSON
    fc = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}
        },
        "features": []
    }
    for item in features_data:
        geom = item["geometry"]
        props = item["properties"]
        if geom is not None:
            fc["features"].append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": props
            })

    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    print(f"[EXPORTED] {shp_path} and {geojson_path}")

def main():
    out_dir = os.path.join("outputs", "shapefiles")
    os.makedirs(out_dir, exist_ok=True)

    # Load grid coordinates and masks
    chirps_path = "data/chirps_pr_et/et_chirps_pr_r25_1993_2025.nc"
    ds = xr.open_dataset(chirps_path)
    lats = ds["lat"].values
    lons = ds["lon"].values

    masks_path = os.path.join("outputs", "masks", "seasonal_masks.npz")
    m = np.load(masks_path)
    regime_map = m["regime_map"]
    mask_kiremt = m["mask_kiremt"]
    mask_belg = m["mask_belg"]
    mask_gu = m["mask_gu"]
    mask_deyr = m["mask_deyr"]
    mask_annual = m["mask_annual"]

    # Compute national JJAS rainfall mask (R1 + R2 minus peripheral QC filter = 832 px)
    # R1 (427 px) + R2 (416 px)
    p = ds["precip"]
    doy = p.time.dt.dayofyear.values
    mask_365 = doy <= 365
    doy_clean = doy[mask_365]
    p_clean = p.values[mask_365]
    q_clim = np.zeros((365, len(lats), len(lons)), dtype=np.float32)
    for d in range(1, 366):
        q_clim[d-1] = np.mean(p_clean[doy_clean == d], axis=0)
    p_ann  = np.sum(q_clim, axis=0)
    p_jjas = np.sum(q_clim[151:273], axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_jjas = np.where(p_ann > 10, p_jjas / p_ann, 0.0)

    # Land mask
    with open("frontend/public/boundaries/eth_admin0.geojson", "r", encoding="utf-8") as f:
        b_data = json.load(f)
    from shapely.geometry import Point
    poly_eth = shape(b_data["features"][0]["geometry"])
    lm = np.zeros((len(lats), len(lons)), dtype=bool)
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            lm[i, j] = poly_eth.contains(Point(lon, lat))

    # Mask JJAS 832 px
    mask_kiremt_jjas = (np.isin(regime_map, [1, 2])) & (p_jjas >= 120.0) & (r_jjas >= 0.20) & lm
    # Small objects cleanup
    import scipy.ndimage as ndi
    labeled, num_features = ndi.label(mask_kiremt_jjas)
    sizes = ndi.sum(mask_kiremt_jjas, labeled, range(num_features + 1))
    mask_kiremt_jjas[sizes[labeled] < 3] = False
    print(f"Mask JJAS active pixels: {np.sum(mask_kiremt_jjas)}")

    TOTAL_LAND_PX = 1485

    # 1. EXPORT FOUR CLIMATE REGIMES SHAPEFILE
    REGIME_INFO = [
        {
            "id": 1,
            "name": "Western Unimodal",
            "season": "Annual Wet Season (Feb/Mar to Oct/Nov)",
            "desc": "Single prolonged wet season; peak Jul-Aug. Core domain: Gambella, Assosa, Jimma, Bahir Dar, Gondar, Bedele.",
            "px": int(np.sum(regime_map == 1)),
        },
        {
            "id": 2,
            "name": "Bimodal Type 1 Highlands",
            "season": "Belg (FMAM) & Kiremt (JJAS)",
            "desc": "Central/Eastern Highlands. Early Belg rains, June pause, then major summer monsoon Kiremt.",
            "px": int(np.sum(regime_map == 2)),
        },
        {
            "id": 3,
            "name": "Bimodal Type 2 Pastoral Lowlands",
            "season": "Gu/Ganna (MAM) & Deyr/Hagaya (SON-OND)",
            "desc": "Southern & Southeastern Lowlands (Somali, Borana, Guji). Equatorial biannual; dry summer (JJAS).",
            "px": int(np.sum(regime_map == 3)),
        },
        {
            "id": 0,
            "name": "Arid / Marginal",
            "season": "Non-Seasonal Desert",
            "desc": "Danakil Depression and hyper-arid Afar lowlands. Insufficient seasonal rainfall for reliable onset/cessation.",
            "px": int(np.sum(regime_map == 0)),
        },
    ]

    regime_features = []
    for r in REGIME_INFO:
        mask_r = (regime_map == r["id"]) & lm
        geom = mask_to_multipolygon(mask_r, lats, lons)
        pct = float(round(r["px"] / TOTAL_LAND_PX * 100.0, 1))
        regime_features.append({
            "geometry": geom,
            "properties": {
                "regime_id": r["id"],
                "regime_nam": r["name"],
                "season_typ": r["season"],
                "pixel_cnt": r["px"],
                "land_pct": pct,
                "desc": r["desc"]
            }
        })

    write_shapefile_and_geojson(os.path.join(out_dir, "ethiopia_four_climate_regimes"), regime_features)

    # 2. INDIVIDUAL SEASONAL MASKS
    MASKS_TO_EXPORT = [
        ("mask_kiremt_jjas", mask_kiremt_jjas, "National JJAS Monsoon Rainfall Domain", "Regime 1 + Regime 2", "Jun-Sep"),
        ("mask_kiremt_onset", mask_kiremt, "Highlands Type-1 Kiremt Bimodal Onset Domain", "Regime 2 Highlands", "Jun-Sep"),
        ("mask_belg_early_rains", mask_belg, "Highlands Type-1 Belg Early Rains Domain", "Regime 2 Highlands", "Feb-May"),
        ("mask_gu_spring_rains", mask_gu, "Pastoral Lowlands Spring Rains (Gu/Ganna)", "Regime 3 Lowlands", "Mar-May"),
        ("mask_deyr_autumn_rains", mask_deyr, "Pastoral Lowlands Autumn Rains (Deyr/Hagaya)", "Regime 3 Lowlands", "Sep-Dec"),
        ("mask_western_annual", mask_annual, "Western Ethiopia Annual Extended Wet Season", "Regime 1 Western", "Mar-Nov"),
    ]

    for fname, mask_arr, title, reg_desc, win in MASKS_TO_EXPORT:
        px_cnt = int(np.sum(mask_arr))
        geom = mask_to_multipolygon(mask_arr, lats, lons)
        pct = float(round(px_cnt / TOTAL_LAND_PX * 100.0, 1))
        feat = [{
            "geometry": geom,
            "properties": {
                "mask_name": title,
                "target_reg": reg_desc,
                "window": win,
                "pixel_cnt": px_cnt,
                "land_pct": pct,
                "authority": "Dunning (2016) / EMI Climatology"
            }
        }]
        write_shapefile_and_geojson(os.path.join(out_dir, fname), feat)

    # 3. Create README.md in outputs/shapefiles/
    readme_content = f"""# Ethiopia Climate Regimes and Seasonal Masks GIS Shapefiles
**Generated by the Operational Seasonal Climate Forecast System**
**Methodology: Dunning Harmonic Baseline with Ethiopia-Specific Climatological Regime Refinement (EMI Climatology)**

---

## Coordinate Reference System (CRS)
- **EPSG**: 4326 (WGS 84 geographic 2D)
- **Datum**: WGS 1984
- **Units**: Decimal Degrees
- **Grid Resolution**: 0.25° (~28 km native CHIRPS cell dimension)

---

## Available Files

| Shapefile (.shp/.shx/.dbf/.prj) | GeoJSON (.geojson) | Description | Target Regime | Pixel Count | Active Land % |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **`ethiopia_four_climate_regimes`** | `ethiopia_four_climate_regimes.geojson` | All Four Objective Climate Regimes | Regimes 0, 1, 2, 3 | 1,485 px | 100.0% |
| **`mask_kiremt_jjas`** | `mask_kiremt_jjas.geojson` | National JJAS Summer Monsoon Rainfall Domain | Regime 1 + Regime 2 | 832 px | 56.0% |
| **`mask_kiremt_onset`** | `mask_kiremt_onset.geojson` | Highlands Type-1 Kiremt Bimodal Onset Domain | Regime 2 Highlands | 416 px | 28.0% |
| **`mask_belg_early_rains`** | `mask_belg_early_rains.geojson` | Highlands Type-1 Belg Early Rains Domain | Regime 2 Highlands | 416 px | 28.0% |
| **`mask_gu_spring_rains`** | `mask_gu_spring_rains.geojson` | Pastoral Lowlands Spring Rains (Gu/Ganna) | Regime 3 Lowlands | 578 px | 38.9% |
| **`mask_deyr_autumn_rains`** | `mask_deyr_autumn_rains.geojson` | Pastoral Lowlands Autumn Rains (Deyr/Hagaya)| Regime 3 Lowlands | 578 px | 38.9% |
| **`mask_western_annual`** | `mask_western_annual.geojson` | Western Ethiopia Extended Annual Wet Season | Regime 1 Western | 426 px | 28.7% |

---

## Attribute Schema for `ethiopia_four_climate_regimes`
- **`regime_id`** (Integer): Numeric regime identifier (1: Unimodal, 2: Bimodal Highlands, 3: Bimodal Pastoral, 0: Arid/Marginal).
- **`regime_nam`** (String): Full scientific name.
- **`season_typ`** (String): Active onset/cessation rainy seasons.
- **`pixel_cnt`** (Integer): Sovereign 0.25° land pixel population.
- **`land_pct`** (Float): Percentage of Ethiopia's total sovereign land surface (1,485 pixels).
- **`desc`** (String): Agro-ecological and meteorological description.

---

## How to Load in GIS Software
### QGIS
1. Open QGIS.
2. Select **Layer -> Add Layer -> Add Vector Layer...**
3. Browse to `outputs/shapefiles/` and select any `.shp` or `.geojson` file.
4. Style by `regime_id` or `mask_name` using categorical symbology.

### ArcGIS / ArcGIS Pro
1. In Catalog pane, navigate to `outputs/shapefiles/`.
2. Drag and drop any `.shp` file into the Map View.

### Python (GeoPandas)
```python
import geopandas as gpd
gdf = gpd.read_file("outputs/shapefiles/ethiopia_four_climate_regimes.shp")
gdf.plot(column="regime_nam", legend=True)
```
"""
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"[SUCCESS] Exported all shapefiles and README to {out_dir}")

if __name__ == "__main__":
    main()
