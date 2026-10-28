#!/usr/bin/env python3
"""
pack_onset_rules.py
───────────────────
Pack the onset / cessation methods computed outside the seasonal pipeline for every Short Rains initialization
into backend/demo_short_rains_rules.npz:
  Agri rules 1–3           onset_rules.py → <run>/icpac_rule<k>/          (key "<k>")
  FAO water balance        fao_water_balance.py → <run>/fao_wb_<def>/     (key "fao-<def>": agricultural,
                           rainfall, cropwater; plus the agricultural run's PAW/TAW outlook for the latest year)
mam_loader builds a "<init> - Agri rule <k>" or "<init> - FAO water balance (<def>)" model from it next to each
parent (Dunning) model: onset, cessation and season length members, probabilities, skill, terciles and CHIRPS
history replaced; seasonal rainfall and daily traces shared with the parent.

Runs whose arrays are identical to an earlier run's (Oct 01 and Oct 01 + Sep obs: both searched from 15 Aug with
observed CHIRPS before 1 Oct) are stored once ("same_as" in the metadata) and share memory in the API.

Usage: python scripts/pack_onset_rules.py
"""
import json
from pathlib import Path

import numpy as np
import xarray as xr

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "backend" / "demo_short_rains_rules.npz"
RUNS = {"ECMWF SEAS5 (Sep)": "outputs/ecmwf_sep_demo", "ECMWF SEAS5 (Oct)": "outputs/ecmwf_oct",
        "ECMWF SEAS5 (Oct+Obs)": "outputs/ecmwf_oct_obs", "ECMWF SEAS5 (Oct+Obs latest)": "outputs/ecmwf_oct_obs_latest"}
VARS = ("onset", "cessation", "lgp")
CAL = (1993, 2016)
KEEP_FROM = 2020       # members and probabilities are packed from this year on (the dashboard offers 2023 – latest;
                       # skill, terciles and CHIRPS history are precomputed over all years) to keep the API small


def load(d):
    a = lambda f: xr.open_dataarray(d / f)
    out = {}
    for v in VARS:
        e = a(f"ECMWF_{v}_all_years.nc")
        c = a(f"CHIRPS_{v}.nc")
        yrs = c.year.values.astype(int)
        cal = (yrs >= CAL[0]) & (yrs <= CAL[1])
        with np.errstate(invalid="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            clim = np.nanmean(c.values[cal], axis=0).astype(np.float32)               # years with an onset / cessation
        out.update({
            f"{v}|members": e.values.astype(np.float16), f"{v}|probs": a(f"probs_damped_{v}.nc").values.astype(np.float16),
            f"{v}|chirps": c.values.astype(np.float16), f"{v}|chirps_clim": clim,
            **{f"{v}|{s}": a(f"{s}_{v}.nc").values.astype(np.float32)
               for s in ("alpha", "hitrate_cal", "hitrate_val", "rpss_val", "t33", "t67")},
        })
        out["chirps_years"] = yrs
        out["model_years"] = e.year.values.astype(int)
    return out


def method_dirs(run):
    """(key, directory, description json) for every packed method of a run."""
    for d in sorted(run.glob("icpac_rule*")):
        if (d / "rule.json").exists():
            yield d.name.removeprefix("icpac_rule"), d, json.loads((d / "rule.json").read_text())
    for d in sorted(run.glob("fao_wb_*")):
        if (d / "method.json").exists():
            yield "fao-" + d.name.removeprefix("fao_wb_"), d, json.loads((d / "method.json").read_text())


def main():
    arrays, meta, seen = {}, {}, {}
    for name, rel in RUNS.items():
        for k, d, rule in method_dirs(BASE / rel):
            data = load(d)
            if (d / "paw_outlook.nc").exists():                          # FAO: PAW/TAW outlook for the latest year
                with xr.open_dataset(d / "paw_outlook.nc") as ds:
                    for q in ("p10", "p50", "p90", "p_below"):
                        data[f"paw|{q}"] = ds[q].values.astype(np.float16)
                    data["paw|meta"] = np.array([ds.attrs["first_doy"], ds.attrs["year"]], np.int32)
            has = (np.isfinite(data["onset|members"].astype(np.float32)).any(axis=(0, 2, 3))
                   | np.isfinite(data["onset|probs"].astype(np.float32)).any(axis=(0, 2, 3)))     # years with members
            keep = has & (data["model_years"] >= KEEP_FROM)
            for v in VARS:                                                   # members (m, year, …), probs (3, year, …)
                data[f"{v}|members"] = np.ascontiguousarray(data[f"{v}|members"][:, keep])
                data[f"{v}|probs"] = np.ascontiguousarray(data[f"{v}|probs"][:, keep])
            info = {"label": rule["label"], "rule": rule, "model_years": data["model_years"].tolist(),
                    "data_years": data["model_years"][keep].tolist(), "packed_years": data["model_years"][keep].tolist(),
                    "skill": bool(rule.get("skill", True))}
            twin = next((src for src, ref in seen.get(k, {}).items()
                         if all(np.array_equal(ref[x], data[x], equal_nan=True) for x in data)), None)
            if twin:
                info["same_as"] = twin
            else:
                arrays.update({f"{name}|r{k}|{x}": val for x, val in data.items() if x != "model_years"})
                seen.setdefault(k, {})[name] = data
            meta.setdefault(name, {})[str(k)] = info
    # identical arrays (e.g. the crop-water definition's onset = the agricultural onset) are stored once
    aliases, by_hash = {}, {}
    for key in list(arrays):
        v = arrays[key]
        h = (v.dtype.str, v.shape, __import__("hashlib").sha1(np.ascontiguousarray(v).tobytes()).hexdigest())
        if h in by_hash:
            aliases[key] = by_hash[h]
            del arrays[key]
        else:
            by_hash[h] = key
    meta["__aliases__"] = aliases
    np.savez_compressed(OUT, __meta__=np.array(json.dumps(meta)), **arrays)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): " + "; ".join(
        f"{n}: rules {', '.join(k + (' (= ' + v['same_as'] + ')' if 'same_as' in v else '') for k, v in r.items())}"
        for n, r in meta.items() if n != "__aliases__") + f"; {len(aliases)} duplicate array(s) aliased")


if __name__ == "__main__":
    main()
