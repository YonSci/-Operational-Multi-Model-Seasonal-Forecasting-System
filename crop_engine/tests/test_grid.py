"""Gridded regional outlook (crop_engine.grid, data/grid_temperature.py): area sums, terciles, the county check and
the cell temperature series, on synthetic data."""
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import grid as G
from crop_engine.data import grid_temperature as gt

YEARS = list(range(1993, 2026))
FAIL = 0.5


def _season(y):
    return {"status": "ok" if y > 0 else "too_late", "yield_t_ha": float(y)}


def _cells():
    return pd.DataFrame([dict(id="a", cell_lat=-1.125, cell_lon=37.125, area_ha=300.0, weights={"X": 300.0}),
                         dict(id="b", cell_lat=-1.125, cell_lon=37.375, area_ha=1000.0, weights={"X": 100.0, "Y": 900.0})])


def _bench(fa, fb):
    """Benchmark entries of cells a and b with yields fa(year), fb(year)."""
    return {cid: {"maize_early": {"fao-agricultural": {"years": {str(y): _season(f(y)) for y in YEARS}}}}
            for cid, f in (("a", fa), ("b", fb))}


def test_area_mean_weights_cells_and_leaves_out_model_errors():
    v = np.array([[1.0, 2.0, np.nan], [3.0, np.nan, np.nan]])
    m = G.area_mean(v, [1.0, 3.0])
    assert m[0] == 2.5 and m[1] == 2.0 and np.isnan(m[2])


def test_chances_need_terciles_that_separate_yields():
    assert G.chances([1, 2, 3, 4], 1.5, 3.5, FAIL) == (0.25, 0.25)
    assert G.chances([1, 2], 0.2, 3.0, FAIL) == (None, None)            # t33 below the failure threshold
    assert G.chances([1, 2], 1.0, 1.0, FAIL) == (None, None)
    assert G.terciles(np.arange(5)) == (None, None)                     # too few seasons


def test_counties_are_the_area_weighted_cells_member_by_member():
    cells = _cells()
    bench = _bench(lambda y: 1.0 + (y % 3), lambda y: 2.0 + (y % 3))
    # every member: cell a 1 t/ha, cell b 4 t/ha
    fc = {"a": {"maize_early": {"fao-agricultural": [_season(1.0)] * 10}},
          "b": {"maize_early": {"fao-agricultural": [_season(4.0)] * 10}}}
    var = {"maize_early": {"failure_t_ha": FAIL}}
    out = G.summarize_counties(fc, bench, cells, var, "maize_early", "fao-agricultural", YEARS)
    assert out["X"]["n_cells"] == 2 and out["X"]["area_ha"] == 400
    assert out["X"]["mean_t_ha"] == round((300 * 1 + 100 * 4) / 400, 3)
    assert out["Y"]["mean_t_ha"] == 4.0 and out["Y"]["p_above_normal"] == 1.0
    assert out["Y"]["pct_normal"] == round(100 * 4.0 / np.mean([2.0 + (y % 3) for y in YEARS]))
    assert out["X"]["failed_area_share_median"] == 0.0


def test_the_failed_area_counts_failed_cells_by_their_area():
    cells = _cells()
    bench = _bench(lambda y: 2.0, lambda y: 2.0)
    fc = {"a": {"maize_early": {"fao-agricultural": [_season(0.0)] * 4}},
          "b": {"maize_early": {"fao-agricultural": [_season(3.0)] * 4}}}
    out = G.summarize_counties(fc, bench, cells, {"maize_early": {"failure_t_ha": FAIL}}, "maize_early", "fao-agricultural", YEARS)
    assert out["X"]["failed_area_share_median"] == 0.75                # cell a: 300 of the county's 400 ha
    assert out["Y"]["failed_area_share_median"] == 0.0


def test_verify_ranks_the_county_normals_against_reported_yields(monkeypatch):
    cells = _cells()
    rng = np.random.default_rng(1)
    good = {y: float(v) for y, v in zip(YEARS, rng.uniform(0.3, 1.2, len(YEARS)))}
    bench = _bench(lambda y: 4 * good[y], lambda y: 4 * good[y] + 0.1)
    monkeypatch.setattr(G, "harveststat_sr", lambda crop="maize": {"X": {y: good[y] for y in YEARS[:20]},
                                                                   "Y": {y: good[y] for y in YEARS[:5]}})
    v = G.verify(bench, cells, "maize_early", "fao-agricultural", YEARS)
    assert v["X"]["n_years"] == 20 and v["X"]["r_rank"] == 1.0 and v["X"]["r_detrended"] > 0.99
    assert v["Y"] == {"n_years": 5}                                     # too few seasons: no correlation


def test_cell_series_reads_the_yearly_files(tmp_path, monkeypatch):
    monkeypatch.setattr(gt, "DIR", tmp_path)
    lat, lon = np.array([-1.125, -0.875]), np.array([37.125, 37.375])
    for y in (2001, 2002):
        t = pd.date_range(f"{y}-08-01", periods=5)
        tx = np.full((5, 2, 2), 25.0 + y - 2001, np.float32)
        xr.Dataset({"tmax": (("time", "lat", "lon"), tx), "tmin": (("time", "lat", "lon"), tx - 10)},
                   coords={"time": t, "lat": lat, "lon": lon}).to_netcdf(gt.path(y))
    cells = [SimpleNamespace(id="c", cell_lat=-0.875, cell_lon=37.375)]
    s = gt.cell_series(cells, years=[2001, 2002, 2003])["c"]
    assert len(s) == 10 and s.loc["2002-08-03", "tmax"] == 26.0 and (s.tmax - s.tmin == 10).all()


def test_only_a_growing_year_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(gt, "DIR", tmp_path)
    today = dt.date(2026, 11, 11)
    assert gt.stale(2010, today)                                        # missing
    for y in (2010, 2024, 2025, 2026):
        gt.path(y).write_text("x")
    assert not gt.stale(2010, today) and not gt.stale(2026, today)       # fresh
    monkeypatch.setattr(gt.time, "time", lambda: gt.path(2026).stat().st_mtime + 25 * 3600)
    assert gt.stale(2026, today) and not gt.stale(2010, today) and not gt.stale(2025, today)
    assert gt.stale(2025, dt.date(2026, 2, 1)) and not gt.stale(2024, dt.date(2026, 2, 1))   # Dec still growing in Feb
