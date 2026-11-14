"""
DSSAT CSM 4.8 (CERES-Maize, CERES-Sorghum, CROPGRO-Dry bean) for one site, variety and planting rule: a third crop
engine on the same weather, soil, initial water and sowing dates as AquaCrop and WOFOST (aquacrop_adapter,
wofost_adapter), with the same task and outcome dictionaries, so any engine can run a forecast.

The model: the DSSAT Cropping System Model's own program (dscsm048.exe), not a re-implementation. It is installed
once into data/crop_engine/dssat (install(), `python -m crop_engine.adapters.dssat_adapter --install`): the program
and its standard data (cultivar, ecotype and species files, CO2 series) are taken from the DSSATTools wheel on PyPI
(version and SHA-256 pinned below), which ships DSSAT's open-source build; nothing of DSSATTools' Python code is
used. Each task runs in its own folder under data/crop_engine/dssat/run: the experiment file (FileX) with one
treatment per member, one weather file per member, the site's soil profile, and DSSAT's run profile (DSSATPRO.V48)
pointing to the standard data; `dscsm048.exe A <FileX>` runs every treatment and Summary.OUT and PlantGro.OUT are
read back. A member DSSAT could not run is retried alone, then reported as an error.

Production: water-limited (WATER Y, NITRO N), as AquaCrop's and WOFOST's: no nitrogen, phosphorus, pest or disease
limitation. With a task's "nitrogen" ({"rate_kg_ha": N, "split": [(days after sowing, share), ...]}: crop_engine.
run_nitrogen) DSSAT's nitrogen balance is on (NITRO Y; the bean's fixation too, SYMBI Y): urea at those days after
sowing (FERTI D), the soil's organic nitrogen from its organic carbon (SLNI = SLOC / C_TO_N × the nitrogen's
"organic_n_factor": a cropped field's depleted organic nitrogen, calibration/dssat.py --nitrogen), its mineral nitrogen
at the start the nitrogen's "initial_no3_ppm" / "initial_nh4_ppm" (default INIT_NO3 / INIT_NH4) in the top 30 cm and
half that below (all three per site where fitted to a site's own field: soil_nitrogen), mineralised by DSSAT's
CERES-Godwin soil organic matter module; no residues, phosphorus or potassium.

Weather (one file per member): the task's rain, Tmax, Tmin, solar radiation, vapour pressure and 2 m wind; DSSAT's
own FAO-56 Penman-Monteith reference ET (EVAPO F) from them, so its demand follows the same ERA5-Land / SEAS5
radiation, humidity and wind as the platform's FAO-56 ET0 (DSSAT cannot be given an ET0 series). TAV and AMP (soil
temperature) from the task's own temperatures.

Soil (the site's SoilGrids layers): lower limit, drained upper limit (the layer's wilting point and field capacity),
saturation and saturated conductivity from Saxton & Rawls (2006) as WOFOST's (wofost_adapter._saxton), bulk density
from them, organic carbon from organic matter / 1.724, clay, silt, coarse fragments; root growth factor 1 to 15 cm,
exp(-0.02 × mid-depth) below, 0 below the variety's rooting depth (AquaCrop's Zmax, varieties.yaml), so the three
engines root to the same depth. Initial water at the simulation start (the task's first day, 1 Aug): the task's
initial_frac of each layer's available water, as AquaCrop's.

Crop: a variety's `dssat: {cultivar: <DSSAT cultivar id>, <coefficient>: value, ...}` (crop_engine/
dssat_cultivars.yaml, attach(); apart from varieties.yaml, so the outlook's configuration does not change) picks the
cultivar from DSSAT's own file (MZCER048.CUL, SGCER048.CUL, BNGRO048.CUL) and overrides its coefficients; the
modified cultivar is written into the run folder's copy of the file as CE0001. Plant population: the variety's
PlantPop (plants / ha, AquaCrop's parameter, or AquaCrop's default for the crop) as plants / m²; rows 75 cm (maize,
sorghum) or 50 cm (bean); sown 5 cm deep. Photosynthesis: radiation use efficiency (CERES), the canopy curve
(CROPGRO, which has no RUE option).

Outcome of a member (as aquacrop_adapter: ok, died, failed_establishment, too_late, not_sown, error):
  failed_establishment  no germination within 15 days of sowing (DSSAT's own test; this build then stops with a
                        floating-point exception before its summary, so the member is run alone and its message
                        read), no emergence, or a maximum leaf area index below 5 % canopy cover (LAI 0.085 with
                        extinction 0.6, as WOFOST's)
  ok                    physiological maturity reached with at least NO_GRAIN_T_HA of grain
  died                  emerged and established, then no grain at maturity, or the crop died before it
  too_late              alive and not mature at the season's end (harvested there: the last weather day)
Yield: DSSAT's harvested grain dry weight (HWAM, kg dm / ha) in t/ha; biomass CWAM; the canopy from the daily LAI
(1 − exp(−0.6 LAI), reporting only). Re-sowing after a failed establishment as AquaCrop. The yield without water
stress (potential_t_ha, task "potential", default on): the member's final sowing grown again with the water balance
off. Water-stress days (stress_days): days from sowing to harvest whose water stress on photosynthesis (PlantGro
WSPD, 1 − the root water uptake over the potential transpiration) is above STRESS_WSPD, i.e. the crop transpires
less than half its potential: AquaCrop's definition (config.STRESS_RATIO).

Management (the scenarios, crop_engine.scenarios.management), where DSSAT has the process:
  density     task "kw" PlantPop (plants / ha) in place of the variety's
  irrigation  task "irrigation" (AquaCrop's method 1 arguments): DSSAT's automatic irrigation (IRRIG A) whenever the
              top IRR_DEPTH_CM falls below SMT % of its available water (the first stage's threshold), back to
              field capacity, until maturity. DSSAT's automatic irrigation has no seasonal cap: a task with a
              MaxIrrSeason cap is not represented (the supplementary scenario is AquaCrop's and WOFOST's only)
  field       mulches: surface residue MULCH_KG_HA kg/ha left on the soil at the start (not incorporated), which
              DSSAT's mulch module turns into a cover that cuts soil evaporation; sr_inhb (no surface runoff, tied
              ridges or pits): the runoff curve number set to RIDGES_CN
A member records the irrigation it received (irrigation_mm, IRCM).
"""
import argparse
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from crop_engine import config as C
from crop_engine.config import RESOW_MAX

# DSSAT's program and data: the DSSATTools wheel (it ships DSSAT CSM 4.8's open-source build for Windows and Linux)
WHEEL = {"name": "DSSATTools", "version": "3.0.2",
         "sha256": "289906cc07cd2703f6a4ec6977c5451a3c1240e9cef0eb14a5cdf706ebe640d0"}
HOME = C.CACHE / "dssat"
EXE = HOME / "bin" / ("dscsm048.exe" if os.name == "nt" else "dscsm048")
DATA = HOME / "Data"
RUNS = Path(os.environ.get("CROP_ENGINE_DSSAT_RUNS") or HOME / "run")   # each task's folder (removed after it)

# AquaCrop crop → DSSAT crop code, its model and cultivar file
CROPS = {"MaizeGDD": ("MZ", "MZCER048", "MZCER048.CUL", "MZX"),
         "SorghumGDD": ("SG", "SGCER048", "SGCER048.CUL", "SGX"),
         "DryBeanGDD": ("BN", "CRGRO048", "BNGRO048.CUL", "BNX")}
# photosynthesis: radiation use efficiency for CERES, the canopy curve for CROPGRO (it has no RUE option); rows, cm
PHOTO = {"MZ": "R", "SG": "R", "BN": "C"}
ROWS_CM = {"MZ": 75, "SG": 75, "BN": 50}
CUSTOM_ID, CUSTOM_NAME = "CE0001", "crop engine"
K_EXT = 0.6
ESTABLISHED_LAI = -np.log(1 - 0.05) / K_EXT
NO_GRAIN_T_HA = 0.01
CANOPY_STEP = 7
ROW_CM, DEPTH_CM = 75, 5
C_TO_N = 10.0                     # soil organic C : N (the soil's organic nitrogen, with nitrogen on)
INIT_NO3, INIT_NH4 = 3.0, 1.0     # ppm mineral N at the start (1 Aug), top 30 cm (half below): a dry-season low
UREA = "FE005"
NO_GERMINATION, GERMINATION_DAYS = "lack of germination", 15     # DSSAT's message and its limit (days after sowing)
SOIL_PH = 6.5                    # SoilGrids pH is not in the profile; neutral (no effect while nitrogen is off)
TIMEOUT_S = 600
STRESS_WSPD = 0.5                 # PlantGro WSPD above this: transpiration below half its potential (a stress day)
IRR_DEPTH_CM = 30                 # automatic irrigation: the managed depth
MULCH_KG_HA = 3000                # the mulch scenario's surface residue (about half the soil covered by maize stover)
RIDGES_CN = 35                    # the ridges scenario's runoff curve number (rain infiltrates where it falls)
RETRIES = 3


CULTIVARS_FILE = Path(__file__).resolve().parent.parent / "dssat_cultivars.yaml"


def cultivars():
    """{variety key: {cultivar: DSSAT cultivar id, coefficient: value, ...}} (crop_engine/dssat_cultivars.yaml)."""
    import yaml
    return (yaml.safe_load(CULTIVARS_FILE.read_text(encoding="utf-8")) or {}).get("varieties") or {}


def soil_settings():
    """The soil settings of crop_engine/dssat_cultivars.yaml ("soil": organic_n_factor)."""
    import yaml
    return (yaml.safe_load(CULTIVARS_FILE.read_text(encoding="utf-8")) or {}).get("soil") or {}


def nitrogen_settings():
    """The nitrogen levels, split and sites' reported practice of crop_engine/dssat_cultivars.yaml ("nitrogen")."""
    import yaml
    return (yaml.safe_load(CULTIVARS_FILE.read_text(encoding="utf-8")) or {}).get("nitrogen") or {}


def soil_nitrogen(site_id=None):
    """A site's soil nitrogen for DSSAT's nitrogen balance: {organic_n_factor, initial_no3_ppm, initial_nh4_ppm}, each
    the site's own fitted value where there is one (dssat_cultivars.yaml "soil" sites), else the regional one, else
    the module's default (organic factor 1, INIT_NO3, INIT_NH4)."""
    soil = soil_settings()
    own = ((soil.get("sites") or {}).get(site_id) or {}) if site_id else {}
    defaults = {"organic_n_factor": 1.0, "initial_no3_ppm": INIT_NO3, "initial_nh4_ppm": INIT_NH4}
    return {k: float(own[k] if own.get(k) is not None else soil.get(k, d) if soil.get(k) is not None else d)
            for k, d in defaults.items()}


def soil_factor(site_id=None):
    """The factor on the soil's organic nitrogen for a site (soil_nitrogen)."""
    return soil_nitrogen(site_id)["organic_n_factor"]


def attach(varieties):
    """The varieties (run_outlook.load_varieties) with their DSSAT cultivar as "dssat", where there is one."""
    cv = cultivars()
    for vk, v in varieties.items():
        if vk in cv:
            v["dssat"] = dict(cv[vk])
    return varieties


def installed():
    return EXE.exists() and (DATA / "Genotype").is_dir()


def available(variety):
    return variety.get("aquacrop_crop") in CROPS and bool((variety.get("dssat") or {}).get("cultivar")) and installed()


# ── installation ────────────────────────────────────────────────────────────────────────────────────────────────────
def install(wheel=None, log=print):
    """DSSAT's program and standard data into HOME, from the pinned DSSATTools wheel (downloaded with pip when no
    local wheel is given; its SHA-256 is checked either way)."""
    with tempfile.TemporaryDirectory() as tmp:
        if wheel is None:
            subprocess.run([sys.executable, "-m", "pip", "download", f"{WHEEL['name']}=={WHEEL['version']}", "--no-deps",
                            "--only-binary", ":all:", "-d", tmp], check=True)
            wheel = next(Path(tmp).glob("*.whl"))
        wheel = Path(wheel)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if digest != WHEEL["sha256"]:
            raise RuntimeError(f"{wheel.name}: SHA-256 {digest}, expected {WHEEL['sha256']}")
        exe_name = "DSSATTools/bin/" + EXE.name
        data_pfx = "DSSATTools/dssat-csm-os/Data/"
        with zipfile.ZipFile(wheel) as z:
            names = z.namelist()
            if exe_name not in names:
                raise RuntimeError(f"{wheel.name} has no {exe_name}")
            if HOME.exists():
                shutil.rmtree(HOME / "bin", ignore_errors=True)
                shutil.rmtree(DATA, ignore_errors=True)
            for n in [exe_name] + [n for n in names if n.startswith(data_pfx) and not n.endswith("/")]:
                dest = EXE if n == exe_name else DATA / n[len(data_pfx):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
    log(f"dssat: DSSAT CSM 4.8 from {wheel.name} → {HOME}")


# ── file writers ────────────────────────────────────────────────────────────────────────────────────────────────────
def yyddd(d):
    d = pd.Timestamp(d)
    return f"{d.year % 100:02d}{d.dayofyear:03d}"


def station(m, dates):
    """The 8-character weather station of member m: a 4-character code, the first year and the number of years
    (DSSAT's file naming), also the weather file's name."""
    d = pd.DatetimeIndex(dates)
    return f"W{m:03d}{d[0].year % 100:02d}{d[-1].year - d[0].year + 1:02d}"


def weather_file(name, lat, lon, elev, dates, rain, tmax, tmin, rad, vap_hpa, wind2_ms):
    """A DSSAT weather file (.WTH): SRAD MJ m-2 d-1, TMAX / TMIN °C, RAIN mm, WIND km d-1, VAPR kPa."""
    d = pd.DatetimeIndex(dates)
    tmean = (np.asarray(tmax) + np.asarray(tmin)) / 2
    monthly = pd.Series(tmean, index=d).groupby(d.month).mean()
    tav, amp = float(np.mean(tmean)), float(monthly.max() - monthly.min()) if len(monthly) > 1 else 0.0
    out = [f"*WEATHER DATA : crop engine {name}", "",
           "@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT",
           f"  {name[:4]:4s} {lat:8.3f} {lon:8.3f} {elev:5.0f} {tav:5.1f} {amp:5.1f}  2.00  2.00",
           "@DATE  SRAD  TMAX  TMIN  RAIN  WIND  VAPR"]
    for k, day in enumerate(d):
        tx, tn = float(tmax[k]), float(tmin[k])
        tn = min(tn, tx)
        out.append(f"{yyddd(day)}{float(rad[k]):6.1f}{tx:6.1f}{tn:6.1f}{max(float(rain[k]), 0.0):6.1f}"
                   f"{max(float(wind2_ms[k]), 0.0) * 86.4:6.0f}{max(float(vap_hpa[k]), 0.1) / 10:6.2f}")
    return "\n".join(out) + "\n"


def soil_layers(layers, root_depth_cm):
    """The DSSAT soil layers (module doc) → list of dicts."""
    from dataclasses import replace
    from crop_engine.adapters.wofost_adapter import _saxton
    split = []                                                            # a layer holding the rooting depth: split
    for L in layers:
        if L.top_cm + 5 <= root_depth_cm <= L.bottom_cm - 5:
            split += [replace(L, bottom_cm=root_depth_cm), replace(L, top_cm=root_depth_cm)]
        else:
            split.append(L)
    rows = []
    for L in split:
        ts, _, _, ks = _saxton(L)                                         # ks: cm / day
        mid = (L.top_cm + L.bottom_cm) / 2
        srgf = 0.0 if L.top_cm >= root_depth_cm else 1.0 if L.bottom_cm <= 15 else float(np.exp(-0.02 * mid))
        sand, clay = float(L.sand), float(L.clay)
        rows.append({"SLB": int(round(L.bottom_cm)), "SLLL": float(L.theta_wp), "SDUL": float(L.theta_fc),
                     "SSAT": float(ts), "SRGF": srgf, "SSKS": float(ks) / 24.0,                # cm / h
                     "SBDM": float(np.clip((1 - ts) * 2.65, 0.9, 1.9)), "SLOC": float(L.om) / 1.724,
                     "SLCL": clay, "SLSI": max(100.0 - sand - clay, 0.0), "SLCF": float(getattr(L, "cfvo", 0.0) or 0.0)})
    return rows


SLNI_MIN = 0.0001                 # % total N: written with four decimals, never 0 (DSSAT reads 0 as missing)


def _slni(sloc, organic_n_factor):
    """The layer's organic nitrogen (% total N), SLOC / C_TO_N × organic_n_factor, at least SLNI_MIN: at three
    decimals a small factor rounded to 0.000, which DSSAT replaced by its own estimate (high nitrogen)."""
    return max(float(sloc) / C_TO_N * float(organic_n_factor), SLNI_MIN)


def _slni_field(v):
    """A 6-character field with a leading blank: '.0580' below 1 (four decimals), '1.234' above."""
    return f"{f'{v:.4f}'[1:] if v < 1 else f'{v:.3f}':>6s}"


def soil_file(soil_id, lat, lon, layers, root_depth_cm, nitrogen=False, organic_n_factor=1.0, curve_number=None,
              cn_adj_pct=0.0):
    """A DSSAT soil file (.SOL) with one profile (nitrogen: the layers' organic nitrogen, SLNI = SLOC / C_TO_N ×
    organic_n_factor; cn_adj_pct: the texture's runoff curve number changed by that %, as AquaCrop's field practices)."""
    rows = soil_layers(layers, root_depth_cm)
    top = rows[0]
    sand0 = 100 - top["SLCL"] - top["SLSI"]
    # surface: albedo, stage-1 evaporation limit (mm), drainage rate (fraction / day), runoff curve number
    slu1 = 6.0 if sand0 > 70 else 9.0 if top["SLCL"] < 35 else 12.0
    sldr = 0.6 if sand0 > 70 else 0.4 if top["SLCL"] < 35 else 0.25
    slro = float(curve_number) if curve_number else 70.0 if sand0 > 70 else 76.0 if top["SLCL"] < 35 else 82.0
    if not curve_number and cn_adj_pct:
        slro = round(slro * (1.0 + float(cn_adj_pct) / 100.0), 1)
    out = ["*SOILS: crop engine (SoilGrids)", "",
           f"*{soil_id:10s}  SoilGrids   -99   {rows[-1]['SLB']:5d} crop engine SoilGrids profile",
           "@SITE        COUNTRY          LAT     LONG SCS FAMILY",
           f" -99         KE          {lat:8.3f} {lon:8.3f} -99",
           "@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE",
           f"   -99  0.13{slu1:6.1f}{sldr:6.2f}{slro:6.1f}  1.00  1.00 IB001 IB001 IB001",
           "@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC"]
    for r in rows:
        out.append(f"{r['SLB']:6d}   -99{r['SLLL']:6.3f}{r['SDUL']:6.3f}{r['SSAT']:6.3f}{r['SRGF']:6.3f}{r['SSKS']:6.2f}"
                   f"{r['SBDM']:6.2f}{r['SLOC']:6.2f}{r['SLCL']:6.1f}{r['SLSI']:6.1f}{r['SLCF']:6.1f}"
                   + (_slni_field(_slni(r['SLOC'], organic_n_factor)) if nitrogen else "   -99")
                   + f"{SOIL_PH:6.1f}   -99   -99   -99")
    return "\n".join(out) + "\n"


def cultivar_file(base_file, cultivar, overrides):
    """DSSAT's cultivar file with the variety's cultivar copied as CUSTOM_ID and its coefficients overridden: the
    file's comment and header lines, the base cultivar's line, and the custom line (the same column widths)."""
    lines = Path(base_file).read_text(encoding="latin-1").splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith("@VAR"))
    names = lines[head][1:].split()
    eco_end = lines[head].index("ECO#") + 4                                 # the fixed part ends with ECO#
    base = next((ln for ln in lines[head + 1:] if ln[:6].strip() == cultivar), None)
    if base is None:
        raise ValueError(f"cultivar {cultivar} not in {Path(base_file).name}")
    coef_names = names[names.index("ECO#") + 1:]
    values = base[eco_end:].split()
    unknown = set(overrides) - set(coef_names)
    if unknown:
        raise ValueError(f"{', '.join(sorted(unknown))}: not coefficients of {Path(base_file).name} ({', '.join(coef_names)})")
    fields = []
    for n, v in zip(coef_names, values):
        x = overrides.get(n)
        fields.append(v.rjust(6) if x is None else _fit6(float(x)))
    prefix = (CUSTOM_ID + " " + CUSTOM_NAME.ljust(16) + base[23:eco_end])[:eco_end]
    custom = prefix + "".join(fields)
    return "\n".join(lines[:head + 1] + [base, custom]) + "\n"


def _fit6(x):
    """x in 6 characters with a leading space (the cultivar files' fixed columns), as many decimals as fit."""
    for p in (3, 2, 1, 0):
        s = f"{x:6.{p}f}"
        if len(s) <= 6 and s[0] == " ":
            return s
    raise ValueError(f"{x}: does not fit a cultivar coefficient's 6 columns")


def experiment_file(name, crop, cultivar_id, soil_id, start, plantings, stations, init_sh2o, ppop_m2, last_day,
                    water=True, nitrogen=None, irrigation=None, mulch_kg_ha=0):
    """The FileX: one treatment per planting (member), each with its own field (weather station) and planting date;
    initial water at `start`; harvest at maturity, or on `last_day` when not mature by then. water False: no water
    balance (no water stress: the yield without water limitation, for the calibration). nitrogen: the nitrogen
    balance on, with urea applications {"rate_kg_ha", "split": [(days after sowing, share), ...]} (module doc)."""
    n = len(plantings)
    auto_irr = bool(irrigation) and water
    ithrl = int(round(float((irrigation or {}).get("SMT", [70])[0]))) if auto_irr else 50
    rate = float((nitrogen or {}).get("rate_kg_ha") or 0.0)
    mf = 1 if nitrogen and rate > 0 else 0
    out = [f"*EXP.DETAILS: {name}{crop} CROP ENGINE MEMBERS", "",
           "*TREATMENTS                        -------------FACTOR LEVELS------------",
           "@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM"]
    for k in range(n):
        out.append(f"{k + 1:2d} 1 0 0 {'M' + str(k + 1):25s}{1:3d}{k + 1:3d}{0:3d}{1:3d}{k + 1:3d}{0:3d}{mf:3d}"
                   + f"{0:3d}" * 5 + f"{1:3d}")
    out += ["", "*CULTIVARS", "@C CR INGENO CNAME", f" 1 {crop} {cultivar_id:6s} {CUSTOM_NAME if cultivar_id == CUSTOM_ID else cultivar_id}",
            "", "*FIELDS",
            "@L ID_FIELD WSTA....  FLSA  FLOB  FLDT  FLDD  FLDS  FLST SLTX  SLDP  ID_SOIL    FLNAME"]
    for k, st in enumerate(stations):
        out.append(f"{k + 1:2d} CEFL{k + 1:04d} {st:8s}   -99     0 DR000     0     0 00000 -99    -99  {soil_id:10s} -99")
    out += ["", "*INITIAL CONDITIONS",
            "@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME",
            f" 1    {crop} {yyddd(start)}   -99   -99     1     1   -99"
            + (f"{int(mulch_kg_ha):6d}   0.8     0     0     0 -99" if mulch_kg_ha else "   -99   -99   -99   -99   -99 -99"),
            "@C  ICBL  SH2O  SNH4  SNO3"]
    nh4 = float((nitrogen or {}).get("initial_nh4_ppm", INIT_NH4))
    no3 = float((nitrogen or {}).get("initial_no3_ppm", INIT_NO3))
    out += [f" 1{slb:6d}{sh2o:6.3f}{nh4 * (1 if slb <= 30 else 0.5):6.2f}{no3 * (1 if slb <= 30 else 0.5):6.2f}"
            for slb, sh2o in init_sh2o]
    out += ["", "*PLANTING DETAILS",
            "@P PDATE EDATE  PPOP  PPOE  PLME  PLDS  PLRS  PLRD  PLDP  PLWT  PAGE  PENV  PLPH  SPRL                        PLNAME"]
    for k, p in enumerate(plantings):
        out.append(f"{k + 1:2d} {yyddd(p)}   -99{ppop_m2:6.1f}{ppop_m2:6.1f}     S     R{ROWS_CM.get(crop, ROW_CM):6d}     0{DEPTH_CM:6d}"
                   "   -99   -99   -99   -99     0                        -99")
    if mf:
        out += ["", "*FERTILIZERS (INORGANIC)",
                "@F FDATE  FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD FERNAME"]
        for das, share in nitrogen.get("split") or [(0, 1.0)]:
            out.append(f" 1 {int(das):5d} {UREA} AP002     5{rate * float(share):6.0f}     0     0     0     0   -99 -99")
    s = yyddd(start)
    out += ["", "*SIMULATION CONTROLS",
            "@N GENERAL     NYERS NREPS START SDATE RSEED SNAME.................... SMODEL",
            f" 1 GE              1     1     S {s}  2150 CROP ENGINE",
            "@N OPTIONS     WATER NITRO SYMBI PHOSP POTAS DISES  CHEM  TILL   CO2",
            f" 1 OP              {'Y' if water else 'N'}     {'Y' if nitrogen else 'N'}     {'Y' if nitrogen and crop == 'BN' else 'N'}"
            "     N     N     N     N     N     M",
            "@N METHODS     WTHER INCON LIGHT EVAPO INFIL PHOTO HYDRO NSWIT MESOM MESEV MESOL",
            f" 1 ME              M     M     E     F     S     {PHOTO.get(crop, 'R')}     R     1     G     S     2",
            "@N MANAGEMENT  PLANT IRRIG FERTI RESID HARVS",
            f" 1 MA              R     {'A' if auto_irr else 'N'}     {'D' if mf else 'N'}     N     A",
            "@N OUTPUTS     FNAME OVVEW SUMRY FROPT GROUT CAOUT WAOUT NIOUT MIOUT DIOUT VBOSE CHOUT OPOUT FMOPT",
            " 1 OU              N     N     Y     1     Y     N     N     N     N     N     Y     N     N     A",
            "",
            "@  AUTOMATIC MANAGEMENT",
            "@N PLANTING    PFRST PLAST PH2OL PH2OU PH2OD PSTMX PSTMN",
            f" 1 PL          {s} {yyddd(last_day)}    40   100    30    40    10",
            "@N IRRIGATION  IMDEP ITHRL ITHRU IROFF IMETH IRAMT IREFF",
            f" 1 IR          {IRR_DEPTH_CM:5d}{ithrl:6d}   100 GS000 IR001    10     1",
            "@N NITROGEN    NMDEP NMTHR NAMNT NCODE NAOFF",
            " 1 NI             30    50    25 FE001 GS000",
            "@N RESIDUES    RIPCN RTIME RIDEP",
            " 1 RE            100     1    20",
            "@N HARVEST     HFRST HLAST HPCNP HPCNR",
            f" 1 HA              0 {yyddd(last_day)}   100     0", ""]
    return "\n".join(out) + "\n"


def short_path(p):
    """p as Windows' short (8.3) path where the drive keeps short names: DSSAT reads at most about 80 characters of
    a path in its run profile (elsewhere, or with no short name, p unchanged)."""
    p = str(Path(p))
    if os.name != "nt":
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
    return buf.value if 0 < n < 1024 else p


MAX_PATH = 79


def run_profile(folder, crop, model):
    """DSSAT's run profile (DSSATPRO.V48) for a run folder: weather and soil in the folder, standard data in HOME."""
    paths = {"WED": folder, "CRD": DATA / "Genotype", "PSD": DATA / "Pest", "SLD": folder, "STD": DATA / "StandardData"}
    paths = {k: short_path(v) for k, v in paths.items()}
    too_long = [v for v in paths.values() if len(v) > MAX_PATH]
    if too_long:
        raise RuntimeError(f"DSSAT path over {MAX_PATH} characters (no short name): {too_long[0]}")
    return (f"WED    {paths['WED']}\nM{crop}    {paths['WED']} {EXE.stem} {model}\nCRD    {paths['CRD']}\n"
            f"PSD    {paths['PSD']}\nSLD    {paths['SLD']}\nSTD    {paths['STD']}\n")


# ── output readers ──────────────────────────────────────────────────────────────────────────────────────────────────
def _num(v):
    try:
        x = float(v)
    except ValueError:
        return None
    return None if x <= -98.5 else x


def read_summary(text):
    """Summary.OUT → {treatment number: {column: value}}. The file is fixed-width: a number sits right-aligned under
    its column name (it ends where the name ends, and starts after the previous name); text columns (names with
    dots, e.g. TNAM....) can hold spaces, and only the numeric columns are read."""
    import re
    out, spans = {}, None
    for ln in text.splitlines():
        if ln.startswith("@"):
            toks = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", ln)]
            spans, prev = [], 0
            for name, a, b in toks:
                if name != "@" and "." not in name:
                    spans.append((name, prev, b))
                prev = b
            continue
        if spans and ln.strip() and not ln.startswith(("*", "!", "$")):
            row = {name: ln[a:b].strip() for name, a, b in spans}
            if row.get("TRNO", "").isdigit():
                out[int(row["TRNO"])] = row
    return out


def read_plantgro(text):
    """PlantGro.OUT → {treatment number: DataFrame (date, lai, wspd)}: each run's block starts with a "*RUN" line
    ending with its treatment number, then the "@YEAR DOY ..." table (wspd: the water stress on photosynthesis)."""
    import re
    runs, trno, cols = {}, None, None
    for ln in text.splitlines():
        if ln.startswith("*RUN"):
            m = re.search(r"(\d+)\s*$", ln)
            trno, cols = (int(m.group(1)) if m else None), None
            continue
        if ln.startswith("@YEAR"):
            cols = ln[1:].split()
            runs.setdefault(trno, [])
            continue
        if cols and trno is not None and ln.strip() and not ln.startswith(("*", "$", "!")):
            v = ln.split()
            if len(v) >= len(cols):
                runs[trno].append(dict(zip(cols, v)))
    frames = {}
    for k, rr in runs.items():
        if not rr:
            continue
        f = pd.DataFrame(rr)
        date = pd.to_datetime(f["YEAR"].astype(int).astype(str) + f["DOY"].astype(int).astype(str).str.zfill(3), format="%Y%j")
        frames[k] = pd.DataFrame({"date": date, "lai": pd.to_numeric(f.get("LAID"), errors="coerce").fillna(0.0),
                                  "wspd": pd.to_numeric(f["WSPD"], errors="coerce").fillna(0.0) if "WSPD" in f
                                  else np.zeros(len(f))})
    return frames


def cultivar_coefficients(crop_key, cultivar):
    """{coefficient: value} of a cultivar in DSSAT's own file for the AquaCrop crop key (e.g. MaizeGDD)."""
    cul = DATA / "Genotype" / CROPS[crop_key][2]
    lines = cul.read_text(encoding="latin-1").splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith("@VAR"))
    names = lines[head][1:].split()
    eco_end = lines[head].index("ECO#") + 4
    base = next((ln for ln in lines[head + 1:] if ln[:6].strip() == cultivar), None)
    if base is None:
        raise ValueError(f"cultivar {cultivar} not in {cul.name}")
    return {n: float(v) for n, v in zip(names[names.index("ECO#") + 1:], base[eco_end:].split())}


def _date(v):
    x = _num(v)
    if x is None or x <= 0:
        return None
    x = int(x)
    return dt.datetime.strptime(f"{x:07d}", "%Y%j").date() if x > 99999 else dt.datetime.strptime(f"{x:05d}", "%y%j").date()


def outcome(row, lai, last_day):
    """A member's outcome from its Summary.OUT row and daily LAI (module doc)."""
    pdat, edat, mdat, hdat = (_date(row.get(k)) for k in ("PDAT", "EDAT", "MDAT", "HDAT"))
    hwam, cwam = _num(row.get("HWAM")), _num(row.get("CWAM"))
    yld = (hwam or 0.0) / 1000.0
    laix = float(lai.lai.max()) if lai is not None and len(lai) else (_num(row.get("LAIX")) or 0.0)
    if edat is None or laix < ESTABLISHED_LAI:
        status = "failed_establishment"
    elif mdat is not None:
        status = "ok" if yld >= NO_GRAIN_T_HA else "died"
    else:
        alive = lai is not None and len(lai) and float(lai.lai.iloc[-1]) >= 0.01
        status = "too_late" if alive and (hdat is None or hdat >= last_day) else "died"
    harvest = mdat or hdat
    if status == "failed_establishment" and lai is not None and len(lai):
        dead = lai[(lai.lai < 0.01) & (lai.date > pd.Timestamp(edat or pdat or last_day))]
        harvest = dead.date.iloc[0].date() if len(dead) else harvest
    return dict(status=status, yield_t_ha=round(yld if status in ("ok", "died") else 0.0, 3),
                biomass_t_ha=None if cwam is None else round(cwam / 1000.0, 3),
                harvest=None if harvest is None else harvest.isoformat(),
                emergence=None if edat is None else edat.isoformat(),
                anthesis=None if _date(row.get("ADAT")) is None else _date(row.get("ADAT")).isoformat(),
                max_lai=round(laix, 2), max_canopy=round(float(1 - np.exp(-K_EXT * laix)), 3))


# ── runs ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _run_folder():
    RUNS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="r", dir=RUNS))


def run_members(task, members, plantings, water=None):
    """DSSAT for the given members (indices) sown on `plantings` → {member: (Summary row or None, LAI frame or None)}."""
    v = task["variety"]
    crop, model, cul_file, ext = CROPS[v["aquacrop_crop"]]
    cfg = dict(v.get("dssat") or {})
    cultivar = cfg.pop("cultivar")
    dates = pd.DatetimeIndex(task["dates"])
    root = float((v.get("parameters") or {}).get("Zmax", 2.0)) * 100
    from crop_engine.data.soil import restrictive_cm
    if restrictive_cm(task["layers"]) is not None:                   # a restrictive layer stops the roots (soil_depth)
        root = min(root, restrictive_cm(task["layers"]))
    folder = _run_folder()
    try:
        cul_id = cultivar
        if cfg:
            (folder / cul_file).write_text(cultivar_file(DATA / "Genotype" / cul_file, cultivar, cfg), encoding="latin-1")
            cul_id = CUSTOM_ID
        soil_id = "CESOIL0001"
        nit = task.get("nitrogen")
        (folder / "SOIL.SOL").write_text(soil_file(soil_id, task["lat"], task.get("lon", 0.0), task["layers"], root,
                                                   nitrogen=bool(nit), organic_n_factor=float((nit or {}).get("organic_n_factor", 1.0)),
                                                   curve_number=RIDGES_CN if (task.get("field") or {}).get("sr_inhb") else None,
                                                   cn_adj_pct=(task.get("field") or {}).get("curve_number_adj_pct", 0.0)),
                                         encoding="ascii")
        stations = []
        for m in members:
            st = station(m + 1, dates)
            stations.append(st)
            (folder / f"{st}.WTH").write_text(weather_file(
                st, task["lat"], task.get("lon", 0.0), task["elev"], dates, task["rain"][m], task["tmax"][m],
                task["tmin"][m], task["rad"][m], task["vap"][m], task["wind2"][m]), encoding="ascii")
        rows = soil_layers(task["layers"], root)
        frac = float(np.clip(task["initial_frac"], 0, 1))
        init = [(r["SLB"], r["SLLL"] + frac * (r["SDUL"] - r["SLLL"])) for r in rows]
        ppop = float((task.get("kw") or {}).get("PlantPop") or (v.get("parameters") or {}).get("PlantPop")
                     or _default_pop(v["aquacrop_crop"])) / 10000.0
        last = dates[-2].date()
        fx = f"CE{dates[0].year % 100:02d}0001.{ext}"
        (folder / fx).write_text(experiment_file("CE000001", crop, cul_id, soil_id, dates[0].date(), plantings,
                                                 stations, init, ppop, last,
                                                 water=task.get("water", True) if water is None else water,
                                                 nitrogen=task.get("nitrogen"), irrigation=task.get("irrigation"),
                                                 mulch_kg_ha=MULCH_KG_HA if (task.get("field") or {}).get("mulches") else 0),
                                 encoding="ascii")
        (folder / "DSSATPRO.V48").write_text(run_profile(folder, crop, model), encoding="ascii")
        env = dict(os.environ, DSSAT_HOME=short_path(DATA) + os.sep)
        run = subprocess.run([str(EXE), "A", fx], cwd=short_path(folder), env=env, capture_output=True, text=True,
                             timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, errors="replace")
        summ = read_summary((folder / "Summary.OUT").read_text(encoding="latin-1")) if (folder / "Summary.OUT").exists() else {}
        lai = read_plantgro((folder / "PlantGro.OUT").read_text(encoding="latin-1")) if (folder / "PlantGro.OUT").exists() else {}
        out = {}
        for k, m in enumerate(members):
            row = summ.get(k + 1)
            out[m] = (row, lai.get(k + 1) if row is not None else None)
        # DSSAT 4.8 stops (a floating-point exception) right after "Crop failure because of lack of germination
        # within 15 days of sowing", before its summary: for a member run alone, that is its outcome
        if len(members) == 1 and out[members[0]][0] is None and NO_GERMINATION in (run.stdout or ""):
            out[members[0]] = ({"_no_germination": True}, None)
        lines = [ln.strip() for ln in (run.stdout or "").splitlines() + (run.stderr or "").splitlines() if ln.strip()]
        said = " | ".join(ln for ln in lines if not ln.startswith("#"))[:300]          # not the backtrace
        for m in members:                                                  # not run: DSSAT's last words kept
            if out[m][0] is None:
                out[m] = ({"_error": f"exit {run.returncode}: {said or 'no output'}"}, None)
        if not os.environ.get("CROP_ENGINE_DSSAT_KEEP"):
            shutil.rmtree(folder, ignore_errors=True)
        return out
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _failed(row):
    return row is None or bool(row.get("_error"))


def _default_pop(crop_key):
    from aquacrop.entities.crop import crop_params
    return float(crop_params[crop_key]["PlantPop"])


def _member(task, m, plant, row, lai, dates):
    r = dict(member=m + 1, planting=plant.isoformat(), status="error", yield_t_ha=0.0, potential_t_ha=None,
             biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None, sources=None)
    if row is None or row.get("_error"):
        return dict(r, error=f"DSSAT did not run this member ({(row or {}).get('_error', 'no summary')})")
    if row.get("_no_germination"):                                       # DSSAT's own failure: no germination
        died = plant + dt.timedelta(days=GERMINATION_DAYS)
        return dict(r, status="failed_establishment", harvest=died.isoformat(), max_canopy=0.0, max_lai=0.0,
                    rain_mm=round(float(np.asarray(task["rain"][m])[
                        max(int(dates.get_indexer([pd.Timestamp(plant)])[0]), 0):
                        max(int(dates.get_indexer([pd.Timestamp(died)])[0]), 0) + 1].sum()), 1),
                    _canopy=np.zeros(len(range(0, len(dates), CANOPY_STEP)), np.float32))
    o = outcome(row, lai, dates[-2].date())
    r.update(o)
    kh = int(dates.get_indexer([pd.Timestamp(o["harvest"])])[0]) if o["harvest"] else len(dates) - 1
    kh = kh if kh >= 0 else len(dates) - 1
    k0 = int(dates.get_indexer([pd.Timestamp(plant)])[0])
    season = slice(max(k0, 0), kh + 1)
    r["rain_mm"] = round(float(np.asarray(task["rain"][m])[season].sum()), 1)
    r["irrigation_mm"] = _num(row.get("IRCM")) or 0.0
    if lai is not None and len(lai) and o["harvest"]:
        w = lai[(lai.date >= pd.Timestamp(plant)) & (lai.date <= pd.Timestamp(o["harvest"]))]
        r["stress_days"] = int((w.wspd > STRESS_WSPD).sum())
    r["sources"] = np.bincount(np.asarray(task["source"])[season].astype(int), minlength=6).tolist()
    canopy = np.zeros(len(dates), np.float32)
    if lai is not None and len(lai):
        s = pd.Series(lai.lai.values, index=pd.DatetimeIndex(lai.date)).reindex(dates).fillna(0.0).values
        canopy[: kh + 1] = (1 - np.exp(-K_EXT * s))[: kh + 1]
    r["_canopy"] = canopy[::CANOPY_STEP]
    return r


def simulate(task):
    """task: as wofost_adapter.simulate (dates, rain, tmax, tmin, et0, rad, vap, wind2, source, planting, resow,
    variety, layers, initial_frac, lat, lon, elev) → list of per-member outcome dicts."""
    dates = pd.DatetimeIndex(task["dates"])
    M, T = len(task["planting"]), len(dates)
    task = dict(task, **{k: np.broadcast_to(np.asarray(task[k], np.float64), (M, T))
                         for k in ("tmax", "tmin", "rad", "vap", "wind2", "rain")})
    resow = task.get("resow") or [[] for _ in task["planting"]]
    sown = [m for m, p in enumerate(task["planting"]) if p is not None]
    res = {}
    if sown:
        got = run_members(task, sown, [task["planting"][m] for m in sown])
        for k in range(RETRIES):                                           # alone, in case one member stopped the run
            bad = [m for m in sown if _failed(got[m][0])]
            if not bad:
                break
            time.sleep(0.5 * (k + 1))                                      # the crashes come under load: a pause
            for m in bad:
                got.update(run_members(task, [m], [task["planting"][m]]))
        res = {m: _member(task, m, task["planting"][m], *got[m], dates) for m in sown}
    out = []
    for m, plant in enumerate(task["planting"]):
        if plant is None:
            out.append(dict(member=m + 1, planting=None, status="not_sown", yield_t_ha=0.0, potential_t_ha=None,
                            biomass_t_ha=None, harvest=None, max_canopy=None, stress_days=None, rain_mm=None,
                            sources=None, sowings=0))
            continue
        r, sowings = res[m], 1
        while r["status"] == "failed_establishment" and sowings <= RESOW_MAX and r.get("harvest"):
            died = dt.date.fromisoformat(r["harvest"])
            later = [d for d in resow[m] if d > died]
            if not later:
                break
            for _ in range(RETRIES + 1):
                row, lai = run_members(task, [m], [later[0]])[m]
                if not _failed(row):
                    break
            again = _member(task, m, later[0], row, lai, dates)
            if again["status"] in ("too_late", "error"):
                break
            r, sowings = dict(again, first_planting=plant.isoformat()), sowings + 1
        r["sowings"] = sowings
        out.append(r)
    if task.get("potential", True) and task.get("water", True):
        _potential(task, out)
    return out


def _potential(task, out):
    """Each simulated member's yield without water stress (module doc): its final sowing, the water balance off."""
    sim = [k for k, r in enumerate(out) if r["status"] in ("ok", "died", "failed_establishment") and r.get("planting")]
    if not sim:
        return
    plants = [dt.date.fromisoformat(out[k]["planting"]) for k in sim]
    got = run_members(dict(task, irrigation=None), sim, plants, water=False)
    for k in sim:
        row = got[k][0]
        if not _failed(row) and not row.get("_no_germination"):
            out[k]["potential_t_ha"] = round((_num(row.get("HWAM")) or 0.0) / 1000.0, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", action="store_true", help="install DSSAT's program and data into data/crop_engine/dssat")
    ap.add_argument("--wheel", help="a local copy of the pinned DSSATTools wheel (else downloaded with pip)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.install:
        install(a.wheel)
    print(f"DSSAT {'installed' if installed() else 'not installed'}: {EXE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
