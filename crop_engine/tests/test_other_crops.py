"""The WOFOST-only crops (crop_engine/wofost_crops.yaml, run_other_crops.py): each crop set loads, its phenology is
scaled to the variety's days at the temperature they were observed at, and a watered season matures with a yield.
Needs PCSE and its crop parameter library; skipped without them."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pcse")
from crop_engine import run_other_crops as oc  # noqa: E402
from crop_engine.adapters import wofost_adapter as wf  # noqa: E402
from crop_engine.tests.test_wofost import LAYERS  # noqa: E402

try:
    wf._cropdata()
except Exception as exc:                                                 # no network for the crop parameters
    pytest.skip(f"WOFOST crop parameters unavailable: {exc}", allow_module_level=True)

CROPS = oc.load_crops()


def test_the_crops_and_their_days():
    assert set(CROPS) == {"cowpea", "green_gram", "pigeonpea", "pearl_millet", "groundnut"}
    for k, c in CROPS.items():
        assert wf.available(c) and c["kw"] == {}
        crop, name, over, base = wf.phenology(c)
        t = c["reference_tmean_c"]
        emerge = base["TSUMEM"] / max(min(t, base["TEFFMX"]) - base["TBASEM"], 0.1)
        rate = float(wf._afgen(base["DTSMTB"], t))
        assert emerge + (over["TSUM1"] + over["TSUM2"]) / rate == pytest.approx(c["maturity_days"], abs=1), k
        if c.get("flowering_days"):
            assert emerge + over["TSUM1"] / rate == pytest.approx(c["flowering_days"], abs=1), k


@pytest.mark.parametrize("ck", sorted(CROPS))
def test_a_watered_season(ck):
    c = CROPS[ck]
    d = pd.date_range("2026-08-01", "2027-03-31")
    T = len(d)
    rain = np.where((d.dayofweek == 0) & (d >= pd.Timestamp("2026-10-15")), 35.0, 0.0)
    tm = c["reference_tmean_c"]
    task = dict(dates=d.values, rain=rain[None], tmax=np.full(T, tm + 6), tmin=np.full(T, tm - 6), et0=np.full(T, 4.5),
                source=np.zeros(T, np.int8), planting=[dt.date(2026, 10, 20)], resow=None, variety=c, kw={},
                layers=LAYERS, initial_frac=0.3, rad=np.full(T, 21.0), vap=np.full(T, 17.0), wind2=np.full(T, 1.6),
                lat=-2.2, lon=37.7, elev=950.0)
    m = wf.simulate(task)[0]
    assert m["status"] == "ok" and m["yield_t_ha"] > 0.2, (ck, m)
    days = (dt.date.fromisoformat(m["harvest"]) - dt.date(2026, 10, 20)).days
    assert abs(days - c["maturity_days"]) <= 12, (ck, days)
