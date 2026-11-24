"""The daily farm crop runs (crop_engine/farms.py): sowing days across seasons, the diary's irrigation, the normal's
cache key and farms outside the forecast area (no weather or model run needed)."""
import datetime as dt

from crop_engine import farms


def test_season_day_moves_the_sowing_to_another_season():
    assert farms._season_day(dt.date(2026, 11, 4), 1997) == dt.date(1997, 11, 4)
    assert farms._season_day(dt.date(2027, 1, 10), 1997) == dt.date(1998, 1, 10)       # Jan of season 1997 is in 1998
    assert farms._season_day(dt.date(2028, 2, 29), 1997) == dt.date(1998, 2, 28)       # no 29 Feb in 1998


def test_irrigation_events_become_days_after_sowing():
    sow = dt.date(2026, 11, 4)
    ev = [{"date": "2026-11-19", "mm": 25}, {"date": "2026-11-01", "mm": 30}, {"date": "2026-12-04", "mm": 40}, {"date": "2026-12-05", "mm": 0}]
    spec = farms._irrigation(ev, sow)
    assert spec == {"schedule_das": [(15, 25.0), (30, 40.0)], "MaxIrr": 40.0}          # before sowing and 0 mm left out
    assert farms._irrigation([], sow) is None and farms._irrigation(None, sow) is None


def test_normal_key_follows_what_shapes_the_normal():
    sow, cell = dt.date(2026, 11, 4), (-2.125, 37.625)
    irr = farms._irrigation([{"date": "2026-11-19", "mm": 25}], sow)
    k = farms._normal_key(cell, "maize_early", sow, irr)
    assert k == farms._normal_key(cell, "maize_early", dt.date(2026, 11, 4), dict(irr))
    assert k != farms._normal_key(cell, "maize_early", dt.date(2026, 11, 5), irr)
    assert k != farms._normal_key(cell, "bean", sow, irr)
    assert k != farms._normal_key(cell, "maize_early", sow, None)
    assert k != farms._normal_key((-2.375, 37.625), "maize_early", sow, irr)


def test_unknown_crops_and_farms_outside_kenya_are_reported_not_run():
    out = farms.run([{"id": "a", "lat": -1.0, "lon": 37.0, "crop": "coffee", "sowing_date": "2026-11-01"},
                     {"id": "b", "lat": 9.0, "lon": 39.0, "crop": "bean", "sowing_date": "2026-11-01"}])
    assert "no crop model" in out["a"]["error"] and "outside the forecast area" in out["b"]["error"]
