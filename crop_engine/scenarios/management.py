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
  irrigation    AquaCrop-OSPy IrrigationManagement: method 1 irrigates (up to MaxIrr mm a day) whenever the root
                zone's water falls below SMT % of its available water, per growth stage (emergence, canopy growth,
                maximum canopy and flowering, senescence), up to MaxIrrSeason mm a season. Supplementary: 30 % from
                canopy growth to flowering (start_stage 2: none before the crop has emerged with rain), 100 mm a
                season reaching the soil (about 130 mm drawn from a pan or tank at 75 % efficiency: the cap is
                counted in net water); full: 70 % throughout, no cap (the water-unlimited yield). Irrigating from
                sowing (the first version) germinated a crop sown into dry soil weeks before the rains, spent the
                cap keeping it alive and let it die before the rains came (every Genco Tana River member, October);
                a lower efficiency only made the cap run out sooner
  field         AquaCrop-OSPy FieldMngt: mulches (mulch_pct % of the surface covered, soil evaporation there cut by
                f_mulch: crop residues, 50 % cover); water harvesting as sr_inhb (surface runoff fully inhibited: the
                rain infiltrates where it falls, as tied ridges or zai pits make it). Bunds are their own scenario, 10 cm
                high (AquaCrop only): the rain held on the field until it infiltrates. (Bunds of 20 cm once stopped most
                crops at Kapiti, Kiboko and Livemo: an AquaCrop-OSPy bug, aquacrop_adapter.patch_submergence, not
                waterlogging.)
Scenarios only AquaCrop can grow (aquacrop_only; WOFOST and DSSAT leave them out):
  irrigation    methods 2-5: every 7 days to field capacity; a fixed schedule from each member's sowing; the net
                irrigation requirement (the water counted, not applied); drip at a constant 3 mm a day
  groundwater   a water table at a constant depth (1.5 or 2.5 m): capillary rise into the root zone
  fertility     AquaCrop 7's soil fertility stress (%), its generic crop response (adapters/aquacrop_stress.py); "no
                fertiliser" at the level fitted to the Kenyan maize nitrogen trials (aquacrop_fertility.yaml: maize
                and sorghum 74 %, the bean none as it fixes its nitrogen)
  weeds         AquaCrop 7's weeds, their relative cover of the canopy (%)
  salinity      AquaCrop 7's salinity: a saline soil (initial ECe), saline irrigation water (ECw) or a saline water
                table (ECgw), dS/m; one season from the stated start (salt builds up over years: ECe ≈ 1.5 ECw)
These are assumed levels, to show what the practice or condition would change, not measured at any site.
Re-sowing after a failed establishment works as in the outlook.
"""
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

FERTILITY = yaml.safe_load((Path(__file__).resolve().parent.parent / "aquacrop_fertility.yaml").read_text(encoding="utf-8"))

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
    # the satellite's estimate (crop_engine.data.smap): run only when the season's SMAP values are on disk
    # (run_scenarios.available_keys); a site without a value keeps the outlook's ERA5-Land soil water
    "soil_smap": dict(label="Soil water on 1 Aug from SMAP (satellite)", group="Initial soil water", initial_source="smap"),
    "irr_supplementary": dict(label="Supplementary irrigation, up to 100 mm a season", group="Water management",
                              irrigation=dict(irrigation_method=1, SMT=[30, 30, 30, 0], MaxIrr=25, MaxIrrSeason=100,
                                             start_stage=2)),
    "irr_full": dict(label="Full irrigation (no water stress)", group="Water management",
                     irrigation=dict(irrigation_method=1, SMT=[70, 70, 70, 70], MaxIrr=50)),
    "mulch": dict(label="Mulch, 50 % residue cover", group="Water management",
                  field=dict(mulches=True, mulch_pct=50, f_mulch=0.5)),
    "ridges": dict(label="Tied ridges or pits (no surface runoff)", group="Water management",
                   field=dict(sr_inhb=True)),
    "bunds": dict(label="Bunds 10 cm high (rain held on the field)", group="Water management",
                  field=dict(bunds=True, z_bund=0.10)),
    # partial runoff reduction: AquaCrop's field-practice adjustment of the runoff curve number (AquaCrop-OSPy
    # FieldMngt curve_number_adj_pct; DSSAT lowers its own curve number by the same share; WOFOST has none). Levels
    # assumed: contour ridging and bunds or terraces cut runoff without stopping it, between bare soil and "ridges"
    "contour_ridges": dict(label="Contour ridging (runoff curve number 15 % lower)", group="Water management",
                           field=dict(curve_number_adj=True, curve_number_adj_pct=-15)),
    "terraces": dict(label="Contour bunds or fanya juu terraces (curve number 30 % lower)", group="Water management",
                     field=dict(curve_number_adj=True, curve_number_adj_pct=-30)),
    # irrigation methods other than soil-moisture targets (AquaCrop only)
    "irr_interval": dict(label="Irrigation every 7 days, to field capacity (up to 30 mm)", group="Irrigation method",
                         irrigation=dict(irrigation_method=2, IrrInterval=7, MaxIrr=30)),
    "irr_schedule": dict(label="Fixed schedule: 25 mm at sowing, 30 mm at 20, 40 and 60 days", group="Irrigation method",
                         irrigation=dict(schedule_das=[[0, 25], [20, 30], [40, 30], [60, 30]], MaxIrr=50)),
    "irr_net": dict(label="Net irrigation requirement (root zone kept at 60 %)", group="Irrigation method",
                    irrigation=dict(irrigation_method=4, NetIrrSMT=60)),
    "irr_constant": dict(label="Drip, 3 mm every day", group="Irrigation method",
                         irrigation=dict(irrigation_method=5, depth=3, MaxIrr=10)),
    # a water table (AquaCrop only)
    "gw_1_5m": dict(label="Water table at 1.5 m", group="Groundwater", groundwater=dict(depth_m=1.5)),
    "gw_2_5m": dict(label="Water table at 2.5 m", group="Groundwater", groundwater=dict(depth_m=2.5)),
    # AquaCrop 7's soil fertility stress, weeds and salinity (adapters/aquacrop_stress.py; AquaCrop only)
    "fert_no_n": dict(label="No fertiliser (fertility stress fitted to Kenyan maize nitrogen trials)",
                      group="Soil fertility", fertility=dict(stress_pct_by_crop=dict(FERTILITY["no_fertiliser"]))),
    "fert_25": dict(label="Soil fertility stress 25 % (about 80 % of the unstressed biomass)", group="Soil fertility",
                    fertility=dict(stress_pct=25)),
    "fert_50": dict(label="Soil fertility stress 50 % (about half the unstressed biomass)", group="Soil fertility",
                    fertility=dict(stress_pct=50)),
    "weeds_20": dict(label="Weeds: 20 % of the canopy", group="Weeds", weeds=dict(rc_pct=20)),
    "weeds_50": dict(label="Weeds: 50 % of the canopy", group="Weeds", weeds=dict(rc_pct=50)),
    "saline_soil": dict(label="Saline soil (ECe 4 dS/m at the start)", group="Salinity",
                        salinity=dict(ece_initial=4.0)),
    "saline_irrigation": dict(label="Full irrigation with saline water (ECw 2 dS/m)", group="Salinity",
                              irrigation=dict(irrigation_method=1, SMT=[70, 70, 70, 70], MaxIrr=50),
                              salinity=dict(ecw=2.0)),
    "saline_water_table": dict(label="Saline water table at 1.5 m (ECgw 4 dS/m)", group="Salinity",
                               groundwater=dict(depth_m=1.5), salinity=dict(ecgw=4.0)),
}
# Crop-model uncertainty: each member grown with its own draw of the calibrated parameters (relative standard
# deviations, normal, truncated at ±2 SD; seeded, so the draws repeat): maximum canopy cover CCx (capped at 0.99),
# the reference harvest index HI0 and the normalised water productivity WP. Phenology is not drawn (the maturity
# classes are defined by it). The spread of this scenario beside the outlook's shows what the parameters add to the
# weather's uncertainty. The levels are assumptions, of the order of the parameters' calibration uncertainty.
SCENARIOS["parameters"] = dict(label="Crop parameters uncertain (canopy ±10 %, harvest index ±15 %, water productivity ±8 %)",
                               group="Crop model uncertainty", perturb=dict(CCx=0.10, HI0=0.15, WP=0.08, seed=20261))
KEYS = ("sow_shift", "sow_fixed", "density", "initial_frac", "initial_source", "irrigation", "field", "groundwater", "fertility", "weeds",
        "salinity", "perturb")
AQUACROP_KEYS = ("groundwater", "fertility", "weeds", "salinity", "perturb")     # only AquaCrop has (or is drawn for)


def parameter_draws(kw, aquacrop_crop, n, perturb):
    """n members' parameter overrides: each of perturb's parameters × (1 + sd × z), z standard normal truncated at
    ±2, from the variety's value (kw, else the crop file's)."""
    from aquacrop.entities.crop import crop_params
    p = crop_params[aquacrop_crop]
    rng = np.random.default_rng(int(perturb.get("seed", 0)))
    out = []
    for _ in range(n):
        d = {}
        for k, sd in perturb.items():
            if k == "seed":
                continue
            z = float(np.clip(rng.standard_normal(), -2.0, 2.0))
            v = float(kw.get(k, p[k])) * (1.0 + float(sd) * z)
            d[k] = round(min(v, 0.99) if k == "CCx" else v, 4)
        out.append(d)
    return out


def aquacrop_only(key):
    """True when only AquaCrop can grow the scenario: a water table, soil fertility, weeds or salinity, bunds, or an
    irrigation method other than soil-moisture targets (WOFOST's and DSSAT's irrigation is method 1's)."""
    s = SCENARIOS[key]
    irr = s.get("irrigation") or {}
    return (any(k in s for k in AQUACROP_KEYS) or bool((s.get("field") or {}).get("bunds"))
            or (bool(irr) and (irr.get("irrigation_method", 3 if "schedule_das" in irr else 1) != 1)))


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
    if scen.get("initial_source") == "smap" and task.get("smap_frac") is not None:
        out["initial_frac"] = float(task["smap_frac"])
    for k in ("irrigation", "field") + AQUACROP_KEYS:
        if k in scen and k != "perturb":
            out[k] = dict(scen[k])
    if "perturb" in scen:
        out["kw_member"] = parameter_draws(task["kw"], task["variety"]["aquacrop_crop"], len(out["planting"]),
                                           scen["perturb"])
    return out
