#!/usr/bin/env python3
"""
DSSAT's sorghum (CSH-1, IB0026) as the class's 100-day crop.

calibration/dssat.py could not bring CERES-Sorghum to the class's maturity_days: with P1 and P5 at the minima of
DSSAT's cultivar file (200 and 300 °C d) it still matures in 109 days at 21 °C and flowers in 79, because the phase
from panicle initiation to anthesis (PANTH, 617.5 °C d), the flag leaf to anthesis (P3, 152.5, inside PANTH) and
anthesis to the beginning of grain filling (P4, 81.5) are the same for every cultivar of DSSAT 4.8's file (its
MINIMA = MAXIMA there, flagged "not used for calibration"). Sowing to maturity is about 50 + GDDE × depth + P1 + P2
+ PANTH + P4 + P5 °C d (P2: end of the juvenile phase to panicle initiation in short days; Kiboko's photoperiod is
below P2O), about 13 °C d a day at 21 °C (TBASE 8).

The fit, at calibration/dssat.py's reference conditions (Kiboko, a constant daily mean of 21 °C, no water stress,
sown 1 Mar 2012): P1 stays the adopted 200 (the file's minimum; P2 the cultivar's); PANTH is shortened, with P3 kept
the same share of it as in DSSAT's file, until anthesis falls on ANTHESIS_TARGET days (Gadam's 50 % flowering at
Embu, 65.3 days, Shinda et al. 2021; the AquaCrop class flowers at about 59 % of its maturity, 59 days: the window
ANTHESIS_WINDOW); then P5 (within the file's 300–700) until maturity falls on the class's maturity_days; P4 stays.
The new phenology changes the yield, so G2 (partitioning to the panicle, within the file's 2–6) is fitted again so
that the no-water-stress yield over the Short Rains 2012 sowings at Kiboko is AquaCrop's (4.97 t/ha), as in
calibration/dssat.py. DSSAT reads G2 to one decimal (5.142 on file runs as 5.1; the yield moves in steps of
about 0.08 t/ha per 0.1), so G2 is written on that grid and the yield matched to within half a step (YIELD_TOL).
Sound (sound()): both phenology targets met, PANTH within PANTH_RANGE and above P3, G2 within
the file's limits and the yield within YIELD_TOL of the target, every sowing grown.

Writes outputs/crop_engine/calibration/dssat/sorghum_100d.json and prints the row for crop_engine/dssat_cultivars.yaml
(edited by hand, citing it). Usage: python -m crop_engine.calibration.sorghum_dssat
"""
import argparse
import datetime as dt
import json
import sys

import numpy as np

from crop_engine import config as C
from crop_engine import run_outlook as ro
from crop_engine.adapters import dssat_adapter as ds
from crop_engine.calibration import dssat as cd
from crop_engine.calibration import dssat_glue as dg

VARIETY = "sorghum"
ANTHESIS_TARGET = 65
ANTHESIS_WINDOW = (59, 67)        # the AquaCrop class's 59 % of 100 days; Gadam's Embu ratio (65.3 / 97.7) × 100
ANTHESIS_SOURCE = ("Gadam, University of Embu farm, LR 2020: 50 % flowering 65.3 days (Shinda et al. 2021, Table 2); "
                   "the AquaCrop class flowers at about 59 % of its maturity")
PANTH_FILE, P3_FILE = 617.5, 152.5           # DSSAT 4.8's SGCER048.CUL, every cultivar
P3_SHARE = P3_FILE / PANTH_FILE
PANTH_RANGE = (300.0, PANTH_FILE)            # sane: shortened, never below about half the file's value
PANTH_GRID = np.linspace(PANTH_RANGE[0], PANTH_RANGE[1], 8)
G2_STEP = 0.1                                # DSSAT reads sorghum's G2 to one decimal (5.142 runs as 5.1)
YIELD_TOL = 0.05                             # t/ha: half the yield step of one G2_STEP (about 0.08 t/ha)
PLANT = dg.PLANT


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] sorghum dssat: {m}", flush=True)


def with_panth(over, panth):
    """The overrides with PANTH and P3 (the file's share of PANTH)."""
    return dict(over, PANTH=round(float(panth), 1), P3=round(float(panth) * P3_SHARE, 1))


def phenology(variety, over, site, elev, tmean):
    """Days from sowing to anthesis and to maturity at a constant tmean, no water stress (calibration/dssat's
    reference run) for the variety with `over` on top of its adopted overrides → (anthesis, maturity) or Nones."""
    r = dg._run(dg._variety_with(variety, over), [PLANT], cd.constant_weather(dg.WEATHER_FROM, tmean), site, elev)[0]
    if r["status"] != "ok":
        return None, None
    days = lambda k: (dt.date.fromisoformat(r[k]) - PLANT).days if r.get(k) else None      # noqa: E731
    return days("anthesis"), days("harvest")


def fit_phenology(variety, site, elev, tmean, anthesis_target=ANTHESIS_TARGET, maturity_target=None):
    """PANTH (P3 its file share) to the anthesis target, then P5 to the maturity target (module doc) → dict with the
    overrides, the days and whether each target was reached."""
    maturity_target = maturity_target or variety["maturity_days"]
    lo, hi = cd.limits(variety["aquacrop_crop"])
    base = {k: float(v) for k, v in variety["dssat"].items() if k != "cultivar"}
    panth, anth, ok_a = cd._fit(lambda p: phenology(variety, with_panth(base, p), site, elev, tmean)[0],
                                anthesis_target, PANTH_GRID, lambda d: d == anthesis_target)
    over = with_panth(base, panth)
    p5, mat, ok_m = cd._fit(lambda p: phenology(variety, dict(over, P5=p), site, elev, tmean)[1], maturity_target,
                            np.linspace(lo["P5"], hi["P5"], 9), lambda d: d == maturity_target)
    over["P5"] = round(float(p5), 1)
    a, m = phenology(variety, over, site, elev, tmean)
    return {"overrides": over, "anthesis_days": a, "maturity_days": m, "targets": {
        "anthesis_days": anthesis_target, "maturity_days": maturity_target},
        "reached": {"anthesis": bool(ok_a and a == anthesis_target), "maturity": bool(ok_m and m == maturity_target)}}


def sowings_yield(variety, over, site, elev, plantings):
    """Mean no-water-stress yield over the sowings and each sowing's days to anthesis and maturity at Kiboko."""
    w = cd.site_weather(site, plantings[0] - dt.timedelta(days=5))
    rs = dg._run(dg._variety_with(variety, over), plantings, w, site, elev)
    ok = [r for r in rs if r["status"] == "ok"]
    days = lambda r, k: (dt.date.fromisoformat(r[k]) - dt.date.fromisoformat(r["planting"])).days if r.get(k) else None  # noqa: E731
    return (float(np.mean([r["yield_t_ha"] for r in ok])) if len(ok) == len(rs) else None,
            [{"planting": r["planting"], "status": r["status"], "yield_t_ha": r["yield_t_ha"],
              "anthesis_days": days(r, "anthesis"), "maturity_days": days(r, "harvest"), "max_lai": r.get("max_lai")}
             for r in rs])


def fit_g2(variety, over, target, site, elev, plantings):
    """G2 on DSSAT's G2_STEP grid within its limits whose mean no-water-stress yield over the sowings is closest to
    target → (G2, yield, reached: within YIELD_TOL). Bracketed and bisected as calibration/dssat._fit, then the grid
    values either side of the result compared."""
    lo, hi = cd.limits(variety["aquacrop_crop"])
    f = lambda g: sowings_yield(variety, dict(over, G2=g), site, elev, plantings)[0]       # noqa: E731
    g, _, _ = cd._fit(f, target, np.linspace(lo["G2"], hi["G2"], 9), lambda y: abs(y - target) < YIELD_TOL)
    near = sorted({float(np.clip(round(g / G2_STEP + k) * G2_STEP, lo["G2"], hi["G2"])) for k in (-1, 0, 1)})
    got = [(round(x, 1), f(x)) for x in near]
    g, y = min(((x, y) for x, y in got if y is not None), key=lambda t: abs(t[1] - target))
    return g, y, abs(y - target) <= YIELD_TOL


def sound(res, limits=None):
    """[reasons the fit is not sound] (module doc); empty when it is."""
    o, why = res["overrides"], []
    lo, hi = limits or ({"G2": 2.0, "P5": 300.0}, {"G2": 6.0, "P5": 700.0})
    if res["maturity_days"] != res["targets"]["maturity_days"]:
        why.append(f"maturity {res['maturity_days']} days, not {res['targets']['maturity_days']}")
    if res["anthesis_days"] is None or not ANTHESIS_WINDOW[0] <= res["anthesis_days"] <= ANTHESIS_WINDOW[1]:
        why.append(f"anthesis {res['anthesis_days']} days, outside {ANTHESIS_WINDOW}")
    if not PANTH_RANGE[0] <= o["PANTH"] <= PANTH_RANGE[1] or not 0 < o["P3"] < o["PANTH"]:
        why.append(f"PANTH {o['PANTH']} / P3 {o['P3']} out of range")
    for k in ("G2", "P5"):
        if not lo[k] <= o[k] <= hi[k]:
            why.append(f"{k} {o[k]} outside DSSAT's {lo[k]}–{hi[k]}")
    y = res.get("yield") or {}
    if y.get("fitted_t_ha") is None or abs(y["fitted_t_ha"] - y["target_t_ha"]) > YIELD_TOL + 1e-9:
        why.append(f"yield {y.get('fitted_t_ha')} t/ha against {y.get('target_t_ha')}")
    return why


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anthesis", type=int, default=ANTHESIS_TARGET, help="days to anthesis at 21 °C")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ds.installed():
        log(f"DSSAT is not installed ({ds.EXE}): python -m crop_engine.adapters.dssat_adapter --install")
        return 1
    tref, vs = ro.load_varieties([VARIETY])
    ds.attach(vs)
    v = vs[VARIETY]
    site, elev = dg.site_and_elev()
    adopted = {k: float(x) for k, x in v["dssat"].items() if k != "cultivar"}
    before = phenology(v, {}, site, elev, tref)
    log(f"adopted {adopted}: anthesis {before[0]}, maturity {before[1]} days at {tref} °C")
    res = fit_phenology(v, site, elev, tref, a.anthesis)
    log(f"phenology: {res['overrides']} → anthesis {res['anthesis_days']}, maturity {res['maturity_days']} days "
        f"(targets {res['targets']})")
    exp = dg.experiments(VARIETY, v)
    plants = exp["sowings"]
    y_adopted, by_adopted = sowings_yield(v, {}, site, elev, plants)
    y_new, by_new = sowings_yield(v, res["overrides"], site, elev, plants)
    log(f"no-water-stress yield, Kiboko SR 2012: adopted {y_adopted:.2f}, 100-day phenology with G2 {adopted['G2']} "
        f"{y_new:.2f} t/ha (target {exp['target_t_ha']})")
    if abs(y_new - exp["target_t_ha"]) > YIELD_TOL:
        g2, y_fit, reached = fit_g2(v, res["overrides"], exp["target_t_ha"], site, elev, plants)
        res["overrides"]["G2"] = round(float(g2), 3)
    y_fit, by_fit = sowings_yield(v, res["overrides"], site, elev, plants)
    log(f"G2 {res['overrides']['G2']}: {y_fit:.3f} t/ha")
    a2, m2 = phenology(v, res["overrides"], site, elev, tref)          # G2 does not move the phenology: checked
    res.update(anthesis_days=a2, maturity_days=m2)
    res["yield"] = {"target_t_ha": exp["target_t_ha"], "source": exp["source"],
                    "adopted_t_ha": round(y_adopted, 3), "new_phenology_adopted_g2_t_ha": round(y_new, 3),
                    "fitted_t_ha": round(y_fit, 3), "sowings": {"adopted": by_adopted, "fitted": by_fit}}
    res["before"] = {"overrides": adopted, "anthesis_days": before[0], "maturity_days": before[1]}
    res["anthesis_source"] = ANTHESIS_SOURCE
    res["file_values"] = {"PANTH": PANTH_FILE, "P3": P3_FILE, "P4": ds.cultivar_coefficients("SorghumGDD", "IB0026")["P4"]}
    res["created"] = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    lo, hi = cd.limits("SorghumGDD")
    res["not_sound"] = sound(res, (lo, hi))
    out = cd.OUT / "sorghum_100d.json"
    cd.OUT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    if res["not_sound"]:
        log(f"not sound: {'; '.join(res['not_sound'])} → {out}")
        return 0
    row = ", ".join(f"{k}: {x}" for k, x in res["overrides"].items())
    log(f"sound → {out}\n  dssat_cultivars.yaml sorghum: {{cultivar: {v['dssat']['cultivar']}, {row}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
