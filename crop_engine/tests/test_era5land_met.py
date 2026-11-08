"""Radiation, humidity and wind (crop_engine.data.era5land.site_met) and their place in the weather Dataset, offline."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from crop_engine.data import era5land as E
from crop_engine.data.sites import Site
from crop_engine.data.weather import to_dataset, validate

A = Site("a", "A", -2.2105, 37.7190, "kenya")
B = Site("b", "B", -2.3871, 37.4851, "kenya")
B2 = Site("b2", "B2", -2.3873, 37.4850, "kenya")            # the same 0.1° cell as B


def _ms(d):
    return int(pd.Timestamp(d).value // 10**6)


def test_rows_are_matched_to_sites_by_cell_and_wind_is_the_mean_of_the_synoptic_hours():
    head = ["id", "longitude", "latitude", "time", "dewpoint_temperature_2m", "surface_solar_radiation_downwards_sum",
            "surface_pressure"]
    daily = [head, ["x", 37.7, -2.2, _ms("2020-01-01"), 293.15, 22e6, 90000.0],
             ["x", 37.5, -2.4, _ms("2020-01-01"), 283.15, 18e6, 85000.0]]
    wind = [["id", "longitude", "latitude", "time", "wind"]] + \
        [["w", 37.7, -2.2, _ms(f"2020-01-01 {h:02d}:00"), v] for h, v in ((0, 1.0), (6, 2.0), (12, 3.0), (18, 4.0))] + \
        [["w", 37.5, -2.4, _ms(f"2020-01-01 {h:02d}:00"), 5.0] for h in (0, 6, 12, 18)]
    f = E.rows_to_frames(daily, wind, [A, B, B2])
    a = f["a"].loc["2020-01-01"]
    assert a.rad_mj_m2 == pytest.approx(22.0) and a.dewpoint_c == pytest.approx(20.0)
    assert a.wind10_ms == pytest.approx(2.5) and a.sp_kpa == pytest.approx(90.0)
    assert f["b"].equals(f["b2"]) and f["b"].loc["2020-01-01"].rad_mj_m2 == pytest.approx(18.0)


def test_derived_vapour_pressure_and_2m_wind():
    raw = pd.DataFrame({"rad_mj_m2": [20.0], "dewpoint_c": [20.0], "wind10_ms": [2.0], "sp_kpa": [90.0]})
    d = E.derive(raw).iloc[0]
    assert d.vap_hpa == pytest.approx(23.38, abs=0.01)                  # FAO-56 Table 2.3: e°(20 °C) = 2.338 kPa
    assert d.wind2_ms == pytest.approx(1.496, abs=0.001)                # FAO-56 Eq. 47: × 0.748


def _fake(calls, last=None, fail=False):
    def fetch(sites, start, end):
        calls.append((tuple(s.id for s in sites), start, end))
        if fail:
            raise RuntimeError("Earth Engine unreachable")
        days = pd.date_range(start, min(end, last or end))
        return {s.id: pd.DataFrame({"rad_mj_m2": 20.0, "dewpoint_c": 15.0, "wind10_ms": 2.0, "sp_kpa": 90.0},
                                   index=days.rename("date")) for s in sites}
    return fetch


def test_cache_is_fetched_once_topped_up_and_kept_when_earth_engine_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "CACHE", tmp_path)
    monkeypatch.setattr(E, "FIRST", dt.date(2026, 1, 1))
    calls = []
    m = E.site_met([A], today=dt.date(2026, 3, 1), fetch=_fake(calls, last=dt.date(2026, 2, 24)))
    assert calls == [(("a",), dt.date(2026, 1, 1), dt.date(2026, 3, 1))]
    assert m["a"].index.max() == pd.Timestamp("2026-02-24") and E.met_path(A).exists()
    calls.clear()
    m = E.site_met([A], today=dt.date(2026, 3, 1), refresh=False, fetch=_fake(calls))
    assert calls == [] and len(m["a"]) == 55
    m = E.site_met([A], today=dt.date(2026, 3, 10), fetch=_fake(calls, last=dt.date(2026, 3, 5)))
    assert calls == [(("a",), dt.date(2026, 2, 17), dt.date(2026, 3, 10))]           # from 7 days before the last
    assert m["a"].index.max() == pd.Timestamp("2026-03-05") and m["a"].index.is_unique and len(m["a"]) == 64
    m = E.site_met([A], today=dt.date(2026, 3, 20), fetch=_fake(calls, fail=True))
    assert m["a"].index.max() == pd.Timestamp("2026-03-05")                         # the cache, as it was
    with pytest.raises(RuntimeError):
        E.site_met([B], today=dt.date(2026, 3, 20), fetch=_fake(calls, fail=True))    # nothing to fall back on


DATES = pd.date_range("2026-08-01", "2027-03-31")
SITE = Site("test_site", "Test site", -2.21, 37.72, "kenya", 0, 0, -2.125, 37.625)


def _ds(extra):
    T = len(DATES)
    rain = np.ones((2, 1, T), np.float32)
    t = lambda v: np.full((1, T), v, np.float32)
    z = np.zeros((1, T), np.int8)
    return to_dataset(rain, t(29), t(16), t(4.5), np.zeros(T, np.int8), z, z, DATES, [SITE],
                      {"forecast_source": "test", "season_year": 2026}, extra)


def _extra(rad=20.0):
    T = len(DATES)
    vals = {"rad_mj_m2": np.full((1, T), rad, np.float32), "vap_hpa": np.full((1, T), 18.0, np.float32),
            "wind2_ms": np.full((1, T), 1.8, np.float32)}
    src = np.zeros((1, T), np.int8)
    src[0, -60:] = 1                                                            # climatology after the last day
    return vals, src, np.array([950.0])


def test_dataset_carries_radiation_humidity_wind_with_their_source():
    ds = _ds(_extra())
    assert validate(ds) == []
    assert ds.rad_mj_m2.attrs["units"] == "MJ m-2 day-1" and float(ds.elev_m[0]) == 950.0
    assert int(ds.rad_source.sum()) == 60 and "Earth Engine" in ds.attrs["radiation"]


def test_dataset_without_them_is_valid_and_says_why():
    ds = _ds("not available: no Earth Engine")
    assert validate(ds) == [] and "rad_mj_m2" not in ds and ds.attrs["radiation"] == "not available: no Earth Engine"


def test_contract_catches_bad_or_incomplete_radiation():
    assert any("rad_mj_m2: values outside" in p for p in validate(_ds(_extra(rad=55.0))))
    assert any("incomplete" in p for p in validate(_ds(_extra()).drop_vars("wind2_ms")))
