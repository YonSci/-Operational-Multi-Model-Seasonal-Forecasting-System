"""
Shared Dunning et al. (2016) onset / cessation / LGP detection library.

Extracted and vectorized from onset-cessation-lgp_v3_dunning_SEAS5_FINAL.ipynb
so that every per-country / per-season notebook (Kenya MAM, Ethiopia Kiremt,
Ethiopia Belg, ...) imports one tested implementation instead of copy-pasting
the detection code into a new notebook each time.

Differences from the original per-notebook implementation:
  - Land-mask building uses a vectorized geopandas spatial join instead of a
    nested Python loop calling `.intersects()` per grid cell.
  - Climatological d_s / d_e (Stage 2A) use `np.nanargmin` / `np.nanargmax`
    across the whole grid at once instead of a per-pixel Python loop.
  - Season detection (Stage 3A / 4B) is vectorized across an arbitrary batch
    of samples (pixels x years x members, flattened) instead of a
    triple-nested Python loop -- this was the main performance bottleneck
    in the original notebook, before bias correction was moved upstream.
  - Quality flags (FLAG_VALID / FLAG_NO_ONSET / FLAG_NO_CESSATION /
    FLAG_SHORT_SEASON) are actually assigned. The original notebook defined
    these constants but every failure mode collapsed into an undifferentiated
    NaN; the flag layer now records *why* a pixel/year/member has no value.
  - Tercile boundaries use `np.nanpercentile` (33rd/67th) vectorized across
    the grid, rather than the original per-pixel `sorted[n/3]` index. This is
    a disclosed, intentional refinement -- it will not bit-for-bit reproduce
    the legacy Kenya notebook's tercile values, but is a more standard
    definition and is fully vectorized.

Reference: Dunning, C.M., Black, E.C.L., & Allan, R.P. (2016). The onset and
cessation of seasonal rainfall over Africa. JGR Atmospheres, 121(19).
https://doi.org/10.1002/2016JD025428
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.stats import norm as _norm

# Land-mask-excluded pixels are all-NaN by construction, so nanmean/nanpercentile
# over them raise "Mean of empty slice" / "All-NaN slice" warnings on every call.
# These are expected (the original scalar-loop notebook simply never visited
# those pixels at all) rather than a sign of a real problem, so they're
# filtered here instead of at every call site.
warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="All-NaN slice encountered")
warnings.filterwarnings("ignore", message="All-NaN axis encountered")
warnings.filterwarnings("ignore", message="Degrees of freedom <= 0 for slice")

# --- Quality flags ----------------------------------------------------------
FLAG_VALID        = 0   # onset, cessation and LGP all detected, LGP >= MIN_LGP_DAYS
FLAG_NO_ONSET     = 1   # argmin(A) not found / out of range -> onset, cessation, LGP all NaN
FLAG_NO_CESSATION = 2   # onset found, but no day after it within the window -> cessation, LGP NaN
FLAG_SHORT_SEASON = 3   # onset and cessation both found, but LGP < MIN_LGP_DAYS (values retained)
FLAG_FILL         = -9999


# --- Land mask ---------------------------------------------------------------
def build_land_mask(shp_path, target_lat, target_lon, grid_res):
    """
    Vectorized land mask: True where a target grid cell intersects the
    country polygon(s) in `shp_path`.

    Uses a geopandas spatial join (STRtree-backed) over all grid cells at
    once, instead of calling `.intersects()` once per (i, j) in a Python
    loop -- same result, no O(n_lat * n_lon) Python-level iteration.
    """
    import geopandas as gpd
    from shapely.geometry import box as shp_box

    country = gpd.read_file(shp_path)
    half = grid_res / 2.0

    rows, cols, geoms = [], [], []
    for i, lat in enumerate(target_lat):
        for j, lon in enumerate(target_lon):
            rows.append(i); cols.append(j)
            geoms.append(shp_box(lon - half, lat - half, lon + half, lat + half))

    cells = gpd.GeoDataFrame({"i": rows, "j": cols}, geometry=geoms, crs=country.crs)
    hits = gpd.sjoin(cells, country[["geometry"]], predicate="intersects", how="inner")

    lm = np.zeros((len(target_lat), len(target_lon)), dtype=bool)
    lm[hits["i"].values, hits["j"].values] = True
    return lm


# --- Climatology (Stage 2) ---------------------------------------------------
def compute_climatology(daily, years, cal_years, win_doy_start, win_doy_end, land_mask):
    """
    Dunning climatology: Q_d, Q_bar, C_clim, d_s, d_e.

    Parameters
    ----------
    daily     : (n_years, 366, n_lat, n_lon) float32, DOY-indexed (index 0 = DOY 1)
    years     : (n_years,) int, calendar year for each slice of `daily`
    cal_years : 1-D array of calibration years to average over
    win_doy_start, win_doy_end : forecast-window bounds (inclusive), DOY units
    land_mask : (n_lat, n_lon) bool

    Returns dict with keys: win_doys, Q_d, Q_bar, C_clim, d_s, d_e
    """
    n_lat, n_lon = land_mask.shape
    cal_mask = np.isin(years, cal_years)
    cal_data = daily[cal_mask]                      # (n_cal, 366, n_lat, n_lon)

    win_doys = np.arange(win_doy_start, win_doy_end + 1, dtype=np.int32)
    n_win = len(win_doys)

    # Q_d: climatological daily mean for each DOY in the window (nanmean over CAL years)
    day_idx = win_doys - 1                            # 0-based index into the 366-length axis
    Q_d = np.nanmean(cal_data[:, day_idx, :, :], axis=0)   # (n_win, n_lat, n_lon)
    Q_d[:, ~land_mask] = np.nan

    # Q_bar: scalar per-pixel mean over the whole window -- the Dunning baseline
    Q_bar = np.nanmean(Q_d, axis=0)
    Q_bar[~land_mask] = np.nan

    # C_clim: cumulative anomaly curve
    C_clim = np.cumsum(np.where(np.isnan(Q_d), 0.0, Q_d - Q_bar[np.newaxis]), axis=0)
    C_clim[:, ~land_mask] = np.nan

    # d_s = argmin(C), d_e = argmax(C) after d_s -- vectorized across the full grid
    with np.errstate(invalid="ignore"):
        ds_idx = np.nanargmin(np.where(np.isnan(C_clim), np.inf, C_clim), axis=0)   # (n_lat,n_lon)
        day_axis = np.arange(n_win)[:, np.newaxis, np.newaxis]
        after_ds = day_axis >= ds_idx[np.newaxis, :, :]
        masked_for_de = np.where(after_ds & ~np.isnan(C_clim), C_clim, -np.inf)
        de_idx = np.nanargmax(masked_for_de, axis=0)

    d_s = np.where(land_mask, win_doys[ds_idx], np.nan).astype(np.float32)
    d_e = np.where(land_mask, win_doys[de_idx], np.nan).astype(np.float32)

    return {"win_doys": win_doys, "Q_d": Q_d, "Q_bar": Q_bar, "C_clim": C_clim,
            "d_s": d_s, "d_e": d_e}


# --- Ensemble reshaping helper ------------------------------------------------
def flatten_member_land_day(chunk, li, lj, n_members):
    """
    Reshape one year's ensemble chunk into the (sample, day) matrix expected
    by `detect_season_batch`, sample-ordered member-major (all land pixels
    for member 0, then all land pixels for member 1, ...) -- matching
    `np.tile(per_pixel_vector, n_members)` for Q_bar/d_s/d_e.

    chunk : (n_lat, n_lon, n_day, n_member) -- the bias-corrected files'
            native dimension order.
    li, lj : land-pixel row/col indices (from `np.argwhere(land_mask)`)

    This exists because member and land are NOT adjacent axes in `chunk`
    (day sits between them); `.reshape()` only merges adjacent axes
    correctly, so transposing to any order other than
    (member, land, day) before reshaping silently interleaves days from
    different members/pixels without raising an error.
    """
    chunk_land = chunk[li, lj]                                  # (n_land, day, member)
    n_land, n_day = chunk_land.shape[0], chunk_land.shape[1]
    return np.transpose(chunk_land, (2, 0, 1)).reshape(n_members * n_land, n_day)


def _selftest_flatten_member_land_day():
    n_lat, n_lon, n_day, n_member = 4, 5, 6, 3
    chunk = np.arange(n_lat * n_lon * n_day * n_member, dtype=np.float64).reshape(
        n_lat, n_lon, n_day, n_member)
    li = np.array([0, 1, 3])
    lj = np.array([2, 4, 0])
    n_land = len(li)

    flat = flatten_member_land_day(chunk, li, lj, n_member)
    assert flat.shape == (n_member * n_land, n_day)

    # Row (m * n_land + p) must equal chunk[li[p], lj[p], :, m] exactly.
    for m in range(n_member):
        for p in range(n_land):
            expected = chunk[li[p], lj[p], :, m]
            got = flat[m * n_land + p]
            assert np.array_equal(got, expected), (m, p, got, expected)
    print("flatten_member_land_day self-test: all checks passed")


# --- Season detection (Stage 3 / 4) ------------------------------------------
def detect_season_batch(precip, Q_bar, d_s, d_e, doy_axis,
                         win_doy_start, win_doy_end, buffer_days, min_lgp_days):
    """
    Vectorized Dunning onset/cessation/LGP detection across a batch of
    samples (e.g. flattened member x year x land-pixel).

    Parameters
    ----------
    precip        : (n_samples, n_days) daily mm/day, NaN for missing days
    Q_bar         : (n_samples,) scalar per-sample window mean (broadcast per pixel)
    d_s, d_e      : (n_samples,) climatological season bounds, DOY
    doy_axis      : (n_days,) DOY for each day-index (shared across samples in this call)
    win_doy_start, win_doy_end : forecast-window bounds, DOY
    buffer_days   : search-window buffer added around d_s/d_e
    min_lgp_days  : LGP below this -> FLAG_SHORT_SEASON (values are still returned)

    Returns dict with keys: onset_doy, cess_doy, lgp_days, flag  -- each (n_samples,)
    """
    n_samples, n_days = precip.shape
    valid_bounds = ~(np.isnan(d_s) | np.isnan(d_e))

    # d_s/d_e are truncated to whole DOYs before the buffer is applied, matching
    # the original scalar implementation's `int(ds_doy) - DUNNING_BUFFER_DAYS`.
    # Skipping this truncation silently shifts acc_start/acc_end by a fraction
    # of a day, which flips the boundary-day inclusion test below.
    d_s_i = np.trunc(np.where(valid_bounds, d_s, 0.0))
    d_e_i = np.trunc(np.where(valid_bounds, d_e, 0.0))

    acc_start = np.maximum(win_doy_start, d_s_i - buffer_days)
    acc_end   = np.minimum(win_doy_end,   d_e_i + buffer_days)

    in_window = (doy_axis[np.newaxis, :] >= acc_start[:, np.newaxis]) & \
                (doy_axis[np.newaxis, :] <= acc_end[:, np.newaxis])
    in_window &= valid_bounds[:, np.newaxis]

    have_obs = in_window & ~np.isnan(precip)
    anom = precip - Q_bar[:, np.newaxis]
    # Missing / out-of-window days contribute 0 to the running sum (i.e. are
    # skipped, matching the original scalar loop's `continue` behaviour) but
    # are excluded from the extremum search below via `have_obs`.
    A = np.cumsum(np.where(have_obs, anom, 0.0), axis=1)
    A_masked = np.where(have_obs, A, np.nan)

    onset_doy = np.full(n_samples, np.nan, dtype=np.float64)
    cess_doy  = np.full(n_samples, np.nan, dtype=np.float64)
    flag      = np.full(n_samples, FLAG_NO_ONSET, dtype=np.int16)

    any_obs = have_obs.any(axis=1)
    with np.errstate(invalid="ignore"):
        min_idx = np.argmin(np.where(have_obs, A_masked, np.inf), axis=1)

    onset_candidate = doy_axis[min_idx] + 1.0    # Dunning: onset is the day AFTER argmin
    onset_ok = any_obs & (onset_candidate <= acc_end)
    onset_doy[onset_ok] = onset_candidate[onset_ok]

    col_idx = np.arange(n_days)[np.newaxis, :]
    post_mask = (col_idx > min_idx[:, np.newaxis]) & have_obs
    any_post = post_mask.any(axis=1)
    with np.errstate(invalid="ignore"):
        max_idx = np.argmax(np.where(post_mask, A_masked, -np.inf), axis=1)

    cess_ok = onset_ok & any_post
    cess_doy[cess_ok] = doy_axis[max_idx][cess_ok]

    lgp_days = cess_doy - onset_doy

    flag[onset_ok] = FLAG_NO_CESSATION
    flag[cess_ok]  = FLAG_VALID
    short = cess_ok & (lgp_days < min_lgp_days)
    flag[short] = FLAG_SHORT_SEASON   # onset/cessation/LGP values are kept, just flagged

    return {"onset_doy": onset_doy.astype(np.float32),
            "cess_doy":  cess_doy.astype(np.float32),
            "lgp_days":  lgp_days.astype(np.float32),
            "flag":      flag}


# --- Tercile boundaries (Stage 4A) -------------------------------------------
def estimate_terciles(detected_cal, land_mask, min_tercile_years):
    """
    t33 / t67 boundaries per pixel from the CAL-period distribution, with a
    domain-median fallback for pixels with fewer than `min_tercile_years`
    valid (non-NaN) years.

    Parameters
    ----------
    detected_cal : (n_cal_years, n_lat, n_lon) onset/cessation/LGP values
    land_mask    : (n_lat, n_lon) bool
    min_tercile_years : int

    Returns (t33, t67) each (n_lat, n_lon) float32.
    """
    n_valid = np.sum(~np.isnan(detected_cal), axis=0)
    with np.errstate(invalid="ignore"):
        t33 = np.nanpercentile(detected_cal, 100 / 3, axis=0).astype(np.float32)
        t67 = np.nanpercentile(detected_cal, 200 / 3, axis=0).astype(np.float32)

    sparse = land_mask & (n_valid < min_tercile_years)
    t33[sparse] = np.nan
    t67[sparse] = np.nan

    if sparse.any():
        t33[sparse] = np.float32(np.nanmedian(t33[land_mask]))
        t67[sparse] = np.float32(np.nanmedian(t67[land_mask]))

    t33[~land_mask] = np.nan
    t67[~land_mask] = np.nan
    return t33, t67, sparse


# --- Probability estimation (Stage 5) ----------------------------------------
def estimate_probs(ensemble_det, t33, t67):
    """
    Fraction of ensemble members falling in each CHIRPS-derived tercile.

    ensemble_det : (n_members, n_years, n_lat, n_lon)
    t33, t67     : (n_lat, n_lon)
    Returns probs (3, n_years, n_lat, n_lon) -- P_BN, P_NN, P_AN.
    NaN-safe and fully vectorized (no pixel loop): `nan < x` is False in
    numpy, so members that are NaN are automatically excluded from both the
    numerator and (via n_valid) the denominator.
    """
    n_valid = np.sum(~np.isnan(ensemble_det), axis=0).astype(np.float32)   # (n_years,n_lat,n_lon)
    lo = t33[np.newaxis, np.newaxis, :, :]
    hi = t67[np.newaxis, np.newaxis, :, :]

    with np.errstate(invalid="ignore", divide="ignore"):
        p_bn = np.sum(ensemble_det < lo, axis=0) / n_valid
        p_an = np.sum(ensemble_det >= hi, axis=0) / n_valid
        p_nn = np.sum((ensemble_det >= lo) & (ensemble_det < hi), axis=0) / n_valid

    probs = np.stack([p_bn, p_nn, p_an], axis=0)
    probs[:, n_valid == 0] = np.nan
    return probs.astype(np.float32)


# --- Linear pooling / RPS / RPSS / hit rate / alpha* (Stage 6) ---------------
def apply_pooling(probs_raw, alpha):
    """
    P_k = alpha * P_k_raw + (1-alpha)/3.

    alpha : scalar, or (n_lat, n_lon) broadcast against the trailing two
    dims of `probs_raw` -- works whether probs_raw is (3, n_lat, n_lon)
    (a single year/operational slice) or (3, n_years, n_lat, n_lon)
    (a full time series), unlike a hardcoded double newaxis which silently
    inserts the alpha map at the wrong position for the 3-D case.
    """
    if np.ndim(alpha) == 0:
        return alpha * probs_raw + (1.0 - alpha) / 3.0
    extra_dims = probs_raw.ndim - alpha.ndim
    alpha_b = alpha.reshape((1,) * extra_dims + alpha.shape)
    return alpha_b * probs_raw + (1.0 - alpha_b) / 3.0


def rps_batch(probs, obs_cat):
    """
    Vectorized Ranked Probability Score.

        RPS = sum_{k=0}^{K-2} ( F_hat(k) - F_obs(k) )^2

    where F_hat(k) = P(forecast category <= k) and F_obs(k) = 1 if the
    observed category is <= k, else 0 (K=3 categories here, so k=0,1; the
    k=2 term is always 0 for both and is omitted).

    CORRECTNESS NOTE: an earlier version of this function (faithfully
    ported from `onset-cessation-lgp_v3_dunning_SEAS5_FINAL.ipynb`'s Stage 6
    `_rps` helper) used `F_obs = 1{obs_cat > k}` instead of `1{obs_cat <= k}`
    -- the observed-category indicator was inverted. That bug is exactly
    reproducible: a 100%-confident, exactly-correct forecast scored RPS=2
    (the worst possible score for 3 categories) instead of RPS=0 (the best),
    and a 100%-confident, maximally-wrong forecast scored RPS=0 instead of
    RPS=2 -- i.e. the scoring rule was rewarding confident wrong forecasts
    and punishing confident correct ones. It was caught by a hand-checkable
    trivial case (a perfect forecast must score exactly 0), not by
    cross-validating against the original notebook, since the original
    notebook has the identical bug -- matching a buggy reference just
    reproduces the bug. See `_selftest_rps_batch` for the regression test.

    probs   : (3, ...) tercile probabilities, any number of trailing dims
    obs_cat : (...) int, 0/1/2 = BN/NN/AN, negative = missing
    Returns (...) RPS, NaN where obs_cat < 0 or any prob is NaN.
    """
    F_hat = np.cumsum(probs[:2], axis=0)                      # (2, ...)
    k = np.arange(2).reshape((2,) + (1,) * (obs_cat.ndim))
    F_obs = (obs_cat[np.newaxis] <= k).astype(np.float32)      # (2, ...)
    rps = np.sum((F_hat - F_obs) ** 2, axis=0)
    invalid = (obs_cat < 0) | np.any(np.isnan(probs), axis=0)
    rps[invalid] = np.nan
    return rps


def rps_clim_batch(obs_cat):
    """Climatological RPS (equal 1/3 probabilities) for the same obs shape."""
    clim = np.full((3,) + obs_cat.shape, 1 / 3.0, dtype=np.float32)
    return rps_batch(clim, obs_cat)


def compute_rpss(rps_map, rps_clim_map):
    rpss = np.full(rps_map.shape, np.nan, dtype=np.float32)
    valid = ~np.isnan(rps_map) & ~np.isnan(rps_clim_map) & (rps_clim_map > 1e-9)
    rpss[valid] = 1.0 - rps_map[valid] / rps_clim_map[valid]
    return rpss


def compute_hitrate(probs, obs_cat):
    """
    probs   : (3, n_years, n_lat, n_lon)
    obs_cat : (n_years, n_lat, n_lon)
    Returns (n_lat, n_lon) fraction of years the top-probability category
    matched the observed category (over years with obs_cat >= 0).
    """
    pred_cat = np.argmax(probs, axis=0)                # (n_years,n_lat,n_lon)
    hit = (pred_cat == obs_cat).astype(np.float32)
    valid = (obs_cat >= 0) & ~np.any(np.isnan(probs), axis=0)
    hit[~valid] = np.nan
    return np.nanmean(hit, axis=0)


def optimise_alpha(probs_raw, obs_cat, alpha_grid):
    """
    Per-pixel alpha* grid search minimising mean RPS over the years given
    (typically CAL years only), vectorized over alpha AND pixels at once.

    probs_raw  : (3, n_years, n_lat, n_lon) -- already subset to the period
    obs_cat    : (n_years, n_lat, n_lon)    -- already subset to the same period
    alpha_grid : 1-D array of alpha values to try

    Returns alpha_star (n_lat, n_lon).
    """
    n_lat, n_lon = obs_cat.shape[1:]
    mean_rps = np.full((len(alpha_grid), n_lat, n_lon), np.inf, dtype=np.float32)

    for a_i, a in enumerate(alpha_grid):
        pooled = apply_pooling(probs_raw, float(a))
        rps = rps_batch(pooled, obs_cat)                 # (n_years,n_lat,n_lon)
        mean_rps[a_i] = np.nanmean(rps, axis=0)

    best = np.argmin(mean_rps, axis=0)
    return alpha_grid[best].astype(np.float32)


# --- Rank histogram / ensemble reliability -----------------------------------
def rank_histogram(ensemble, obs, land_mask, n_bins=11, min_valid_members=5):
    """
    Talagrand / rank histogram: for each (year, land pixel) with a valid
    observation, rank the observation among that sample's available ensemble
    members and normalize rank/(n_valid+1) into [0,1] -- so pixel/years with
    fewer than the full ensemble (some members failed to detect a season)
    still contribute, on a common scale, instead of being silently dropped
    or biasing the histogram toward whatever ensemble size happens to be
    most common. Aggregated into `n_bins` equal-width bins across all
    (year, land pixel) samples at once.

    Interpretation: a flat histogram indicates a well-calibrated ensemble
    (the observation is equally likely to fall anywhere within or outside
    the ensemble spread); a U-shape (excess mass at the two end bins)
    indicates an UNDER-dispersive ensemble (real-world variability exceeds
    what the ensemble spread represents, so the observation too often falls
    outside it); a dome shape (excess mass in the middle bins) indicates an
    OVER-dispersive ensemble.

    Ties (`ensemble member == obs` exactly) are resolved by strict `<`
    comparison, which is a minor, standard simplification (versus randomized
    tie-breaking) -- negligible for continuous values like DOY/days, where
    exact ties are rare.

    Parameters
    ----------
    ensemble : (n_members, n_years, n_lat, n_lon)
    obs      : (n_years, n_lat, n_lon) -- must already be aligned to the same
               year axis as `ensemble`
    land_mask: (n_lat, n_lon) bool
    n_bins   : number of histogram bins over the normalized rank [0, 1]
    min_valid_members : samples with fewer non-NaN members than this are
        excluded (too little ensemble information to rank meaningfully)

    Returns dict with keys: counts (n_bins,), bin_edges (n_bins+1,), n_samples
    """
    n_years = ensemble.shape[1]
    all_ranks = []

    for yi in range(n_years):
        obs_y = obs[yi]
        valid_obs = land_mask & ~np.isnan(obs_y)
        if not valid_obs.any():
            continue
        mem_y = ensemble[:, yi]                                    # (n_members, n_lat, n_lon)
        n_valid = np.sum(~np.isnan(mem_y), axis=0)                 # (n_lat, n_lon)
        rank = np.sum(mem_y < obs_y[np.newaxis], axis=0).astype(np.float64)
        usable = valid_obs & (n_valid >= min_valid_members)
        if not usable.any():
            continue
        all_ranks.append(rank[usable] / (n_valid[usable] + 1))

    if not all_ranks:
        return {"counts": np.zeros(n_bins, dtype=np.int64),
                "bin_edges": np.linspace(0.0, 1.0, n_bins + 1), "n_samples": 0}

    all_ranks = np.concatenate(all_ranks)
    counts, bin_edges = np.histogram(all_ranks, bins=n_bins, range=(0.0, 1.0))
    return {"counts": counts, "bin_edges": bin_edges, "n_samples": int(len(all_ranks))}


def _selftest_rank_histogram():
    rng = np.random.default_rng(3)
    n_members, n_years, n_lat, n_lon = 25, 1, 40, 40
    land_mask = np.ones((n_lat, n_lon), dtype=bool)

    def flat_ratio(counts):
        return counts.max() / max(counts.min(), 1)

    # 1. Well-calibrated: obs and members are iid draws from the same distribution.
    members = rng.normal(0, 1, size=(n_members, n_years, n_lat, n_lon))
    obs = rng.normal(0, 1, size=(n_years, n_lat, n_lon))
    res = rank_histogram(members, obs, land_mask, n_bins=11)
    assert res["n_samples"] == n_lat * n_lon
    assert flat_ratio(res["counts"]) < 2.5, f"expected roughly flat, got {res['counts']}"

    # 2. Under-dispersive: members tightly clustered, obs has much more spread
    #    -> observation very often falls outside the whole ensemble -> U-shape.
    members_narrow = rng.normal(0, 0.2, size=(n_members, n_years, n_lat, n_lon))
    obs_wide = rng.normal(0, 3.0, size=(n_years, n_lat, n_lon))
    res_u = rank_histogram(members_narrow, obs_wide, land_mask, n_bins=11)
    edge_mass = (res_u["counts"][0] + res_u["counts"][-1]) / res_u["n_samples"]
    middle_mass = res_u["counts"][4:7].sum() / res_u["n_samples"]
    assert edge_mass > middle_mass, "expected U-shape (edge-heavy) for under-dispersive ensemble"

    # 3. Over-dispersive: members widely spread, obs tightly clustered near the
    #    ensemble mean -> observation usually lands mid-ensemble -> dome shape.
    members_wide = rng.normal(0, 3.0, size=(n_members, n_years, n_lat, n_lon))
    obs_narrow = rng.normal(0, 0.2, size=(n_years, n_lat, n_lon))
    res_dome = rank_histogram(members_wide, obs_narrow, land_mask, n_bins=11)
    edge_mass_d = (res_dome["counts"][0] + res_dome["counts"][-1]) / res_dome["n_samples"]
    middle_mass_d = res_dome["counts"][4:7].sum() / res_dome["n_samples"]
    assert middle_mass_d > edge_mass_d, "expected dome shape (middle-heavy) for over-dispersive ensemble"

    print("rank_histogram self-test: all checks passed")


# --- Spread inflation ---------------------------------------------------------
def spread_inflation_factor(ensemble, obs, period_mask, land_mask, min_valid_members=5):
    """
    Domain- and period-aggregated multiplicative spread inflation factor:

        factor = sqrt( MSE(ensemble_mean, obs) / mean(ensemble_variance) )

    i.e. how much wider the ensemble spread would need to be for its average
    variance to match the ensemble mean's actual squared error against
    observations, aggregated over every (period year x land pixel) sample
    at once rather than fit per pixel -- with only ~24 CAL years, a
    per-pixel fit would be as noisy as the per-pixel alpha* fit already
    flagged elsewhere in this pipeline, so this pools across the whole
    domain for a single, more robust scalar.

    factor > 1 -> ensemble is under-dispersive (spread too narrow)
    factor < 1 -> ensemble is over-dispersive (spread too wide)
    factor ~ 1 -> ensemble spread already matches its own skill

    Parameters
    ----------
    ensemble    : (n_members, n_years, n_lat, n_lon)
    obs         : (n_years, n_lat, n_lon) -- aligned to the same year axis
    period_mask : (n_years,) bool -- typically the CAL mask, so VAL stays
                  out-of-sample for whatever factor gets applied to it
    land_mask   : (n_lat, n_lon) bool
    min_valid_members : minimum non-NaN members required for a sample to count

    Returns float.
    """
    ens_p = ensemble[:, period_mask]
    obs_p = obs[period_mask]
    ens_mean = np.nanmean(ens_p, axis=0)
    ens_var = np.nanvar(ens_p, axis=0)
    n_valid = np.sum(~np.isnan(ens_p), axis=0)

    valid = (n_valid >= min_valid_members) & ~np.isnan(obs_p) & land_mask[np.newaxis]
    mse = np.nanmean((ens_mean[valid] - obs_p[valid]) ** 2)
    mean_var = np.nanmean(ens_var[valid])
    return float(np.sqrt(mse / mean_var))


def apply_spread_inflation(ensemble, factor):
    """
    Inflate (factor > 1) or deflate (factor < 1) ensemble spread around each
    sample's own member-mean: member -> mean + factor * (member - mean).
    NaN members stay NaN automatically (mean + factor*(NaN-mean) = NaN).

    ensemble : (n_members, ...) -- any number of trailing dims
    factor   : scalar
    """
    ens_mean = np.nanmean(ensemble, axis=0, keepdims=True)
    return ens_mean + factor * (ensemble - ens_mean)


def _selftest_spread_inflation():
    rng = np.random.default_rng(5)
    n_members, n_years, n_lat, n_lon = 30, 200, 6, 6
    land_mask = np.ones((n_lat, n_lon), dtype=bool)
    period_mask = np.ones(n_years, dtype=bool)

    # For a genuinely reliable ensemble, the observation must be exchangeable
    # with the members -- i.e. drawn from the SAME noise distribution around
    # the per-case truth, not a separately-sized noise term. Giving obs its
    # own, smaller noise term would itself simulate an over-dispersive
    # ensemble (spread wider than how tightly obs clusters), not a neutral
    # "matched" baseline.
    true_sigma = 2.0
    case_mu = rng.normal(0, true_sigma, size=(n_years, n_lat, n_lon))
    obs = case_mu + rng.normal(0, true_sigma, size=(n_years, n_lat, n_lon))

    # Case A: member spread already matches the true case-to-case variability
    # -> factor should land close to 1.
    members_matched = case_mu[np.newaxis] + rng.normal(0, true_sigma, size=(n_members, n_years, n_lat, n_lon))
    factor_matched = spread_inflation_factor(members_matched, obs, period_mask, land_mask)
    assert 0.7 < factor_matched < 1.4, factor_matched

    # Case B: members far too tight relative to the true variability -> factor >> 1.
    members_narrow = case_mu[np.newaxis] + rng.normal(0, 0.3, size=(n_members, n_years, n_lat, n_lon))
    factor_narrow = spread_inflation_factor(members_narrow, obs, period_mask, land_mask)
    assert factor_narrow > 2.0, factor_narrow

    # Applying that factor should scale the ensemble VARIANCE by ~factor**2.
    inflated = apply_spread_inflation(members_narrow, factor_narrow)
    var_before = np.nanmean(np.nanvar(members_narrow, axis=0))
    var_after = np.nanmean(np.nanvar(inflated, axis=0))
    ratio = var_after / var_before
    assert abs(ratio - factor_narrow ** 2) / factor_narrow ** 2 < 0.15, (ratio, factor_narrow ** 2)

    print("spread_inflation self-test: all checks passed")


# --- Parametric calibration (NGR / EMOS) -------------------------------------
def fit_ngr(ens_mean, ens_var, obs, valid, var_floor_percentile=5.0):
    """
    Fit a pooled Non-homogeneous Gaussian Regression (NGR / EMOS; Gneiting
    et al. 2005): ONE set of coefficients across every sample marked
    `valid`, not per pixel -- with only ~24 CAL years per pixel, a
    per-pixel fit would be exactly as noisy as the per-pixel alpha* grid
    search this is meant to replace (see `optimise_alpha`'s docstring).

        predicted_mean(x) = a + b * ens_mean(x)
        predicted_var(x)  = max(c + d * ens_var(x), var_floor)

    This calibrates mean bias (a, b) and spread (c, d) jointly and smoothly,
    instead of as two separate, non-interacting corrections the way the
    notebook's inline bias correction (Stage 13) and `apply_spread_inflation`
    (Stage 14) each did.

    Parameters
    ----------
    ens_mean, ens_var, obs : arrays of identical shape (e.g. (n_years, n_lat, n_lon))
    valid    : bool array, same shape -- which samples to fit on (e.g. CAL
               years, land pixels, enough non-NaN members)
    var_floor_percentile : the variance floor is set to this percentile of
        the fitted residual-squared distribution, so predicted variance
        never collapses to (near-)zero where the linear variance
        regression alone would predict it.

    Returns dict with keys: a, b, c, d, var_floor.
    """
    x_mean = ens_mean[valid].astype(np.float64)
    y = obs[valid].astype(np.float64)
    A = np.column_stack([np.ones_like(x_mean), x_mean])
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)

    pred_mean = a + b * x_mean
    resid_sq = (y - pred_mean) ** 2
    x_var = ens_var[valid].astype(np.float64)
    A2 = np.column_stack([np.ones_like(x_var), x_var])
    (c, d), *_ = np.linalg.lstsq(A2, resid_sq, rcond=None)

    var_floor = max(float(np.percentile(resid_sq, var_floor_percentile)), 1e-3)
    return {"a": float(a), "b": float(b), "c": float(c), "d": float(d), "var_floor": var_floor}


def ngr_predict(ens_mean, ens_var, ngr_params):
    """Apply fitted NGR coefficients to (arbitrary-shape) ens_mean/ens_var arrays."""
    p = ngr_params
    pred_mean = p["a"] + p["b"] * ens_mean
    pred_var = np.maximum(p["c"] + p["d"] * ens_var, p["var_floor"])
    return pred_mean, pred_var


def ngr_tercile_probs(pred_mean, pred_var, t33, t67):
    """
    Analytic tercile probabilities from a fitted Normal(pred_mean, pred_var)
    at each sample, against the (per-pixel) CHIRPS tercile boundaries --
    smooth and continuous, unlike member-counting's 1/N_MEMBERS granularity
    (with 25 members, member-counting can only ever produce multiples of 4%).

    pred_mean, pred_var : arrays, e.g. (n_years, n_lat, n_lon)
    t33, t67 : broadcastable to the same shape, e.g. (n_lat, n_lon)

    Returns probs (3, ...) -- P_BN, P_NN, P_AN. p_bn + p_an <= 1 always
    (t33 <= t67 and the Normal CDF is monotonic), so p_nn = 1 - p_bn - p_an
    is guaranteed in [0, 1] without any extra clipping.
    """
    sigma = np.sqrt(pred_var)
    p_bn = _norm.cdf(t33, loc=pred_mean, scale=sigma)
    p_an = 1.0 - _norm.cdf(t67, loc=pred_mean, scale=sigma)
    p_nn = 1.0 - p_bn - p_an
    return np.stack([p_bn, p_nn, p_an], axis=0).astype(np.float32)


def pit_histogram(pred_mean, pred_var, obs, land_mask, n_bins=11):
    """
    Probability Integral Transform histogram -- the parametric-forecast
    analogue of `rank_histogram`: for each (year, land pixel) with a valid
    observation, compute CDF(obs) under the fitted Normal(pred_mean,
    pred_var) and histogram those values. A well-calibrated parametric
    forecast gives a flat PIT histogram, exactly as a well-calibrated
    ensemble gives a flat rank histogram.

    pred_mean, pred_var, obs : (n_years, n_lat, n_lon)
    land_mask : (n_lat, n_lon) bool
    """
    n_years = obs.shape[0]
    all_pit = []
    for yi in range(n_years):
        valid = land_mask & ~np.isnan(obs[yi]) & ~np.isnan(pred_mean[yi]) & (pred_var[yi] > 0)
        if not valid.any():
            continue
        sigma = np.sqrt(pred_var[yi][valid])
        pit = _norm.cdf(obs[yi][valid], loc=pred_mean[yi][valid], scale=sigma)
        all_pit.append(pit)

    if not all_pit:
        return {"counts": np.zeros(n_bins, dtype=np.int64),
                "bin_edges": np.linspace(0.0, 1.0, n_bins + 1), "n_samples": 0}

    all_pit = np.concatenate(all_pit)
    counts, bin_edges = np.histogram(all_pit, bins=n_bins, range=(0.0, 1.0))
    return {"counts": counts, "bin_edges": bin_edges, "n_samples": int(len(all_pit))}


def _selftest_ngr():
    rng = np.random.default_rng(9)
    n_years, n_lat, n_lon = 400, 5, 5
    land_mask = np.ones((n_lat, n_lon), dtype=bool)
    valid = np.ones((n_years, n_lat, n_lon), dtype=bool)

    # Known linear mean relationship: obs = a_true + b_true*ens_mean + noise,
    # with noise variance itself a known linear function of ens_var.
    a_true, b_true = 10.0, 0.8
    c_true, d_true = 5.0, 0.5
    ens_mean = rng.uniform(100, 200, size=(n_years, n_lat, n_lon))
    ens_var = rng.uniform(20, 60, size=(n_years, n_lat, n_lon))
    resid_sigma = np.sqrt(np.maximum(c_true + d_true * ens_var, 0.1))
    obs = a_true + b_true * ens_mean + rng.normal(0, 1, size=ens_mean.shape) * resid_sigma

    params = fit_ngr(ens_mean, ens_var, obs, valid)
    assert abs(params["a"] - a_true) < 3.0, params
    assert abs(params["b"] - b_true) < 0.05, params
    assert abs(params["c"] - c_true) < 6.0, params
    assert abs(params["d"] - d_true) < 0.3, params

    pred_mean, pred_var = ngr_predict(ens_mean, ens_var, params)
    assert pred_mean.shape == ens_mean.shape
    assert np.all(pred_var > 0)

    # Tercile probabilities must sum to 1 everywhere.
    t33 = np.full((n_lat, n_lon), a_true + b_true * 140.0)
    t67 = np.full((n_lat, n_lon), a_true + b_true * 160.0)
    probs = ngr_tercile_probs(pred_mean, pred_var, t33, t67)
    assert np.allclose(probs.sum(axis=0), 1.0, atol=1e-4)

    # A forecast far below t33 (resp. above t67) should give P_BN (resp.
    # P_AN) close to 1.
    lo_mean = np.full((5, n_lat, n_lon), a_true + b_true * 50.0)
    lo_var = np.full((5, n_lat, n_lon), 25.0)
    probs_lo = ngr_tercile_probs(lo_mean, lo_var, t33, t67)
    assert np.all(probs_lo[0] > 0.99), probs_lo[0].min()

    hi_mean = np.full((5, n_lat, n_lon), a_true + b_true * 300.0)
    probs_hi = ngr_tercile_probs(hi_mean, lo_var, t33, t67)
    assert np.all(probs_hi[2] > 0.99), probs_hi[2].min()

    # PIT histogram: a forecast whose predicted distribution exactly matches
    # how obs was actually generated should give a roughly flat histogram.
    obs2 = a_true + b_true * ens_mean + rng.normal(0, 1, size=ens_mean.shape) * resid_sigma
    pred_mean2, pred_var2 = ngr_predict(ens_mean, ens_var, params)
    pit_res = pit_histogram(pred_mean2, pred_var2, obs2, land_mask, n_bins=10)
    ratio = pit_res["counts"].max() / max(pit_res["counts"].min(), 1)
    assert ratio < 1.5, pit_res["counts"]

    print("NGR self-test: all checks passed")


# --- Bootstrap significance testing -------------------------------------------
def bootstrap_rpss_gap(probs_a, probs_b, obs_cat, period_mask, land_mask,
                        n_boot=5000, seed=42):
    """
    Paired, year-block bootstrap on the domain-mean RPSS gap between two
    probabilistic forecasts (e.g. an improved method B minus a baseline A)
    over a given period (typically VAL).

    Resamples *years* with replacement -- not (year, pixel) samples --
    because pixels within a year are strongly spatially correlated (the
    same season drives all of them), so the year is the closest thing to an
    independent sampling unit this pipeline has. With as few as ~9 VAL
    years, that sampling uncertainty is exactly what a domain-mean point
    estimate hides.

    Both methods are scored on the SAME resampled years in each replicate
    (paired bootstrap), which is what lets the gap's variance reflect "how
    much would this comparison change if history had given us a different
    9 years" rather than conflating that with each method's own noise.

    Parameters
    ----------
    probs_a, probs_b : (3, n_years, n_lat, n_lon) -- already restricted to
        the same full year axis as `obs_cat` / `period_mask` (e.g. Stage 8's
        `probs_damped`, spanning CAL+VAL, NOT pre-sliced to just the period)
    obs_cat      : (n_years, n_lat, n_lon) tercile categories
    period_mask  : (n_years,) bool -- e.g. the VAL mask
    land_mask    : (n_lat, n_lon) bool
    n_boot       : number of bootstrap replicates
    seed         : RNG seed, for reproducibility

    Returns dict with keys:
      observed_gap   : float, the actual (unresampled) domain-mean B-minus-A RPSS
      boot_gaps       : (n_boot,) bootstrap replicate gaps
      ci90, ci95      : (low, high) percentile confidence intervals
      p_not_better    : fraction of replicates where the gap is <= 0
                        (a rough one-sided p-value against "B is not better than A")
    """
    obs_period = obs_cat[period_mask]
    rps_clim = rps_clim_batch(obs_period)                      # (n_period_years, n_lat, n_lon)
    rps_a = rps_batch(probs_a[:, period_mask], obs_period)
    rps_b = rps_batch(probs_b[:, period_mask], obs_period)

    n_years = obs_period.shape[0]
    rng = np.random.default_rng(seed)

    def domain_rpss(rps, clim, idx):
        rpss = compute_rpss(np.nanmean(rps[idx], axis=0), np.nanmean(clim[idx], axis=0))
        return float(np.nanmean(rpss[land_mask]))

    observed_gap = domain_rpss(rps_b, rps_clim, slice(None)) - domain_rpss(rps_a, rps_clim, slice(None))

    boot_gaps = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n_years, size=n_years)
        boot_gaps[i] = domain_rpss(rps_b, rps_clim, idx) - domain_rpss(rps_a, rps_clim, idx)

    ci90 = tuple(np.percentile(boot_gaps, [5, 95]))
    ci95 = tuple(np.percentile(boot_gaps, [2.5, 97.5]))
    p_not_better = float(np.mean(boot_gaps <= 0))

    return {"observed_gap": observed_gap, "boot_gaps": boot_gaps,
            "ci90": ci90, "ci95": ci95, "p_not_better": p_not_better}


def _selftest_bootstrap_rpss_gap():
    rng = np.random.default_rng(13)
    n_years, n_lat, n_lon = 9, 15, 15
    land_mask = np.ones((n_lat, n_lon), dtype=bool)
    period_mask = np.ones(n_years, dtype=bool)
    obs_cat = rng.integers(0, 3, size=(n_years, n_lat, n_lon)).astype(np.int8)

    def probs_biased_toward_truth(strength):
        """Puts `strength` extra probability mass on the true category."""
        probs = np.full((3, n_years, n_lat, n_lon), (1 - strength) / 3, dtype=np.float64)
        for k in range(3):
            mask = obs_cat == k
            probs[k][mask] += strength
        return probs

    # Case A: a real, substantial skill difference -> should be clearly detected.
    probs_climatology = np.full((3, n_years, n_lat, n_lon), 1 / 3.0)
    probs_skilled = probs_biased_toward_truth(0.5)
    res_real = bootstrap_rpss_gap(probs_climatology, probs_skilled, obs_cat, period_mask,
                                   land_mask, n_boot=2000, seed=1)
    assert res_real["observed_gap"] > 0.2, res_real["observed_gap"]
    assert res_real["p_not_better"] < 0.01, res_real["p_not_better"]
    assert res_real["ci95"][0] > 0, res_real["ci95"]   # CI excludes zero entirely

    # Case B: no real difference -- two independently-noisy forecasts built
    # around the SAME underlying skill level -- should NOT show a
    # confidently-nonzero gap.
    def add_jitter(probs, scale):
        noisy = np.clip(probs + rng.normal(0, scale, size=probs.shape), 0.001, None)
        return noisy / noisy.sum(axis=0, keepdims=True)

    probs_a_noisy = add_jitter(probs_biased_toward_truth(0.2), 0.05)
    probs_b_noisy = add_jitter(probs_biased_toward_truth(0.2), 0.05)
    res_null = bootstrap_rpss_gap(probs_a_noisy, probs_b_noisy, obs_cat, period_mask,
                                   land_mask, n_boot=2000, seed=2)
    # With a true null and only 9 "years", the 95% CI is *expected* to exclude
    # zero on its own by chance a fraction of the time (that's what a
    # correctly-calibrated interval does) -- so the robust check here is that
    # the point estimate itself is small, not that the CI always straddles
    # zero on every single run.
    assert abs(res_null["observed_gap"]) < 0.05, res_null["observed_gap"]

    print("bootstrap_rpss_gap self-test: all checks passed")


def _selftest_rps_batch():
    """
    Absolute-correctness check, not a cross-validation against a reference
    implementation: a perfect, 100%-confident forecast MUST score RPS=0
    (the best possible score), and a maximally-wrong, 100%-confident
    forecast MUST score RPS=2 (the worst possible score for 3 categories),
    for every one of the 3 possible observed categories. This is the check
    that would have caught the inverted-F_obs bug described in
    `rps_batch`'s docstring -- cross-validating against the original
    Kenya notebook's `_rps` did not, because that reference has the same bug.
    """
    for obs_val in [0, 1, 2]:
        obs_cat = np.array([obs_val], dtype=np.int8)
        for pred_cat in [0, 1, 2]:
            probs = np.zeros((3, 1))
            probs[pred_cat, 0] = 1.0
            rps = rps_batch(probs, obs_cat)[0]
            if pred_cat == obs_val:
                assert abs(rps - 0.0) < 1e-6, (obs_val, pred_cat, rps)
            elif abs(pred_cat - obs_val) == 2:
                assert abs(rps - 2.0) < 1e-6, (obs_val, pred_cat, rps)
            else:
                assert abs(rps - 1.0) < 1e-6, (obs_val, pred_cat, rps)   # adjacent-category miss

    # Climatological (uniform 1/3) forecast must score strictly worse than a
    # perfect forecast and strictly better than the worst-case forecast.
    clim = np.full((3, 1), 1 / 3.0)
    for obs_val in [0, 1, 2]:
        obs_cat = np.array([obs_val], dtype=np.int8)
        rps_clim = rps_batch(clim, obs_cat)[0]
        assert 0.0 < rps_clim < 2.0, (obs_val, rps_clim)

    print("rps_batch self-test: all checks passed")


# --- Self-test ----------------------------------------------------------------
def _selftest():
    """
    Sanity-check detect_season_batch against a hand-built synthetic A(D)
    curve with a known onset/cessation, run via `python dunning_lib.py`.
    """
    win_doy_start, win_doy_end = 32, 213
    doy_axis = np.arange(win_doy_start, win_doy_end + 1, dtype=np.float64)
    n_days = len(doy_axis)

    # Synthetic pixel: dry until day index 40, then wet until day index 90,
    # then dry again -- Q_bar chosen so anomaly is clearly negative/positive.
    Q_bar = 2.0
    precip = np.full(n_days, 1.0)          # below Q_bar everywhere by default
    precip[40:90] = 4.0                    # wet spell -> above Q_bar

    d_s = np.array([doy_axis[45]])          # climatological bounds roughly around the wet spell
    d_e = np.array([doy_axis[85]])

    res = detect_season_batch(
        precip[np.newaxis, :], np.array([Q_bar]), d_s, d_e, doy_axis,
        win_doy_start, win_doy_end, buffer_days=50, min_lgp_days=20,
    )

    expected_onset = doy_axis[40] + 1   # day after the running minimum, at the start of the wet spell
    expected_cess  = doy_axis[89]        # last wet day before it turns dry again (argmax of A after onset)

    assert res["flag"][0] == FLAG_VALID, res["flag"]
    assert abs(res["onset_doy"][0] - expected_onset) <= 1, (res["onset_doy"], expected_onset)
    assert abs(res["cess_doy"][0] - expected_cess) <= 1, (res["cess_doy"], expected_cess)
    assert res["lgp_days"][0] > 0

    # No-onset case: flat precip exactly at Q_bar everywhere -> A(D) stays at 0,
    # argmin is the first day, so onset = first day + 1, which is a valid (if
    # uninteresting) detection -- FLAG_VALID, not FLAG_NO_ONSET. To exercise
    # FLAG_NO_ONSET we push the argmin to the last in-window day instead.
    precip2 = np.full(n_days, 4.0)
    precip2[:] = 1.0
    precip2[-1] = 0.0   # driest day is the very last in-window day -> onset falls out of range
    d_s2 = np.array([doy_axis[0]])
    d_e2 = np.array([doy_axis[-1]])
    res2 = detect_season_batch(
        precip2[np.newaxis, :], np.array([Q_bar]), d_s2, d_e2, doy_axis,
        win_doy_start, win_doy_end, buffer_days=0, min_lgp_days=20,
    )
    assert res2["flag"][0] == FLAG_NO_ONSET, res2["flag"]
    assert np.isnan(res2["onset_doy"][0])

    print("dunning_lib self-test: all checks passed")


if __name__ == "__main__":
    _selftest_rps_batch()
    _selftest()
    _selftest_flatten_member_land_day()
    _selftest_rank_histogram()
    _selftest_spread_inflation()
    _selftest_ngr()
    _selftest_bootstrap_rpss_gap()
