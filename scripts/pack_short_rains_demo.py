#!/usr/bin/env python3
"""
pack_short_rains_demo.py
────────────────────────
Pack the extra Short Rains initializations (mam_loader._EXTRA_SHORT_RAINS: Oct, Oct+Obs, Oct+Obs latest)
into backend/demo_short_rains_extra.npz, so the hosted API (demo mode, no NetCDF outputs) can serve them.

Each model's loaded entry is flattened to arrays named "<model>|<field>[|<subfield>]" (float16, compressed);
scalars, strings and dict structure go in "__meta__" (JSON). Daily rainfall traces (bc_daily) are left out —
the hosted API runs with LOAD_BC_DAILY=0 and draws synthetic plumes.
"""
import json
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "backend"))
import mam_loader as ml  # noqa: E402

OUT = BASE / "backend" / "demo_short_rains_extra.npz"
SKIP = {"bc_daily"}


def main():
    ml.configure()
    models = {}
    ml._attach_extra_short_rains(models)
    arrays, meta = {}, {}

    def pack(v, key):
        """Arrays → npz entries (float16 when floating); dicts recurse; scalars stay in the JSON metadata."""
        if isinstance(v, np.ndarray):
            arrays[key] = v.astype(np.float16) if v.dtype.kind == "f" else v
            return "array"
        if isinstance(v, dict):
            return {str(sk): pack(sv, f"{key}|{sk}") for sk, sv in v.items()}
        if isinstance(v, (np.integer, np.floating)):
            return v.item()
        return v if v is None or isinstance(v, (int, float, str, bool)) else None

    for name, entry in models.items():
        meta[name] = {k: pack(v, f"{name}|{k}") for k, v in entry.items() if k not in SKIP}
    np.savez_compressed(OUT, __meta__=np.array(json.dumps(meta)), **arrays)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): {', '.join(meta)}")


if __name__ == "__main__":
    main()
