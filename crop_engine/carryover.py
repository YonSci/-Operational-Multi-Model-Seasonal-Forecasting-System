#!/usr/bin/env python3
"""
Soil water carried between seasons: AquaCrop grown continuously at each registered site, season after season, so the
soil on 1 Aug is what the Long Rains, the crop and the dry season before it left, not an estimate made afresh.

The outlook starts every season on 1 Aug from ERA5-Land's root-zone soil moisture through the FAO water balance's
bucket (weather.Inputs.initial_water): a separate model's estimate, one fraction of the available water for the whole
profile. Here AquaCrop-OSPy runs the sites' years in observed weather (CHIRPS v2, ERA5-Land) without a break, from
1 Aug 1993 (started from ERA5-Land's value) to 31 Jul of the latest year, with the FAO-56 reference ET of the
sites' own ERA5-Land weather for every day (reference_et0), in two stages a year:
  Short Rains  1 Aug – end of Feb: a crop sown on the first day from 1 Oct to 15 Dec that meets Agri rule
               C.RESOW_RULE's onset criteria (or fallow), harvested when mature, the field bare after
  Long Rains   1 Mar – 31 Jul: a crop sown on the first such day from 1 Mar to 30 Apr (or fallow), then the dry season
Each stage starts from the soil water profile the one before left (compartment by compartment), so water stored deep
in a wet year carries into the next. The plan says what grows: "maize" (early maize both seasons, the variety of the
outlook), "fallow" (bare soil all year) or "grass" (a dry-season cover of grass and weeds all year, COVER). The result per site and year: the profile on 1 Aug (compartment depths and
volumetric water) and two fractions of the plant-available water, over 0–100 cm (comparable with SMAP's root zone,
data/smap.py) and over the whole 2 m (the outlook's measure).

Used by
  - the scenario "soil_carryover" (Soil water carried over from the Long Rains): the season grown from the profile
    itself (AquaCrop; WOFOST and DSSAT from its 2 m fraction);
  - CROP_INITIAL_WATER=carryover: every product's 1 Aug soil water (weather.Inputs.initial_water) from the 2 m
    fraction where a site has one, ERA5-Land's elsewhere (1993, grid cells). Off until the comparisons show it is
    better; the engines' configuration hashes then include the carried-over values.

  python -m crop_engine.carryover --build              # every year to the latest 31 Jul (both plans)
  python -m crop_engine.carryover --compare            # ERA5-Land, SMAP and the carried-over water, per site

Output (not committed): outputs/crop_engine/carryover/<plan>.json; the comparison
outputs/crop_engine/verification/initial_water_carryover.json.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from crop_engine import config as C
from crop_engine.adapters import aquacrop_adapter as aq

OUT = C.OUT / "carryover"
PLANS = {"maize": {"short_rains": "maize_early", "long_rains": "maize_early"},
         "fallow": {"short_rains": None, "long_rains": None},
         "grass": {"short_rains": "cover", "long_rains": "cover"}}
# The dry-season cover of plan "grass" (an approximation: AquaCrop has no perennial grass): grass and weeds already
# standing at each stage's start (set out as established plants: no germination to wait for), a sparse canopy (CCx
# 0.4) rooting to 1.5 m, long-lived; it transpires from the subsoil while there is water and senesces as the soil dries,
# as dry-season vegetation does. A bare fallow keeps the subsoil far too wet (checked against SMAP, CROP_ENGINE.md).
COVER = {"aquacrop_crop": "MaizeGDD", "label": "Dry-season grass and weeds", "maturity_days": 260,
         "parameters": {"CCx": 0.4, "Zmax": 1.5, "HI0": 0.01, "PlantPop": 44444}, "cover": True}
COVER_ESTABLISHED = {"nursery_days": 30, "seedling_cm2": 300}
DEFAULT_PLAN = "maize"
FIRST_YEAR = C.HIST_YEARS[0]                     # 1 Aug 1993: started from ERA5-Land
WINDOWS = {"short_rains": ((10, 1), (12, 15)), "long_rains": ((3, 1), (4, 30))}
PAD_DAYS = 420                                    # weather after a stage, so AquaCrop-OSPy's calendar can mature a crop
INITIAL_WATER = os.environ.get("CROP_INITIAL_WATER", "era5land")    # "era5land" (default) or "carryover"


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def path(plan=DEFAULT_PLAN):
    return OUT / f"{plan}.json"


def load(plan=DEFAULT_PLAN):
    p = path(plan)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"sites": {}}


def initial(site_id, year, plan=DEFAULT_PLAN, data=None):
    """The carried-over state on 1 Aug of `year` at the site: {"z_m", "th", "frac_100cm", "frac_200cm", ...} or None."""
    d = (data or load(plan)).get("sites", {}).get(site_id, {})
    return d.get(str(year))


def available(year, plan=DEFAULT_PLAN):
    return any(str(year) in v for v in load(plan).get("sites", {}).values())


def fractions(site_ids, year, default, plan=DEFAULT_PLAN):
    """CROP_INITIAL_WATER=carryover (module doc): the 2 m fraction per site where carried over, else `default`'s."""
    data = load(plan)
    out = np.array(default, float).copy()
    for k, sid in enumerate(site_ids):
        s = initial(sid, year, plan, data)
        if s is not None:
            out[k] = s["frac_200cm"]
    return out


def hash_part(plan=DEFAULT_PLAN):
    """For the engines' configuration hashes: "" unless CROP_INITIAL_WATER=carryover, then the carried-over values."""
    if INITIAL_WATER != "carryover":
        return ""
    p = path(plan)
    return hashlib.sha1(p.read_bytes()).hexdigest()[:12] if p.exists() else "missing"


def config_hash(plan):
    """Changes when the plan, the AquaCrop adapter, the varieties or the sowing rule change: every year is rebuilt."""
    h = hashlib.sha1(json.dumps(PLANS[plan], sort_keys=True).encode())
    h.update(Path(aq.__file__).read_bytes())
    h.update(C.VARIETIES_FILE.read_bytes())
    h.update(json.dumps([C.RESOW_RULE, WINDOWS, FIRST_YEAR]).encode())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:12]


# ── one site's chain ─────────────────────────────────────────────────────────────────────────────────────────────
def sow_date(rain, dates, window):
    """The first day in the window (month, day) to (month, day) that meets Agri rule C.RESOW_RULE's onset criteria."""
    sys.path.insert(0, str(C.BASE / "scripts"))
    import agro_onset as ao                                            # noqa: E402
    import onset_rules as orl                                          # noqa: E402
    dates = pd.DatetimeIndex(dates)
    (m0, d0), (m1, d1) = window
    a = np.where((dates.month == m0) & (dates.day == d0))[0]
    b = np.where((dates.month == m1) & (dates.day == d1))[0]
    if not len(a) or not len(b):
        return None
    idx, _ = ao.detect(np.asarray(rain, np.float32)[None], int(a[0]), dry_day_mm=orl.DRY_DAY_MM, end_idx=int(b[0]),
                       **orl.RULES[C.RESOW_RULE]["onset"])
    return None if not np.isfinite(idx[0]) else dates[int(idx[0])].date()


def stage(wx, start, end, layers, variety, plant, init):
    """AquaCrop-OSPy from `start` to `end` (inclusive) with the crop sown on `plant` (None: fallow) from the initial
    state `init` ({"frac": f} or {"z_m", "th"}) → (state on the day after `end`, the crop's yield or None)."""
    from aquacrop import AquaCropModel, Crop, InitialWaterContent
    aq.patch_delayed_maturity()
    aq.patch_pollination_heat()
    d = pd.date_range(start, end)
    k = wx["dates"].get_indexer(d)
    pad = pd.date_range(d[-1] + pd.Timedelta(days=1), periods=PAD_DAYS)
    rep = np.resize(k, PAD_DAYS)                                         # the stage's temperatures again, no rain
    wdf = pd.DataFrame({"MinTemp": np.r_[wx["tmin"][k], wx["tmin"][rep]], "MaxTemp": np.r_[wx["tmax"][k], wx["tmax"][rep]],
                        "Precipitation": np.r_[wx["rain"][k], np.zeros(PAD_DAYS)],
                        "ReferenceET": np.maximum(np.r_[wx["et0"][k], wx["et0"][rep]], 0.1), "Date": d.append(pad)})
    kw = aq.rooting_limited(variety["kw"], variety["aquacrop_crop"], layers)
    cover = bool(variety.get("cover"))
    if cover:                                                           # standing grass: established from the start
        aq.patch_transplant()
        g = np.clip((wx["tmax"][k] + wx["tmin"][k]) / 2 - 8.0, 0, None)
        kw = aq.transplant_kw(kw, COVER_ESTABLISHED, variety["aquacrop_crop"], g[:COVER_ESTABLISHED["nursery_days"]])
    sow = plant or pad[0].date()                                         # fallow: "sown" the day after the stage
    if "z_m" in init:
        iwc = InitialWaterContent(wc_type="Num", method="Depth", depth_layer=list(init["z_m"]), value=list(init["th"]))
    else:
        iwc = InitialWaterContent(wc_type="Pct", method="Depth", depth_layer=[0.05, 2.0], value=[100 * init["frac"]] * 2)
    model = AquaCropModel(sim_start_time=f"{d[0]:%Y/%m/%d}", sim_end_time=f"{pad[-1]:%Y/%m/%d}", weather_df=wdf,
                          soil=aq.make_soil(layers), crop=Crop(variety["aquacrop_crop"], planting_date=f"{sow:%m/%d}", **kw),
                          initial_water_content=iwc, off_season=True, co2_concentration=aq.co2())
    model._initialize()
    if cover:
        aq._TRANSPLANT.append(True)
    try:
        model.run_model(num_steps=len(d))
    finally:
        aq._TRANSPLANT.clear()
    prof = model._param_struct.Soil.profile
    th = np.asarray(model._init_cond.th, float)
    state = {"z_m": [round(float(z), 3) for z in prof.zMid], "th": [round(float(t), 4) for t in th]}
    wp, fc, dz, zm = (np.asarray(prof.th_wp, float), np.asarray(prof.th_fc, float), np.asarray(prof.dz, float),
                      np.asarray(prof.zMid, float))
    for name, depth in (("frac_100cm", 1.0), ("frac_200cm", 9.0)):
        w = dz * (zm < depth)
        state[name] = round(float(np.clip(np.sum((th - wp) * w) / max(np.sum((fc - wp) * w), 1e-9), 0, 1)), 3)
    yld = None
    if plant is not None:
        g = np.asarray(model.get_crop_growth())                         # raw rows while the run is unfinished
        yld = round(float(np.nanmax(g[: len(d), 12])), 2) if g.ndim == 2 and len(g) else None   # column DryYield
    return state, yld


def chain(job):
    """One site's years (module doc): job = (site id, plan, weather, layers, varieties, first state, years) →
    {year: state on 1 Aug of that year}."""
    sid, plan, wx, layers, varieties, state, years = job
    out = {}
    for y in years:                                                     # season y-1's Short Rains, then y's Long Rains
        notes = {}
        for st_name, (a, b) in (("short_rains", (dt.date(y - 1, 8, 1), dt.date(y, 3, 1) - dt.timedelta(days=1))),
                                ("long_rains", (dt.date(y, 3, 1), dt.date(y, 7, 31)))):
            vk = PLANS[plan][st_name]
            rng = pd.date_range(a, b)
            if vk == "cover":
                plant, v = a, varieties["_cover"]
            else:
                plant = sow_date(wx["rain"][wx["dates"].get_indexer(rng)], rng, WINDOWS[st_name]) if vk else None
                v = varieties[vk] if vk else varieties["maize_early"]
            try:
                state, yld = stage(wx, a, b, layers, v, plant, state)
            except Exception as exc:                                    # a stage that fails ends the site's chain
                log(f"{sid} {y} {st_name}: {type(exc).__name__}: {str(exc)[:120]}")
                return out
            notes[st_name] = {"sown": plant.isoformat() if plant else None, "yield_t_ha": yld}
        out[str(y)] = dict(state, **notes)
    return out


def reference_et0(inp, dates, tmax, tmin):
    """FAO-56 reference evapotranspiration (mm/day, site × day) for every day, Long Rains and dry season included:
    the platform's ERA5-Land ET0 covers 1 Aug – 31 Mar only, so it is computed here (PCSE's reference_ET) from the
    sites' ERA5-Land temperature, solar radiation, humidity and wind (their day-of-year climatology where missing)."""
    from pcse.util import reference_ET
    r = inp.radiation(dates)
    if r is None:
        raise RuntimeError("the carried-over soil water needs the sites' ERA5-Land radiation, humidity and wind")
    met, _, elev = r
    out = np.empty(tmax.shape, np.float32)
    for k, s in enumerate(inp.sites):
        for i, d in enumerate(dates):
            tn = float(min(tmin[k, i], tmax[k, i]))
            out[k, i] = reference_ET(d.date(), float(s.lat), float(elev[k]), tn, float(tmax[k, i]),
                                     float(met["rad_mj_m2"][k, i]) * 1e6, float(met["vap_hpa"][k, i]),
                                     float(met["wind2_ms"][k, i]), 0.25, 0.5)[2]
    return np.maximum(out, 0.1)


# ── build and compare ────────────────────────────────────────────────────────────────────────────────────────────
def build(plans, workers=2, last_year=None):
    from crop_engine import run_outlook as ro
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.weather import Inputs
    today = dt.date.today()
    last_year = last_year or (today.year if today >= dt.date(today.year, 8, 1) else today.year - 1)
    years = list(range(FIRST_YEAR + 1, last_year + 1))
    inp = Inputs(refresh=False)
    _, varieties = ro.load_varieties(["maize_early"])
    cover = dict(COVER)
    cover["kw"], cover["scale"] = aq.crop_parameters(cover, 21.0)
    varieties["_cover"] = cover
    dates = pd.date_range(f"{FIRST_YEAR}-08-01", f"{last_year}-07-31")
    rain = inp.observed_rain(dates)
    met = [inp.met(y, pd.date_range(f"{y}-08-01", f"{y + 1}-07-31")) for y in range(FIRST_YEAR, last_year)]
    tmax, tmin = (np.concatenate([m[i] for m in met], axis=1) for i in (0, 1))
    et0 = reference_et0(inp, dates, tmax, tmin)
    if not (rain.shape[1] == tmax.shape[1] == et0.shape[1] == len(dates)):
        raise RuntimeError(f"weather of {tmax.shape[1]} days for {len(dates)} dates")
    frac0 = inp.initial_water(FIRST_YEAR)
    for plan in plans:
        h = config_hash(plan)
        old = load(plan)
        keep = old.get("config_hash") == h
        jobs = []
        for k, s in enumerate(inp.sites):
            done = old["sites"].get(s.id, {}) if keep else {}
            have = sorted(int(y) for y in done)
            todo = [y for y in years if y not in done]
            if not todo:
                continue
            # continue from the last year carried over, when the chain is unbroken up to it
            start = ({"z_m": done[str(have[-1])]["z_m"], "th": done[str(have[-1])]["th"]}
                     if have and have == list(range(FIRST_YEAR + 1, have[-1] + 1)) and todo[0] == have[-1] + 1
                     else {"frac": float(frac0[k])})
            todo = todo if "z_m" in start else years
            wx = {"dates": dates, "rain": rain[k].astype(float), "tmax": tmax[k].astype(float),
                  "tmin": tmin[k].astype(float), "et0": et0[k].astype(float)}
            jobs.append((s.id, plan, wx, soil_mod.profile(s), varieties, start, todo))
        t0 = time.time()
        res = dict(old["sites"]) if keep else {}
        with ProcessPoolExecutor(workers) as ex:
            for job, r in zip(jobs, ex.map(chain, jobs)):
                res.setdefault(job[0], {}).update(r)
        OUT.mkdir(parents=True, exist_ok=True)
        path(plan).write_text(json.dumps({"plan": plan, "crops": PLANS[plan], "config_hash": h, "first_year": FIRST_YEAR,
                                          "built": dt.datetime.now().isoformat(timespec="minutes"), "sites": res},
                                         indent=1), encoding="utf-8")
        log(f"carryover ({plan}): {len(jobs)} sites to {last_year} in {time.time() - t0:.0f} s -> {path(plan)}")


def compare(plans):
    """Per site: ERA5-Land's 1 Aug fraction (the outlook's), SMAP's (0-100 cm, from 2015) and each plan's carried-over
    fractions; their means and the correlations across years."""
    from crop_engine.data import smap
    from crop_engine.data import soil as soil_mod
    from crop_engine.data.weather import Inputs
    inp = Inputs(refresh=False, with_met=False)
    data = {p: load(p) for p in plans}
    years = sorted({int(y) for p in plans for v in data[p]["sites"].values() for y in v})
    era = {}
    for y in years:
        try:
            era[y] = inp.initial_water(y)
        except Exception:
            continue
    out = {}
    for k, s in enumerate(inp.sites):
        layers = soil_mod.profile(s)
        rows = []
        for y in years:
            r = {"year": y, "era5land": round(float(era[y][k]), 3) if y in era else None,
                 "smap_100cm": smap.initial_fraction(s.id, y, layers)}
            for p in plans:
                c = initial(s.id, y, p, data[p])
                r[f"{p}_100cm"], r[f"{p}_200cm"] = (c["frac_100cm"], c["frac_200cm"]) if c else (None, None)
            rows.append(r)

        def stats(a, b):
            pr = [(r[a], r[b]) for r in rows if r[a] is not None and r[b] is not None]
            if len(pr) < 3:
                return None
            x, z = np.array(pr).T
            return {"n": len(pr), "mean_a": round(float(x.mean()), 3), "mean_b": round(float(z.mean()), 3),
                    "r": round(float(np.corrcoef(x, z)[0, 1]), 2) if x.std() > 0 and z.std() > 0 else None}
        out[s.id] = {"rows": rows, "vs_smap": {p: stats(f"{p}_100cm", "smap_100cm") for p in plans},
                     "era5land_vs_smap": stats("era5land", "smap_100cm"),
                     "vs_era5land": {p: stats(f"{p}_200cm", "era5land") for p in plans}}
        log(f"{s.id:32s} vs SMAP (r): ERA5-Land {(out[s.id]['era5land_vs_smap'] or {}).get('r')}  "
            + "  ".join(f"{p} {(out[s.id]['vs_smap'][p] or {}).get('r')}" for p in plans))
    dest = C.OUT / "verification" / "initial_water_carryover.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--plans", nargs="+", choices=list(PLANS), default=list(PLANS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--last-year", type=int)
    ap.add_argument("--if-missing", action="store_true", help="build only when a plan lacks the latest year or is stale")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.build:
        plans = a.plans
        if a.if_missing:
            today = dt.date.today()
            last = a.last_year or (today.year if today >= dt.date(today.year, 8, 1) else today.year - 1)
            plans = [p for p in plans if load(p).get("config_hash") != config_hash(p) or not available(last, p)]
            if not plans:
                log(f"carryover: up to date ({last})")
        if plans:
            build(plans, a.workers, a.last_year)
    if a.compare:
        compare(a.plans)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
