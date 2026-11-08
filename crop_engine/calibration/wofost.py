#!/usr/bin/env python3
"""
WOFOST's maize yield level, calibrated as AquaCrop's was (calibration set kiboko_v3): medium maize under full
irrigation (WOFOST's potential production, Wofost72_PP: no water or nutrient limitation) at KARI Kiboko in the 2012
dry season, sown every 14 days from 1 Jun to 31 Jul, should yield what Duma 43 yielded well watered there in 2012
(7.76 t/ha, Ngugi, Collins & Muchira 2013, Table 5).

WOFOST has no harvest index: the fitted parameter is AMAXTB_scale, one factor on the crop's light-saturated leaf
photosynthesis table (AMAXTB, kg CO2 ha-1 h-1 by development stage), a standard WOFOST calibration parameter.
Phenology stays on AquaCrop's calibrated targets (wofost_adapter.phenology), so yield alone is fitted, and the one
number carries every difference between the model's potential yield and the trial's (management, grain moisture,
the trial's density: WOFOST has no plant population). Early maize takes the same factor (as HI0 in kiboko_v3) and is
checked against the Local Katumani composite (3.02 t/ha) and the IITA 2013 Kiboko trials (median 4.5, best 7.4).
Sorghum has no well-watered trial near the sites: it keeps WOFOST's own table.

Weather: the site's ERA5-Land temperature, solar radiation, vapour pressure and wind (crop_engine.data.era5land).

Usage: python -m crop_engine.calibration.wofost            # fit, check, print (varieties.yaml is edited by hand)
"""
import argparse
import datetime as dt
import sys
import warnings

import numpy as np
import pandas as pd

from crop_engine import run_outlook as ro
from crop_engine.adapters import wofost_adapter as wf
from crop_engine.data import era5land
from crop_engine.data.sites import registered_sites

SITE = "kalro_kiboko_makueni_farm"
TRAIN = {"variety": "maize_medium", "observed_t_ha": 7.76, "year": 2012,
         "source": "Duma 43, well watered, KARI Kiboko 2012 (Ngugi et al. 2013, Table 5)"}
CHECKS = [{"variety": "maize_early", "observed_t_ha": 3.02, "year": 2012,
           "source": "Local Katumani composite, well watered, KARI Kiboko 2012 (Ngugi et al. 2013)"},
          {"variety": "maize_early", "observed_t_ha": 4.5, "year": 2013,
           "source": "IITA 2013 Kiboko trials, median (best 7.4)"}]
RANGE = (0.3, 1.5)
DAYS = 300


def sowings(year):
    return [d.date() for d in pd.date_range(f"{year}-06-01", f"{year}-07-31", freq="14D")]


def potential(variety, scale, site, temps, met, plant, elev):
    """WOFOST potential production of the variety sown on `plant` with AMAXTB × scale → (yield t/ha, maturity)."""
    from pcse.base import ParameterProvider
    from pcse.models import Wofost72_PP
    warnings.filterwarnings("ignore")
    dates = pd.date_range(plant, periods=DAYS)
    t, m = temps.reindex(dates), met.reindex(dates)
    if t.isna().any().any() or m[era5land.MET].isna().any().any():
        return None, None
    crop, name, over, base = wf.phenology(dict(variety, wofost={"AMAXTB_scale": scale}))
    task = {"tmax": t.tmax.values[None], "tmin": t.tmin.values[None], "rain": np.zeros((1, DAYS)),
            "rad": m.rad_mj_m2.values[None], "vap": m.vap_hpa.values[None], "wind2": m.wind2_ms.values[None],
            "et0": np.full((1, DAYS), 5.0), "lat": site.lat, "lon": site.lon, "elev": elev}
    p = wf._cropdata()
    p.set_active_crop(crop, name)
    soil, sitedata = wf.soil_parameters([_LOAM], 1.0)
    params = ParameterProvider(cropdata=p, soildata=soil, sitedata=sitedata)
    for k, v in over.items():
        params.set_override(k, v, check=False)
    agro = [{dates[0].date(): {"CropCalendar": {
        "crop_name": crop, "variety_name": name, "crop_start_date": plant, "crop_start_type": "sowing",
        "crop_end_date": None, "crop_end_type": "maturity", "max_duration": DAYS - 1},
        "TimedEvents": None, "StateEvents": None}}, {dates[-1].date(): None}]
    model = Wofost72_PP(params, wf._weather(task, 0, dates), agro)
    model.run_till_terminate()
    out = pd.DataFrame(model.get_output()).set_index("day")
    mat = out[out.DVS >= 2.0]
    if mat.empty:
        return None, None
    return float(out.TWSO.max()) / 1000.0, mat.index[0]


class _Layer:                                                   # a generic loam: no water limitation in PP anyway
    top_cm, bottom_cm, sand, clay, om, cfvo, theta_fc, theta_wp = 0, 200, 40, 20, 1.5, 0, 0.30, 0.14


_LOAM = _Layer()


def mean_potential(variety, scale, site, temps, met, year, elev):
    ys = [potential(variety, scale, site, temps, met, d, elev)[0] for d in sowings(year)]
    ys = [y for y in ys if y is not None]
    return float(np.mean(ys)) if ys else None


def fit(variety, target, site, temps, met, year, elev, tol=0.02):
    """AMAXTB_scale whose mean potential yield over the sowing window is `target` (bisection on RANGE)."""
    lo, hi = RANGE
    y_lo, y_hi = (mean_potential(variety, s, site, temps, met, year, elev) for s in (lo, hi))
    if not (y_lo <= target <= y_hi):
        raise ValueError(f"target {target} t/ha outside {y_lo:.2f}–{y_hi:.2f} over the scale range {RANGE}")
    for _ in range(30):
        mid = (lo + hi) / 2
        y = mean_potential(variety, mid, site, temps, met, year, elev)
        if abs(y - target) < tol:
            return round(mid, 3), y
        lo, hi = (mid, hi) if y < target else (lo, mid)
    return round((lo + hi) / 2, 3), y


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    site = next(s for s in registered_sites() if s.id == SITE)
    temps = era5land.site_temperature(site, refresh=False)
    met = era5land.site_met([site], refresh=False)[site.id]
    from crop_engine.config import CAL_YEARS
    import fao_water_balance as fw  # noqa: E402
    cal = met[(met.index.year >= CAL_YEARS[0]) & (met.index.year <= CAL_YEARS[1])]
    elev = float(fw.elevation_from_pressure(float(cal.sp_kpa.mean())))
    _, varieties = ro.load_varieties(["maize_early", "maize_medium"])
    v = varieties[TRAIN["variety"]]
    print(f"[{dt.datetime.now():%H:%M:%S}] WOFOST {TRAIN['variety']}, full irrigation, Kiboko {TRAIN['year']}: "
          f"WOFOST's own table {mean_potential(v, 1.0, site, temps, met, TRAIN['year'], elev):.2f} t/ha")
    scale, y = fit(v, TRAIN["observed_t_ha"], site, temps, met, TRAIN["year"], elev)
    print(f"  fitted AMAXTB_scale {scale}: {y:.2f} t/ha against {TRAIN['observed_t_ha']} ({TRAIN['source']})")
    for c in CHECKS:
        vv = varieties[c["variety"]]
        own = mean_potential(vv, 1.0, site, temps, met, c["year"], elev)
        cal_ = mean_potential(vv, scale, site, temps, met, c["year"], elev)
        print(f"  check {c['variety']} {c['year']}: {own:.2f} → {cal_:.2f} t/ha against {c['observed_t_ha']} "
              f"({c['source']}; upper bound)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
