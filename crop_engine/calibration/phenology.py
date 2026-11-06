"""Phenology of a variety at a site: days from sowing to a stage in the site's daily temperatures, the fit of the
variety's maturity days to observed days, and the scores of a fit.

The days are counted as the AquaCrop adapter counts them for its expected maturity: growing degree days from the
sowing day (AquaCrop's method 3, the crop's Tbase and Tupp) until their sum passes the stage's GDD.
"""
import numpy as np
import pandas as pd
from aquacrop.entities.crop import crop_params

from crop_engine.adapters.aquacrop_adapter import crop_parameters, gdd

STAGE = {"days_to_flowering": "HIstart", "days_to_maturity": "Maturity"}


def sowing_dates(windows):
    """Every day of each window [{start, end, label}] → DatetimeIndex."""
    days = [pd.date_range(w["start"], w["end"], freq="D") for w in windows]
    return days[0].append(days[1:]) if days else pd.DatetimeIndex([])


def cumulative_gdd(temps, crop, dates, horizon=400):
    """Cumulative GDD from each sowing date over the next `horizon` days → (len(dates), horizon); NaN past the data."""
    p = crop_params[crop]
    g = pd.Series(gdd(temps.tmax.values, temps.tmin.values, p["Tbase"], p["Tupp"]), index=temps.index)
    out = np.full((len(dates), horizon), np.nan)
    for i, d in enumerate(dates):
        v = g.loc[d:].values[:horizon]
        out[i, : len(v)] = np.cumsum(v)
    return out


def days_to(cum, target):
    """Days from sowing (0 = the sowing day) until the cumulative GDD passes `target`, per sowing date; NaN if the
    data end first."""
    passed = cum > target
    reached = passed.any(axis=1)
    return np.where(reached, np.argmax(passed, axis=1), np.nan).astype(float)


def stage_gdd(variety, reference_tmean, target, maturity_days=None):
    """GDD of the target's AquaCrop stage for the variety (with maturity_days in place of its own, if given)."""
    v = dict(variety, maturity_days=maturity_days or variety["maturity_days"])
    return crop_parameters(v, reference_tmean)[0][STAGE[target]]


def fit_maturity_days(groups, variety, reference_tmean, lo=40, hi=260):
    """The whole number of maturity days (at reference_tmean) whose model median days to each group's stage best
    match the groups' observed medians (least squares over the groups; ties → nearest the variety's own value).
    groups: [{"target", "cum" (sowing date, day), "observed" (values)}] → (maturity_days, {days: objective})."""
    obj = {}
    for md in range(lo, hi + 1):
        err = [np.nanmedian(days_to(g["cum"], stage_gdd(variety, reference_tmean, g["target"], md)))
               - float(np.median(g["observed"])) for g in groups]
        obj[md] = float(np.mean(np.square(err)))
    best = min(obj.values())
    ties = [md for md, v in obj.items() if v <= best + 1e-9]
    return min(ties, key=lambda md: (abs(md - variety["maturity_days"]), md)), obj


def score(model_days, observed):
    """Model days (one per sowing date) against observed values (one per entry)."""
    m = model_days[np.isfinite(model_days)]
    obs = np.asarray(observed, float)
    med = float(np.median(m)) if len(m) else float("nan")
    return {"n_obs": int(len(obs)), "obs_median": round(float(np.median(obs)), 1),
            "obs_min": round(float(obs.min()), 1), "obs_max": round(float(obs.max()), 1),
            "model_median": round(med, 1), "model_min": float(m.min()) if len(m) else None,
            "model_max": float(m.max()) if len(m) else None,
            "bias_days": round(med - float(np.median(obs)), 1),
            "mae_days": round(float(np.mean(np.abs(obs - med))), 1),
            "obs_median_in_model_range": bool(len(m) and m.min() <= np.median(obs) <= m.max())}
