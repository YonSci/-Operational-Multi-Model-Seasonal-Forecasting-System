#!/usr/bin/env python3
"""
pack_onset_rules.py
───────────────────
Pack the ICPAC onset / cessation rules (onset_rules.py → <run>/icpac_rule<k>/) for every Short Rains initialization
into backend/demo_short_rains_rules.npz. mam_loader builds a "<init> - ICPAC rule <k>" model from it next to each
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


def main():
    arrays, meta, seen = {}, {}, {}
    for name, rel in RUNS.items():
        for d in sorted((BASE / rel).glob("icpac_rule*")):
            if not (d / "rule.json").exists():
                continue
            k = int(d.name.removeprefix("icpac_rule"))
            rule = json.loads((d / "rule.json").read_text())
            data = load(d)
            has = (np.isfinite(data["onset|members"].astype(np.float32)).any(axis=(0, 2, 3))
                   | np.isfinite(data["onset|probs"].astype(np.float32)).any(axis=(0, 2, 3)))     # years with members
            info = {"label": rule["label"], "rule": rule, "model_years": data["model_years"].tolist(),
                    "data_years": data["model_years"][has].tolist(), "skill": bool(rule.get("skill", True))}
            twin = next((src for src, ref in seen.get(k, {}).items()
                         if all(np.array_equal(ref[x], data[x], equal_nan=True) for x in data)), None)
            if twin:
                info["same_as"] = twin
            else:
                arrays.update({f"{name}|r{k}|{x}": val for x, val in data.items() if x != "model_years"})
                seen.setdefault(k, {})[name] = data
            meta.setdefault(name, {})[str(k)] = info
    np.savez_compressed(OUT, __meta__=np.array(json.dumps(meta)), **arrays)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): " + "; ".join(
        f"{n}: rules {', '.join(k + (' (= ' + v['same_as'] + ')' if 'same_as' in v else '') for k, v in r.items())}"
        for n, r in meta.items()))


if __name__ == "__main__":
    main()
