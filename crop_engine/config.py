"""Paths, periods and scenario choices shared by the crop engine."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CACHE = BASE / "data" / "crop_engine"            # downloaded site series (not committed)
OUT = BASE / "outputs" / "crop_engine"           # weather inputs and results (not committed)
WEATHER_OUT = OUT / "weather"
RESULTS_OUT = OUT / "results"
VARIETIES_FILE = Path(__file__).with_name("varieties.yaml")

CAL_YEARS = (1993, 2016)                         # the platform's calibration years: terciles of the benchmark
HIST_YEARS = (1993, 2025)                        # seasons with observed weather for the benchmark (season y: Aug y – Mar y+1)

# Planting rules: the platform's onset methods (forecast_runs.Methods keys) used as sowing dates
PLANTING_RULES = {
    "rule1": dict(method="1", label="Agri rule 1 onset"),
    "fao-agricultural": dict(method="fao-agricultural", label="FAO agricultural onset"),
}

# Per-day source of the rainfall (precip_source) and of temperature / ET0 (met_source)
PRECIP_SOURCES = ["obs_final", "obs_prelim", "gap", "forecast", "seasonal", "climatology"]
MET_SOURCES = ["era5land", "climatology"]

# AquaCrop soil compartments: 2 m, finer near the surface (SoilGrids layers reach 200 cm)
SOIL_DZ = [0.1] * 12 + [0.2] * 4

# Water-stress day: transpiration below this fraction of its potential on a day with potential >= 0.5 mm
STRESS_RATIO = 0.5
