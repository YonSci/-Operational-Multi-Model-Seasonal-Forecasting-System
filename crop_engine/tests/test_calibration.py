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


def test_inline_published_values_become_observations():
    cs = {"version": "t", "site": "s1", "fit": {"varieties": ["maize_early"]}}
    g = {"id": "lit", "role": "train", "variety": "maize_early", "target": "days_to_flowering",
         "location": {"id": "far", "lat": 0.0, "lon": 37.0, "name": "x"},
         "observed": {"source": "a paper, Table 2", "values": [{"entry": "V1", "days_to_flowering": 53.0},
                                                            {"entry": "V2", "yield_t_ha": 3.0}]}}
    rows = cal.validate(dict(cs, groups=[g]), _obs([]))["lit"]
    assert list(rows.obs_id) == ["lit:t:lit:1"] and rows.site_id.iloc[0] == "far" and rows.days_to_flowering.iloc[0] == 53
    y = cal.inline(cs, g)
    assert y.grain_yield_dry_kg_ha.iloc[1] == 3000 and y.study.iloc[0] == "a paper, Table 2"


def test_hargreaves_et0_is_plausible_for_kenya():
    from crop_engine.calibration.potential import hargreaves_et0
    dates = pd.date_range("2012-06-01", periods=30)
    et0 = hargreaves_et0(np.full(30, 28.0), np.full(30, 16.0), dates, -2.2)
    assert 3.5 < et0.mean() < 5.5                                  # mm/day, a warm dry-season month near the equator


def test_irrigated_potential_matures_without_water_stress():
    from crop_engine.adapters.aquacrop_adapter import crop_parameters
    from crop_engine.calibration.potential import irrigated_potential
    kw, _ = crop_parameters(MAIZE, 21.0)
    r = irrigated_potential("MaizeGDD", kw, _temps(22.0, days=400), "2013-03-01", -2.2)
    assert r["status"] == "ok" and r["yield_t_ha"] > 3 and r["irrigation_mm"] > 0
    assert irrigated_potential("MaizeGDD", kw, _temps(22.0, days=100), "2013-03-01", -2.2)["status"] == "no weather"


@pytest.mark.parametrize("version", ["kiboko_v1", "kiboko_v2"])
def test_the_kiboko_sets_are_well_formed(version):
    cs, _ = cal.load_set(version)
    roles = {g["id"]: g["role"] for g in cs["groups"]}
    assert set(roles.values()) <= set(cal.ROLES)
    for v in cs["fit"]["varieties"]:                               # every fitted variety: a training group
        assert any(g["role"] == "train" and g.get("variety") == v for g in cs["groups"])
    pheno = [g for g in cs["groups"] if g.get("target") in ph.STAGE]
    for g in pheno:                                                # every phenology group: sowing windows
        assert ph.sowing_dates(g["windows"]).size > 0
    pre = {}                                                       # train and holdout never share observations
    for g in pheno:
        if "observed" in g:                                        # published values: their own obs ids
            assert g["observed"]["source"] and g["observed"]["values"]
            continue
        for p in cal._as_list(g["select"]["obs_id_prefix"]):
            assert p not in pre, f"{p} in {pre.get(p)} and {g['id']}"
            pre[p] = g["id"]
