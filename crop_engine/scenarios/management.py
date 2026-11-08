"""
Management scenarios: the outlook's crops grown again in the same forecast weather with one management choice
changed, so a user can see what an earlier or later sowing, a calendar sowing date, a sparser or denser stand or a
drier or wetter soil at the start would change (crop_engine.run_scenarios).

A scenario changes one thing of a member's AquaCrop task (adapters.aquacrop_adapter.simulate):
  sow_shift     days added to each member's sowing date (the planting rule's onset); a member with no onset stays
                not sown; a date past the season's end leaves too little time to mature (too late)
  sow_fixed     (month, day): every member sown on that date of the season year, onset or not (a calendar sowing)
  density       factor on the variety's plant population. AquaCrop-OSPy sets only the initial canopy cover from it
                (CCo = plant population × seed size): the canopy closes sooner or later, its maximum (CCx, calibrated
                at Kiboko) does not change
  initial_frac  plant-available water on 1 Aug as a fraction of TAW, in place of the ERA5-Land value
  irrigation    AquaCrop-OSPy IrrigationManagement: method 1 irrigates (up to MaxIrr mm a day, AppEff % of it
                reaching the soil) whenever the root zone's water falls below SMT % of its available water, per
                growth stage (emergence, canopy growth, maximum canopy and flowering, senescence), up to MaxIrrSeason
                mm a season. Supplementary: 30 % from sowing to flowering, 100 mm a season at 75 % efficiency (bucket,
                hose or furrow from a pan or tank); full: 70 % throughout, no cap (the water-unlimited yield)
  field         AquaCrop-OSPy FieldMngt: mulches (mulch_pct % of the surface covered, soil evaporation there cut by
                f_mulch: crop residues, 50 % cover), bunds (z_bund m high: rain held on the field instead of running
                off, as tied ridges or zai pits do; 15 cm)
Re-sowing after a failed establishment works as in the outlook.
"""
import datetime as dt

import numpy as np
import pandas as pd

SCENARIOS = {
    "sow_minus14": dict(label="Sow 14 days earlier", group="Sowing date", sow_shift=-14),
    "sow_plus14": dict(label="Sow 14 days later", group="Sowing date", sow_shift=14),
    "sow_plus28": dict(label="Sow 28 days later", group="Sowing date", sow_shift=28),
    "sow_oct15": dict(label="Sow on 15 Oct (every member)", group="Calendar sowing", sow_fixed=(10, 15)),
    "sow_nov01": dict(label="Sow on 1 Nov (every member)", group="Calendar sowing", sow_fixed=(11, 1)),
    "sow_nov15": dict(label="Sow on 15 Nov (every member)", group="Calendar sowing", sow_fixed=(11, 15)),
    "density_low": dict(label="Plant density × 0.67", group="Plant density", density=0.67),
    "density_high": dict(label="Plant density × 1.2", group="Plant density", density=1.2),
    "soil_dry": dict(label="Dry soil on 1 Aug (wilting point)", group="Initial soil water", initial_frac=0.0),
    "soil_wet": dict(label="Wet soil on 1 Aug (field capacity)", group="Initial soil water", initial_frac=1.0),
    "irr_supplementary": dict(label="Supplementary irrigation, up to 100 mm a season", group="Water management",
                              irrigation=dict(irrigation_method=1, SMT=[30, 30, 30, 0], MaxIrr=25, MaxIrrSeason=100,
                                              AppEff=75)),
    "irr_full": dict(label="Full irrigation (no water stress)", group="Water management",
                     irrigation=dict(irrigation_method=1, SMT=[70, 70, 70, 70], MaxIrr=50)),
    "mulch": dict(label="Mulch, 50 % residue cover", group="Water management",
                  field=dict(mulches=True, mulch_pct=50, f_mulch=0.5)),
    "bunds": dict(label="Tied ridges / bunds, 15 cm (runoff kept)", group="Water management",
                  field=dict(bunds=True, z_bund=0.15)),
}
KEYS = ("sow_shift", "sow_fixed", "density", "initial_frac", "irrigation", "field")


def describe(key):
    """The scenario's label, group and settings, for the results' meta."""
    s = SCENARIOS[key]
    return {"label": s["label"], "group": s["group"], **{k: s[k] for k in KEYS if k in s}}


def _sowing(planting, scen, dates):
    """Each member's sowing date under the scenario (None: not sown)."""
    first, last = dates[0].date(), dates[-1].date()
    if "sow_fixed" in scen:
        m, d = scen["sow_fixed"]
        y = first.year if (m, d) >= (first.month, first.day) else first.year + 1
        return [dt.date(y, m, d)] * len(planting)
    shift = dt.timedelta(days=scen.get("sow_shift", 0))
    return [None if p is None else min(max(p + shift, first), last) for p in planting]


def apply(task, key):
    """The AquaCrop task (one site, variety, rule; every member) with the scenario `key` applied: a new dict."""
    scen = SCENARIOS[key]
    dates = pd.DatetimeIndex(task["dates"])
    out = dict(task, planting=_sowing(list(task["planting"]), scen, dates))
    if "density" in scen:
        from aquacrop.entities.crop import crop_params
        pop = task["kw"].get("PlantPop", crop_params[task["variety"]["aquacrop_crop"]]["PlantPop"])
        out["kw"] = dict(task["kw"], PlantPop=float(np.round(pop * scen["density"])))
    if "initial_frac" in scen:
        out["initial_frac"] = float(scen["initial_frac"])
    for k in ("irrigation", "field"):
        if k in scen:
            out[k] = dict(scen[k])
    return out
