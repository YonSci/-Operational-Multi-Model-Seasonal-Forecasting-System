"""Unit tests of the yield databases on small synthetic tables (no downloads needed): python -m pytest crop_engine/tests"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from crop_engine.data.sites import Site
from crop_engine.yields import OBS_COLUMNS, doi_of, dry, haversine_km, season_of, season_year
from crop_engine.yields import build, observations, statistics

KIBOKO = Site("kalro_kiboko_makueni_farm", "KALRO Kiboko, Makueni Farm", -2.21046, 37.719, "kenya")
TANA = Site("genco_ltd_tana_river_farm", "Genco LTD Tana River Farm", -2.21314, 40.0517, "kenya")


def test_seasons():
    assert [season_of(m) for m in (3, 4, 7, 9, 10, 11, 1)] == ["LR", "LR", "LR", "SR", "SR", "SR", "SR"]
    assert season_of(None) is None and season_of(float("nan")) is None
    assert season_year(2021, 1) == 2020 and season_year(2020, 10) == 2020 and season_year(2020, float("nan")) == 2020


def test_units_and_identifiers():
    assert dry(2000.0, 12.5) == pytest.approx(1750.0)
    assert doi_of("doi_10.7910_DVN_GXUNAZ") == "10.7910/DVN/GXUNAZ"
    assert doi_of("doi_10.5061_dryad.fg15tg2") == "10.5061/dryad.fg15tg2"
    assert doi_of("INM_siaya") is None
    assert haversine_km(0, 37, 1, 37) == pytest.approx(111.2, abs=0.2)


def test_date_parsing():
    assert observations._parse_date("20/09/2011") == (dt.date(2011, 9, 20), "day")
    assert observations._parse_date("2014-08") == (dt.date(2014, 8, 1), "month")
    assert observations._parse_date("2015") == (None, "year only")
    assert observations._parse_date("31/02/2015") == (None, "unparsed")
    assert observations._parse_date("nan") == (None, None)


def test_iita_maturity_class():
    assert observations._iita_maturity("INTERNATIONAL MAIZE TRIAL - RUVT EXTRA-EARLY") == ("extra-early", "maize_early")
    assert observations._iita_maturity("INTERNATIONAL MAIZE TRIAL - RUVT EARLY") == ("early", "maize_early")
    assert observations._iita_maturity("Evt-Lsr-W (Late-Maturing, White-Grain Varieties)") == ("late", "maize_medium")
    assert observations._iita_maturity("Evt-Msr (White)") == (None, None)


def test_published_table_is_complete():
    p = observations.published()
    assert list(p.columns) == OBS_COLUMNS
    assert len(p) == 28 and p.obs_id.is_unique
    kib = p[p.location == "KALRO Kiboko"]
    # sum of the 14 transcribed Kiboko yields (28.65 t/ha); the paper's "Mean" row (2.1) is not the column mean
    assert kib.grain_yield_kg_ha.sum() == pytest.approx(28650)
    assert np.allclose(p.grain_yield_dry_kg_ha, p.grain_yield_kg_ha * 0.875, atol=0.05)   # at 12.5 % moisture
    assert not p.moisture_assumed.any()


def test_link_sites():
    obs = pd.DataFrame(dict(latitude=[-2.22, -2.27, 0.1, np.nan], longitude=[37.70, 37.65, 34.4, np.nan]))
    out = build.link_sites(obs, [KIBOKO, TANA])
    assert list(out.site_id[:2]) == [KIBOKO.id, KIBOKO.id]                     # western Kenya is far from both
    assert pd.isna(out.site_id.iloc[2])
    assert out.site_km[0] < 3 and out.site_km[1] < 11 and np.isnan(out.site_km[3])


def test_cell_of_matches_the_grid():
    assert statistics.cell_of(KIBOKO.lat, KIBOKO.lon) == (-2.125, 37.625)
    assert statistics.cell_of(0.2074, 36.9038) == (0.125, 36.875)


def test_compare_county():
    years = np.arange(2000, 2012)
    signal = np.sin(years)
    bench = pd.DataFrame(dict(site_id=KIBOKO.id, engine_variety="maize_early", rule="rule1", year=years,
                              planting="", harvest="", model_t_ha=3 + signal, status="ok"))
    bench.loc[0, "status"] = "not_sown"
    stats = pd.DataFrame(dict(source="HarvestStat Africa v1.2", season="SR", admin_1="Makueni", crop="maize",
                              year=years, yield_dry_kg_ha=600 + 100 * signal))
    c = build.compare_county(bench, stats, {KIBOKO.id: "Makueni"}).iloc[0]
    assert c.overlap_years == 11 and c.not_sown_in_overlap == 1                 # the unsown season is left out
    assert c.r_detrended > 0.95 and c.model_over_county == pytest.approx(5.0, abs=0.3)
