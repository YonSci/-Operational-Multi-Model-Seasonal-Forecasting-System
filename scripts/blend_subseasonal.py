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

Bias correction is PROVISIONAL: ECMWF's extended-range reforecasts are not yet available here, so ENS and
extended-range rainfall are quantile-mapped to CHIRPS with the transfer the SEAS5 run uses for the same valid
day (SEAS5 October-start hindcasts 1993–2016, all members, same IFS model family; cube-root transform with
wet-day frequency adjustment, as in process_ecmwf_september.py). Replace it with a reforecast-based mapping
once the S2S reforecasts are downloaded.

Output: outputs/ecmwf_oct_s2s/blend_<year>.nc  (precip: member, day, lat, lon; day 0 = window start, 1 Sep)
        and blend_<year>.json (the sources and dates of every segment)
Then:   process_ecmwf_september.py ... --out-dir outputs/ecmwf_oct_s2s --bc-op-override outputs/ecmwf_oct_s2s/blend_<year>.nc
Usage:  python scripts/blend_subseasonal.py [--base <repo holding data/ and outputs/>]
"""
import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from process_ecmwf_september import _build_qm_transfer, QM_DOY_WINDOW, CAL_YEARS  # noqa: E402

N_MEMBERS = 25


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, default=HERE.parent, help="repository holding data/ and outputs/")
    ap.add_argument("--run-dir", default="outputs/ecmwf_oct_obs_latest", help="SEAS5 + latest obs run (relative to --base)")
    ap.add_argument("--out-dir", default="outputs/ecmwf_oct_s2s")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = a.base
    run_dir, out_dir = base / a.run_dir, base / a.out_dir

    meta = json.loads((run_dir / "run_meta.json").read_text())
    obs_end = dt.date.fromisoformat(meta["obs_end"])
    bc_all = xr.open_dataarray(run_dir / "ECMWF_bc_daily_all_years.nc")
    year = int(bc_all.year.values[-1])
    seas = bc_all.sel(year=year).values.astype(np.float32)               # (member, day, lat, lon)
    lat, lon = bc_all.lat.values, bc_all.lon.values
    win0 = dt.date(year, 9, 1)                                           # day 0 of the run window
    n_day = seas.shape[1]
    day = lambda d: (d - win0).days                                     # noqa: E731

    ens_path = sorted(glob.glob(str(base / "data" / "ecmwf_ens" / "ens_tp_*_kenya.nc")))[-1]
    ext_paths = sorted(glob.glob(str(base / "data" / "ecmwf_ext" / "ext_tp_*_kenya.nc")))
    ens = xr.open_dataset(ens_path)["precip"].reindex(lat=lat, lon=lon, method="nearest")
    ens_days = [d.date() for d in ens.time.to_index()]
    ext = xr.open_dataset(ext_paths[-1])["precip"]
    ext_init = dt.datetime.strptime(Path(ext_paths[-1]).stem.split("_")[2], "%Y%m%d").date()
    ext_days = [d.date() for d in ext.time.to_index()]

    # segment dates (inclusive) inside the season window
    gap = [obs_end + dt.timedelta(days=i) for i in range(1, (ens_days[0] - obs_end).days)]
    ens_seg = [d for d in ens_days if d > obs_end]
    ext_seg = [d for d in ext_days if d > ens_seg[-1]]
    last = dt.date(year, 12, 31)
    gap, ens_seg, ext_seg = ([d for d in s if d <= last] for s in (gap, ens_seg, ext_seg))
    print(f"[blend] {year}: observed to {obs_end}; gap {len(gap)} d; ENS {ens_seg[0]}–{ens_seg[-1]} "
          f"({Path(ens_path).stem}); extended range {ext_seg[0]}–{ext_seg[-1]} (run {ext_init}); SEAS5 after")

    # provisional bias correction: the SEAS5 run's transfer for the same valid day
    lm = ~np.isnan(seas[0, 0])
    lead0 = dt.date(year, 10, 1)
    n_lead = (ext_seg[-1] - lead0).days + 1
    raw = load_seas5_raw(base / "data" / "seasonal_pr_downloads_ke" / "ecmwf_oct", lat, lon, n_lead)
    chirps = chirps_daily(base / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc", lat, lon)

    def corrector(d):
        """{(i, j): transfer} for valid day d."""
        li, dd = (d - lead0).days, doy(d) - 1
        out = {}
        for i, j in np.argwhere(lm):
            c = chirps[:, max(0, dd - QM_DOY_WINDOW):min(366, dd + QM_DOY_WINDOW + 1), i, j].ravel()
            s = raw[:, :, li, i, j].ravel()
            out[i, j] = _build_qm_transfer(c[~np.isnan(c)], s[~np.isnan(s)])
        return out

    def correct(field, d):
        """field: (member, lat, lon) raw rainfall on valid day d → bias-corrected copy."""
        f = field.copy()
        for (i, j), fn in corrector(d).items():
            f[:, i, j] = fn(field[:, i, j])
        return f

    blend = seas.copy()
    source = np.array(["seasonal"] * n_day, dtype=object)
    source[: day(obs_end) + 1] = "observed"

    # gap days: the extended-range run started that day (lead day 1), else the seasonal member is kept
    ext_by_init = {dt.datetime.strptime(Path(p).stem.split("_")[2], "%Y%m%d").date(): p for p in ext_paths}
    for d in gap:
        if d in ext_by_init:
            g = xr.open_dataset(ext_by_init[d])["precip"].sel(time=str(d)).reindex(lat=lat, lon=lon, method="nearest").values
            blend[:, day(d)] = correct(g[1:N_MEMBERS + 1], d)
            source[day(d)] = f"extended range run {d}"

    # ENS days 1–15: member k → path k
    e = ens.values.astype(np.float32)                                     # (50, 15, lat, lon)
    for d in ens_seg:
        blend[:, day(d)] = correct(e[:N_MEMBERS, ens_days.index(d)], d)
        source[day(d)] = f"ENS {Path(ens_path).stem.split('_')[2]}"

    # extended range: 25 of the 100 perturbed members spanning their range, matched by rank to the SEAS5 members
    x = ext.reindex(lat=lat, lon=lon, method="nearest").values.astype(np.float32)[1:]    # perturbed members 1..100
    xi = [ext_days.index(d) for d in ext_seg]
    xc = np.stack([correct(x[:, k], d) for k, d in zip(xi, ext_seg)], axis=1)          # (100, n, lat, lon)
    tot_x = np.nanmean(xc[:, :, lm].sum(axis=1), axis=1)
    pick = np.argsort(tot_x)[np.round((np.arange(N_MEMBERS) + 0.5) * len(tot_x) / N_MEMBERS - 0.5).astype(int)]
    seg = [day(d) for d in ext_seg]
    tot_s = np.nanmean(seas[:, seg][:, :, lm].sum(axis=1), axis=1)
    pair = np.empty(N_MEMBERS, int)
    pair[np.argsort(tot_s)] = pick                                        # k-th driest SEAS5 member ← k-th driest pick
    blend[:, seg] = xc[pair]
    source[seg] = f"extended range run {ext_init}"

    out_dir.mkdir(parents=True, exist_ok=True)
    da = bc_all.sel(year=year).copy(data=blend)
    da.attrs.update(long_name="Daily rainfall: observations, ECMWF ENS, ECMWF extended range, SEAS5", units="mm/day",
                    bias_correction="provisional: SEAS5 October-start quantile mapping for the same valid day")
    da.to_netcdf(out_dir / f"blend_{year}.nc")
    info = {"year": year, "obs_end": str(obs_end), "ens_run": Path(ens_path).stem.split("_")[2],
            "ext_run": str(ext_init), "gap": [str(gap[0]), str(gap[-1])] if gap else None,
            "ens_days": [str(ens_seg[0]), str(ens_seg[-1])], "ext_days": [str(ext_seg[0]), str(ext_seg[-1])],
            "seasonal_from": str(ext_seg[-1] + dt.timedelta(days=1)), "ext_members": (pair + 1).tolist(),
            "bias_correction": "provisional (SEAS5 October-start quantile mapping)",
            "created": dt.datetime.now().astimezone().isoformat(timespec="minutes")}
    (out_dir / f"blend_{year}.json").write_text(json.dumps(info, indent=1))
    # read by the backend (run label, /models "weather") and by update_forecast.py; strings only, so it packs
    ens_run = dt.datetime.strptime(info["ens_run"], "%Y%m%d%H")
    weather = {"ens_run": f"{ens_run:%Y-%m-%d} {ens_run:%H} UTC", "ens_days": "/".join(info["ens_days"]),
               "ext_run": f"{ext_init} 00 UTC", "ext_days": "/".join(info["ext_days"]),
               "seasonal_from": info["seasonal_from"], "bias_correction": "provisional", "experimental": "yes"}
    (out_dir / "run_meta.json").write_text(json.dumps(
        {"init": f"{year}-10-01", "obs_end": str(obs_end), "obs_end_doy": doy(obs_end), "weather": weather,
         "updated": info["created"]}, indent=1))
    print(f"[blend] wrote {out_dir / f'blend_{year}.nc'}; land-mean rain over the extended-range days "
          f"{np.nanmean(tot_s):.0f} mm in SEAS5 → {np.nanmean(tot_x[pick]):.0f} mm blended")


if __name__ == "__main__":
    main()
