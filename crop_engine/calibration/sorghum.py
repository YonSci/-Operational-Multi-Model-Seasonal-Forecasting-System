#!/usr/bin/env python3
"""
Sorghum (the Gadam-type class) for both engines: phenology with flowering set apart from maturity, and WOFOST's
yield level matched to AquaCrop's.

Phenology. kiboko_v2 could not fit the class with one parameter: Gadam's flowering at the University of Embu farm
(65.3 days, LR 2020, Shinda et al. 2021, Table 2) matched the class, its maturity there (97.7 days) needed a
shorter one. With `flowering_days` (aquacrop_adapter.crop_parameters, wofost_adapter.phenology) the two are fitted
separately on the same trial: maturity_days to the maturity, then flowering_days to the flowering, both at Embu's
ERA5-Land temperatures over the trial's sowing window (15 Mar – 15 May 2020), as calibration.run counts them.
Checks: the days at Kiboko for Short Rains sowings (20 Oct – 30 Nov, 1993–2025) against the catalogue ranges
(KALRO: maturity 2.5–3 months; seed trade: flowering 45–52, maturity 85–90 days; not trials) and the Koima et al.
2023 Kiboko trial (maturity scored once, 105 days: weak); the flowering of the 2016 Mpambaa (Tanzania) short-
duration trial (71 days) has no location to compute it at and is quoted only.

Decision rule: the fitted phenology is adopted only if it also passes the checks: maturity at Kiboko within the
catalogue's 75–90 days and AquaCrop's no-water-stress yield at least the lower Kampi ya Mawe yield; otherwise the
class keeps its phenology (the first result, November 2026: Embu fitted, maturity_days 100 → 85 with flowering_days
59, but Kiboko maturity 84 → 71 days and the no-stress yield 4.97 → 4.14 t/ha: both checks fail, not adopted).

Yield level. No irrigated Gadam trial was found in East Africa. AquaCrop's sorghum keeps HI0 0.30 (set against the
Kiboko trials' harvest index, 0.28); its no-water-stress yield at Kiboko for Short Rains 2012 sowings is checked
against the best fertilised Gadam yields of that season at KARI Kampi ya Mawe, about 40 km away (4.86 t/ha with
N75-P50, 5.39 with NP50 and manure; Mwadalu et al. 2022, Tables 2–3; rainfed, over 540 mm: an upper bound's floor).
WOFOST's AMAXTB_scale is fitted so its potential production (Wofost72_PP) over the same sowings equals AquaCrop's
no-water-stress yield: the two engines then share the sorghum yield level and differ in their response to water.

Writes outputs/crop_engine/calibration/sorghum/result.json; varieties.yaml is edited by hand, citing it.
Usage: python -m crop_engine.calibration.sorghum
"""
import argparse
import datetime as dt
import json
import sys
import warnings

import numpy as np
import pandas as pd

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.calibration import phenology as ph
from crop_engine.calibration import run as cr
from crop_engine.calibration import wofost as cw
from crop_engine.calibration.potential import irrigated_potential
from crop_engine.data import era5land
from crop_engine.data.sites import registered_sites

EMBU = {"id": "university_of_embu_farm", "name": "University of Embu farm (1463 m)", "lat": -0.5903, "lon": 37.4253}
EMBU_SOWING = [{"start": "2020-03-15", "end": "2020-05-15"}]
TRAIN = {"days_to_flowering": 65.3, "days_to_maturity": 97.7}
TRAIN_SOURCE = "Gadam, University of Embu farm, LR 2020 (Shinda et al. 2021, J. Exp. Biol. Agric. Sci. 9(4), Table 2)"
SITE = "kalro_kiboko_makueni_farm"
SR_SOWING = ("10-20", "11-30")
CATALOGUE_MATURITY = (75, 90)    # days, KALRO "2.5–3 months" and the seed trade's 85–90 (catalogue ranges)
KOIMA = {"days_to_maturity": 105, "year": 2020, "source": "Koima et al. 2023, Kiboko SR 2020, one scoring date (weak)"}
YIELD_YEAR = 2012
YIELD_CHECK = {"t_ha": [4.86, 5.39], "source": "Gadam, KARI Kampi ya Mawe SR 2012, N75-P50 / NP50 + 10 t manure, "
                                                "rainfed (Mwadalu et al. 2022, IJAEB 15(1), Tables 2–3)"}
OUT = cr.OUT / "sorghum"


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] sorghum: {m}", flush=True)


def days(cum, v, ref, target):
    kw, _ = aq.crop_parameters(v, ref)
    return float(np.nanmedian(ph.days_to(cum, kw[ph.STAGE[target]])))


def fit_flowering(cum, v, ref, observed):
    """The whole number of flowering days (at ref) whose median days to flowering best match `observed`."""
    best = None
    for fd in range(30, int(v["maturity_days"]) - 5):
        d = days(cum, dict(v, flowering_days=fd), ref, "days_to_flowering")
        if best is None or abs(d - observed) < abs(best[1] - observed) - 1e-9:
            best = (fd, d)
    return best


def sr_sowings(years):
    return pd.DatetimeIndex([d for y in years for d in pd.date_range(f"{y}-{SR_SOWING[0]}", f"{y}-{SR_SOWING[1]}", freq="D")])


def wofost_fit(v, target, site, temps, met, plants, elev, tol=0.02):
    """AMAXTB_scale whose mean WOFOST potential over `plants` is `target` (bisection on calibration.wofost.RANGE)."""
    def mean(s):
        ys = [cw.potential(v, s, site, temps, met, p, elev)[0] for p in plants]
        ys = [y for y in ys if y is not None]
        return float(np.mean(ys)) if ys else None
    lo, hi = cw.RANGE
    own = mean(1.0)
    y_lo, y_hi = mean(lo), mean(hi)
    if not (y_lo <= target <= y_hi):
        raise ValueError(f"target {target:.2f} t/ha outside {y_lo:.2f}–{y_hi:.2f} over {cw.RANGE}")
    for _ in range(30):
        mid = (lo + hi) / 2
        y = mean(mid)
        if abs(y - target) < tol:
            break
        lo, hi = (mid, hi) if y < target else (lo, mid)
    return round(mid, 3), y, own


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    warnings.filterwarnings("ignore")
    ref, varieties = ro.load_varieties(["sorghum"])
    v0 = {k: x for k, x in varieties["sorghum"].items() if k not in ("kw", "scale")}
    res = {"created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "train": TRAIN_SOURCE}

    # ── phenology at Embu ──
    embu = cr.location_temperature(EMBU)
    cum = ph.cumulative_gdd(embu, v0["aquacrop_crop"], ph.sowing_dates(EMBU_SOWING))
    md, _ = ph.fit_maturity_days([{"target": "days_to_maturity", "cum": cum, "observed": [TRAIN["days_to_maturity"]]}],
                                 v0, ref)
    v1 = dict(v0, maturity_days=md)
    fd, fl = fit_flowering(cum, v1, ref, TRAIN["days_to_flowering"])
    v1["flowering_days"] = fd
    res["fit"] = {"maturity_days": [v0["maturity_days"], md], "flowering_days": fd}
    res["embu"] = {name: {t: round(days(cum, v, ref, t), 1) for t in TRAIN} for name, v in (("before", v0), ("after", v1))}
    log(f"fit at Embu: maturity_days {v0['maturity_days']} → {md}, flowering_days {fd}")
    for name in ("before", "after"):
        e = res["embu"][name]
        log(f"  {name:6s} Embu: flowering {e['days_to_flowering']} (observed {TRAIN['days_to_flowering']}), maturity "
            f"{e['days_to_maturity']} (observed {TRAIN['days_to_maturity']})")

    # ── checks at Kiboko ──
    site = next(s for s in registered_sites() if s.id == SITE)
    temps = era5land.site_temperature(site, refresh=False)
    cum_k = ph.cumulative_gdd(temps, v0["aquacrop_crop"], sr_sowings(range(1993, 2026)))
    cum_koima = ph.cumulative_gdd(temps, v0["aquacrop_crop"], sr_sowings([KOIMA["year"]]))
    res["kiboko_sr"] = {name: {t: round(days(cum_k, v, ref, t), 1) for t in TRAIN} for name, v in (("before", v0), ("after", v1))}
    res["koima"] = {name: round(days(cum_koima, v, ref, "days_to_maturity"), 1) for name, v in (("before", v0), ("after", v1))}
    for name in ("before", "after"):
        k = res["kiboko_sr"][name]
        log(f"  {name:6s} Kiboko SR sowings 1993–2025: flowering {k['days_to_flowering']}, maturity {k['days_to_maturity']} "
            f"(catalogue: flowering 45–52, maturity 75–90); SR 2020 maturity {res['koima'][name]} (Koima: 105, weak)")

    # ── yield level: AquaCrop's no-water-stress yield; the decision; WOFOST matched to the adopted class ──
    plants = list(pd.date_range(f"{YIELD_YEAR}-{SR_SOWING[0]}", f"{YIELD_YEAR}-{SR_SOWING[1]}", freq="14D").date)

    def aq_potential(v):
        kw, _ = aq.crop_parameters(v, ref)
        ys = [irrigated_potential(v["aquacrop_crop"], kw, temps, p, site.lat)["yield_t_ha"] for p in plants]
        return float(np.mean([y for y in ys if y is not None]))
    aq_pot0, aq_pot1 = aq_potential(v0), aq_potential(v1)
    log(f"AquaCrop no-water-stress yield, Kiboko SR {YIELD_YEAR} sowings: {aq_pot0:.2f} → {aq_pot1:.2f} t/ha "
        f"(check: at least {YIELD_CHECK['t_ha']} t/ha, {YIELD_CHECK['source']})")
    mat1 = res["kiboko_sr"]["after"]["days_to_maturity"]
    adopt = CATALOGUE_MATURITY[0] <= mat1 <= CATALOGUE_MATURITY[1] and aq_pot1 >= min(YIELD_CHECK["t_ha"])
    v, aq_pot = (v1, aq_pot1) if adopt else (v0, aq_pot0)
    res["phenology_adopted"] = adopt
    log(f"phenology fit {'adopted' if adopt else 'NOT adopted (fails the Kiboko checks): the class keeps its own'}")
    met = era5land.site_met([site], refresh=False)[site.id]
    import fao_water_balance as fw  # noqa: E402
    cal = met[(met.index.year >= C.CAL_YEARS[0]) & (met.index.year <= C.CAL_YEARS[1])]
    elev = float(fw.elevation_from_pressure(float(cal.sp_kpa.mean())))
    scale, y, own = wofost_fit(v, aq_pot, site, temps, met, plants, elev)
    log(f"WOFOST potential, same sowings: own table {own:.2f} t/ha; AMAXTB_scale {scale} → {y:.2f} (AquaCrop {aq_pot:.2f})")
    res["yield"] = {"sowings": [str(p) for p in plants], "aquacrop_potential_t_ha": [round(aq_pot0, 2), round(aq_pot1, 2)],
                    "check": YIELD_CHECK, "wofost_own_t_ha": round(own, 2), "wofost_scale": scale,
                    "wofost_fitted_t_ha": round(y, 2)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    log(f"proposed: sorghum maturity_days {v['maturity_days']}"
        + (f", flowering_days {v['flowering_days']}" if v.get("flowering_days") else "")
        + f", wofost AMAXTB_scale {scale} → {OUT / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
