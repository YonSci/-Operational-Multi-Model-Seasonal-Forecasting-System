#!/usr/bin/env python3
"""
Crop outlook for every source, each in its own process (crop_engine.run_outlook --sources <one>): the memory of a run
is released before the next, and this parent imports nothing heavy. The first child also builds the benchmark and
tops up the ERA5-Land temperatures. Then, in the time left, the management scenarios (weekly) and the gridded regional
outlook of the seasonal run (crop_engine/grid.py), and the results index and the Crop outlook tab's data are rewritten.

Used by the daily update (scripts/update_forecast.py):
  python -m crop_engine.run_all --workers 1 --minutes 240
  python -m crop_engine.run_all --sources seasonal s2s-ecmwf --force
"""
import argparse
import json
import os
import subprocess
import sys
import time

from crop_engine import config as C
from crop_engine import dashboard


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", nargs="+", help="only these sources (default: seasonal and every run on disk)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--climatology", action="store_true", help="rebuild the observed-weather benchmark")
    ap.add_argument("--force", action="store_true", help="rebuild runs already made from the same observations")
    ap.add_argument("--no-refresh", action="store_true", help="do not top up the ERA5-Land temperature series")
    ap.add_argument("--minutes", type=float, default=None,
                    help="time limit: the running source is stopped and no new one started after it (results so far kept)")
    a = ap.parse_args()
    end = time.monotonic() + a.minutes * 60 if a.minutes else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    child = [sys.executable, "-m", "crop_engine.run_outlook"]
    # one BLAS thread: the engine's array work is element-wise, and each BLAS thread reserves ~60 MB at import
    # (821 MB → 113 MB per child on a 12-thread PC)
    env = {**os.environ, **{k: os.environ.get(k, "1") for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}
    got = subprocess.run(child + ["--list-sources"], cwd=C.BASE, env=env, capture_output=True, text=True)
    if got.returncode:
        print(got.stderr[-2000:], file=sys.stderr)
        return 1
    sources = [s for s in json.loads(got.stdout.strip().splitlines()[-1]) if not a.sources or s in a.sources]
    failed = []
    for k, s in enumerate(sources):
        left = end - time.monotonic() if end else None
        if left is not None and left <= 0:
            failed += sources[k:]
            print(f"crop: time limit reached; not run: {', '.join(sources[k:])}", flush=True)
            break
        cmd = child + ["--sources", s, "--workers", str(a.workers), "--no-dashboard"] + (["--force"] if a.force else []) + \
              (["--climatology"] if a.climatology and k == 0 else []) + (["--no-refresh"] if k or a.no_refresh else [])
        try:
            if subprocess.run(cmd, cwd=C.BASE, env=env, timeout=left).returncode:
                failed.append(s)
        except subprocess.TimeoutExpired:                                # the child is killed; its previous results stay
            failed.append(s)
            print(f"crop: {s} stopped at the time limit", flush=True)
    # management scenarios of the seasonal run in the time left (weekly; crop_engine.run_scenarios)
    left = end - time.monotonic() if end else None
    if "seasonal" in sources and "seasonal" not in failed and (left is None or left > 0):
        cmd = [sys.executable, "-m", "crop_engine.run_scenarios", "--max-age-days", "7", "--workers",
               str(max(a.workers, 2)), "--no-dashboard"]
        try:
            if subprocess.run(cmd, cwd=C.BASE, env=env, timeout=left).returncode:
                print("crop: management scenarios failed; the previous ones kept", flush=True)
        except subprocess.TimeoutExpired:
            print("crop: management scenarios stopped at the time limit; the previous ones kept", flush=True)
    # the gridded regional outlook of the seasonal run in the time left (crop_engine/grid.py: it writes its own
    # tab data, grid.json; its benchmark is rebuilt only when its configuration changes)
    left = end - time.monotonic() if end else None
    if "seasonal" in sources and "seasonal" not in failed and (left is None or left > 0):
        cmd = [sys.executable, "-m", "crop_engine.grid", "--workers", str(max(a.workers, 2))]
        try:
            if subprocess.run(cmd, cwd=C.BASE, env=env, timeout=left).returncode:
                print("crop: regional outlook failed; the previous one kept", flush=True)
        except subprocess.TimeoutExpired:
            print("crop: regional outlook stopped at the time limit; the previous one kept", flush=True)
    dashboard.write_index()
    dashboard.write()
    if failed:
        print(f"crop: failed: {', '.join(failed)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
