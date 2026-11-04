"""
AquaCrop-OSPy (FAO AquaCrop, water-driven crop growth) for one site, variety and planting rule: each weather member is
simulated from 1 Aug (soil water from ERA5-Land, as the FAO water balance) to 31 Mar, sown on that member's onset.

Kept free of the climate pipeline's imports, so worker processes start light.

Outcome of a member (status):
  ok          sown, reached maturity
  died        sown, the crop died before maturity (AquaCrop ends the season early)
  failed_establishment  died before its canopy reached 5 % (a false start: the seedlings dried out)
  too_late    sown too late to reach maturity by 31 Mar (not simulated: AquaCrop needs the full season)
  not_sown    no planting opportunity (no onset by the rule's search end)
  error       the model failed (message kept)
A member that is not sown or too late counts as zero yield in the risk figures.

After a failed establishment the member is re-sown at its next sowing opportunity after the crop died (task
"resow": Agri rule dates, config.RESOW_MAX times at most) when the variety can still mature; the outcome is then the
re-sown crop's, with `sowings` and `first_planting` recording it.

A simulated member also carries `_canopy`: its canopy cover (fraction) every CANOPY_STEP days from the season start,
for the canopy bands of the summaries (run_outlook.canopy_band); it is not written to the results.
"""
import datetime as dt
import warnings

import numpy as np
import pandas as pd

from crop_engine.config import RESOW_MAX, SOIL_DZ, STRESS_RATIO

ESTABLISHED_CC = 0.05          # canopy cover a crop must reach to count as established
CANOPY_STEP = 7                # days between the canopy values kept per member (from the season start, 1 Aug)
PHENOLOGY = ("Emergence", "MaxRooting", "Senescence", "Maturity", "HIstart", "Flowering", "YldForm")


def crop_parameters(variety, reference_tmean):
    """AquaCrop parameter overrides of a variety: GDD phenology scaled to its maturity days at reference_tmean,
    canopy growth / decline coefficients scaled inversely, then the variety's own `parameters` (calibrated values,
    e.g. PlantPop, CCx, HI0, used as given) → (kwargs, scale factor)."""
    from aquacrop.entities.crop import crop_params
    p = crop_params[variety["aquacrop_crop"]]
    f = variety["maturity_days"] * (reference_tmean - p["Tbase"]) / p["Maturity"]
    kw = {k: float(p[k]) * f for k in PHENOLOGY}
    kw["CGC"], kw["CDC"] = float(p["CGC"]) / f, float(p["CDC"]) / f
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


def make_soil(layers):
    from aquacrop import Soil
    s = Soil("custom", dz=list(SOIL_DZ))
    for L in layers:
        s.add_layer_from_texture(thickness=L.thickness_m, Sand=L.sand, Clay=L.clay, OrgMat=L.om, penetrability=100)
    return s


def _sow(task, m, plant, dates, g):
    """One sowing of member m on `plant` → outcome dict (status, yield, dates, stress)."""
    from aquacrop import AquaCropModel, Crop, InitialWaterContent
    r = dict(member=m + 1, planting=plant.isoformat(), status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
             biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None, sources=None)
    k0 = int(dates.get_indexer([pd.Timestamp(plant)])[0])
    if k0 < 0:
        return dict(r, status="error", error="planting date outside the weather period")
    cum = np.cumsum(g[k0:])
    if cum[-1] <= task["kw"]["Maturity"] * 1.01:
        return dict(r, status="too_late")
    expected_maturity = dates[k0 + int(np.argmax(cum > task["kw"]["Maturity"]))]
    wdf = pd.DataFrame({"MinTemp": task["tmin"], "MaxTemp": task["tmax"], "Precipitation": task["rain"][m],
                        "ReferenceET": np.maximum(task["et0"], 0.1), "Date": dates})
    try:
        model = AquaCropModel(
            sim_start_time=f"{dates[0]:%Y/%m/%d}", sim_end_time=f"{dates[-1]:%Y/%m/%d}", weather_df=wdf,
            soil=make_soil(task["layers"]), crop=Crop(task["variety"]["aquacrop_crop"], planting_date=f"{plant:%m/%d}", **task["kw"]),
            initial_water_content=InitialWaterContent(wc_type="Pct", method="Depth", depth_layer=[0.05, 2.0],
                                                      value=[100 * task["initial_frac"]] * 2))
        model.run_model(till_termination=True)
        res = model.get_simulation_results()
        growth = model.get_crop_growth()
        flux = model.get_water_flux()
    except Exception as exc:                                         # one member must not stop the others
        return dict(r, status="error", error=f"{type(exc).__name__}: {str(exc)[:160]}")
    if len(res):
        harvest = pd.Timestamp(res["Harvest Date (YYYY/MM/DD)"].iloc[0])
        yld = float(res["Dry yield (tonne/ha)"].iloc[0])
        pot = float(res["Yield potential (tonne/ha)"].iloc[0])
    else:                                                            # season not closed by 31 Mar
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
             rain_mm=round(float(task["rain"][m][season].sum()), 1), sources=src.tolist(),
             _canopy=ccs[::CANOPY_STEP])
    return r


def simulate(task):
    """task: dict(dates, rain (member, T), tmax, tmin, et0 (T,), source (T,), planting [date|None per member],
    resow [[date, ...] per member] (optional), variety, kw, layers, initial_frac) → list of per-member outcome dicts."""
    from aquacrop.entities.crop import crop_params
    warnings.filterwarnings("ignore")
    dates = pd.DatetimeIndex(task["dates"])
    base = crop_params[task["variety"]["aquacrop_crop"]]
    g = gdd(task["tmax"], task["tmin"], base["Tbase"], base["Tupp"])
    resow = task.get("resow") or [[] for _ in task["planting"]]
    out = []
    for m, plant in enumerate(task["planting"]):
        if plant is None:
            out.append(dict(member=m + 1, planting=None, status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
                            biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None,
                            sources=None, sowings=0))
            continue
        r, sowings = _sow(task, m, plant, dates, g), 1
        while r["status"] == "failed_establishment" and sowings <= RESOW_MAX:
            died = dt.date.fromisoformat(r["harvest"])
            later = [d for d in resow[m] if d > died]
            if not later:
                break
            again = _sow(task, m, later[0], dates, g)
            if again["status"] in ("too_late", "error"):              # no time left to re-sow: the failure stands
                break
            r, sowings = dict(again, first_planting=plant.isoformat()), sowings + 1
        r["sowings"] = sowings
        out.append(r)
    return out
