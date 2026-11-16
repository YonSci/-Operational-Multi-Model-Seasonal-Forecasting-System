"""The sites' own nitrogen trials (calibration/dssat.py --nitrogen-sites), on synthetic tables: python -m pytest crop_engine/tests"""
import numpy as np
import pandas as pd
import pytest

from crop_engine.calibration import dssat as cd


def _obs(study, location, year, rates_yields):
    return pd.DataFrame([dict(study=study, crop="maize", location=location, year=year, n_kg_ha=r,
                              grain_yield_dry_kg_ha=y) for r, y in rates_yields])


def test_observed_response_top_rate_mean_of_copies():
    trial = dict(studies=("a", "b"), location="Kiboko", year=2013, rates=(0, 40, 80, 160))
    obs = pd.concat([_obs("a", "Kiboko", 2013, [(0, 1000), (0, 3000), (40, 4000), (80, 6000), (160, 8000)]),
                     _obs("b", "Kiboko", np.nan, [(0, 1000), (40, 2000), (80, 3000), (160, 4000)]),
                     _obs("a", "Embu", 2013, [(0, 9000), (160, 9000)]),           # another place: not the trial
                     _obs("a", "Kiboko", 2014, [(0, 9000), (160, 9000)])],        # another year
                    ignore_index=True)
    rel, per = cd.observed_response(obs, trial)
    assert rel == {0: pytest.approx((0.25 + 0.25) / 2), 40: 0.5, 80: pytest.approx((0.75 + 0.75) / 2), 160: 1.0}
    assert per["a"] == {0: 2.0, 40: 4.0, 80: 6.0, 160: 8.0}


def test_observed_response_fertilised_reference():
    trial = dict(studies=("m",), location="Machakos", year=2015, rates=(0, 30, 60), reference="fertilised")
    rel, _ = cd.observed_response(_obs("m", "Machakos", 2015, [(0, 500), (30, 800), (60, 700)]), trial)
    assert rel[0] == pytest.approx(500 / 750, abs=1e-3) and rel[30] == pytest.approx(800 / 750, abs=1e-3)
    assert cd._fitted_rates(trial) == [0]
    assert cd._fitted_rates(dict(rates=(0, 40, 80, 160))) == [0, 40, 80]
    assert cd._reference({0: 1.0, 30: 2.0, 60: 4.0}, trial) == 3.0
    assert cd._reference({0: 1.0, 160: 5.0}, dict(rates=(0, 160))) == 5.0
