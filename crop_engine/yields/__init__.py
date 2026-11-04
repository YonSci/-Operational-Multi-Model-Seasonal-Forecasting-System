"""
Yield data for calibrating and validating the crop engine, kept as two separate databases so a field-scale model is
never calibrated against a county average or a modelled yield:

  observations   measured yields of plots and trials (CGIAR, published KALRO trials): calibration and site checks
  statistics     reported or estimated yields of areas (HarvestStat counties, FAOSTAT national, MapSPAM 2020 cells):
                 regional validation and plausibility only

Both are rebuilt from the downloads in data/Yield/ (not committed) by `python -m crop_engine.yields.build`, which
also links them to the monitored sites and compares the engine's observed-weather benchmark with them.

Yields are kg/ha as reported, with the grain moisture of the source (`moisture_pct`; an assumed value is flagged)
and a dry-matter yield (`grain_yield_dry_kg_ha`), which is what AquaCrop reports.
"""
import math
import re

from crop_engine.config import BASE, CACHE, OUT

YIELD_DATA = BASE / "data" / "Yield"                 # the downloads (not committed)
YIELD_CACHE = CACHE / "yields"                       # Kenya extracts of the large global files
YIELD_OUT = OUT / "yields"                           # the two databases, the comparisons and the report
PUBLISHED = BASE / "crop_engine" / "yields" / "published"   # yield tables transcribed from papers (committed)

# Source crop -> the engine's crop, and the engine varieties it can check
CROPS = {"maize": ["maize_early", "maize_medium"], "sorghum": ["sorghum"], "bean": ["bean"]}

# Grain moisture assumed when a source does not state it (%): IITA/CIMMYT maize trials report at 15 %; the others are
# the usual trade moisture of dry grain. Flagged as assumed in every row that uses it.
ASSUMED_MOISTURE = {"maize": 15.0, "sorghum": 12.5, "bean": 13.0}

NEAR_SITE_KM = 25.0                                  # an observation this close to a monitored site is "at" the site

OBS_COLUMNS = [
    "obs_id", "source", "study", "doi", "location", "latitude", "longitude", "coord_quality", "site_id", "site_km",
    "crop", "engine_variety", "maturity_class", "cultivar", "season", "year",
    "planting_date", "date_quality", "flowering_date", "maturity_date", "harvest_date",
    "days_to_flowering", "days_to_maturity",
    "grain_yield_kg_ha", "moisture_pct", "moisture_assumed", "grain_yield_dry_kg_ha", "harvest_index",
    "plant_density_m2", "n_kg_ha", "p_kg_ha", "irrigated", "irrigation_mm", "soil",
    "treatment", "replicate", "n_obs", "aggregation", "use", "quality_flag", "notes",
]

STAT_COLUMNS = [
    "source", "level", "country", "admin_1", "site_id", "crop", "season", "year", "harvest_year", "technology",
    "yield_kg_ha", "moisture_pct", "moisture_assumed", "yield_dry_kg_ha", "area_ha", "production_t",
    "qc_flag", "notes",
]


def season_of(month):
    """Kenya's rainy season of a planting month: LR (Long Rains, planted Feb–Jul) or SR (Short Rains, Aug–Jan)."""
    if month is None or (isinstance(month, float) and math.isnan(month)):
        return None
    return "LR" if 2 <= int(month) <= 7 else "SR"


def season_year(year, month):
    """The year a season is named by: its planting year, except a Short Rains crop sown in January (year before)."""
    known = month is not None and not (isinstance(month, float) and math.isnan(month))
    return int(year) - 1 if known and int(month) == 1 else int(year)


def dry(yield_kg_ha, moisture_pct):
    """Dry-matter grain yield from a yield reported at `moisture_pct` % moisture."""
    return yield_kg_ha * (1 - moisture_pct / 100.0)


def doi_of(study_source):
    """'doi_10.7910_DVN_GXUNAZ' -> '10.7910/DVN/GXUNAZ' (the soil-health dataset's Study_Source); None otherwise."""
    s = str(study_source)
    return s[4:].replace("_", "/") if re.match(r"doi_10\.\d+_", s) else None


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))
