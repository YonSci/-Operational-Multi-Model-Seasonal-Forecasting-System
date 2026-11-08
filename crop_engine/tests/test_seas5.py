"""SEAS5 temperature and March rain for the crop weather (crop_engine.data.seas5), on synthetic files."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from crop_engine import config as C
from crop_engine.data import seas5 as s5

LATS, LONS = np.array([-2.0, -1.0]), np.array([37.0, 38.0])
SITES = ["a", "b"]


def _file(path, year, warm=0.0, members=3):
    rng = np.random.default_rng(year)
    n = s5.LEAD_DAYS
    shape = (members, 1, n, len(LATS), len(LONS))
    tmax = np.full(shape, 300.15 + warm) + rng.normal(0, 0.5, shape)          # 27 °C (+ warm)
    tmin = np.full(shape, 290.15 + warm) + rng.normal(0, 0.5, shape)          # 17 °C
    rain = rng.gamma(0.5, 6.0, shape) / 1000.0                                 # m/day
    dims = ("number", "forecast_reference_time", "forecast_period", "latitude", "longitude")
    xr.Dataset({"mx2t24": (dims, tmax), "mn2t24": (dims, tmin), "tp": (dims, np.cumsum(rain, axis=2))},
               coords={"number": np.arange(members), "forecast_reference_time": [pd.Timestamp(year, 10, 1)],
                       "forecast_period": np.arange(1, n + 1), "latitude": LATS, "longitude": LONS}).to_netcdf(path)


def test_temperature_bias_is_removed_and_the_anomaly_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(s5, "DIR", tmp_path)
    monkeypatch.setattr(C, "CAL_YEARS", (2001, 2005))
    monkeypatch.setattr(s5, "MIN_CAL_YEARS", 3)
    for y in range(2001, 2004):                                                # 3 of the 5 calibration years
        _file(s5.path(y), y)
    assert "missing" in s5.missing(2026)
    _file(s5.path(2026), 2026, warm=1.0)                                       # the run: 1 °C warmer than its hindcasts
    assert s5.missing(2026) is None and s5.calibration_years() == [2001, 2002, 2003]
    monkeypatch.setattr(s5, "MIN_CAL_YEARS", 4)
    assert "3 of the calibration years" in s5.missing(2026)
    monkeypatch.setattr(s5, "MIN_CAL_YEARS", 3)
    idx = pd.date_range("1993-01-01", "2027-06-30")
    temps = {s: pd.DataFrame({"tmax": 25.0, "tmin": 15.0}, index=idx) for s in SITES}   # ERA5-Land: 2 °C cooler
    rng = np.random.default_rng(0)
    hist = pd.DataFrame(rng.gamma(0.5, 4.0, (len(idx), 2)), index=idx, columns=SITES)
    s = s5.Seas5(2026, SITES, LATS, LONS, temps, hist)
    assert s.tmax.shape == (3, s5.LEAD_DAYS, 2) and s.dates[0] == pd.Timestamp("2026-10-01")
    assert s.dates[-1] == pd.Timestamp("2027-03-31")
    assert abs(float(s.tmax.mean()) - 26.0) < 0.1 and abs(float(s.tmin.mean()) - 16.0) < 0.1
    assert (s.tmin <= s.tmax).all()
    assert s.march.shape == (3, 31, 2) and (s.march >= 0).all() and len(s.march_dates) == 31
    assert (s.on(pd.DatetimeIndex(["2026-09-30", "2026-10-01", "2027-03-31"])) == [-1, 0, 181]).all()
    assert "3 of the 5 calibration years" in s5.describe(s)


def test_hargreaves_ratio():
    assert s5.hargreaves_ratio(30.0, 16.0, 30.0, 16.0) == 1.0
    assert s5.hargreaves_ratio(32.0, 17.0, 30.0, 16.0) > 1.0                   # warmer, wider range: more ET0
    assert s5.hargreaves_ratio(40.0, 5.0, 30.0, 25.0) == 1.3                   # clipped


def test_a_past_run_leaves_its_own_year_out_of_the_correction(tmp_path, monkeypatch):
    monkeypatch.setattr(s5, "DIR", tmp_path)
    monkeypatch.setattr(C, "CAL_YEARS", (2001, 2004))
    monkeypatch.setattr(s5, "MIN_CAL_YEARS", 3)
    for y, warm in ((2001, 0.0), (2002, 0.0), (2003, 0.0), (2004, 3.0)):         # 2004: a 3 °C warmer season
        _file(s5.path(y), y, warm=warm)
    idx = pd.date_range("2000-01-01", "2005-06-30")
    temps = {s: pd.DataFrame({"tmax": 27.0, "tmin": 17.0}, index=idx) for s in SITES}   # SEAS5 unbiased
    hist = pd.DataFrame(1.0, index=idx, columns=SITES)
    out = s5.Seas5(2004, SITES, LATS, LONS, temps, hist, exclude=2004)
    assert out.cal_years == [2001, 2002, 2003]
    assert abs(float(out.tmax.mean()) - 30.0) < 0.15                             # the warm anomaly is kept
    inn = s5.Seas5(2004, SITES, LATS, LONS, temps, hist)                          # in-sample: part of it removed
    assert float(inn.tmax.mean()) < float(out.tmax.mean()) - 0.5
    monkeypatch.setattr(s5, "MIN_CAL_YEARS", 4)
    with pytest.raises(ValueError):
        s5.Seas5(2004, SITES, LATS, LONS, temps, hist, exclude=2004)


def _met_file(path, year, scale=1.0, members=3):
    rng = np.random.default_rng(year + 7)
    n = s5.LEAD_DAYS
    shape = (members, 1, n, len(LATS), len(LONS))
    rad = np.full(shape, 25e6 * scale) * rng.uniform(0.9, 1.1, shape)             # J m-2 day-1: SEAS5 25 MJ
    d2m = np.full(shape, 288.15) + rng.normal(0, 0.3, shape)                        # 15 °C dewpoint
    u10 = np.full(shape, 3.0) + rng.normal(0, 0.2, shape)
    dims = ("number", "forecast_reference_time", "forecast_period", "latitude", "longitude")
    xr.Dataset({"ssrd": (dims, np.cumsum(rad, axis=2)), "d2m": (dims, d2m), "u10": (dims, u10), "v10": (dims, 0 * u10)},
               coords={"number": np.arange(members), "forecast_reference_time": [pd.Timestamp(year, 10, 1)],
                       "forecast_period": np.arange(1, n + 1), "latitude": LATS, "longitude": LONS}).to_netcdf(path)


def test_radiation_humidity_wind_are_ratio_corrected_to_era5land(tmp_path, monkeypatch):
    monkeypatch.setattr(s5, "DIR", tmp_path / "t")
    monkeypatch.setattr(s5, "MET_DIR", tmp_path / "m")
    (tmp_path / "t").mkdir()
    (tmp_path / "m").mkdir()
    monkeypatch.setattr(C, "CAL_YEARS", (2001, 2003))
    monkeypatch.setattr(s5, "MIN_CAL_YEARS", 3)
    for y in (2001, 2002, 2003, 2026):
        _file(s5.path(y), y)
        _met_file(s5.path(y, "met"), y, scale=1.1 if y == 2026 else 1.0)           # the run: 10 % sunnier
    idx = pd.date_range("2000-01-01", "2027-06-30")
    temps = {s: pd.DataFrame({"tmax": 27.0, "tmin": 17.0}, index=idx) for s in SITES}
    hist = pd.DataFrame(1.0, index=idx, columns=SITES)
    met = {s: pd.DataFrame({"rad_mj_m2": 20.0, "vap_hpa": 15.0, "wind2_ms": 1.5}, index=idx) for s in SITES}
    no = s5.Seas5(2026, SITES, LATS, LONS, temps, hist)
    assert no.met is None and "no ERA5-Land" in no.met_note and "ET0 scaled by temperature" in s5.describe(no)
    out = s5.Seas5(2026, SITES, LATS, LONS, temps, hist, met=met)
    assert out.met["rad"].shape == (3, s5.LEAD_DAYS, 2) and out.met_cal_years == [2001, 2002, 2003]
    assert abs(float(out.met["rad"][:, 1:].mean()) - 22.0) < 0.3                   # 20 MJ × the run's 1.1
    assert abs(float(out.met["vap"].mean()) - 15.0) < 0.3 and abs(float(out.met["wind2"].mean()) - 1.5) < 0.05
    assert "Penman-Monteith" in s5.describe(out)


def test_penman_monteith_ratio():
    ref = {"tmax": 28.0, "tmin": 16.0, "vap": 15.0, "wind2": 1.8, "rad": 20.0}
    r = lambda **kw: float(s5.pm_ratio({**ref, **kw}, ref, 90.0, -2.2, 300, 950.0))
    assert r() == pytest.approx(1.0)
    assert r(rad=24.0) > 1.0 and r(vap=20.0) < 1.0 and r(wind2=3.0) > 1.0 and r(tmax=31.0) > 1.0
    assert r(rad=200.0) == 1.5                                                       # clipped


def test_download_requests_and_order():
    pytest.importorskip("cdsapi")                           # the platform's CDS downloader imports it (not in CI)
    from crop_engine.data import seas5_download as sd
    r = sd.request(2026, "met")
    assert r["variable"] == s5.VARIABLES["met"] and r["month"] == "10" and r["day"] == "01"
    assert len(r["leadtime_hour"]) == s5.LEAD_DAYS and r["leadtime_hour"][0] == "24"
    assert sd.order(range(1993, 1998), {1993}) == [1997, 1995, 1994, 1996]
