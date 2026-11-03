#!/usr/bin/env python3
"""
forecast_runs.py
────────────────
Forecast runs for the Forecast tab's Sub-seasonal and Medium-range views: for each weather model and run date, the
25 members of the Oct 01 + latest obs SEAS5 run with that model's forecast joined in (blend_subseasonal.Blender),
and every onset / cessation method run on them for the operational year.

  source                         forecast joined in from its run date                  members
  s2s-ecmwf                      ECMWF ENS days 1–15, then the extended range to day 46  ENS k; 25 of 100 by rank
  s2s-gefs                       NOAA GEFS 35-day                                       25 of 31 by rank
  mr-ecmwf_ens_median            ECMWF ENS days 1–15                                    ENS k
  mr-ecmwf_ifs025, mr-gfs_global, mr-gem_global, mr-icon_global,                        the same forecast in all 25
  mr-ukmo_global_deterministic_10km   (deterministic, data/nwp/nwp_<date>.csv, 0.5°)
Before the forecast: observed CHIRPS, then the gap days (ECMWF extended range, day 1 of the run started that day);
after it: each SEAS5 member to 31 Dec, and its 1 Jan – 28 Feb for the Agri rules and the FAO water balance.

Methods: Dunning (dunning_lib, 1 Sep – 31 Dec), Agri rules 1–3 (onset_rules.py, 15 Aug – 28 Feb) and the FAO water
balance (fao_water_balance.py: agricultural, rainfall and crop-water definitions; CHIRPS v3 and ERA5-Land ET0 to
their last observed day). The joined runs share their hindcasts with the Oct 01 + latest obs run, so its terciles,
calibration of the probabilities (alpha) and skill apply; only the operational year's members and probabilities
are new.

Output, one small file per run:
  backend/forecast_runs/<source>_<YYYYMMDD>.npz   "<method>|<var>|members" (member, lat, lon) and
                                                  "<method>|<var>|probs" (3, lat, lon), float16; "__meta__" JSON
  backend/forecast_runs/index.json                every run: source, kind, model, run date, rainfall sources
  frontend/public/tracker/data/nwp_runs/          each medium-range run's daily rain (0.5°) for the rainfall maps
A run already built from the same observations is skipped.

Usage:
  python scripts/forecast_runs.py                    # the latest run of every source on disk
  python scripts/forecast_runs.py --all              # every run on disk (rebuilds the archive)
  python scripts/forecast_runs.py --sources s2s-gefs mr-gfs_global --dates 20261101
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
import blend_subseasonal as bs  # noqa: E402
import fao_water_balance as fw  # noqa: E402
import onset_rules as orl  # noqa: E402
import process_ecmwf_september as pes  # noqa: E402

PARENT = BASE / "outputs" / "ecmwf_oct_obs_latest"
OUT = BASE / "backend" / "forecast_runs"
NWP_OUT = BASE / "frontend" / "public" / "tracker" / "data" / "nwp_runs"
VARS = ("onset", "cessation", "lgp")
FAO_CHUNK = 5                   # members per FAO water-balance pass
SOURCES = {
    "s2s-ecmwf": ("s2s", "ECMWF ENS + extended range"),
    "s2s-gefs": ("s2s", "NOAA GEFS 35-day"),
    "mr-ecmwf_ifs025": ("medium", "ECMWF IFS (HRES)"),            # labels as in the tracker's products.csv
    "mr-ecmwf_ens_median": ("medium", "ECMWF ENS"),
    "mr-gfs_global": ("medium", "GFS"),
    "mr-gem_global": ("medium", "GDPS"),
    "mr-icon_global": ("medium", "ICON"),
    "mr-ukmo_global_deterministic_10km": ("medium", "UKMO Global"),
}
# how the weather forecast fills the 25 members: an ensemble member by member, or one deterministic forecast repeated
# in every member (no near-term spread; the spread comes from the observations and SEAS5 only)
ENSEMBLE_SOURCES = {"s2s-ecmwf", "s2s-gefs", "mr-ecmwf_ens_median"}
members_kind = lambda source: "ensemble" if source in ENSEMBLE_SOURCES else "deterministic, repeated in every member"  # noqa: E731


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] runs: {m}", flush=True)


class Methods:
    """Every onset / cessation method for the operational year's members, with the parent run's terciles and alpha."""

    def __init__(self, year):
        q = xr.open_dataarray(PARENT / "chirps_Q_bar.nc")
        self.lat, self.lon, self.lm = q.lat.values, q.lon.values, np.isfinite(q.values)
        self.year, lm = year, self.lm
        rd = lambda p: xr.open_dataarray(p).values.astype(np.float32)                  # noqa: E731
        # Dunning: CHIRPS climatology of the window, terciles and alpha of the parent run
        self.dn = {k: rd(PARENT / f"chirps_{k}.nc")[lm] for k in ("Q_bar", "d_s", "d_e")}
        sfx = {"onset": "onset_doy", "cessation": "cessation_doy", "lgp": "lgp_days"}
        self.terc = {"dunning": {v: (rd(PARENT / "calibration_params" / f"t33_{sfx[v]}.nc"),
                                     rd(PARENT / "calibration_params" / f"t67_{sfx[v]}.nc"), rd(PARENT / f"alpha_{v}.nc"))
                                 for v in VARS}}
        # Agri rules: CHIRPS 15–31 Aug, PET, the SEAS5 members' 1 Jan – 28 Feb
        o26 = orl.obs_2026(self.lat, self.lon)
        self.pre = o26[orl.SEARCH_START_DOY - 1:pes.WIN_DOY_START - 1][:, lm]                  # (17, S)
        if np.isnan(self.pre).any():
            raise RuntimeError("CHIRPS gaps in 15–31 Aug")
        with xr.open_dataarray(orl.EXT_CACHE) as da:
            self.janfeb = da.sel(year=year).values.astype(np.float32)[:, :, lm]               # (member, 59, S)
        self.pet = orl.load_pet(self.lat, self.lon, orl.EXT_DAYS)[:, lm].T                    # (S, n)
        for k in orl.RULES:
            d = PARENT / f"icpac_rule{k}"
            self.terc[str(k)] = {v: (rd(d / f"t33_{v}.nc"), rd(d / f"t67_{v}.nc"), rd(d / f"alpha_{v}.nc")) for v in VARS}
        # FAO water balance: observed CHIRPS v3 / ERA5-Land ET0 to their last day, the members, then FAO's own SEAS5
        # 1 Jan – 28 Feb (quantile-mapped to CHIRPS v3)
        cfg = self.cfg = fw.load_config()
        self.t0, self.T, _ = fw.season_days(cfg)
        taw, _, _ = fw.taw_mm(cfg["crop_params"]["rooting_depth_m"])
        self.taw = np.where(lm, taw, np.nan).astype(np.float32)[lm]
        clim = fw.et0_climatology(cfg, self.lat, self.lon)[:, lm].T                         # (S, T)
        self.peak = fw.climatological_peak(cfg, self.lat, self.lon)[lm]
        self.oe = fw.obs_end_doy(PARENT)
        self.k_obs = self.oe - self.t0 + 1
        p_obs = fw.chirps3_season(year, self.t0, self.T, self.lat, self.lon)[:, lm].T
        e_obs = fw.fill_et0(fw.era5_season(year, self.t0, self.T, self.lat, self.lon)[:, lm].T, clim, p_obs)
        self.P_obs, self.E = p_obs, clim.copy()
        self.E[:, :self.k_obs] = e_obs[:, :self.k_obs]
        self.sw0 = fw.initial_storage(cfg, year, self.t0, self.lat, self.lon, taw)[lm]
        with xr.open_dataarray(fw.BC_CACHE) as da:                    # FAO's own SEAS5 members from 1 Oct, CHIRPS v3
            self.fao_mem = da.sel(year=year).values.astype(np.float32)[:, :, lm]               # (member, 151, S)
        for d in fw.DEFINITIONS:
            dd = PARENT / f"fao_wb_{d}"
            self.terc[f"fao-{d}"] = {v: (rd(dd / f"t33_{v}.nc"), rd(dd / f"t67_{v}.nc"), rd(dd / f"alpha_{v}.nc")) for v in VARS}

    def probs(self, key, v, members):
        """Calibrated tercile probabilities (3, lat, lon) of the members, as in the seasonal pipeline."""
        t33, t67, alpha = self.terc[key][v]
        p = pes.dl.apply_pooling(pes.dl.estimate_probs(members[:, None], t33, t67), alpha)[:, 0]
        if key.startswith("fao-"):                                  # no tercile forecast where t33 = t67
            p = np.where((np.isfinite(t33) & (t33 == t67))[None], np.nan, p)
        return p

    def run(self, P, joined):
        """P (member, 1 Sep – 31 Dec, lat, lon), joined (day,) True on the days a weather forecast replaced the SEAS5
        member → {method: {var: (members (member, lat, lon), probs (3, lat, lon))}}."""
        lm, n_mem = self.lm, P.shape[0]
        S = int(lm.sum())

        def grid(a):                                                    # (member, S) land cells → (member, lat, lon)
            o = np.full((n_mem, *lm.shape), np.nan, np.float32)
            o[:, lm] = a
            return o

        out = {}
        # Dunning: the turning points of the accumulated anomaly, 1 Sep – 31 Dec
        doy_axis = np.arange(pes.WIN_DOY_START, pes.WIN_DOY_END + 1)
        e = {v: np.full((n_mem, S), np.nan, np.float32) for v in VARS}
        for m in range(n_mem):
            r = pes.dl.detect_season_batch(precip=P[m][:, lm].T, Q_bar=self.dn["Q_bar"], d_s=self.dn["d_s"],
                                           d_e=self.dn["d_e"], doy_axis=doy_axis, win_doy_start=pes.WIN_DOY_START,
                                           win_doy_end=pes.WIN_DOY_END, buffer_days=pes.DUNNING_BUFFER_DAYS,
                                           min_lgp_days=pes.MIN_LGP_DAYS)
            e["onset"][m], e["cessation"][m], e["lgp"][m] = r["onset_doy"], r["cess_doy"], r["lgp_days"]
        out["dunning"] = {v: (grid(e[v]), self.probs("dunning", v, grid(e[v]))) for v in VARS}
        # Agri rules 1–3: CHIRPS 15–31 Aug, the members to 31 Dec, their 1 Jan – 28 Feb
        d = np.concatenate([np.broadcast_to(self.pre, (n_mem, *self.pre.shape)), P[:, :, lm], self.janfeb[:n_mem]], axis=1)
        n = d.shape[1]
        d = np.moveaxis(d, 1, -1).reshape(-1, n)
        pet = np.tile(self.pet, (n_mem, 1))
        for k, rule in orl.RULES.items():
            on, cs, lg = orl.apply_rule(d, pet, rule)
            e = {v: grid(a.reshape(n_mem, S)) for v, a in zip(VARS, (on, cs, lg))}
            f = dict(zip(VARS, orl.for_terciles(e["onset"], e["cessation"], e["lgp"], lm[None])))
            out[str(k)] = {v: (e[v], self.probs(str(k), v, f[v])) for v in VARS}
        del d, pet
        # FAO water balance: as the seasonal FAO run (CHIRPS v3 observed, then FAO's own SEAS5 members, quantile-mapped
        # to CHIRPS v3), with the weather forecasts on the days they replaced the member, so a run with no forecast
        # days is exactly the seasonal run
        T, t0 = self.T, self.t0
        Pf = np.empty((n_mem, S, T), np.float32)
        Pf[:] = self.P_obs[None]
        a, f0 = self.k_obs, 274 - t0                                       # members from the day after the obs
        Pf[:, :, max(a, f0):] = np.moveaxis(self.fao_mem[:n_mem, max(a, f0) - f0:T - f0], 1, 2)
        for i in np.where(joined)[0]:
            k = pes.WIN_DOY_START + i - t0                                 # season day index of window day i
            if k >= a:
                Pf[:, :, k] = P[:, i, lm]
        keys = (*fw.DATE_VARS, *fw.LGP_VARS)
        r = {k: np.empty((n_mem, S), np.float32) for k in keys}
        for m0 in range(0, n_mem, FAO_CHUNK):                          # a few members at a time: the daily update runs
            m1 = min(n_mem, m0 + FAO_CHUNK)                             # short of memory
            n = m1 - m0
            rc = fw.season(Pf[m0:m1].reshape(-1, T), np.tile(self.E, (n, 1)), np.tile(self.taw, n), np.tile(self.sw0, n),
                           self.cfg, peak_idx=np.tile(self.peak, n), keep_daily=False)
            for k in keys:
                r[k][m0:m1] = rc[k].reshape(n, S)
        del Pf
        res = {k: grid(r[k] + (t0 if k in fw.DATE_VARS else 0)) for k in keys}
        for dname, dd in fw.DEFINITIONS.items():
            e = {"onset": res[dd["onset"]], "cessation": res[dd["cessation"]], "lgp": res[dd["lgp"]]}
            f = dict(zip(VARS, fw.for_terciles(e["onset"], e["cessation"], e["lgp"], lm[None])))
            out[f"fao-{dname}"] = {v: (e[v], self.probs(f"fao-{dname}", v, f[v])) for v in VARS}
        return out


def joined_rain(b, source, run, path, nwp_cache):
    """The run's joined daily rain (member, 1 Sep – 31 Dec, lat, lon) → (P, info, segments, extra metadata), or the
    reason it cannot be built. Also used by the crop engine (crop_engine/data/weather.py)."""
    extra = {}
    if source == "s2s-ecmwf":
        if not [p for i, p in b.ext_by_init.items() if i < run]:
            return "no extended-range run before it on disk"
        P, info, weather, segs = b.ecmwf(path)
        extra["weather"] = weather
    elif source == "s2s-gefs":
        P, info, segs = b.gefs(path)
    elif source == "mr-ecmwf_ens_median" and (BASE / "data" / "ecmwf_ens" / f"ens_tp_{run:%Y%m%d}00_kenya.nc").exists():
        P, info, segs = b.ens_only(BASE / "data" / "ecmwf_ens" / f"ens_tp_{run:%Y%m%d}00_kenya.nc")
    else:
        if path not in nwp_cache:
            nwp_cache.clear()
            df = pd.read_csv(path)
            nwp_cache[path] = df[df.kind == "grid"]
        rows = nwp_cache[path][nwp_cache[path].model == source[3:]]
        P, info, segs = b.nwp(source[3:], run, rows, SOURCES[source][1])
        if info["fc_days"] is None:
            return "no forecast day after the observations"
    return P, info, segs, extra


def save(source, run, info, segs, results, extra=None):
    kind, label = SOURCES[source]
    meta = {"source": source, "kind": kind, "model_label": label, "run": str(run), "obs_end": info["obs_end"],
            "segments": segs, "bias_correction": info.get("bias_correction"),
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes"), **(extra or {})}
    arrays = {}
    for mk, vs in results.items():
        for v, (mem, p) in vs.items():
            arrays[f"{mk}|{v}|members"] = mem.astype(np.float16)
            arrays[f"{mk}|{v}|probs"] = p.astype(np.float16)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{source}_{run:%Y%m%d}.npz"
    np.savez_compressed(path, __meta__=np.array(json.dumps(meta)), **arrays)
    return path, meta


def write_index():
    runs = []
    for p in sorted(OUT.glob("*_????????.npz")):
        with np.load(p) as z:
            meta = json.loads(str(z["__meta__"]))
        if meta["source"] not in SOURCES:
            continue
        runs.append({**{k: meta[k] for k in ("source", "kind", "run", "obs_end", "segments", "bias_correction", "created")},
                     "model_label": SOURCES[meta["source"]][1], "members": members_kind(meta["source"]), "file": p.name})
    runs.sort(key=lambda r: (r["kind"], r["source"], r["run"]))
    (OUT / "index.json").write_text(json.dumps({"updated": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
                                                "runs": runs}, indent=1) + "\n", encoding="utf-8")
    log(f"index: {len(runs)} runs")


def write_nwp_runs(dates):
    """Each medium-range run's daily rain on the 0.5° grid for the dashboard's rainfall maps, compact:
    model, lat, lon, first day, daily mm joined by ';'."""
    NWP_OUT.mkdir(parents=True, exist_ok=True)
    for d in dates:
        src = BASE / "data" / "nwp" / f"nwp_{d}.csv"
        out = NWP_OUT / f"nwp_{d}.csv"
        if not src.exists() or (out.exists() and out.stat().st_mtime >= src.stat().st_mtime):
            continue
        df = pd.read_csv(src)
        df = df[df.kind == "grid"].sort_values(["model", "lat", "lon", "date"])
        rows = [{"model": m, "lat": la, "lon": lo, "start": g.date.iloc[0],
                 "rain": ";".join(f"{v:g}" for v in g.rain_mm.round(1))} for (m, la, lo), g in df.groupby(["model", "lat", "lon"])]
        pd.DataFrame(rows).to_csv(out, index=False)
    runs = []
    for p in sorted(NWP_OUT.glob("nwp_????????.csv")):
        df = pd.read_csv(p, usecols=["model", "start", "rain"])
        models = {m: {"start": g.start.min(), "days": int(g.rain.str.count(";").max()) + 1} for m, g in df.groupby("model")}
        runs.append({"run": f"{p.stem[4:8]}-{p.stem[8:10]}-{p.stem[10:12]}", "file": p.name, "models": models})
    (NWP_OUT / "index.json").write_text(json.dumps({"runs": runs}, indent=1) + "\n", encoding="utf-8")


def built(source, run, obs_end):
    p = OUT / f"{source}_{run:%Y%m%d}.npz"
    if not p.exists():
        return False
    with np.load(p) as z:
        return json.loads(str(z["__meta__"])).get("obs_end") == str(obs_end)


def candidates(all_runs, dates):
    """(source, run date, input) for the runs on disk."""
    ymd = lambda p, i=2: dt.datetime.strptime(Path(p).stem.split("_")[i][:8], "%Y%m%d").date()     # noqa: E731
    ens = {ymd(p): p for p in sorted((BASE / "data" / "ecmwf_ens").glob("ens_tp_*_kenya.nc"))}
    gefs = {ymd(p): p for p in sorted((BASE / "data" / "gefs").glob("gefs_tp_*_kenya.nc"))}
    nwp = {ymd(p, 1): p for p in sorted((BASE / "data" / "nwp").glob("nwp_????????.csv"))}
    pick = lambda d: (sorted(d) if all_runs else sorted(d)[-1:]) if not dates else [x for x in sorted(d) if f"{x:%Y%m%d}" in dates]  # noqa: E731
    out = [("s2s-ecmwf", r, ens[r]) for r in pick(ens)] + [("s2s-gefs", r, gefs[r]) for r in pick(gefs)]
    for r in pick(nwp):
        models = set(pd.read_csv(nwp[r], usecols=["model"]).model)
        out += [(s, r, nwp[r]) for s in SOURCES if s.startswith("mr-") and s[3:] in models]
    return out, sorted(nwp) if all_runs else sorted(nwp)[-1:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="every run on disk, not only the latest of each source")
    ap.add_argument("--sources", nargs="+", choices=list(SOURCES))
    ap.add_argument("--dates", nargs="+", help="run dates YYYYMMDD")
    ap.add_argument("--force", action="store_true", help="rebuild runs already built")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    todo, nwp_dates = candidates(a.all, a.dates)
    write_nwp_runs([f"{d:%Y%m%d}" for d in nwp_dates])
    b = bs.Blender(BASE)
    todo = [t for t in todo if (not a.sources or t[0] in a.sources) and (a.force or not built(t[0], t[1], b.obs_end))]
    if not todo:
        log(f"all runs already built (observations to {b.obs_end})")
        write_index()
        return
    log(f"{len(todo)} run(s) to build; observations to {b.obs_end}")
    meth = Methods(b.year)
    nwp_cache = {}
    for source, run, path in todo:
        t0 = time.time()
        try:
            got = joined_rain(b, source, run, path, nwp_cache)
            if isinstance(got, str):
                log(f"{source} {run}: {got}; skipped")
                continue
            P, info, segs, extra = got
            res = meth.run(P, (P != b.seas).any(axis=(0, 2, 3)))
            p, meta = save(source, run, info, segs, res, extra)
            med = lambda k, v: np.nanmedian(res[k][v][0][:, meth.lm])           # noqa: E731
            log(f"{source} {run}: median onset DOY Dunning {med('dunning', 'onset'):.0f}, rule 1 {med('1', 'onset'):.0f}, "
                f"FAO agricultural {med('fao-agricultural', 'onset'):.0f} → {p.name} ({p.stat().st_size / 1e3:.0f} kB, "
                f"{time.time() - t0:.0f} s)")
        except Exception as exc:                                      # one run must not stop the others
            log(f"{source} {run}: failed ({type(exc).__name__}: {str(exc)[:200]})")
    write_index()


if __name__ == "__main__":
    main()
