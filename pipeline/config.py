"""
pipeline/config.py
──────────────────
Declarative Registry & Configuration for Multi-Country Seasonal Forecasting.
Defines country bounds, season windows, initialization months, model systems,
and staging/operational directory paths.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

@dataclass
class SeasonConfig:
    id: str
    label: str
    country: str
    init_month: int           # e.g. 9 for Sep 01, 2 for Feb 01
    init_day: int = 1
    lead_start_day: int = 30  # Lead day index where season starts (e.g. 30 for Oct 1)
    lead_end_day: int = 122   # Lead day index where season ends (e.g. 122 for Dec 31)
    target_period_label: str = "October–December"
    operational_model: str = "ECMWF SEAS5"
    operational_system: str = "51"
    raw_download_dir: Path = field(default_factory=Path)
    output_dir: Path = field(default_factory=Path)
    chirps_path: Path = field(default_factory=Path)
    mask_file: Path = field(default_factory=Path)
    mask_var: str = "mask"
    demo_npz_key: str = ""
    target_lats: tuple = (-4.875, 5.375, 0.25)
    target_lons: tuple = (33.625, 41.875, 0.25)
    bbox: tuple = (5.5, 33.5, -5.5, 42.5)  # [north, west, south, east]

# ──────────────────────────────────────────────────────────────────────────────
# Registry of Supported Country & Season Combinations
# ──────────────────────────────────────────────────────────────────────────────
SEASON_REGISTRY: Dict[str, SeasonConfig] = {
    # ── Kenya Short Rains (OND) ───────────────────────────────────────────────
    "kenya_short_rains": SeasonConfig(
        id="short_rains",
        label="Short Rains (OND: Oct–Dec)",
        country="kenya",
        init_month=9,
        init_day=1,
        lead_start_day=30,
        lead_end_day=122,
        target_period_label="October–December",
        operational_model="ECMWF SEAS5",
        operational_system="51",
        raw_download_dir=BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_sep",
        output_dir=BASE_DIR / "outputs" / "ecmwf_sep",
        chirps_path=BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc",
        mask_file=BASE_DIR / "outputs" / "masks" / "mask_kenya_ond.nc",
        mask_var="mask",
        demo_npz_key="ke_ecmwf_p_rf",
        target_lats=(-4.875, 5.375, 0.25),   # 42 lats
        target_lons=(33.625, 41.875, 0.25),  # 34 lons
        bbox=(5.5, 33.5, -5.5, 42.5),
    ),

    # ── Kenya Long Rains (MAM) ────────────────────────────────────────────────
    "kenya_long_rains": SeasonConfig(
        id="long_rains",
        label="Long Rains (MAM: Mar–May)",
        country="kenya",
        init_month=2,
        init_day=1,
        lead_start_day=28,
        lead_end_day=120,
        target_period_label="March–May",
        operational_model="ECMWF SEAS5",
        operational_system="51",
        raw_download_dir=BASE_DIR / "data" / "seasonal_pr_downloads_ke" / "ecmwf_feb",
        output_dir=BASE_DIR / "outputs" / "ecmwf_v3",
        chirps_path=BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc",
        mask_file=BASE_DIR / "outputs" / "masks" / "mask_kenya_mam.nc",
        mask_var="mask",
        demo_npz_key="ke_mam_ecmwf_p_rf",
        target_lats=(-4.875, 5.375, 0.25),
        target_lons=(33.625, 41.875, 0.25),
        bbox=(5.5, 33.5, -5.5, 42.5),
    ),

    # ── Ethiopia Deyr / Hagaya (OND) ──────────────────────────────────────────
    "ethiopia_deyr": SeasonConfig(
        id="deyr",
        label="Deyr / Hagaya (OND: Oct–Dec)",
        country="ethiopia",
        init_month=9,
        init_day=1,
        lead_start_day=30,
        lead_end_day=122,
        target_period_label="October–December",
        operational_model="ECMWF SEAS5",
        operational_system="51",
        raw_download_dir=BASE_DIR / "data" / "seasonal_pr_downloads_et_sep",
        output_dir=BASE_DIR / "outputs" / "ecmwf_bega",
        chirps_path=BASE_DIR / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc",
        mask_file=BASE_DIR / "outputs" / "masks" / "mask_deyr.nc",
        mask_var="mask_deyr",
        demo_npz_key="bega_ecmwf_p_rf",
        target_lats=(3.125, 14.875, 0.25),   # 48 lats
        target_lons=(33.125, 47.875, 0.25),  # 60 lons
        bbox=(15.5, 32.5, 3.0, 48.5),
    ),

    # ── Ethiopia Belg / FMAM ──────────────────────────────────────────────────
    "ethiopia_belg": SeasonConfig(
        id="belg",
        label="Belg Early Rains (FMAM: Feb–May)",
        country="ethiopia",
        init_month=2,
        init_day=1,
        lead_start_day=0,
        lead_end_day=120,
        target_period_label="February–May",
        operational_model="ECMWF SEAS5",
        operational_system="51",
        raw_download_dir=BASE_DIR / "data" / "seasonal_pr_downloads_et_feb",
        output_dir=BASE_DIR / "outputs" / "ecmwf_fmam",
        chirps_path=BASE_DIR / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc",
        mask_file=BASE_DIR / "outputs" / "masks" / "mask_belg.nc",
        mask_var="mask_belg",
        demo_npz_key="fmam_ecmwf_p_rf",
        target_lats=(3.125, 14.875, 0.25),
        target_lons=(33.125, 47.875, 0.25),
        bbox=(15.5, 32.5, 3.0, 48.5),
    ),

    # ── Ethiopia Kiremt (JJAS) ────────────────────────────────────────────────
    "ethiopia_kiremt": SeasonConfig(
        id="kiremt",
        label="Kiremt Main Rains (JJAS: Jun–Sep)",
        country="ethiopia",
        init_month=5,
        init_day=1,
        lead_start_day=31,
        lead_end_day=153,
        target_period_label="June–September",
        operational_model="ECMWF SEAS5",
        operational_system="51",
        raw_download_dir=BASE_DIR / "data" / "seasonal_pr_downloads_et_may",
        output_dir=BASE_DIR / "outputs" / "ecmwf_kiremt",
        chirps_path=BASE_DIR / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc",
        mask_file=BASE_DIR / "outputs" / "masks" / "mask_kiremt.nc",
        mask_var="mask_kiremt",
        demo_npz_key="kiremt_ecmwf_p_rf",
        target_lats=(3.125, 14.875, 0.25),
        target_lons=(33.125, 47.875, 0.25),
        bbox=(15.5, 32.5, 3.0, 48.5),
    ),
}

STAGING_DIR = BASE_DIR / "outputs" / "staging"
DEMO_NPZ_PATH = BASE_DIR / "backend" / "demo_data.npz"

def get_season_config(country: str, season: str) -> SeasonConfig:
    """Retrieve SeasonConfig by country and season name with fuzzy aliases."""
    c = country.strip().lower()
    s = season.strip().lower()
    if s in ("ond", "short_rains", "short"):
        key = f"{c}_short_rains" if c == "kenya" else f"{c}_deyr"
    elif s in ("mam", "long_rains", "long"):
        key = f"{c}_long_rains"
    elif s in ("belg", "fmam"):
        key = f"{c}_belg"
    elif s in ("kiremt", "jjas"):
        key = f"{c}_kiremt"
    else:
        key = f"{c}_{s}"

    if key in SEASON_REGISTRY:
        return SEASON_REGISTRY[key]
    raise KeyError(f"No configuration found for country='{country}', season='{season}'. Available: {list(SEASON_REGISTRY.keys())}")
