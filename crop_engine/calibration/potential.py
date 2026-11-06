"""Yield potential under full irrigation: AquaCrop with net irrigation (the root zone kept above 80 % of its
available water), no rain, and ET0 from the site's temperatures (Hargreaves) — the no-water-stress yield of a
variety at a site and sowing date, for yield checks against well-watered trials.

Kept apart from the AquaCrop adapter (whose changes rebuild every crop result): only the calibration uses it.
A generic loam is used: with no water stress the soil barely matters.
"""
import warnings

import numpy as np
import pandas as pd

NET_IRRIGATION_SMT = 80          # % of the root zone's available water kept by net irrigation (AquaCrop method 4)


def extraterrestrial_radiation(dates, lat):
    """Ra (MJ m-2 day-1), FAO-56 eq. 21."""
    j = pd.DatetimeIndex(dates).dayofyear.values
    phi = np.radians(lat)
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    d = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(d), -1, 1))
    return 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(d) + np.cos(phi) * np.cos(d) * np.sin(ws))


def hargreaves_et0(tmax, tmin, dates, lat):
    """ET0 (mm/day), Hargreaves (FAO-56 eq. 52)."""
    tmax, tmin = np.asarray(tmax, float), np.asarray(tmin, float)
    return 0.0023 * ((tmax + tmin) / 2 + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0)) * 0.408 * \
        extraterrestrial_radiation(dates, lat)


def irrigated_potential(crop, kw, temps, plant, lat, days=300):
    """crop: AquaCrop crop name; kw: its parameters (aquacrop_adapter.crop_parameters); temps: DataFrame tmax, tmin
    by date; plant: sowing date → dict(status, yield_t_ha, harvest, irrigation_mm)."""
    from aquacrop import AquaCropModel, Crop, InitialWaterContent, IrrigationManagement, Soil
    warnings.filterwarnings("ignore")
    plant = pd.Timestamp(plant)
    t = temps.loc[plant: plant + pd.Timedelta(days=days - 1)]
    if len(t) < days:
        return {"status": "no weather", "yield_t_ha": None, "harvest": None, "irrigation_mm": None}
    wdf = pd.DataFrame({"MinTemp": np.minimum(t.tmin.values, t.tmax.values), "MaxTemp": t.tmax.values,
                        "Precipitation": 0.0, "ReferenceET": np.maximum(hargreaves_et0(t.tmax, t.tmin, t.index, lat), 0.1),
                        "Date": t.index})
    model = AquaCropModel(sim_start_time=f"{plant:%Y/%m/%d}", sim_end_time=f"{t.index[-1]:%Y/%m/%d}", weather_df=wdf,
                          soil=Soil("Loam"), crop=Crop(crop, planting_date=f"{plant:%m/%d}", **kw),
                          initial_water_content=InitialWaterContent(value=["FC"]),
                          irrigation_management=IrrigationManagement(irrigation_method=4, NetIrrSMT=NET_IRRIGATION_SMT))
    model.run_model(till_termination=True)
    res = model.get_simulation_results()
    if not len(res):
        return {"status": "not matured", "yield_t_ha": None, "harvest": None, "irrigation_mm": None}
    return {"status": "ok", "yield_t_ha": round(float(res["Dry yield (tonne/ha)"].iloc[0]), 2),
            "harvest": f"{pd.Timestamp(res['Harvest Date (YYYY/MM/DD)'].iloc[0]):%Y-%m-%d}",
            "irrigation_mm": round(float(res["Seasonal irrigation (mm)"].iloc[0]), 0)}
