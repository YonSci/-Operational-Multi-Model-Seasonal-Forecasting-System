#!/usr/bin/env python3
"""
pack_planting_onset.py
──────────────────────
Pack the planting-onset presets (agro_onset.py, one folder per preset) for every Short Rains initialization
into backend/demo_short_rains_planting.npz. mam_loader builds a "<init> - Planting <k>d" model from it next to
each parent model (same cessation, season length and rainfall; onset, onset probabilities, onset skill,
terciles and CHIRPS onset history replaced), so the local and the hosted API offer the same presets.

  October runs: outputs/<run>/agro_onset_d<k>/ (agro_onset.py seasonal <run> --dry-spell <k> --out-name agro_onset_d<k>)
  Sep 01 run:   no hindcast daily data on disk, only the 2025 and 2026 bias-corrected members in
                backend/demo_data.npz → planting onset for those two years, raw (uncalibrated) probabilities
                against the CHIRPS terciles; skill not available.

Usage: python scripts/pack_planting_onset.py
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, str(BASE / "backend"))
import agro_onset as ao  # noqa: E402

OUT = BASE / "backend" / "demo_short_rains_planting.npz"
PRESETS = {7: "20 mm in 3 days, no 7-day dry spell in the next 21 days",
           10: "20 mm in 3 days, no 10-day dry spell in the next 21 days"}
RUNS = {"ECMWF SEAS5 (Oct)": "outputs/ecmwf_oct", "ECMWF SEAS5 (Oct+Obs)": "outputs/ecmwf_oct_obs",
        "ECMWF SEAS5 (Oct+Obs latest)": "outputs/ecmwf_oct_obs_latest"}
SEP = "ECMWF SEAS5 (Sep)"
CAL = (1993, 2016)


def nc(path):
    return xr.open_dataarray(path).values.astype(np.float32)


def chirps_part(d):
    """CHIRPS planting onset per year (1993–2025) and its 1993–2016 mean (no-onset years left out of the mean)."""
    c = xr.open_dataarray(d / "CHIRPS_agro_onset_doy.nc")
    years = c.year.values.astype(int)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)                  # all-NaN cells (no onset in any year)
        clim = np.nanmean(c.values[(years >= CAL[0]) & (years <= CAL[1])], axis=0).astype(np.float32)
    return c.values.astype(np.float32), years, clim


def main():
    arrays, meta = {}, {}
    ref = None
    for name, rel in RUNS.items():
        for k, label in PRESETS.items():
            d = BASE / rel / f"agro_onset_d{k}"
            if not (d / "rule.json").exists():
                print(f"  skip {name} d{k}: {d} missing")
                continue
            on = xr.open_dataarray(d / "ECMWF_agro_onset_doy_all_years.nc")
            c_on, c_years, clim = chirps_part(d)
            key = f"{name}|d{k}"
            arrays.update({
                f"{key}|onset_doy": on.values.astype(np.float16), f"{key}|probs": nc(d / "probs_damped_agro_onset.nc").astype(np.float16),
                f"{key}|alpha": nc(d / "alpha_agro_onset.nc"), f"{key}|hitrate_cal": nc(d / "hitrate_cal_agro_onset.nc"),
                f"{key}|hitrate_val": nc(d / "hitrate_val_agro_onset.nc"), f"{key}|rpss_val": nc(d / "rpss_val_agro_onset.nc"),
                f"{key}|t33": nc(d / "t33_agro_onset.nc"), f"{key}|t67": nc(d / "t67_agro_onset.nc"),
                f"{key}|chirps_onset": c_on.astype(np.float16), f"{key}|chirps_years": c_years, f"{key}|chirps_clim": clim,
            })
            meta.setdefault(name, {})[str(k)] = {"label": label, "model_years": on.year.values.astype(int).tolist(),
                                                 "rule": json.loads((d / "rule.json").read_text()), "skill": True}
            if name.endswith("latest)"):
                ref = ref or {}
                ref[k] = d

    # Sep 01 run: 2025 and 2026 members only (demo_data.npz), CHIRPS terciles from the October preset folders
    demo = np.load(BASE / "backend" / "demo_data.npz")
    sep_years = demo["sep_ecmwf_years"].astype(int)
    for k, label in PRESETS.items():
        if not ref or k not in ref:
            continue
        d = ref[k]
        t33, t67 = nc(d / "t33_agro_onset.nc"), nc(d / "t67_agro_onset.nc")
        c_on, c_years, clim = chirps_part(d)
        lm = np.isfinite(t33)
        rule = {kk: v for kk, v in json.loads((d / "rule.json").read_text()).items() if kk in ao.RULE}
        on = np.full((25, len(sep_years), *lm.shape), np.nan, np.float32)
        probs = np.full((3, len(sep_years), *lm.shape), np.nan, np.float32)
        for y in (2025, 2026):
            if f"sep_ecmwf_bc_daily_{y}" not in demo.files or y not in sep_years:
                continue
            yi = int(np.where(sep_years == y)[0][0])
            bc = demo[f"sep_ecmwf_bc_daily_{y}"].astype(np.float32)          # (member, day from 1 Sep, lat, lon)
            idx, _ = ao.detect(np.moveaxis(bc[:, :, lm], 1, -1), rule["search_start_doy"] - 244,
                               **{kk: v for kk, v in rule.items() if kk != "search_start_doy"})
            on[:, yi][:, lm] = idx + 244
            f = np.where(lm & np.isnan(on[:, yi]), ao.NO_ONSET, on[:, yi])   # no onset by 31 Dec counts as late
            with np.errstate(invalid="ignore"):
                probs[0, yi] = np.mean(f < t33, axis=0)
                probs[1, yi] = np.mean((f >= t33) & (f < t67), axis=0)
                probs[2, yi] = np.mean(f >= t67, axis=0)
            probs[:, yi][:, ~lm] = np.nan
        key = f"{SEP}|d{k}"
        nanmap = np.full(lm.shape, np.nan, np.float32)
        arrays.update({
            f"{key}|onset_doy": on.astype(np.float16), f"{key}|probs": probs.astype(np.float16),
            f"{key}|alpha": nanmap, f"{key}|hitrate_cal": nanmap, f"{key}|hitrate_val": nanmap, f"{key}|rpss_val": nanmap,
            f"{key}|t33": t33, f"{key}|t67": t67,
            f"{key}|chirps_onset": c_on.astype(np.float16), f"{key}|chirps_years": c_years, f"{key}|chirps_clim": clim,
        })
        meta.setdefault(SEP, {})[str(k)] = {"label": label, "model_years": sep_years.tolist(), "rule": rule, "skill": False,
                                            "note": "2025 and 2026 only; probabilities not calibrated; no hindcast skill"}

    np.savez_compressed(OUT, __meta__=np.array(json.dumps(meta)), **arrays)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): " + "; ".join(f"{n}: d{', d'.join(v)}" for n, v in meta.items()))


if __name__ == "__main__":
    main()
