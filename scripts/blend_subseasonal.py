#!/usr/bin/env python3
"""
blend_subseasonal.py
────────────────────
Join observations, medium-range and sub-seasonal forecasts and the seasonal forecast into one set of daily
rainfall members for the Kenya Short Rains, so the existing onset / cessation methods can run on them unchanged.

For the operational year, each of the 25 members of the "+ latest obs" SEAS5 run becomes:
  observed CHIRPS (to the run's observation cut-off)
  → gap days up to the ENS run: the ECMWF extended-range run started that day (shortest lead available)
  → ECMWF ENS days 1–15 (open data, 0.25°; fetch_ecmwf_ens.py)
  → ECMWF extended range to its day 46 (dynamical.org, 1.5°; fetch_ecmwf_extended.py)
  → the SEAS5 member itself to 31 Dec (and Jan–Feb for the Agri rules), unchanged.
SEAS5 member k stays member k. ENS member k fills days 1–15. From the 100 perturbed extended-range members,
25 spread over their range are taken and matched to the SEAS5 members by rank of land-mean rainfall over the
extended-range days, so a member that is wet over weeks 3–6 continues as a wet seasonal member.

Bias correction (quantile mapping to CHIRPS: cube-root transform with wet-day frequency adjustment, as in
process_ecmwf_september.py):
  extended range: ECMWF's extended-range reforecasts (fetch_ecmwf_reforecast.py) by lead. For a run started on
    day I and lead L, the model sample is the reforecasts of the model-version dates within REFC_MAX_GAP days of I
    (all 20 hindcast years × 10 members, leads L ± REFC_LEAD_WINDOW, same 1.5° grid as the real-time forecast) and
    the observed sample is CHIRPS on the same valid days of the same years, so the mapping also corrects how the
    model's bias changes with lead. Leads with no reforecast date close enough fall back to the provisional mapping.
  ENS days 1-15: provisional, the transfer the SEAS5 run uses for the same valid day (SEAS5 October-start
    hindcasts 1993–2016, all members). The reforecasts are on a 1.5° grid and ENS is 0.25°, so the reforecast
    mapping would over-correct ENS's sharper rainfall.

Output: outputs/ecmwf_oct_s2s/blend_<year>.nc  (precip: member, day, lat, lon; day 0 = window start, 1 Sep)
        and blend_<year>.json (the sources and dates of every segment)
Then:   process_ecmwf_september.py ... --out-dir outputs/ecmwf_oct_s2s --bc-op-override outputs/ecmwf_oct_s2s/blend_<year>.nc
The Blender class also joins NOAA GEFS 35-day runs and the medium-range models (forecast_runs.py), for any run on disk.
Usage:  python scripts/blend_subseasonal.py [--base <repo holding data/ and outputs/>]
"""
import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from process_ecmwf_september import _build_qm_transfer, QM_DOY_WINDOW, CAL_YEARS  # noqa: E402

N_MEMBERS = 25
REFC_MAX_GAP = 7          # days between a real-time run and the reforecast model-version dates pooled for it
REFC_LEAD_WINDOW = 3      # leads L ± 3 (a week) pooled for lead L


def doy(d):
    return d.timetuple().tm_yday


def load_seas5_raw(ecmwf_dir, lat, lon, n_lead):
    """Raw SEAS5 October-start daily rainfall for the calibration years: (year, member, lead day, lat, lon)."""
    out = []
    for yr in CAL_YEARS:
        with xr.open_dataset(ecmwf_dir / f"ecmwf_{yr}10_d01.nc") as ds:
            tp = ds["tp"]
            if "forecast_reference_time" in tp.dims:
                tp = tp.squeeze("forecast_reference_time")
            v = tp.reindex(latitude=lat, longitude=lon, method="nearest").values[:N_MEMBERS, :n_lead]
        d = np.diff(v, axis=1, prepend=0.0)
        out.append(np.clip(d, 0, None).astype(np.float32) * 1000.0)       # cumulative m → mm/day
    return np.stack(out)


def chirps_daily(path, lat, lon):
    """CHIRPS calibration years as (year, doy index 0..365, lat, lon)."""
    with xr.open_dataset(path) as ds:
        ds = ds.reindex(lat=lat, lon=lon, method="nearest")
        t = ds.time.to_index()
        arr = np.full((len(CAL_YEARS), 366, len(lat), len(lon)), np.nan, np.float32)
        for yi, yr in enumerate(CAL_YEARS):
            m = t.year == yr
            arr[yi, t[m].dayofyear.values - 1] = ds["precip"].values[m]
    return arr


def chirps_all(path, lat, lon):
    """All CHIRPS days: ({date: index}, (day, lat, lon))."""
    with xr.open_dataset(path) as ds:
        ds = ds.reindex(lat=lat, lon=lon, method="nearest")
        return ({d.date(): i for i, d in enumerate(ds.time.to_index())},
                ds["precip"].values.astype(np.float32))


def load_reforecasts(refc_dir, lat, lon):
    """{model-version date: (hyears, (hyear, member, lead, lat, lon))} on the target grid (nearest 1.5° cell)."""
    out = {}
    for p in sorted(refc_dir.glob("refc_tp_*_kenya.nc")):
        d = dt.datetime.strptime(p.stem.split("_")[2], "%Y%m%d").date()
        with xr.open_dataarray(p) as da:
            out[d] = (da.hyear.values, da.reindex(lat=lat, lon=lon, method="nearest").values.astype(np.float32))
    return out

class Blender:
    """The operational year's 25 SEAS5 "+ latest obs" members with weather forecasts joined in, for any run on disk.
    Shared by this script (the daily ECMWF run) and forecast_runs.py (every model and run date). Every joined run
    starts from the same members and gap days, so runs differ only from their own run date on."""

    def __init__(self, base, run_dir="outputs/ecmwf_oct_obs_latest", refc_dir="data/ecmwf_s2s_reforecast"):
        self.base = Path(base)
        run_dir = self.base / run_dir
        self.obs_end = dt.date.fromisoformat(json.loads((run_dir / "run_meta.json").read_text())["obs_end"])
        self.bc_all = xr.open_dataarray(run_dir / "ECMWF_bc_daily_all_years.nc")
        self.year = int(self.bc_all.year.values[-1])
        self.seas = self.bc_all.sel(year=self.year).values.astype(np.float32)        # (member, day, lat, lon)
        self.lat, self.lon = self.bc_all.lat.values, self.bc_all.lon.values
        self.win0 = dt.date(self.year, 9, 1)                                         # day 0 of the run window
        self.last = dt.date(self.year, 12, 31)
        self.lead0 = dt.date(self.year, 10, 1)
        self.lm = ~np.isnan(self.seas[0, 0])
        self.ext_paths = sorted(glob.glob(str(self.base / "data" / "ecmwf_ext" / "ext_tp_*_kenya.nc")))
        self.ext_by_init = {self.init_of(p): p for p in self.ext_paths}
        self.chirps = chirps_daily(self.base / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc", self.lat, self.lon)
        self.refc = load_reforecasts(self.base / refc_dir, self.lat, self.lon)
        self.c_idx, self.c_val = (chirps_all(self.base / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc",
                                             self.lat, self.lon) if self.refc else ({}, None))
        self.raw, self.qm = None, {}
        self.bc_used = {"reforecast": 0, "provisional": 0}

    @staticmethod
    def init_of(path):
        return dt.datetime.strptime(Path(path).stem.split("_")[2][:8], "%Y%m%d").date()

    def day(self, d):
        return (d - self.win0).days

    def season_days(self, days, run=None):
        """Days of a forecast that join the season: after the last observation (and from the run date), to 31 Dec."""
        return [d for d in days if d > self.obs_end and d <= self.last and (run is None or d >= run)]

    # ── bias correction ─────────────────────────────────────────────────────
    def need(self, last_day):
        """Raw SEAS5 hindcasts to the lead day of last_day (about 3 MB a lead day: loaded only as far as needed)."""
        n_lead = (min(last_day, self.last) - self.lead0).days + 1
        if self.raw is None or n_lead > self.raw.shape[2]:
            self.raw = None
            self.raw = load_seas5_raw(self.base / "data" / "seasonal_pr_downloads_ke" / "ecmwf_oct", self.lat, self.lon, n_lead)

    def correct(self, field, d):
        """Provisional: the SEAS5 run's quantile mapping for valid day d. field (member, lat, lon) → corrected copy."""
        li, dd = (d - self.lead0).days, doy(d) - 1
        self.need(d)
        if d not in self.qm:
            fn = {}
            for i, j in np.argwhere(self.lm):
                c = self.chirps[:, max(0, dd - QM_DOY_WINDOW):min(366, dd + QM_DOY_WINDOW + 1), i, j].ravel()
                s = self.raw[:, :, li, i, j].ravel()
                fn[i, j] = _build_qm_transfer(c[~np.isnan(c)], s[~np.isnan(s)])
            self.qm[d] = fn
        f = field.copy()
        for (i, j), fn in self.qm[d].items():
            f[:, i, j] = fn(field[:, i, j])
        return f

    def correct_ext(self, field, init, d):
        """ECMWF extended range, run started on init, valid day d: mapping from the reforecasts by lead."""
        lead = (d - init).days + 1
        near = [m for m in self.refc if abs((m - init).days) <= REFC_MAX_GAP]
        if not near:
            self.bc_used["provisional"] += 1
            return self.correct(field, d)
        lo, hi = max(1, lead - REFC_LEAD_WINDOW), lead + REFC_LEAD_WINDOW
        s_pool, c_days = [], []
        for m in near:
            hyears, vals = self.refc[m]
            s_pool.append(vals[:, :, lo - 1:hi].reshape(-1, len(self.lat), len(self.lon)))    # (hyear·member·lead, lat, lon)
            for y in hyears:
                start = dt.date(int(y), m.month, m.day)
                c_days += [self.c_idx.get(start + dt.timedelta(days=k - 1)) for k in range(lo, min(hi, vals.shape[2]) + 1)]
        s_pool = np.concatenate(s_pool)
        c_pool = self.c_val[[k for k in c_days if k is not None]]
        f = field.copy()
        for i, j in np.argwhere(self.lm):
            c, s = c_pool[:, i, j], s_pool[:, i, j]
            f[:, i, j] = _build_qm_transfer(c[~np.isnan(c)], s[~np.isnan(s)])(field[:, i, j])
        self.bc_used["reforecast"] += 1
        return f

    # ── building blocks ─────────────────────────────────────────────────────
    def start(self, run):
        """Members to join a run started on `run`: observed to the cut-off, gap days to the day before the run from
        the ECMWF extended-range run started that day (lead day 1; else the SEAS5 member), SEAS5 after."""
        blend = self.seas.copy()
        source = np.array(["seasonal"] * blend.shape[1], dtype=object)
        source[: self.day(self.obs_end) + 1] = "observed"
        gap = [self.obs_end + dt.timedelta(days=i) for i in range(1, (run - self.obs_end).days)]
        gap = [d for d in gap if d <= self.last]
        for d in gap:
            if d in self.ext_by_init:
                g = xr.open_dataset(self.ext_by_init[d])["precip"].sel(time=str(d)).reindex(
                    lat=self.lat, lon=self.lon, method="nearest").values
                blend[:, self.day(d)] = self.correct_ext(g[1:N_MEMBERS + 1], d, d)
                source[self.day(d)] = f"extended range run {d}"
        return blend, source, gap

    def join_ranked(self, blend, members_by_day, seg):
        """Join an ensemble longer than one member per SEAS5 member: N_MEMBERS spread over the range of land-mean rain
        over the segment, the k-th driest matched to the k-th driest SEAS5 member over the same days (a member wet
        over these weeks continues as a wet seasonal member). members_by_day (member, n, lat, lon), corrected.
        Returns the picked source member index for each SEAS5 member."""
        tot_x = np.nanmean(members_by_day[:, :, self.lm].sum(axis=1), axis=1)
        pick = np.argsort(tot_x)[np.round((np.arange(N_MEMBERS) + 0.5) * len(tot_x) / N_MEMBERS - 0.5).astype(int)]
        idx = [self.day(d) for d in seg]
        tot_s = np.nanmean(self.seas[:, idx][:, :, self.lm].sum(axis=1), axis=1)
        pair = np.empty(N_MEMBERS, int)
        pair[np.argsort(tot_s)] = pick
        blend[:, idx] = members_by_day[pair]
        return pair

    def regrid(self, da):
        return da.reindex(lat=self.lat, lon=self.lon, method="nearest")

    # ── sources ─────────────────────────────────────────────────────────────
    def ecmwf(self, ens_path, ext_path=None):
        """ECMWF ENS days 1–15 (member k → member k), then the extended range (run ext_path, else the latest run
        started before the ENS run) to its day 46. The daily "+ weather forecasts" run."""
        self.bc_used = {"reforecast": 0, "provisional": 0}
        ens = self.regrid(xr.open_dataset(ens_path)["precip"])
        ens_days = [d.date() for d in ens.time.to_index()]
        run = ens_days[0]
        if ext_path is None:
            ext_path = max((p for i, p in self.ext_by_init.items() if i < run), key=self.init_of)
        ext = xr.open_dataset(ext_path)["precip"]
        ext_init, ext_days = self.init_of(ext_path), [d.date() for d in ext.time.to_index()]
        blend, source, gap = self.start(run)
        ens_seg = self.season_days(ens_days)
        ext_seg = [d for d in self.season_days(ext_days) if d > ens_seg[-1]]
        print(f"[blend] {self.year}: observed to {self.obs_end}; gap {len(gap)} d; ENS {ens_seg[0]}–{ens_seg[-1]} "
              f"({Path(ens_path).stem}); extended range {ext_seg[0]}–{ext_seg[-1]} (run {ext_init}); SEAS5 after")
        self.need(ext_seg[-1])
        e = ens.values.astype(np.float32)                                     # (50, 15, lat, lon)
        for d in ens_seg:
            blend[:, self.day(d)] = self.correct(e[:N_MEMBERS, ens_days.index(d)], d)
            source[self.day(d)] = f"ENS {Path(ens_path).stem.split('_')[2]}"
        x = self.regrid(ext).values.astype(np.float32)[1:]                   # perturbed members 1..100
        xc = np.stack([self.correct_ext(x[:, ext_days.index(d)], ext_init, d) for d in ext_seg], axis=1)
        pair = self.join_ranked(blend, xc, ext_seg)
        source[[self.day(d) for d in ext_seg]] = f"extended range run {ext_init}"
        ext_bc = ("reforecast" if not self.bc_used["provisional"] else
                  "provisional" if not self.bc_used["reforecast"] else "reforecast, provisional for some days")
        ens_run = dt.datetime.strptime(Path(ens_path).stem.split("_")[2], "%Y%m%d%H")
        info = {"year": self.year, "obs_end": str(self.obs_end), "ens_run": Path(ens_path).stem.split("_")[2],
                "ext_run": str(ext_init), "gap": [str(gap[0]), str(gap[-1])] if gap else None,
                "ens_days": [str(ens_seg[0]), str(ens_seg[-1])], "ext_days": [str(ext_seg[0]), str(ext_seg[-1])],
                "seasonal_from": str(ext_seg[-1] + dt.timedelta(days=1)), "ext_members": (pair + 1).tolist(),
                "bias_correction": f"ENS: provisional (SEAS5 October-start quantile mapping for the same valid day); "
                                   f"extended range: {ext_bc} ({len(self.refc)} reforecast model-version dates on disk)",
                "ext_days_bc": dict(self.bc_used)}
        weather = {"ens_run": f"{ens_run:%Y-%m-%d} {ens_run:%H} UTC", "ens_days": "/".join(info["ens_days"]),
                   "ext_run": f"{ext_init} 00 UTC", "ext_days": "/".join(info["ext_days"]),
                   "seasonal_from": info["seasonal_from"], "bias_correction": f"ENS provisional; extended range {ext_bc}",
                   "experimental": "yes"}
        segs = [("gap", gap), ("ens", ens_seg), ("ext", ext_seg)]
        return blend, info, weather, self.segments(segs, {"ens": f"ECMWF ENS, run {ens_run:%Y-%m-%d}",
                                                          "ext": f"ECMWF extended range, run {ext_init}"})

    def gefs(self, path):
        """NOAA GEFS 35-day: the 31 members corrected provisionally, 25 of them joined by rank."""
        g = self.regrid(xr.open_dataset(path)["precip"])
        days = [d.date() for d in g.time.to_index()]
        run = days[0]
        blend, source, gap = self.start(run)
        seg = self.season_days(days, run)
        self.need(seg[-1])
        v = g.values.astype(np.float32)                                         # (31, n, lat, lon)
        xc = np.stack([self.correct(v[:, days.index(d)], d) for d in seg], axis=1)
        pair = self.join_ranked(blend, xc, seg)
        print(f"[blend] GEFS run {run}: observed to {self.obs_end}; gap {len(gap)} d; GEFS {seg[0]}–{seg[-1]}; SEAS5 after")
        info = {"year": self.year, "obs_end": str(self.obs_end), "run": str(run), "gap": [str(gap[0]), str(gap[-1])] if gap else None,
                "fc_days": [str(seg[0]), str(seg[-1])], "seasonal_from": str(seg[-1] + dt.timedelta(days=1)),
                "members": (pair).tolist(),
                "bias_correction": "provisional (SEAS5 October-start quantile mapping for the same valid day)"}
        return blend, info, self.segments([("gap", gap), ("fc", seg)], {"fc": f"NOAA GEFS 35-day, run {run}"})

    def nwp(self, model, run, rows, label):
        """One medium-range model run (data/nwp rows of that model: lat, lon (0.5° cells), date, rain_mm): the same
        forecast in every member (deterministic), each 0.25° cell from the nearest 0.5° cell, corrected provisionally."""
        blend, source, gap = self.start(run)
        pts = rows[["lat", "lon"]].drop_duplicates().to_numpy()
        la, lo = np.meshgrid(self.lat, self.lon, indexing="ij")
        near = np.argmin((la[..., None] - pts[:, 0]) ** 2 + (lo[..., None] - pts[:, 1]) ** 2, axis=-1)   # (lat, lon)
        days = sorted({dt.date.fromisoformat(d) for d in rows.date})
        seg = self.season_days(days, run)
        piv = rows.pivot_table(index="date", columns=["lat", "lon"], values="rain_mm")
        for d in seg:
            r = piv.loc[str(d)].reindex(pd.MultiIndex.from_arrays([pts[:, 0], pts[:, 1]])).to_numpy(np.float32)
            field = r[near][None]                                              # (1, lat, lon)
            fc = self.correct(np.where(np.isfinite(field), field, 0), d)[0]
            blend[:, self.day(d)] = np.where(np.isfinite(field[0]), fc, blend[:, self.day(d)])
        info = {"year": self.year, "obs_end": str(self.obs_end), "run": str(run), "model": model,
                "gap": [str(gap[0]), str(gap[-1])] if gap else None,
                "fc_days": [str(seg[0]), str(seg[-1])] if seg else None,
                "seasonal_from": str((seg[-1] if seg else self.obs_end) + dt.timedelta(days=1)),
                "bias_correction": "provisional (SEAS5 October-start quantile mapping for the same valid day)"}
        return blend, info, self.segments([("gap", gap), ("fc", seg)], {"fc": f"{label}, run {run}"})

    def ens_only(self, ens_path):
        """ECMWF ENS days 1–15 (member k → member k), then SEAS5 (the medium-range view of ENS)."""
        ens = self.regrid(xr.open_dataset(ens_path)["precip"])
        days = [d.date() for d in ens.time.to_index()]
        blend, source, gap = self.start(days[0])
        seg = self.season_days(days)
        e = ens.values.astype(np.float32)
        for d in seg:
            blend[:, self.day(d)] = self.correct(e[:N_MEMBERS, days.index(d)], d)
        info = {"year": self.year, "obs_end": str(self.obs_end), "run": str(days[0]), "gap": [str(gap[0]), str(gap[-1])] if gap else None,
                "fc_days": [str(seg[0]), str(seg[-1])], "seasonal_from": str(seg[-1] + dt.timedelta(days=1)),
                "bias_correction": "provisional (SEAS5 October-start quantile mapping for the same valid day)"}
        return blend, info, self.segments([("gap", gap), ("fc", seg)], {"fc": f"ECMWF ENS (25 members), run {days[0]}"})

    def segments(self, parts, labels):
        """Where each day's rain comes from, for the dashboard: [{kind, label, start, end}] from 1 Sep to 31 Dec."""
        out = [{"kind": "obs", "label": "Observed rainfall (CHIRPS)", "start": str(self.win0), "end": str(self.obs_end)}]
        for kind, days in parts:
            if not days:
                continue
            if kind == "gap":
                out.append({"kind": "gap", "label": "Weather forecast for the day (ECMWF extended range, day 1)",
                            "start": str(days[0]), "end": str(days[-1])})
            else:
                out.append({"kind": kind, "label": labels[kind], "start": str(days[0]), "end": str(days[-1])})
        nxt = max(dt.date.fromisoformat(s["end"]) for s in out) + dt.timedelta(days=1)
        if nxt <= self.last:
            out.append({"kind": "seas", "label": "ECMWF SEAS5 seasonal forecast", "start": str(nxt), "end": str(self.last)})
        return out

    def to_da(self, blend, long_name, bias_correction):
        da = self.bc_all.sel(year=self.year).copy(data=blend)
        da.attrs.update(long_name=long_name, units="mm/day", bias_correction=bias_correction)
        return da


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, default=HERE.parent, help="repository holding data/ and outputs/")
    ap.add_argument("--run-dir", default="outputs/ecmwf_oct_obs_latest", help="SEAS5 + latest obs run (relative to --base)")
    ap.add_argument("--out-dir", default="outputs/ecmwf_oct_s2s")
    ap.add_argument("--refc-dir", default="data/ecmwf_s2s_reforecast", help="extended-range reforecasts (fetch_ecmwf_reforecast.py)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    b = Blender(a.base, a.run_dir, a.refc_dir)
    out_dir = a.base / a.out_dir
    ens_path = sorted(glob.glob(str(a.base / "data" / "ecmwf_ens" / "ens_tp_*_kenya.nc")))[-1]
    blend, info, weather, _ = b.ecmwf(ens_path, b.ext_paths[-1])
    out_dir.mkdir(parents=True, exist_ok=True)
    b.to_da(blend, "Daily rainfall: observations, ECMWF ENS, ECMWF extended range, SEAS5",
            info["bias_correction"]).to_netcdf(out_dir / f"blend_{b.year}.nc")
    info["created"] = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    (out_dir / f"blend_{b.year}.json").write_text(json.dumps(info, indent=1))
    # read by the backend (run label, /models "weather") and by update_forecast.py; strings only, so it packs
    (out_dir / "run_meta.json").write_text(json.dumps(
        {"init": f"{b.year}-10-01", "obs_end": str(b.obs_end), "obs_end_doy": doy(b.obs_end), "weather": weather,
         "updated": info["created"]}, indent=1))
    print(f"[blend] extended-range days bias-corrected with the reforecasts: {b.bc_used['reforecast']}, "
          f"provisionally: {b.bc_used['provisional']}")
    print(f"[blend] wrote {out_dir / f'blend_{b.year}.nc'}")


if __name__ == "__main__":
    main()
