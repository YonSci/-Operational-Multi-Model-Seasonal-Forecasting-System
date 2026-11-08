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
