"""The WOFOST-only crops, part 2 (run_other_crops.py, wofost_crops.yaml): a WOFOST crop that never establishes is dated
when its seedling's leaves are gone, so it can be re-sown (the pearl millet of the 1 Oct 2026 run); the legumes' WOFOST
8.1 nitrogen levels; DSSAT's cowpea, pigeonpea, groundnut and millet (dssat_adapter OTHER_CROPS) and their fitted
phenology. Needs PCSE and its crop parameters; the DSSAT runs need DSSAT installed (skipped otherwise)."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pcse")
from crop_engine import run_other_crops as oc  # noqa: E402
from crop_engine.adapters import dssat_adapter as ds  # noqa: E402
from crop_engine.adapters import wofost_adapter as wf  # noqa: E402
from crop_engine.tests.test_wofost import LAYERS  # noqa: E402

try:
    wf._cropdata()
except Exception as exc:                                                 # no network for the crop parameters
    pytest.skip(f"WOFOST crop parameters unavailable: {exc}", allow_module_level=True)

CROPS = oc.load_crops()
DATES = pd.date_range("2026-08-01", "2027-03-31")


def _task(crop, rain, planting, resow=None, initial_frac=0.3, tmean=None):
    T = len(DATES)
    tm = tmean or crop["reference_tmean_c"]
    return dict(dates=DATES.values, rain=np.asarray(rain, float)[None], tmax=np.full(T, tm + 6), tmin=np.full(T, tm - 6),
                et0=np.full(T, 4.5), source=np.zeros(T, np.int8), planting=[planting], resow=resow, variety=crop, kw={},
                layers=LAYERS, initial_frac=initial_frac, rad=np.full(T, 21.0), vap=np.full(T, 17.0),
                wind2=np.full(T, 1.6), lat=-2.2, lon=37.7, elev=950.0)


def _rain(wet_from, first=None):
    """35 mm every Monday from wet_from, and `first` mm on the day before the first sowing."""
    r = np.where((DATES.dayofweek == 0) & (DATES >= pd.Timestamp(wet_from)), 35.0, 0.0)
    if first:
        r[DATES.get_indexer([pd.Timestamp("2026-10-04")])[0]] = first
    return r


# ── 1. the pearl millet: a failed establishment is re-sown ────────────────────────────────────────────────────────────
def test_a_stalled_seedling_is_dated_early_and_resown():
    """Sown into a dry profile after one rain, then eight dry weeks: WOFOST's millet never reaches 5 % cover. Its
    failure is dated when its leaves are gone (before the maturity WOFOST's stalled crop still reaches), so the crop is
    sown again at the next opportunity, as AquaCrop's and DSSAT's are."""
    c = CROPS["pearl_millet"]
    rain = _rain("2026-12-07", first=30.0)
    alone = wf.simulate(_task(c, rain, dt.date(2026, 10, 5), initial_frac=0.05))[0]
    assert alone["status"] == "failed_establishment" and alone["max_lai"] < wf.ESTABLISHED_LAI
    died = dt.date.fromisoformat(alone["harvest"])
    assert died < dt.date.fromisoformat(alone["expected_maturity"]) - dt.timedelta(days=30)
    again = wf.simulate(_task(c, rain, dt.date(2026, 10, 5), resow=[[dt.date(2026, 12, 8)]], initial_frac=0.05))[0]
    assert again["sowings"] == 2 and again["planting"] == "2026-12-08" and again["first_planting"] == "2026-10-05"
    assert again["status"] == "ok" and again["yield_t_ha"] > 0.3


def test_an_established_crop_keeps_its_maturity_date():
    c = CROPS["pearl_millet"]
    m = wf.simulate(_task(c, _rain("2026-10-12"), dt.date(2026, 10, 20)))[0]
    assert m["status"] == "ok" and m["sowings"] == 1
    assert (dt.date.fromisoformat(m["harvest"]) - dt.date(2026, 10, 20)).days > 60


# ── 2. the legumes' nitrogen (WOFOST 8.1) ─────────────────────────────────────────────────────────────────────────────
def test_the_nitrogen_crops_and_levels():
    assert set(oc.nitrogen_crops(CROPS)) == {"cowpea", "green_gram", "pigeonpea", "groundnut"}   # no millet
    lv = oc.n_levels()
    assert list(lv) == ["unlimited", "n0", "n25", "n50"]                  # plain urea levels, no maize practice
    assert [lv[k]["rate_kg_ha"] for k in ("n0", "n25", "n50")] == [0, 25, 50]
    t = oc.with_nitrogen({"variety": CROPS["cowpea"]}, lv["n25"])
    assert t["nitrogen"]["split"] == [(0, 1.0)] and t["nitrogen"]["rate_kg_ha"] == 25
    assert t["nitrogen"]["NSOILBASE"] == oc.rnw.soil_settings()["soil"]["NSOILBASE"]
    u = oc.with_nitrogen({"variety": CROPS["cowpea"]}, lv["unlimited"])["nitrogen"]
    assert u["NSOILBASE"] == 2000.0 and u["NAVAILI"] == 500.0 and u["rate_kg_ha"] == 0


@pytest.mark.parametrize("ck", ["cowpea", "groundnut"])
def test_a_legume_with_nitrogen(ck):
    """A watered legume grows with WOFOST 8.1's nitrogen balance at every level; unfertilised it yields no more than
    with no nitrogen limit (it fixes most of its nitrogen, so not much less)."""
    c, lv = CROPS[ck], oc.n_levels()
    y = {}
    for lk in ("unlimited", "n0", "n50"):
        m = wf.simulate(oc.with_nitrogen(_task(c, _rain("2026-10-12"), dt.date(2026, 10, 20)), lv[lk]))[0]
        assert m["status"] == "ok", (ck, lk, m)
        y[lk] = m["yield_t_ha"]
    assert y["n0"] <= y["unlimited"] + 0.05 and y["n0"] <= y["n50"] + 0.05
    assert y["n0"] > 0.5 * y["unlimited"]


def test_millet_has_no_nitrogen_parameters():
    t = oc.with_nitrogen(_task(CROPS["pearl_millet"], _rain("2026-10-12"), dt.date(2026, 10, 20)), oc.n_levels()["n0"])
    assert wf.simulate(t)[0]["status"] == "error"


# ── 3. DSSAT for the WOFOST-only crops ────────────────────────────────────────────────────────────────────────────────
def test_dssat_crop_keys():
    assert ds.crop_key({"aquacrop_crop": "MaizeGDD"}) == "MaizeGDD"
    assert ds.crop_key(CROPS["cowpea"]) == "cowpea" and ds.crop_spec("cowpea")[:3] == ("CP", "CRGRO048", "CPGRO048.CUL")
    assert ds.crop_spec("pigeonpea")[0] == "PP"              # PRGRO048 is bell pepper, not pigeonpea
    assert ds.crop_spec("millet")[:2] == ("ML", "MLCER048") and ds.crop_spec("peanut")[0] == "PN"
    assert ds.crop_key(CROPS["green_gram"]) is None           # DSSAT 4.8 has no mung bean
    assert ds._default_pop("cowpea") == pytest.approx(83000) and ds._default_pop("millet") == pytest.approx(67000)
    for ck in ("cowpea", "pigeonpea", "pearl_millet", "groundnut"):
        assert CROPS[ck]["dssat"]["root_depth_cm"] <= 200


def test_legumes_fix_nitrogen_in_dssat():
    fx = ds.experiment_file("CE000001", "CP", "CE0001", "CESOIL0001", dt.date(2026, 8, 1), [dt.date(2026, 10, 20)],
                            ["W001"], [(30, 0.2)], 8.3, dt.date(2027, 3, 30), nitrogen={"rate_kg_ha": 25})
    opts = next(ln for ln in fx.splitlines() if ln.startswith(" 1 OP"))
    assert opts.split()[2:5] == ["Y", "Y", "Y"]                               # water, nitrogen, fixation (SYMBI)
    row = next(ln for ln in fx.splitlines() if ln.startswith(" 1 26293"))
    assert row.split()[7] == "60"                                              # cowpea rows 60 cm


needs_dssat = pytest.mark.skipif(not ds.installed(), reason="DSSAT not installed")


@needs_dssat
@pytest.mark.parametrize("ck", ["cowpea", "pigeonpea", "pearl_millet", "groundnut"])
def test_dssat_coefficients_within_the_files_limits(ck):
    c = CROPS[ck]
    key = ds.crop_key(c)
    lo, hi = (ds.cultivar_coefficients(key, x) for x in ("999991", "999992"))
    coef = {k: v for k, v in c["dssat"].items() if k not in ds.NOT_COEFFICIENTS + ("cultivar",)}
    assert coef
    for k, v in coef.items():
        assert lo[k] - 1e-6 <= v <= hi[k] + 1e-6, (ck, k, v, lo[k], hi[k])
    txt = ds.cultivar_file(ds.DATA / "Genotype" / ds.crop_spec(key)[2], c["dssat"]["cultivar"], coef)
    assert txt.splitlines()[-1].startswith(ds.CUSTOM_ID)


@needs_dssat
@pytest.mark.parametrize("ck,days", [("cowpea", 87), ("pigeonpea", 100), ("pearl_millet", 80), ("groundnut", 101)])
def test_dssat_phenology_fitted(ck, days):
    """No water stress, the crop's reference temperature: DSSAT matures in the variety's days (groundnut: 101, the
    file's minima; Red Valencia's 95 is out of reach), as calibration/dssat.py --other-crops fitted them."""
    from crop_engine.calibration import dssat as cd
    c = CROPS[ck]
    site, elev = cd.kiboko()
    plant = dt.date(2012, 3, 1)                                         # the coefficients on file, as run_other_crops
    r = cd.run(c, [plant], cd.constant_weather(dt.date(2012, 2, 25), c["reference_tmean_c"]), site, elev)[0]
    assert r["status"] == "ok", r
    mat = (dt.date.fromisoformat(r["harvest"]) - plant).days
    assert abs(mat - days) <= 1, (ck, mat)


@needs_dssat
@pytest.mark.parametrize("ck", ["cowpea", "pearl_millet"])
def test_dssat_grows_a_watered_season(ck):
    c = CROPS[ck]
    m = ds.simulate(dict(_task(c, _rain("2026-10-12"), dt.date(2026, 10, 20)), potential=False))[0]
    assert m["status"] == "ok" and m["yield_t_ha"] > 0.3, (ck, m)


# ── 4. the tab's copy ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_slim_keeps_the_summaries():
    s = {"yield_if_sown_t_ha": {"median": 1.0}}
    d = {"meta": {"crops": ["cowpea", "green_gram"], "nitrogen": {"levels": {}}, "dssat": {"crops": {}}},
         "results": {"site": {"cowpea": {"rule1": {"summary": s, "members": [{}], "nitrogen": {"n0": s},
                                                   "dssat": {"summary": s, "members": [{}]}}},
                              "green_gram": {"rule1": {"summary": s, "members": [{}], "nitrogen": {"n0": s}}}}}}
    out = oc.slim(d)
    assert out["sites"]["site"]["cowpea"]["rule1"] == s
    assert out["nitrogen"]["site"]["green_gram"]["rule1"]["n0"] == s
    assert out["dssat"]["site"] == {"cowpea": {"rule1": s}}                  # green gram: no DSSAT, left out
    d["meta"].pop("dssat")
    assert "dssat" not in oc.slim(d)
