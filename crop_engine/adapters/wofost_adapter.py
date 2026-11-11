"""
WOFOST 7.2 (PCSE 6, water-limited production with the classic water balance: Wofost72_WLP_CWB) for one site,
variety and planting rule: the crop engine's second model, on the same weather, soil, initial water and sowing dates
as AquaCrop (aquacrop_adapter), and with the same task and outcome dictionaries, so either engine can run a forecast.

Weather: the task's rain, Tmax, Tmin and the ERA5-Land / SEAS5 solar radiation, vapour pressure and 2 m wind
(task keys rad, vap, wind2, from the crop-weather Dataset). WOFOST's crop transpiration is driven by ET0, which is
the task's ET0 (the platform's FAO-56 ET0, as AquaCrop's); its open-water and bare-soil evaporation (E0, ES0, PCSE's
modified Penman) are scaled by the same day's ratio of the task's ET0 to PCSE's own, so both engines see the same
evaporative demand.

Crops (WOFOST crop parameter library, Van Heemst 1988 tropical sets): maize Maize_VanHeemst_1988, sorghum
Sorghum_VanHeemst_1988. WOFOST has no dry bean set: the bean is AquaCrop-only (a task for it raises).
Phenology: TSUM1 and TSUM2 are scaled together (their ratio kept) so the crop matures in the variety's
`maturity_days` at the varieties' reference temperature (21 °C), through the crop's own DTSMTB, with emergence
from TSUMEM at TBASEM: the same targets AquaCrop's phenology is scaled to (the maize classes calibrated at Kiboko,
varieties.yaml). A variety's `flowering_days` (as AquaCrop's) sets TSUM1 apart: anthesis at that many days at the
reference temperature, TSUM2 the rest to maturity. Yield level: a variety's `wofost: {AMAXTB_scale: f}` multiplies the leaf photosynthesis table
AMAXTB (maize fitted to Duma 43 under full irrigation at Kiboko: crop_engine/calibration/wofost.py); without it,
WOFOST's own. Rooting depth: a variety's `wofost: {RDMCR: cm}` sets the crop's maximum rooting depth (maize: the
depth AquaCrop's Zmax is given, varieties.yaml); without it, the crop file's.

Soil (one root zone, as the classic water balance): the SoilGrids layers' wilting point and field capacity averaged
over the crop's maximum rooting depth (RDMCR), saturation from Saxton & Rawls (2006) Eq. 2–5 and the saturated
conductivity (Eq. 16) for the percolation limits (SOPE: the rooted zone, KSUB: below), the 200 cm profile as the
rootable depth. Initial water:
the task's initial_frac of the available water over the profile (WAV), from 1 Aug, as AquaCrop.

Outcome of a member: as aquacrop_adapter (ok, died, failed_establishment, too_late, not_sown, error), with
  died                  all leaves dead (LAI < 0.01) after emergence and before development stage 1.9, or matured
                        with no grain (below NO_GRAIN_T_HA): WOFOST's crop otherwise survives drought
  failed_establishment  died before the canopy reached 5 % cover (LAI 0.085 with extinction 0.6)
and re-sowing after a failed establishment as AquaCrop. Yield: storage organ dry weight (TWSO) in t/ha.

Management (the scenarios, crop_engine.scenarios.management), with the classic water balance, as AquaCrop's where
WOFOST has the process:
  irrigation  task "irrigation" (AquaCrop's IrrigationManagement method 1 arguments): the model is stepped day by day
              from sowing; whenever the root zone's water falls below SMT % of its available water (SMW to SMFCF) in
              the crop's growth stage (emergence: before DVS 0; canopy growth: DVS 0–0.8; maximum canopy and flowering:
              0.8–1.5; senescence: from 1.5), it is refilled to field capacity, at most MaxIrr mm a day and MaxIrrSeason
              mm a season (net water: PCSE's irrigation signal with efficiency 1)
  field       task "field" (FieldMngt arguments): mulches cut the open-soil evaporation ES0 by mulch_pct % × f_mulch, as
              AquaCrop's; sr_inhb (no surface runoff) gives the surface 10 cm of storage (SSMAX), so rain that cannot
              infiltrate at once ponds and soaks in later instead of running off. The classic balance has no
              curve-number runoff: its runoff is only that excess, so ridges change less than in AquaCrop
  density     not represented: WOFOST has no plant population (the scenario is AquaCrop's only)
A member records the irrigation it received (irrigation_mm).

Water balance (task "water_balance", default WATER_BALANCE): "cwb", WOFOST 7.2's classic one-zone balance above;
"mlwb", WOFOST 7.3's multi-layer balance (Wofost73_WLP_MLWB), on the SoilGrids layers themselves: each layer's
water retention SMfromPF anchored at its own field capacity (33 kPa, pF 2.53) and wilting point (1500 kPa, pF 4.18),
Campbell-type between them and beyond (Saxton & Rawls 2006 Eq. 11), linear to saturation (Eq. 5) above the air-entry
tension (Eq. 4), and its conductivity CONDfromPF = Ks (θ / θs)^(3 + 2/λ) (Eq. 16, 18); the 200 cm profile with the
last layer repeated below as the subsoil. Its initial water is the task's fraction of the available water in every
layer (WAV over the profile), as AquaCrop's. The crop parameters are the same library's 7.3 sets.
"""
import datetime as dt
import warnings

import numpy as np
import pandas as pd

from crop_engine.config import RESOW_MAX

CROPS = {"MaizeGDD": ("maize", "Maize_VanHeemst_1988"), "SorghumGDD": ("sorghum", "Sorghum_VanHeemst_1988")}
REFERENCE_TMEAN = 21.0            # °C: the varieties' reference temperature (varieties.yaml reference_tmean_c)
K_EXT = 0.6                       # light extinction for canopy cover from LAI (reporting only)
ESTABLISHED_LAI = -np.log(1 - 0.05) / K_EXT
CANOPY_STEP = 7
NO_GRAIN_T_HA = 0.01             # a matured crop with less grain than this counts as died
ANGST = (0.25, 0.50)              # Angstrom coefficients for PCSE's Penman E0 / ES0
_CROPDATA = {}


def available(variety):
    return variety.get("aquacrop_crop") in CROPS


def _quiet():
    """PCSE logs every phenology change of every run to ~/.pcse/logs (and several worker processes then contend for
    its log rotation): only warnings and errors are kept."""
    import logging
    logging.getLogger("pcse").setLevel(logging.WARNING)


WATER_BALANCE = "cwb"
PF_FC, PF_WP = float(np.log10(33.0 / 0.0980665)), float(np.log10(1500.0 / 0.0980665))   # 33, 1500 kPa as pF
PF_POINTS = (-1.0, 0.0, 1.0, 1.5, 2.0, 2.3, PF_FC, 2.7, 3.0, 3.4, 3.7, 4.0, PF_WP, 5.0, 6.0)


CO2_PPM = 425.0                  # WOFOST 7.3's atmospheric CO2 (2026); 7.2 has none
WB73 = ("cwb73", "mlwb")


def _model(water_balance):
    """cwb: WOFOST 7.2, classic water balance; cwb73: WOFOST 7.3, classic (the version alone, for comparisons);
    mlwb: WOFOST 7.3, multi-layer."""
    from pcse.models import Wofost72_WLP_CWB, Wofost73_WLP_CWB, Wofost73_WLP_MLWB
    return {"cwb": Wofost72_WLP_CWB, "cwb73": Wofost73_WLP_CWB, "mlwb": Wofost73_WLP_MLWB}[water_balance]


def _cropdata(water_balance="cwb"):
    """PCSE's WOFOST crop parameter library (downloaded once by PCSE, then read from its cache), per process and model."""
    _quiet()
    if water_balance not in _CROPDATA:
        from pcse.input import YAMLCropDataProvider
        _CROPDATA[water_balance] = YAMLCropDataProvider(_model(water_balance))
    return _CROPDATA[water_balance]


def _afgen(table, x):
    t = np.asarray(table, float).reshape(-1, 2)
    return np.interp(x, t[:, 0], t[:, 1])


def phenology(variety, reference_tmean=REFERENCE_TMEAN):
    """The variety's WOFOST crop, variety and TSUM overrides: TSUM1 + TSUM2 scaled to maturity_days at
    reference_tmean (after emergence) → (crop, variety name, overrides, base parameters)."""
    if not available(variety):
        raise ValueError(f"{variety.get('label', variety.get('aquacrop_crop'))}: no WOFOST crop parameter set")
    crop, name = CROPS[variety["aquacrop_crop"]]
    p = _cropdata()
    p.set_active_crop(crop, name)
    base = {k: p[k] for k in ("TSUMEM", "TBASEM", "TEFFMX", "TSUM1", "TSUM2", "DTSMTB", "AMAXTB", "RDMCR")}
    emerge_days = base["TSUMEM"] / max(min(reference_tmean, base["TEFFMX"]) - base["TBASEM"], 0.1)
    rate = float(_afgen(base["DTSMTB"], reference_tmean))
    total = max(variety["maturity_days"] - emerge_days, 10) * rate
    share = base["TSUM1"] / (base["TSUM1"] + base["TSUM2"])
    if variety.get("flowering_days"):                                   # anthesis set apart (varieties.yaml)
        share = min(max((variety["flowering_days"] - emerge_days) * rate / total, 0.05), 0.95)
    over = {"TSUM1": round(total * share, 1), "TSUM2": round(total * (1 - share), 1)}
    scale = (variety.get("wofost") or {}).get("AMAXTB_scale")
    if scale is not None:                                               # the yield level (calibration/wofost.py)
        t = list(base["AMAXTB"])
        over["AMAXTB"] = [v * scale if i % 2 else v for i, v in enumerate(t)]
    rdmcr = (variety.get("wofost") or {}).get("RDMCR")
    if rdmcr is not None:                                               # the maximum rooting depth (varieties.yaml)
        over["RDMCR"] = base["RDMCR"] = float(rdmcr)
    return crop, name, over, base


def thermal(tmax, tmin, base, over):
    """Daily development (°C d) toward maturity of each day: DTSMTB of the mean temperature (after emergence)."""
    return _afgen(base["DTSMTB"], (np.asarray(tmax) + np.asarray(tmin)) / 2)


def soil_parameters(layers, initial_frac, root_depth_cm=100.0):
    """Classic water balance soil and site parameters from the SoilGrids layers (module doc)."""
    def w(depth_lo, depth_hi):
        out = []
        for L in layers:
            lo, hi = max(depth_lo, L.top_cm), min(depth_hi, L.bottom_cm)
            if hi > lo:
                out.append((L, hi - lo))
        return out

    def sat_ks(L):
        S, Cl, OM = L.sand / 100, L.clay / 100, L.om
        t = 0.278 * S + 0.034 * Cl + 0.022 * OM - 0.018 * S * OM - 0.027 * Cl * OM - 0.584 * S * Cl + 0.078
        ts33 = t + (0.636 * t - 0.107)                                 # Eq. 2
        ts = L.theta_fc + ts33 - 0.097 * S + 0.043                      # Eq. 5
        B = (np.log(1500) - np.log(33)) / (np.log(L.theta_fc) - np.log(L.theta_wp))
        ks = 1930 * max(ts - L.theta_fc, 0.01) ** (3 - 1 / B)          # Eq. 16, mm/h
        return ts, ks * 2.4                                             # cm/day

    top = w(0, root_depth_cm)
    sub = w(root_depth_cm, 1e9) or top
    avg = lambda f, part: sum(f(L) * d for L, d in part) / sum(d for _, d in part)
    smfcf, smw = avg(lambda L: L.theta_fc, top), avg(lambda L: L.theta_wp, top)
    sm0 = max(avg(lambda L: sat_ks(L)[0], top), smfcf + 0.03)
    depth = float(layers[-1].bottom_cm)
    soil = {"SMFCF": smfcf, "SMW": smw, "SM0": sm0, "CRAIRC": 0.06, "RDMSOL": depth, "K0": 10.0,
            "SOPE": float(np.clip(avg(lambda L: sat_ks(L)[1], top), 0.1, 10.0)),
            "KSUB": float(np.clip(avg(lambda L: sat_ks(L)[1], sub), 0.05, 10.0)), "SPADS": 0.1, "SPODS": 0.03,
            "SPASS": 0.2, "SPOSS": 0.05, "DEFLIM": -0.3}
    site = {"WAV": float(np.clip(initial_frac, 0, 1)) * (smfcf - smw) * depth, "SMLIM": smfcf, "IFUNRN": 0,
            "NOTINF": 0.0, "SSMAX": 0.0, "SSI": 0.0}
    return soil, site


def _saxton(L):
    """Saturation, air-entry tension (kPa), Campbell B and saturated conductivity (cm/day) of a SoilGrids layer, its
    retention anchored at the layer's own field capacity and wilting point (Saxton & Rawls 2006)."""
    S, Cl, OM = L.sand / 100, L.clay / 100, L.om
    t = 0.278 * S + 0.034 * Cl + 0.022 * OM - 0.018 * S * OM - 0.027 * Cl * OM - 0.584 * S * Cl + 0.078
    ts33 = t + (0.636 * t - 0.107)                                     # Eq. 2
    ts = max(L.theta_fc + ts33 - 0.097 * S + 0.043, L.theta_fc + 0.03)   # Eq. 5
    pet = -21.67 * S - 27.93 * Cl - 81.97 * ts33 + 71.12 * S * ts33 + 8.29 * Cl * ts33 + 14.05 * S * Cl + 27.16
    psi_e = float(np.clip(pet + (0.02 * pet ** 2 - 0.113 * pet - 0.70), 0.5, 30.0))   # Eq. 4
    B = (np.log(1500) - np.log(33)) / (np.log(L.theta_fc) - np.log(L.theta_wp))
    ks = 1930 * (ts - L.theta_fc) ** (3 - 1 / B) * 2.4                 # Eq. 16: mm/h → cm/day
    return ts, psi_e, B, ks


def layer_curves(L):
    """SMfromPF and CONDfromPF (PCSE's flat [pF, value, ...] tables) of a SoilGrids layer (module doc)."""
    ts, psi_e, B, ks = _saxton(L)
    A = np.exp(np.log(33) + B * np.log(L.theta_fc))
    sm, cond = [], []
    for pf in PF_POINTS:
        psi = 10 ** pf * 0.0980665                                      # kPa
        if psi >= 33:
            th = (psi / A) ** (-1 / B)                                  # Eq. 11
        elif psi > psi_e:
            th = L.theta_fc + (33 - psi) * (ts - L.theta_fc) / (33 - psi_e)
        else:
            th = ts
        th = float(np.clip(th, 0.005, ts))
        sm += [pf, round(th, 5)]
        cond += [pf, round(float(np.log10(max(ks * (th / ts) ** (3 + 2 * B), 1e-12))), 5)]   # Eq. 18, 2/λ = 2B
    return sm, cond


def soil_profile(layers, initial_frac, split_at=()):
    """Multi-layer water balance soil and site parameters (module doc) → (soildata, sitedata). split_at: depths (cm)
    that must be layer boundaries (PCSE's multi-layer balance needs one at the crop's maximum rooting depth); the
    SoilGrids layer holding one is split there, keeping every piece at least 5 cm."""
    from dataclasses import replace
    cuts = sorted({float(d) for d in split_at})
    pieces = []
    for L in layers:
        edges = [L.top_cm] + [d for d in cuts if L.top_cm + 5 <= d <= L.bottom_cm - 5] + [L.bottom_cm]
        pieces += [replace(L, top_cm=a, bottom_cm=b) for a, b in zip(edges[:-1], edges[1:])]
    layers = pieces
    def layer(L, thickness):
        sm, cond = layer_curves(L)
        return {"SMfromPF": sm, "CONDfromPF": cond, "CRAIRC": 0.06, "Thickness": float(thickness),
                "FSOMI": 0.0, "RHOD": 1.4, "Soil_pH": 7.0, "CNRatioSOMI": 9.0, "SoilID": f"L{L.top_cm:.0f}"}
    profile = {"PFWiltingPoint": PF_WP, "PFFieldCapacity": PF_FC,
               "SurfaceConductivity": float(np.clip(_saxton(layers[0])[3], 1.0, 200.0)),
               "SoilLayers": [layer(L, L.bottom_cm - L.top_cm) for L in layers],
               "SubSoilType": layer(layers[-1], 200.0), "GroundWater": None}
    paw = sum((L.theta_fc - L.theta_wp) * (L.bottom_cm - L.top_cm) for L in layers)
    site = {"WAV": float(np.clip(initial_frac, 0, 1)) * paw, "SMLIM": float(layers[0].theta_fc), "IFUNRN": 0,
            "NOTINF": 0.0, "SSMAX": 0.0, "SSI": 0.0}
    return {"SoilProfileDescription": profile, "RDMSOL": float(layers[-1].bottom_cm)}, site


def _weather(task, m, dates):
    """PCSE weather of member m (WeatherDataProvider), with E0 / ES0 scaled to the task's ET0 (module doc)."""
    from pcse.base import WeatherDataContainer, WeatherDataProvider
    from pcse.util import reference_ET

    class Weather(WeatherDataProvider):
        pass

    wdp = Weather()
    lat, lon, elev = float(task["lat"]), float(task.get("lon", 0.0)), float(task["elev"])
    tx, tn, rr = task["tmax"][m], task["tmin"][m], task["rain"][m]
    rad, vap, wind, et0 = task["rad"][m], task["vap"][m], task["wind2"][m], task["et0"][m]
    for k, d in enumerate(dates):
        day = d.date()
        tmin = float(min(tn[k], tx[k]))
        e0, es0, et0p = reference_ET(day, lat, elev, tmin, float(tx[k]), float(rad[k]) * 1e6, float(vap[k]),
                                     float(wind[k]), ANGST[0], ANGST[1])
        r = float(et0[k]) / et0p if et0p > 0.05 else 1.0
        es_r = r * float(task.get("es0_factor", 1.0))                  # mulch: less open-soil evaporation
        wdp._store_WeatherDataContainer(WeatherDataContainer(
            LAT=lat, LON=lon, ELEV=elev, DAY=day, IRRAD=float(rad[k]) * 1e6, TMIN=tmin, TMAX=float(tx[k]),
            VAP=float(np.clip(vap[k], 0.1, 199)), RAIN=float(np.clip(rr[k], 0, 249)) / 10.0, WIND=float(wind[k]),
            E0=float(np.clip(e0 * r, 0, 24.9)) / 10.0, ES0=float(np.clip(es0 * es_r, 0, 24.9)) / 10.0,
            ET0=float(np.clip(et0[k], 0, 24.9)) / 10.0), day)
    return wdp


def _sow(task, m, plant, dates, dev):
    """One sowing of member m on `plant` → outcome dict, as aquacrop_adapter._sow."""
    from pcse.base import ParameterProvider
    r = dict(member=m + 1, planting=plant.isoformat(), status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
             biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None, sources=None)
    k0 = int(dates.get_indexer([pd.Timestamp(plant)])[0])
    if k0 < 0:
        return dict(r, status="error", error="planting date outside the weather period")
    crop, name, over, base = task["wofost"]
    tmean = (task["tmax"][m] + task["tmin"][m]) / 2
    em = np.cumsum(np.clip(np.minimum(tmean[k0:], base["TEFFMX"]) - base["TBASEM"], 0, None))
    if em[-1] < base["TSUMEM"]:
        return dict(r, status="too_late")
    ke = k0 + int(np.argmax(em >= base["TSUMEM"]))
    cum = np.cumsum(dev[ke:])
    need = over["TSUM1"] + over["TSUM2"]
    if cum[-1] <= need * 1.01:
        return dict(r, status="too_late")
    expected_maturity = dates[ke + int(np.argmax(cum > need))]
    try:
        wb = task.get("water_balance") or WATER_BALANCE
        p = _cropdata(wb)
        p.set_active_crop(crop, name)
        site = dict(task["site"], **({"CO2": CO2_PPM} if wb in WB73 else {}))
        params = ParameterProvider(cropdata=p, soildata=task["soil"], sitedata=site)
        for k, v in over.items():
            params.set_override(k, v, check=False)
        agro = [{dates[0].date(): {"CropCalendar": {
            "crop_name": crop, "variety_name": name, "crop_start_date": plant, "crop_start_type": "sowing",
            "crop_end_date": None, "crop_end_type": "maturity", "max_duration": int((dates[-1] - pd.Timestamp(plant)).days)},
            "TimedEvents": None, "StateEvents": None}}, {dates[-1].date(): None}]
        model = _model(wb)(params, _weather(task, m, dates), agro)
        irrigated = _run(model, task, plant) if task.get("irrigation") else model.run_till_terminate() or 0.0
        out = pd.DataFrame(model.get_output()).set_index("day")
    except Exception as exc:                                             # one member must not stop the others
        return dict(r, status="error", error=f"{type(exc).__name__}: {str(exc)[:160]}")
    out.index = pd.DatetimeIndex(out.index)
    grow = out[out.DVS.notna()]
    if grow.empty:
        return dict(r, status="error", error="the crop did not start")
    lai = grow.LAI.fillna(0.0)
    emerged = grow[grow.DVS > 0]
    dead = emerged[(emerged.LAI.fillna(0) < 0.01) & (emerged.DVS < 1.9) & (emerged.index > emerged.index[0] + pd.Timedelta(days=10))]
    matured = grow[grow.DVS >= 2.0]
    if len(matured):
        harvest = matured.index[0]
    elif len(dead):
        harvest = dead.index[0]
    else:
        harvest = grow.index[-1]
    upto = grow[grow.index <= harvest]
    yld = float(np.nan_to_num(upto.TWSO.max())) / 1000.0
    cc = 1 - np.exp(-K_EXT * float(lai[lai.index <= harvest].max()))
    # WOFOST's crop survives drought (its leaves die back, its stems and pods keep an area): a crop that reaches
    # maturity with no grain counts as died, as AquaCrop's would
    status = ("failed_establishment" if lai[lai.index <= harvest].max() < ESTABLISHED_LAI
              else "ok" if len(matured) and yld >= NO_GRAIN_T_HA else "died")
    kh = int(dates.get_indexer([harvest])[0])
    kh = kh if kh >= 0 else len(dates) - 1
    season = slice(k0, kh + 1)
    src = np.bincount(np.asarray(task["source"])[season].astype(int), minlength=6)
    canopy = np.zeros(len(dates), np.float32)
    lai_all = lai.reindex(dates).fillna(0.0).values
    canopy[: kh + 1] = (1 - np.exp(-K_EXT * lai_all))[: kh + 1]
    r.update(status=status, yield_t_ha=round(yld, 3), biomass_t_ha=round(float(np.nan_to_num(upto.TAGP.max())) / 1000.0, 3),
             harvest=f"{harvest:%Y-%m-%d}", expected_maturity=f"{expected_maturity:%Y-%m-%d}",
             max_canopy=round(float(cc), 3), max_lai=round(float(lai.max()), 2),
             rain_mm=round(float(task["rain"][m][season].sum()), 1), sources=src.tolist(), _canopy=canopy[::CANOPY_STEP],
             irrigation_mm=round(float(irrigated), 1))
    return r


STAGE_DVS = (0.0, 0.8, 1.5)      # DVS where AquaCrop's growth stages 2, 3, 4 start (module doc)


def _run(model, task, plant):
    """Step the model day by day, irrigating as AquaCrop's method 1 (module doc) → the season's irrigation (mm)."""
    from pcse import signals
    irr = task["irrigation"]
    smt = list(irr.get("SMT", [100, 100, 100, 100]))
    max_day, cap = float(irr.get("MaxIrr", 25.0)), float(irr.get("MaxIrrSeason", 1e9))
    smw, smfc = task["soil"]["SMW"], task["soil"]["SMFCF"]
    total = 0.0
    while not model.flag_terminate:
        if model.day >= plant and total < cap:
            dvs = model.get_variable("DVS")
            stage = 0 if dvs is None or dvs < STAGE_DVS[0] else 1 if dvs < STAGE_DVS[1] else 2 if dvs < STAGE_DVS[2] else 3
            sm, rd = model.get_variable("SM"), model.get_variable("RD") or 10.0
            if sm is not None and smt[stage] > 0 and sm < smw + smt[stage] / 100.0 * (smfc - smw):
                mm = min(max_day, (smfc - sm) * rd * 10.0, cap - total)
                if mm > 0.1:
                    model._send_signal(signal=signals.irrigate, amount=mm / 10.0, efficiency=1.0)
                    total += mm
        model.run(days=1)
    return total


def management(task):
    """The task's field management for WOFOST (module doc): es0_factor and the site's surface storage."""
    f = task.get("field") or {}
    out = {}
    if f.get("mulches"):
        out["es0_factor"] = 1.0 - float(f.get("mulch_pct", 50)) / 100.0 * float(f.get("f_mulch", 0.5))
    if f.get("sr_inhb"):
        out["site"] = dict(task["site"], SSMAX=10.0)
    return out


def prepare(task):
    """The task with its WOFOST parts: phenology overrides (task "wofost"), soil and site parameters."""
    wb = task.get("water_balance") or WATER_BALANCE
    wof = phenology(task["variety"])
    if wb == "mlwb":
        soil, site = soil_profile(task["layers"], task["initial_frac"], split_at=[wof[3]["RDMCR"]])
    else:
        soil, site = soil_parameters(task["layers"], task["initial_frac"], root_depth_cm=float(wof[3]["RDMCR"]))
    t = dict(task, wofost=wof, soil=soil, site=site)
    return dict(t, **management(t))


def simulate(task):
    """task: as aquacrop_adapter.simulate, plus rad, vap, wind2 ((member, T) or (T,)), lat, elev (and lon) →
    list of per-member outcome dicts."""
    warnings.filterwarnings("ignore")
    dates = pd.DatetimeIndex(task["dates"])
    M, T = len(task["planting"]), len(dates)
    task = dict(task, **{k: np.broadcast_to(np.asarray(task[k], np.float64), (M, T))
                         for k in ("tmax", "tmin", "et0", "rad", "vap", "wind2")})
    task = prepare(task) if "wofost" not in task else task
    _, _, over, base = task["wofost"]
    dev = thermal(task["tmax"], task["tmin"], base, over)
    resow = task.get("resow") or [[] for _ in task["planting"]]
    out = []
    for m, plant in enumerate(task["planting"]):
        if plant is None:
            out.append(dict(member=m + 1, planting=None, status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
                            biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None,
                            sources=None, sowings=0))
            continue
        r, sowings = _sow(task, m, plant, dates, dev[m]), 1
        while r["status"] == "failed_establishment" and sowings <= RESOW_MAX:
            died = dt.date.fromisoformat(r["harvest"])
            later = [d for d in resow[m] if d > died]
            if not later:
                break
            again = _sow(task, m, later[0], dates, dev[m])
            if again["status"] in ("too_late", "error"):
                break
            r, sowings = dict(again, first_planting=plant.isoformat()), sowings + 1
        r["sowings"] = sowings
        out.append(r)
    return out
