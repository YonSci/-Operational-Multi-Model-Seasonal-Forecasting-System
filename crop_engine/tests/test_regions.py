"""Forecast regions (scripts/regions.py): Kenya keeps every grid and path the input scripts always used; other
regions get their own grid and files."""
import numpy as np
import pytest

from crop_engine import config as C  # noqa: F401  (puts scripts/ on sys.path)
import regions

B = regions.BASE_DIR


def test_kenya_is_the_platform_grid_and_the_default(monkeypatch):
    monkeypatch.delenv(regions.ENV, raising=False)
    k = regions.get()
    assert k.key == "kenya"
    assert np.array_equal(k.lat, np.arange(-4.875, 5.4, 0.25)) and np.array_equal(k.lon, np.arange(33.625, 41.9, 0.25))
    assert (len(k.lat), len(k.lon)) == (42, 34) and k.bounds == (33.5, -5.0, 42.0, 5.5)


def test_kenya_paths_are_the_old_ones():
    k = regions.get("kenya")
    assert k.obs_run == B / "outputs" / "ecmwf_oct_obs_latest"
    assert k.fao_wb == B / "outputs" / "fao_wb"
    assert k.chirps_v3(2026) == B / "data" / "chirps_v3" / "chirps_v3_p25_kenya_2026.nc"
    assert k.soil == B / "data" / "soilgrids" / "soil_hydraulics_kenya_p25.nc"
    assert k.soil_raw == B / "data" / "soilgrids" / "raw"
    assert k.era5land == B / "data" / "era5land"
    assert k.seas5_rain == B / "data" / "seasonal_pr_downloads_ke" / "ecmwf_oct"
    assert k.chirps_hist == B / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
    assert k.chirps_prelim(2026) == B / "data" / "chirps_prelim_2026" / "chirps_prelim_2026_p25_kenya.nc"
    assert k.chirps_final(2026) == B / "data" / "chirps_2026" / "chirps-v2.0.2026.days_p25.nc"
    assert k.pet_clim == B / "data" / "worldclim" / "pet_mhargreaves_clim_kenya.nc"
    assert k.janfeb_cache == B / "outputs" / "ecmwf_oct" / "ECMWF_bc_daily_janfeb.nc"
    assert k.mask is None and regions.cell_mask(k) is None


def test_ethiopia_deyr_grid_covers_its_mask_and_has_its_own_files():
    e = regions.get("ethiopia_deyr")
    assert (len(e.lat), len(e.lon)) == (22, 50) and e.bounds == (35.25, 3.5, 47.75, 9.0)
    assert (e.lat * 8 % 2 == 1).all() and (e.lon * 8 % 2 == 1).all()          # x.125 / x.375 / ... (CHIRPS p25)
    assert e.obs_run == B / "outputs" / "ethiopia_deyr" / "ecmwf_oct_obs_latest"
    assert e.chirps_v3(2026).name == "chirps_v3_p25_ethiopia_deyr_2026.nc"
    assert e.seas5_rain == B / "data" / "seasonal_pr_downloads_et" / "ecmwf_oct"
    assert e.chirps_hist == B / "data" / "chirps_pr_et" / "et_chirps_pr_r25_1993_2025.nc"
    assert e.soil_raw.name == "raw_ethiopia_deyr" and e.era5land.name == "era5land_ethiopia_deyr"


def test_ethiopia_mask_keeps_every_cell_overlapping_the_deyr_polygon():
    pytest.importorskip("geopandas")
    e = regions.get("ethiopia_deyr")
    m = regions.cell_mask(e)
    assert m.shape == (22, 50) and 600 < m.sum() < 800
    assert m.any(axis=1).all() and m.any(axis=0).all()                  # the grid is no larger than the mask


def test_region_from_the_environment_and_unknown_names(monkeypatch):
    monkeypatch.setenv(regions.ENV, "ethiopia_deyr")
    assert regions.get().key == "ethiopia_deyr"
    assert regions.get("kenya").key == "kenya"                         # an explicit name wins
    with pytest.raises(ValueError):
        regions.get("atlantis")


def test_scripts_switch_their_paths_with_the_region(monkeypatch):
    monkeypatch.delenv(regions.ENV, raising=False)
    import fao_era5land_gee as g
    import fao_water_balance as fw
    import onset_rules as orl
    try:
        fw.use_region("ethiopia_deyr")
        assert fw.ET0_DIR == B / "outputs" / "ethiopia_deyr" / "fao_wb" / "et0" and fw.SOIL.name == "soil_hydraulics_ethiopia_deyr_p25.nc"
        orl.use_region("ethiopia_deyr")
        assert orl.RAW_OCT == B / "data" / "seasonal_pr_downloads_et" / "ecmwf_oct"
        assert orl.EXT_CACHE == B / "outputs" / "ethiopia_deyr" / "ecmwf_oct" / "ECMWF_bc_daily_janfeb.nc"
        assert g.set_grid("ethiopia_deyr")["dimensions"] == {"width": 250, "height": 110}
    finally:
        fw.use_region("kenya")
        orl.use_region("kenya")
    assert fw.ET0_DIR == B / "outputs" / "fao_wb" / "et0" and orl.PRELIM_2026.name == "chirps_prelim_2026_p25_kenya.nc"
    assert g.set_grid("kenya") == {"dimensions": {"width": 170, "height": 210}, "crsCode": "EPSG:4326",
                                   "affineTransform": {"scaleX": 0.05, "shearX": 0, "translateX": 33.5, "shearY": 0,
                                                       "scaleY": -0.05, "translateY": 5.5}}
