"""Calibration sets and the phenology fit (crop_engine.calibration)."""
import numpy as np
import pandas as pd
import pytest

from crop_engine.calibration import phenology as ph
from crop_engine.calibration import run as cal

MAIZE = {"label": "test maize", "aquacrop_crop": "MaizeGDD", "maturity_days": 100}


def _temps(tmean, start="2013-01-01", days=500):
    idx = pd.date_range(start, periods=days, freq="D")
    return pd.DataFrame({"tmax": tmean + 5.0, "tmin": tmean - 5.0}, index=idx)


def test_days_to_counts_like_the_adapter():
    # 18 °C mean, MaizeGDD Tbase 8 → 10 GDD a day; the sum passes 100 on the 11th day (index 10)
    cum = ph.cumulative_gdd(_temps(18.0), "MaizeGDD", pd.DatetimeIndex(["2013-03-01"]))
    assert ph.days_to(cum, 100.0)[0] == 10
    assert np.isnan(ph.days_to(cum[:, :5], 100.0)[0])            # data end before the stage: no day


def test_fit_recovers_the_maturity_days_of_synthetic_observations():
    temps = _temps(23.0)
    dates = ph.sowing_dates([{"start": "2013-03-15", "end": "2013-04-30"}])
    cum = ph.cumulative_gdd(temps, "MaizeGDD", dates)
    truth = float(np.median(ph.days_to(cum, ph.stage_gdd(MAIZE, 21.0, "days_to_flowering", 130))))
    md, obj = ph.fit_maturity_days([{"target": "days_to_flowering", "cum": cum, "observed": [truth] * 5}], MAIZE, 21.0)
    days = np.median(ph.days_to(cum, ph.stage_gdd(MAIZE, 21.0, "days_to_flowering", md)))
    assert days == truth and obj[md] == 0
    s = ph.score(ph.days_to(cum, ph.stage_gdd(MAIZE, 21.0, "days_to_flowering", md)), [truth - 1, truth + 1])
    assert s["bias_days"] == 0 and s["mae_days"] == 1 and s["obs_median_in_model_range"]


def _obs(rows):
    return pd.DataFrame(rows, columns=["obs_id", "site_id", "days_to_flowering", "grain_yield_dry_kg_ha"])


def _set(groups):
    return {"version": "t", "site": "s1", "fit": {"varieties": ["maize_early"]}, "groups": groups}


def test_validate_keeps_each_target_of_an_observation_in_one_group():
    obs = _obs([("a:1", "s1", 60, 4000), ("a:2", "s1", 62, 4200), ("b:1", "s1", 58, 3900), ("a:1", "s2", 50, 1)])
    train = {"id": "tr", "role": "train", "variety": "maize_early", "target": "days_to_flowering",
             "select": {"obs_id_prefix": "a:"}}
    hold = {"id": "ho", "role": "holdout", "variety": "maize_early", "target": "days_to_flowering",
            "select": {"obs_id_prefix": "b:"}}
    check = {"id": "ck", "role": "check", "variety": "maize_early", "target": "yield", "select": {"obs_id_prefix": "a:"}}
    rows = cal.validate(_set([train, hold, check]), obs)
    assert list(rows["tr"].obs_id) == ["a:1", "a:2"]             # the set's site only
    assert len(rows["ck"]) == 2                                    # the same trial may give a yield check
    with pytest.raises(ValueError, match="already in tr"):
        cal.validate(_set([train, dict(hold, select={"obs_id_prefix": ["a:2", "b:"]})]), obs)
    with pytest.raises(ValueError, match="no training group"):
        cal.validate(_set([hold]), obs)
    with pytest.raises(ValueError, match="selects no observations"):
        cal.validate(_set([train, dict(hold, select={"obs_id_prefix": "zz:"})]), obs)


def test_the_kiboko_set_is_well_formed():
    cs, _ = cal.load_set("kiboko_v1")
    roles = {g["id"]: g["role"] for g in cs["groups"]}
    assert set(roles.values()) <= set(cal.ROLES)
    for v in cs["fit"]["varieties"]:                               # every fitted variety: a training group
        assert any(g["role"] == "train" and g.get("variety") == v for g in cs["groups"])
    pheno = [g for g in cs["groups"] if g.get("target") in ph.STAGE]
    for g in pheno:                                                # every phenology group: sowing windows
        assert ph.sowing_dates(g["windows"]).size > 0
    pre = {}                                                       # train and holdout never share observations
    for g in pheno:
        for p in cal._as_list(g["select"]["obs_id_prefix"]):
            assert p not in pre, f"{p} in {pre.get(p)} and {g['id']}"
            pre[p] = g["id"]
