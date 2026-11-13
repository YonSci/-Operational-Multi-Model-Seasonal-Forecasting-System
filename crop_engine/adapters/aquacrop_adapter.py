"""
AquaCrop-OSPy (FAO AquaCrop, water-driven crop growth) for one site, variety and planting rule: each weather member is
simulated from 1 Aug (soil water from ERA5-Land, as the FAO water balance) to the season's end, sown on that member's
onset. The season runs from 1 Aug (the FAO water balance's start) to config.SEASON_END, 31 Mar: the weather's days.

Kept free of the climate pipeline's imports, so worker processes start light.

Outcome of a member (status):
  ok          sown, reached maturity
  died        sown, the crop died before maturity (AquaCrop ends the season early)
  failed_establishment  died before its canopy reached 5 % (a false start: the seedlings dried out)
  too_late    sown too late to reach maturity by the season's end (not simulated: AquaCrop needs the full season)
  not_sown    no planting opportunity (no onset by the rule's search end)
  error       the model failed (message kept): no outcome, left out of every probability
A member that is not sown or too late counts as zero yield in the overall figures; the summaries also give the
chance of a sowing opportunity and the yield and failure of the sown crops apart (run_outlook.outcome_rates).

After a failed establishment the member is re-sown at its next sowing opportunity after the crop died (task
"resow": Agri rule dates, config.RESOW_MAX times at most) when the variety can still mature; the outcome is then the
re-sown crop's, with `sowings` and `first_planting` recording it.

Delayed germination (seed waiting in dry soil). AquaCrop-OSPy 3.1.0 counts the growing degree days of the delay
(delayed_gdds) and takes them off every stage, the canopy and the harvest index, as FAO AquaCrop does, but its end
of season, the maturity check of run_single_timestep (step 19), compares the raw sum from sowing with the crop's
maturity: a crop that waited weeks for rain was ended at its sowing date's maturity, before its grain had filled (a
Meru cell sown on 20 Sep 2026 emerged on 9 Nov at 590 of its GDD and was "mature" in February with a harvest index
of 0.06). patch_delayed_maturity() makes that one check count from germination too: harvest_index (step 17) moves
the crop's maturity by the delay for the check, and growth_stage (step 10) puts it back before the canopy (step 11),
the only other reader. A crop's season is then as long after a late germination as after a prompt one.

A simulated member also carries `_canopy`: its canopy cover (fraction) every CANOPY_STEP days from the season start,
for the canopy bands of the summaries (run_outlook.canopy_band); it is not written to the results.

Atmospheric CO2 (every run): the annual series of crop_engine/data/co2_annual.csv (NOAA's global annual mean to
2025, SSP2-4.5 after), in place of AquaCrop-OSPy's bundled Mauna Loa to 2009 with the A1B projection after (which
puts 2020 at 418 ppm against the observed 412 and 2026 at 435 against about 429). AquaCrop scales its water
productivity by CO2 against its 369.41 ppm reference.

Management (the scenarios, crop_engine.scenarios.management), each a task key left out of the outlook:
  irrigation   AquaCrop-OSPy IrrigationManagement arguments: method 1 soil-moisture targets SMT per growth stage
               (with a seasonal cap MaxIrrSeason), 2 a fixed interval IrrInterval (to field capacity, up to MaxIrr
               a day), 3 a fixed schedule, 4 net irrigation (the root zone kept at NetIrrSMT % of its available
               water, the water counted, not applied), 5 a constant depth every day. The schedule is given as
               "schedule_das": [[days after sowing, mm], ...], placed on each member's own sowing date
  field        FieldMngt arguments: mulches, runoff inhibition (sr_inhb), bunds (z_bund, m)
  groundwater  {"depth_m": d}: a water table at a constant depth d below the surface all season (AquaCrop-OSPy
               GroundWater): capillary rise from it, and the field capacity above it raised as AquaCrop does
Without them the crop is rain-fed on bare, free-draining soil, as the outlook. A member records the irrigation it
received (`irrigation_mm`, the season's depth; net irrigation's requirement under method 4).
"""
import datetime as dt
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from crop_engine.config import RESOW_MAX, SOIL_DZ, STRESS_RATIO

CO2_FILE = Path(__file__).resolve().parent.parent / "data" / "co2_annual.csv"
_CO2 = []


def co2():
    """AquaCrop-OSPy's CO2 from CO2_FILE (module doc), read once per process."""
    from aquacrop import CO2
    if not _CO2:
        _CO2.append(pd.read_csv(CO2_FILE, comment="#")[["year", "ppm"]])
    return CO2(co2_data=_CO2[0].copy())


def irrigation(spec, plant):
    """The IrrigationManagement of a task's irrigation spec for a sowing on `plant` (module doc), or None."""
    from aquacrop import IrrigationManagement
    if not spec:
        return None
    spec = dict(spec)
    das = spec.pop("schedule_das", None)
    if das is not None:
        spec["irrigation_method"] = 3
        spec["Schedule"] = pd.DataFrame({"Date": [pd.Timestamp(plant) + pd.Timedelta(days=int(d)) for d, _ in das],
                                         "Depth": [float(mm) for _, mm in das]})
    return IrrigationManagement(**spec)


def groundwater(spec, start):
    """AquaCrop-OSPy's GroundWater for a task's groundwater spec (module doc), or None (no water table)."""
    from aquacrop import GroundWater
    if not spec:
        return None
    return GroundWater(water_table="Y", method="Constant", dates=[f"{start:%Y/%m/%d}"], values=[float(spec["depth_m"])])

ESTABLISHED_CC = 0.05          # canopy cover a crop must reach to count as established
CANOPY_STEP = 7                # days between the canopy values kept per member (from the season start, 1 Aug)
PHENOLOGY = ("Emergence", "MaxRooting", "Senescence", "Maturity", "HIstart", "Flowering", "YldForm")


def crop_parameters(variety, reference_tmean):
    """AquaCrop parameter overrides of a variety: GDD phenology scaled to its maturity days at reference_tmean,
    canopy growth / decline coefficients scaled inversely, then the variety's own `parameters` (calibrated values,
    e.g. PlantPop, CCx, HI0, used as given) → (kwargs, scale factor).

    `flowering_days` (optional): days from sowing to flowering (AquaCrop's HIstart, the start of yield formation)
    at reference_tmean, set apart from maturity: yield formation (YldForm) then runs from it to maturity (keeping
    the crop file's gap between the two, scaled), and flowering's own duration is capped at it. Without it every
    stage keeps the crop file's proportions (sorghum: flowering at 59 % of the maturity GDD)."""
    from aquacrop.entities.crop import crop_params
    p = crop_params[variety["aquacrop_crop"]]
    f = variety["maturity_days"] * (reference_tmean - p["Tbase"]) / p["Maturity"]
    kw = {k: float(p[k]) * f for k in PHENOLOGY}
    kw["CGC"], kw["CDC"] = float(p["CGC"]) / f, float(p["CDC"]) / f
    if variety.get("flowering_days"):
        fl = float(variety["flowering_days"]) * (reference_tmean - p["Tbase"])
        if not kw["Emergence"] < fl < kw["Maturity"]:
            raise ValueError(f"{variety.get('label', variety['aquacrop_crop'])}: flowering_days "
                             f"{variety['flowering_days']} not between emergence and maturity")
        gap = (float(p["Maturity"]) - float(p["HIstart"]) - float(p["YldForm"])) * f
        kw["HIstart"] = fl
        kw["YldForm"] = max(kw["Maturity"] - fl - gap, 1.0)
        kw["Flowering"] = min(kw["Flowering"], kw["YldForm"])
        kw["Senescence"] = min(max(kw["Senescence"], fl), kw["Maturity"])
    own = variety.get("parameters") or {}
    unknown = sorted(set(own) - set(p))
    if unknown:
        raise ValueError(f"{variety.get('label', variety['aquacrop_crop'])}: not AquaCrop {variety['aquacrop_crop']} "
                         f"parameters: {unknown}")
    kw.update({k: float(v) for k, v in own.items()})
    return kw, f


def gdd(tmax, tmin, tbase, tupp):
    """Daily growing degree days as AquaCrop's method 3 (the GDD crops' default)."""
    tx = np.clip(tmax, tbase, tupp)
    tn = np.minimum(tmin, tupp)
    return np.maximum((tx + tn) / 2, tbase) - tbase


_PATCHED = []


def patch_delayed_maturity():
    """AquaCrop-OSPy's maturity check counted from germination (module doc). Idempotent, per process."""
    if _PATCHED:
        return
    import aquacrop.timestep.run_single_timestep as rst
    hi0, gs0 = rst.harvest_index, rst.growth_stage

    def growth_stage(crop, new_cond, growing_season):
        m0 = getattr(crop, "_maturity_gdd", None)
        if m0 is not None:
            crop.Maturity = m0                                          # the crop's own maturity for the canopy
        return gs0(crop, new_cond, growing_season)

    def harvest_index(prof, z_top, crop, new_cond, *args):
        out = hi0(prof, z_top, crop, new_cond, *args)
        if crop.CalendarType == 2:                                      # GDD crops: the check right after this
            if getattr(crop, "_maturity_gdd", None) is None:
                crop._maturity_gdd = crop.Maturity
            crop.Maturity = crop._maturity_gdd + float(out.delayed_gdds)
        return out

    rst.harvest_index, rst.growth_stage = harvest_index, growth_stage
    _PATCHED.append(True)


_CR_PATCHED = []


def patch_capillary_rise():
    """AquaCrop-OSPy 3.1.0's capillary rise (only run with a water table) asserts that the bottom compartment's soil
    layer is the soil's last layer, before a loop over unmodelled layers below the profile that its own comment marks
    as broken ("this needs fixing, will currently break"). The SoilGrids profile's top layer (0-5 cm) is thinner
    than a compartment (10 cm), so the compartments map to layers 2-6 while the soil counts 6: the assertion fails
    and every member with a water table errors. The profile has no layer below its 2 m, so the loop has nothing to
    do; the layer count passed is the bottom compartment's own, which passes the check and skips the loop, as for a
    soil whose layers line up. Idempotent, per process."""
    if _CR_PATCHED:
        return
    import aquacrop.timestep.run_single_timestep as rst
    cr0 = rst.capillary_rise

    def capillary_rise(prof, n_layer, fshape_cr, cond, flux_out, wt):
        return cr0(prof, int(prof.Layer[-1]), fshape_cr, cond, flux_out, wt)

    rst.capillary_rise = capillary_rise
    _CR_PATCHED.append(True)


def make_soil(layers):
    from aquacrop import Soil
    s = Soil("custom", dz=list(SOIL_DZ))
    for L in layers:
        s.add_layer_from_texture(thickness=L.thickness_m, Sand=L.sand, Clay=L.clay, OrgMat=L.om, penetrability=100)
    return s


def _sow(task, m, plant, dates, g):
    """One sowing of member m on `plant` → outcome dict (status, yield, dates, stress)."""
    from aquacrop import AquaCropModel, Crop, FieldMngt, InitialWaterContent
    patch_delayed_maturity()
    if task.get("groundwater"):
        patch_capillary_rise()
    r = dict(member=m + 1, planting=plant.isoformat(), status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
             biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None, sources=None)
    k0 = int(dates.get_indexer([pd.Timestamp(plant)])[0])
    if k0 < 0:
        return dict(r, status="error", error="planting date outside the weather period")
    cum = np.cumsum(g[k0:])
    if cum[-1] <= task["kw"]["Maturity"] * 1.01:
        return dict(r, status="too_late")
    expected_maturity = dates[k0 + int(np.argmax(cum > task["kw"]["Maturity"]))]
    wdf = pd.DataFrame({"MinTemp": task["tmin"][m], "MaxTemp": task["tmax"][m], "Precipitation": task["rain"][m],
                        "ReferenceET": np.maximum(task["et0"][m], 0.1), "Date": dates})
    try:
        model = AquaCropModel(
            sim_start_time=f"{dates[0]:%Y/%m/%d}", sim_end_time=f"{dates[-1]:%Y/%m/%d}", weather_df=wdf,
            soil=make_soil(task["layers"]), crop=Crop(task["variety"]["aquacrop_crop"], planting_date=f"{plant:%m/%d}", **task["kw"]),
            initial_water_content=InitialWaterContent(wc_type="Pct", method="Depth", depth_layer=[0.05, 2.0],
                                                      value=[100 * task["initial_frac"]] * 2),
            irrigation_management=irrigation(task.get("irrigation"), plant),
            field_management=FieldMngt(**task["field"]) if task.get("field") else None,
            groundwater=groundwater(task.get("groundwater"), dates[0]), co2_concentration=co2())
        stressed = any(task.get(k) for k in ("fertility", "weeds", "salinity"))
        if stressed:                                                 # AquaCrop 7's processes (aquacrop_stress)
            from crop_engine.adapters import aquacrop_stress as st
            st.install()
            st.activate(st.Context(task["variety"]["aquacrop_crop"], cum, task.get("fertility"), task.get("weeds"),
                                   task.get("salinity")))
        try:
            model.run_model(till_termination=True)
        finally:
            if stressed:
                st.deactivate()
        res = model.get_simulation_results()
        growth = model.get_crop_growth()
        flux = model.get_water_flux()
    except Exception as exc:                                         # one member must not stop the others
        return dict(r, status="error", error=f"{type(exc).__name__}: {str(exc)[:160]}")
    if len(res):
        harvest = pd.Timestamp(res["Harvest Date (YYYY/MM/DD)"].iloc[0])
        yld = float(res["Dry yield (tonne/ha)"].iloc[0])
        pot = float(res["Yield potential (tonne/ha)"].iloc[0])
    else:                                                            # season not closed by its end (31 Mar)
        harvest, yld, pot = dates[-1], float(growth.DryYield.max()), float(growth.YieldPot.max())
    kh = int(dates.get_indexer([harvest])[0]) if harvest in dates else len(dates) - 1
    season = slice(k0, kh + 1)
    tr, trp = flux.Tr.values[: len(dates)], flux.TrPot.values[: len(dates)]
    with np.errstate(invalid="ignore", divide="ignore"):
        stressed = (trp[season] >= 0.5) & (tr[season] < STRESS_RATIO * trp[season])
    src = np.bincount(task["source"][season].astype(int), minlength=6)
    ccs = np.nan_to_num(growth.canopy_cover.values[: len(dates)].astype(np.float32))
    ccs = np.pad(ccs, (0, len(dates) - len(ccs)))                     # zero after the season ends
    cc = float(ccs[: kh + 1].max())
    status = ("ok" if harvest >= expected_maturity - pd.Timedelta(days=3)
              else "failed_establishment" if cc < ESTABLISHED_CC else "died")
    r.update(status=status, yield_t_ha=round(yld, 3), potential_t_ha=round(pot, 3),
             biomass_t_ha=round(float(growth.biomass.values[: kh + 1].max()) / 100.0, 3),
             harvest=f"{harvest:%Y-%m-%d}", expected_maturity=f"{expected_maturity:%Y-%m-%d}",
             max_canopy=round(cc, 3), stress_days=int(stressed.sum()),
             irrigation_mm=round(float(np.nansum(flux.IrrDay.values[: len(dates)][season])), 1) if "IrrDay" in flux else 0.0,
             rain_mm=round(float(task["rain"][m][season].sum()), 1), sources=src.tolist(),
             _canopy=ccs[::CANOPY_STEP])
    return r


def simulate(task):
    """task: dict(dates, rain (member, T), tmax, tmin, et0 ((member, T), or (T,) for every member), source (T,),
    planting [date|None per member],
    resow [[date, ...] per member] (optional), variety, kw, layers, initial_frac) → list of per-member outcome dicts."""
    from aquacrop.entities.crop import crop_params
    warnings.filterwarnings("ignore")
    dates = pd.DatetimeIndex(task["dates"])
    base = crop_params[task["variety"]["aquacrop_crop"]]
    M, T = len(task["planting"]), len(dates)
    task = dict(task, **{k: np.broadcast_to(np.asarray(task[k], np.float64), (M, T)) for k in ("tmax", "tmin", "et0")})
    g = gdd(task["tmax"], task["tmin"], base["Tbase"], base["Tupp"])           # (member, T)
    resow = task.get("resow") or [[] for _ in task["planting"]]
    out = []
    for m, plant in enumerate(task["planting"]):
        if plant is None:
            out.append(dict(member=m + 1, planting=None, status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
                            biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None,
                            sources=None, sowings=0))
            continue
        r, sowings = _sow(task, m, plant, dates, g[m]), 1
        while r["status"] == "failed_establishment" and sowings <= RESOW_MAX:
            died = dt.date.fromisoformat(r["harvest"])
            later = [d for d in resow[m] if d > died]
            if not later:
                break
            again = _sow(task, m, later[0], dates, g[m])
            if again["status"] in ("too_late", "error"):              # no time left to re-sow: the failure stands
                break
            r, sowings = dict(again, first_planting=plant.isoformat()), sowings + 1
        r["sowings"] = sowings
        out.append(r)
    return out
