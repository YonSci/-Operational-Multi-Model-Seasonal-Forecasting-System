"""Hindcast verification (crop_engine.hindcast): scores and the forecast weather, on synthetic data."""
import numpy as np
import pandas as pd

from crop_engine import hindcast as hc


def test_a_perfect_forecast_scores_well_and_noise_does_not():
    rng = np.random.default_rng(3)
    obs = rng.uniform(0, 4, 24)
    perfect = obs[:, None] + rng.normal(0, 0.05, (24, 25))
    s = hc.scores(perfect, obs, 0.5)
    assert s["spearman"] > 0.95 and s["rpss"] > 0.6 and s["failure_auc"] > 0.95 and s["failure_bss"] > 0.5
    noise = rng.uniform(0, 4, (24, 25))
    n = hc.scores(noise, obs, 0.5)
    assert abs(n["spearman"]) < 0.5 and n["rpss"] < 0.2


def test_terciles_are_skipped_when_a_third_failed():
    obs = np.r_[np.zeros(10), np.linspace(1, 3, 14)]
    s = hc.scores(np.tile(obs[:, None], 25), obs, 0.5)
    assert s["rpss"] is None and s["failure_rate"] == round(10 / 24, 3) and s["failure_auc"] == 1.0


def test_auc_and_baseline_orientation():
    assert hc._auc([0.9, 0.8, 0.1, 0.2], [True, True, False, False]) == 1.0
    assert hc._auc([0.1, 0.2], [True, True]) is None
    obs = np.linspace(0, 4, 24)
    lgp = np.linspace(60, 150, 24)                      # longer season, more yield
    onset = np.linspace(330, 280, 24)                   # later onset, less yield
    assert hc.baseline_scores(lgp, 1, obs, 0.5)["spearman"] == 1.0
    assert hc.baseline_scores(onset, -1, obs, 0.5)["spearman"] == 1.0
    assert hc.baseline_scores(lgp, 1, obs, 0.5)["failure_auc"] == 1.0


def test_assemble_rain_puts_each_source_in_its_days():
    y = 2005
    dates = pd.date_range(f"{y}-08-01", f"{y + 1}-03-31")
    M, S, T = 3, 2, len(dates)
    obs = np.full((S, T), 1.0, np.float32)
    oct_dec = np.full((M, 92, S), 2.0, np.float32)
    janfeb = np.full((M, 59, S), 3.0, np.float32)
    nmar = int((dates >= pd.Timestamp(y + 1, 3, 1)).sum())
    march = np.full((M, S, nmar), 4.0, np.float32)
    r = hc.assemble_rain(obs, oct_dec, janfeb, march, dates, y)
    at = lambda d: r[:, :, dates.get_loc(pd.Timestamp(d))]
    assert r.shape == (M, S, T)
    assert (at(f"{y}-09-30") == 1).all() and (at(f"{y}-10-01") == 2).all() and (at(f"{y}-12-31") == 2).all()
    assert (at(f"{y + 1}-01-01") == 3).all() and (at(f"{y + 1}-02-28") == 3).all() and (at(f"{y + 1}-03-31") == 4).all()
