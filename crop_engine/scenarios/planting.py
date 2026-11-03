"""
Sowing dates from the platform's onset methods. The methods' own outputs are used unchanged:

  forecast runs   each member's onset from forecast_runs.Methods.run (the dates the dashboard shows for that run)
  observed years  Agri rules: onset_rules.apply_rule on the site's observed CHIRPS v2 from 15 Aug (as the hindcasts);
                  FAO agricultural onset: the FAO water balance's historical run (outputs/fao_wb/historical)

A member or year without an onset by the method's search end (15 Jan) has no sowing date: "no planting opportunity".
"""
import datetime as dt

import numpy as np
import pandas as pd
import xarray as xr

from crop_engine import config as C

import onset_rules as orl  # noqa: E402

FAO_HIST = C.BASE / "outputs" / "fao_wb" / "historical" / "fao_wb_seasons.nc"
LATE = orl.LATE


def doy_to_date(doy, season_year, t0=213):
    """A season DOY (no-leap numbering from 1 Jan of the season year; > 365 = next year) → date, None for none.
    The FAO season starts on 1 Aug (DOY t0) in every year, so dates count from 1 Aug of the season year."""
    if doy is None or not np.isfinite(doy) or doy >= LATE:
        return None
    return dt.date(season_year, 8, 1) + dt.timedelta(days=int(round(doy)) - t0)


def forecast_dates(results, sites, season_year, rule_key):
    """{site id: [date or None per member]} from Methods.run results for one planting rule."""
    on = results[C.PLANTING_RULES[rule_key]["method"]]["onset"][0]            # (member, lat, lon)
    return {s.id: [doy_to_date(v, season_year) for v in on[:, s.i, s.j]] for s in sites}


def observed_rule_date(rain, dates, pet, rule_key):
    """Onset of an Agri rule in one observed season: rain (T,) and dates of the season (from 1 Aug), pet (n,) from
    15 Aug (onset_rules.load_pet with 59 extension days) → date or None."""
    k = int(rule_key.replace("rule", ""))
    start = np.where((dates.month == 8) & (dates.day == 15))[0][0]
    n = len(pet)
    x = rain[start:start + n][None].astype(np.float32)
    if x.shape[1] < n:
        return None
    on, _, _ = orl.apply_rule(x, pet[None].astype(np.float32), orl.RULES[k])
    if not np.isfinite(on[0]):
        return None
    return (dates[start] + pd.Timedelta(days=int(on[0]) - orl.SEARCH_START_DOY)).date()


def observed_fao_dates(sites, years):
    """{site id: {year: date or None}} FAO agricultural onset of the historical FAO water-balance run."""
    with xr.open_dataset(FAO_HIST) as ds:
        da = ds["agricultural_onset_doy"]
        out = {}
        for s in sites:
            v = da.sel(lat=s.cell_lat, lon=s.cell_lon, method="nearest")
            have = set(int(y) for y in v.year.values)
            out[s.id] = {y: (doy_to_date(float(v.sel(year=y)), y) if y in have else None) for y in years}
    return out
