"""Unit tests of the crop engine on synthetic data (no forecast pipeline needed): python -m pytest crop_engine/tests"""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from crop_engine import config as C
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.data import era5land, soil
from crop_engine.data.sites import Site, on_grid, registered_sites, slug
from crop_engine.data.weather import to_dataset, validate
from crop_engine.scenarios.planting import doy_to_date

DATES = pd.date_range("2026-08-01", "2027-03-31")
SITE = Site("test_site", "Test site", -2.21, 37.72, "kenya", 0, 0, -2.125, 37.625)
LAYERS = [soil.Layer(t, b, 60, 22, 1.2, 5, 0.22, 0.12) for t, b in ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))]
VARIETY = {"label": "Early-maturing maize", "aquacrop_crop": "MaizeGDD", "maturity_days": 90, "failure_t_ha": 0.5}


def weather(n_mem=2, wet=True):
    rng = np.random.default_rng(1)
    rain = rng.gamma(0.4, 14, (n_mem, 1, len(DATES))).astype(np.float32)
    rain[..., ~DATES.month.isin([10, 11, 12])] = 0
    if not wet:
        rain[:] = 0
    T = len(DATES)
    tmax, tmin, et0 = np.full((1, T), 29.0, np.float32), np.full((1, T), 16.0, np.float32), np.full((1, T), 4.5, np.float32)
    src = np.zeros(T, np.int8)
    met = np.zeros((1, T), np.int8)
    return to_dataset(rain, tmax, tmin, et0, src, met, met, DATES, [SITE], {"forecast_source": "test", "season_year": 2026})


# ── weather contract ────────────────────────────────────────────────────────
def test_valid_dataset_passes():
    assert validate(weather()) == []


def test_contract_catches_problems():
    ds = weather()
    ds["precip_mm"].values[0, 0, 5] = np.nan
    ds["tmin_c"].values[0, 10] = 40.0
    p = validate(ds)
    assert any("precip_mm" in x for x in p) and any("tmin above tmax" in x for x in p)
    ds2 = weather().drop_vars("et0_mm")
    assert "missing et0_mm" in validate(ds2)


def test_provenance_attrs():
    ds = weather()
    assert json.loads(ds.attrs["precip_sources"]) == C.PRECIP_SOURCES
    assert ds.precip_mm.attrs["units"] == "mm/day"


# ── varieties ───────────────────────────────────────────────────────────────
def test_variety_scaling_hits_maturity_days():
    kw, f = aq.crop_parameters(VARIETY, 23.0)
    g = aq.gdd(np.full(200, 29.0), np.full(200, 17.0), 8.0, 30.0)       # mean 23 °C
    days = int(np.argmax(np.cumsum(g) > kw["Maturity"])) + 1
    assert abs(days - 90) <= 1
    from aquacrop.entities.crop import crop_params
    p = crop_params["MaizeGDD"]
    assert kw["CGC"] == pytest.approx(p["CGC"] / f) and kw["Flowering"] == pytest.approx(p["Flowering"] * f)


# ── planting dates ──────────────────────────────────────────────────────────
def test_doy_to_date():
    assert doy_to_date(227, 2026) == dt.date(2026, 8, 15)
    assert doy_to_date(366, 2026) == dt.date(2027, 1, 1)
    assert doy_to_date(np.nan, 2026) is None and doy_to_date(500, 2026) is None
    assert doy_to_date(244, 1996) == dt.date(1996, 9, 1)                  # no-leap DOY numbering from 1 Aug


# ── sites and soil ──────────────────────────────────────────────────────────
def test_registered_sites():
    s = registered_sites()
    assert len(s) >= 6 and all(x.country == "kenya" for x in s)
    assert slug("KALRO Kiboko, Makueni Farm") == "kalro_kiboko_makueni_farm"
    g = on_grid(s[:1], np.array([-2.375, -2.125]), np.array([37.375, 37.625]))[0]
    assert (g.cell_lat, g.cell_lon) == (-2.375, 37.375)


def test_soil_check():
    soil.check(LAYERS)
    assert soil.taw_mm(LAYERS) == pytest.approx(100.0)
    bad = [soil.Layer(0, 5, 60, 50, 1, 0, 0.2, 0.1)] + LAYERS[1:]
    with pytest.raises(ValueError):
        soil.check(bad)


@pytest.mark.skipif(not soil.SOIL_FILE.exists(), reason="no SoilGrids file")
def test_site_profile_from_file():
    s = on_grid(registered_sites()[:1], np.arange(-4.875, 5.4, 0.25), np.arange(33.625, 41.9, 0.25))[0]
    L = soil.profile(s)
    assert [x.bottom_cm for x in L] == [5, 15, 30, 60, 100, 200] and 30 < soil.taw_mm(L) < 250


def test_climatology_is_smooth_and_complete():
    idx = pd.date_range("1993-01-01", "2016-12-31")
    s = pd.Series(20 + 5 * np.sin(2 * np.pi * idx.dayofyear / 365), index=idx)
    c = era5land.climatology(s)
    assert len(c) == 366 and np.isfinite(c).all() and np.abs(np.diff(c[:365])).max() < 0.2


# ── AquaCrop ────────────────────────────────────────────────────────────────
def _task(ds, planting):
    kw, _ = aq.crop_parameters(VARIETY, 23.0)
    return dict(dates=ds.time.values, rain=ds.precip_mm.values[:, 0], tmax=ds.tmax_c.values[0], tmin=ds.tmin_c.values[0],
                et0=ds.et0_mm.values[0], source=ds.precip_source.values, planting=planting, variety=VARIETY, kw=kw,
                layers=LAYERS, initial_frac=0.3)


def test_aquacrop_wet_beats_dry_and_statuses():
    wet = aq.simulate(_task(weather(1, True), [dt.date(2026, 10, 20)]))[0]
    dry = aq.simulate(_task(weather(1, False), [dt.date(2026, 10, 20)]))[0]
    assert wet["status"] in ("ok", "died") and wet["yield_t_ha"] > dry["yield_t_ha"]
    assert wet["stress_days"] < dry["stress_days"] or dry["status"] in ("died", "failed_establishment")
    late, none = aq.simulate(_task(weather(2, True), [dt.date(2027, 3, 1), None]))
    assert late["status"] == "too_late" and none["status"] == "not_sown" and none["yield_t_ha"] == 0.0
