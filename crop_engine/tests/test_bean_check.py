"""The bean check's trial selection (calibration/bean.py), on a small synthetic table: python -m pytest crop_engine/tests"""
import numpy as np
import pandas as pd

from crop_engine.calibration import bean


def test_habit():
    assert bean.habit("bush bean", "Kenya Tamu") == "bush"            # N2Africa's experiment label first
    assert bean.habit("climbing bean", None) == "climbing"
    assert bean.habit(np.nan, "Kenya Umoja") == "bush"
    assert bean.habit(np.nan, "KAT B9") == "bush"
    assert bean.habit(np.nan, "NEWROSCOCO") == "bush"
    assert bean.habit(np.nan, "KENYA TAMU") == "climbing"
    assert bean.habit(np.nan, "Kenya Mavuno") == "climbing"
    assert bean.habit(np.nan, "MAC44") == "climbing"
    assert bean.habit(np.nan, "RWV 2070") == "climbing"
    assert bean.habit(np.nan, "Some local") is None
    assert bean.habit(np.nan, np.nan) is None


def _plots(n, **kw):
    base = dict(crop="bean", date_quality="day", latitude=-0.6, longitude=34.55, maturity_class=np.nan,
                cultivar="Kenya Umoja", study="s1", location="Bungoma", season="LR", planting_date="2010-03-12",
                grain_yield_dry_kg_ha=1000.0, days_to_flowering=np.nan, days_to_maturity=np.nan, harvest_date=None)
    return pd.DataFrame([dict(base, **kw) for _ in range(n)])


def test_trial_seasons():
    obs = pd.concat([
        _plots(4).assign(grain_yield_dry_kg_ha=[500.0, 1000.0, 1500.0, 2000.0]),
        _plots(4, planting_date="2010-09-12", season="SR"),                 # another season at the same place
        _plots(2, study="s2"),                                              # too few plots
        _plots(5, cultivar="Kenya Tamu"),                                   # climbing: its own trial-season
        _plots(5, date_quality="year only"),                                # no sowing day
        _plots(5, planting_date="1990-03-10"),                              # before the weather
        _plots(5, latitude=np.nan),                                         # no place
    ], ignore_index=True)
    t = bean.trial_seasons(obs)
    assert sorted(zip(t.habit, t.planting_date)) == [("bush", "2010-03-12"), ("bush", "2010-09-12"),
                                                     ("climbing", "2010-03-12")]
    first = t[(t.habit == "bush") & (t.planting_date == "2010-03-12")].iloc[0]
    assert first.plots == 4 and first.obs_median == 1.25 and first.obs_max == 2.0
    assert np.isclose(first.obs_p90, np.quantile([0.5, 1.0, 1.5, 2.0], 0.9))
    assert first.point == "bean_-0.60_34.55"
