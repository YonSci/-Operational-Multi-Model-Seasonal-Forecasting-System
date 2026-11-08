"""The WOFOST adapter (crop_engine.adapters.wofost_adapter) on synthetic weather: phenology targets, soil, outcomes.
Needs PCSE and its crop parameter library (downloaded once by PCSE); skipped without them."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pcse")
from crop_engine.adapters import wofost_adapter as wf  # noqa: E402
from crop_engine.data import soil  # noqa: E402

try:
    wf._cropdata()
except Exception as exc:                                                 # no network for the crop parameters
    pytest.skip(f"WOFOST crop parameters unavailable: {exc}", allow_module_level=True)

DATES = pd.date_range("2026-08-01", "2027-03-31")
LAYERS = [soil.Layer(t, b, 50, 25, 1.5, 5, 0.26, 0.13) for t, b in ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))]
MAIZE = {"label": "Early-maturing maize", "aquacrop_crop": "MaizeGDD", "maturity_days": 115, "failure_t_ha": 0.5, "kw": {}}


def task(rain_mm_per_week=30.0, plant=dt.date(2026, 10, 20), n=2, tmean=22.0):
    T = len(DATES)
    rain = np.zeros((n, T))
    rain[:, DATES.dayofweek == 0] = rain_mm_per_week
    rain[:, DATES < pd.Timestamp("2026-10-15")] = 0
    return dict(dates=DATES.values, rain=rain, tmax=np.full(T, tmean + 6), tmin=np.full(T, tmean - 6),
                et0=np.full(T, 4.5), source=np.zeros(T, np.int8), planting=[plant] * n, resow=None, variety=MAIZE,
                kw={}, layers=LAYERS, initial_frac=0.2, rad=np.full(T, 21.0), vap=np.full(T, 17.0),
                wind2=np.full(T, 1.6), lat=-2.2, lon=37.7, elev=950.0)


def test_phenology_matures_in_the_variety_days_at_the_reference_temperature():
    crop, name, over, base = wf.phenology(MAIZE)
    assert crop == "maize" and name == "Maize_VanHeemst_1988"
    emerge = base["TSUMEM"] / (wf.REFERENCE_TMEAN - base["TBASEM"])
    rate = wf._afgen(base["DTSMTB"], wf.REFERENCE_TMEAN)
    assert emerge + (over["TSUM1"] + over["TSUM2"]) / rate == pytest.approx(115, abs=0.5)
    assert over["TSUM1"] / over["TSUM2"] == pytest.approx(base["TSUM1"] / base["TSUM2"], rel=1e-3)
    with pytest.raises(ValueError):
        wf.phenology({"label": "Dry bean", "aquacrop_crop": "DryBeanGDD", "maturity_days": 75})


def test_soil_parameters_are_ordered_and_hold_the_initial_water():
    s, site = wf.soil_parameters(LAYERS, 0.5)
    assert 0 < s["SMW"] < s["SMFCF"] < s["SM0"] < 0.7 and s["RDMSOL"] == 200
    assert site["WAV"] == pytest.approx(0.5 * (0.26 - 0.13) * 200)
    assert 0.1 <= s["SOPE"] <= 10 and 0.05 <= s["KSUB"] <= 10


def test_a_watered_crop_yields_and_a_dry_one_does_not():
    wet = wf.simulate(task(40.0))
    assert [m["status"] for m in wet] == ["ok", "ok"] and wet[0]["yield_t_ha"] > 1.0
    assert wet[0]["yield_t_ha"] == wet[1]["yield_t_ha"]                  # the same weather, the same crop
    days = (dt.date.fromisoformat(wet[0]["harvest"]) - dt.date(2026, 10, 20)).days
    assert 95 <= days <= 125                                             # 115 days at 21 °C, a little faster at 22 °C
    dry = wf.simulate(task(0.0))
    assert dry[0]["status"] in ("died", "failed_establishment") and dry[0]["yield_t_ha"] < 0.5


def test_not_sown_and_too_late():
    t = task(30.0, plant=dt.date(2027, 2, 20))
    t["planting"] = [None, dt.date(2027, 2, 20)]
    out = wf.simulate(t)
    assert out[0]["status"] == "not_sown" and out[1]["status"] == "too_late"
