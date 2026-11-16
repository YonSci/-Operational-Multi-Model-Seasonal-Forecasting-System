"""DSSAT calibration, part 2: the GLUE check (calibration/dssat_glue.py) on synthetic cases, and the sorghum 100-day
overrides (calibration/sorghum_dssat.py, dssat_cultivars.yaml) within sane bounds. No full GLUE run."""
import numpy as np
import pytest

from crop_engine.adapters import dssat_adapter as ds
from crop_engine.calibration import dssat_glue as dg
from crop_engine.calibration import sorghum_dssat as sd

BOUNDS = {"P1": (5.0, 450.0), "P5": (580.0, 999.0), "G2": (248.0, 990.0), "G3": (5.0, 16.5)}
needs_dssat = pytest.mark.skipif(not ds.installed(), reason="DSSAT is not installed")


@pytest.mark.parametrize("lhs", [True, False])
def test_sampling_stays_within_the_files_limits(lhs):
    th = dg.sample(BOUNDS, 200, seed=7, lhs=lhs)
    assert th.shape == (200, 4)
    for j, (lo, hi) in enumerate(BOUNDS.values()):
        assert (th[:, j] >= lo).all() and (th[:, j] <= hi).all()
    assert np.array_equal(th, dg.sample(BOUNDS, 200, seed=7, lhs=lhs))           # seeded
    assert not np.array_equal(th, dg.sample(BOUNDS, 200, seed=8, lhs=lhs))


def test_latin_hypercube_puts_one_draw_in_each_stratum():
    n = 50
    th = dg.sample(BOUNDS, n, seed=1)
    for j, (lo, hi) in enumerate(BOUNDS.values()):
        strata = np.floor((th[:, j] - lo) / (hi - lo) * n).astype(int)
        assert sorted(strata) == list(range(n))


def test_likelihood_is_gaussian_on_both_targets():
    L = dg.likelihood([115, 118, 115, None, 115], [5.0, 5.0, 5.5, 5.0, np.nan], 115, 5.0, sigma_days=3, sigma_rel=0.1)
    assert L[0] == pytest.approx(1.0)
    assert L[1] == pytest.approx(np.exp(-0.5))                                   # one sigma in days
    assert L[2] == pytest.approx(np.exp(-0.5))                                   # 10 % in yield
    assert L[3] == 0.0 and L[4] == 0.0                                           # not grown: no likelihood
    assert dg.likelihood(118, 5.5, 115, 5.0)[0] == pytest.approx(np.exp(-1.0))


def test_weighted_quantile_and_ess():
    x = np.arange(1.0, 102.0)
    w = np.ones_like(x)
    assert dg.weighted_quantile(x, w, 0.5) == pytest.approx(51.0)
    assert dg.ess(w) == pytest.approx(len(x))
    w1 = np.zeros_like(x)
    w1[10] = 1.0
    assert dg.ess(w1) == pytest.approx(1.0)
    assert dg.weighted_cdf(x, w, 51.0) == pytest.approx(51 / 101)


def test_posterior_weights_a_synthetic_case():
    """Two coefficients on a grid, the 'model' days = a + b; the likelihood peaks along a + b = 10 and on a = 3
    (a second target): the posterior centres there, with b's posterior negatively tied to a's."""
    rng = np.random.default_rng(0)
    th = rng.uniform([0, 0], [10, 10], size=(4000, 2))
    days, yld = th[:, 0] + th[:, 1], 1.0 + 0.1 * (th[:, 0] - 3.0)
    L = dg.likelihood(days, yld, 10.0, 1.0, sigma_days=0.5, sigma_rel=0.05)
    p = dg.posterior(th, ("a", "b"), L, adopted={"a": 3.0, "b": 9.5}, bounds={"a": (0, 10), "b": (0, 10)})
    a, b = p["coefficients"]["a"], p["coefficients"]["b"]
    assert a["mean"] == pytest.approx(3.0, abs=0.15) and b["mean"] == pytest.approx(7.0, abs=0.3)
    assert a["q05"] < 3.0 < a["q95"] and a["adopted_in_90"] and 0.3 < a["adopted_quantile"] < 0.7
    assert not b["adopted_in_90"] and b["adopted_quantile"] > 0.95             # an adopted value off the posterior
    assert p["correlation"]["a~b"] < -0.5
    assert th[p["best_index"]].tolist() == [a["best"], b["best"]]
    assert 1 < p["ess"] < 4000 and a["prior"] == [0.0, 10.0]
    assert dg.posterior(th, ("a", "b"), np.zeros(len(th))) is None             # nothing behavioural: no posterior


def test_summarise_skips_sets_not_grown():
    s = dg.summarise([100, None, 110], [1.0, 1.0, 1.0])
    assert s["mean"] == pytest.approx(105.0) and 100 <= s["q05"] <= s["q95"] <= 110


# ── sorghum as a 100-day crop ──────────────────────────────────────────────────────────────────────────────────────
def test_sorghum_overrides_are_sane():
    s = ds.cultivars()["sorghum"]
    assert 200.0 <= s["P1"] <= 500.0 and 300.0 <= s["P5"] <= 700.0 and 2.0 <= s["G2"] <= 6.0   # the file's limits
    if "PANTH" in s:                                                             # the 100-day fit (sorghum_dssat)
        assert sd.PANTH_RANGE[0] <= s["PANTH"] <= sd.PANTH_RANGE[1]
        assert 0 < s["P3"] < s["PANTH"] and s["P3"] / s["PANTH"] == pytest.approx(sd.P3_SHARE, rel=0.01)
        assert s.get("P4", 81.5) == pytest.approx(81.5)
        # thermal time sowing to maturity about 100 days × 13 °C d (21 °C, TBASE 8), give or take a week
        total = 50 + 6 * 5 + s["P1"] + 102.0 + s["PANTH"] + s.get("P4", 81.5) + s["P5"]
        assert 93 * 13 <= total <= 107 * 13


def test_sound_flags_what_is_off():
    good = {"overrides": {"P1": 200.0, "PANTH": 450.0, "P3": 111.2, "P5": 360.0, "G2": 5.5},
            "anthesis_days": 65, "maturity_days": 100, "targets": {"anthesis_days": 65, "maturity_days": 100},
            "yield": {"fitted_t_ha": 4.96, "target_t_ha": 4.97}}
    assert sd.sound(good) == []
    bad = dict(good, anthesis_days=75, overrides=dict(good["overrides"], G2=6.5, PANTH=200.0))
    why = " ".join(sd.sound(bad))
    assert "anthesis" in why and "G2" in why and "PANTH" in why
    assert sd.with_panth({"P1": 200.0}, 400.0) == {"P1": 200.0, "PANTH": 400.0, "P3": round(400 * sd.P3_SHARE, 1)}


@needs_dssat
def test_cultivar_file_takes_panth_beyond_dssats_fixed_values():
    txt = ds.cultivar_file(ds.DATA / "Genotype" / "SGCER048.CUL", "IB0026", {"PANTH": 450.0, "P3": 111.2, "P5": 360.0})
    head = next(ln for ln in txt.splitlines() if ln.startswith("@VAR"))
    custom = next(ln for ln in txt.splitlines() if ln.startswith(ds.CUSTOM_ID))
    col = lambda name: custom[head.index(name) + len(name) - 6: head.index(name) + len(name)].strip()   # noqa: E731
    assert float(col("PANTH")) == 450.0 and float(col("P3")) == pytest.approx(111.2) and float(col("P5")) == 360.0


@needs_dssat
def test_sorghum_on_file_matures_in_the_class_days():
    """One DSSAT run at calibration/dssat's reference conditions with dssat_cultivars.yaml's sorghum."""
    import datetime as dt
    from crop_engine import run_outlook as ro
    from crop_engine.calibration import dssat as cd
    from crop_engine.data.sites import registered_sites
    tref, vs = ro.load_varieties(["sorghum"])
    ds.attach(vs)
    v = vs["sorghum"]
    if "PANTH" not in v["dssat"]:
        pytest.skip("the 100-day overrides are not adopted")
    site = next(s for s in registered_sites() if s.id == cd.SITE)
    anth, mat = sd.phenology(v, {}, site, 950.0, tref)
    assert mat == v["maturity_days"]
    assert sd.ANTHESIS_WINDOW[0] <= anth <= sd.ANTHESIS_WINDOW[1]
