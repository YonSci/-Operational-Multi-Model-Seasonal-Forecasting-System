#!/usr/bin/env python3
"""
Crop outlook for every source, each in its own process (crop_engine.run_outlook --sources <one>): the memory of a run
is released before the next, and this parent imports nothing heavy. The first child also builds the benchmark and
tops up the ERA5-Land temperatures. Then, in the time left, the gridded regional outlook of the seasonal run
(crop_engine/grid.py, daily), the management scenarios (weekly) and DSSAT's nitrogen levels (weekly,
crop_engine/run_nitrogen.py), and the results index and the Crop outlook tab's data are rewritten.

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
    # Then, in the time left and in this order: the gridded regional outlook (daily: the Crop outlook tab's map;
    # crop_engine/grid.py writes its own tab data, grid.json, and rebuilds its benchmark only when its
    # configuration changes), the management scenarios (weekly) and DSSAT's nitrogen levels (weekly). The grid goes
    # first: the weekly steps keep their previous results when stopped, and before it moved up the scenarios could
    # take the whole time left, so the published map stayed days behind the outlook (13 Nov 2026: the grid was
    # still the 11 Nov build, made before the delayed-germination fix).
    steps = [("regional outlook", ["crop_engine.grid", "--workers", str(max(a.workers, 2))], "the previous one kept"),
             ("management scenarios", ["crop_engine.run_scenarios", "--max-age-days", "7", "--workers",
                                       str(max(a.workers, 2)), "--no-dashboard"], "the previous ones kept"),
             ("nitrogen levels", ["crop_engine.run_nitrogen", "--max-age-days", "7", "--workers",
                                  str(max(a.workers, 2)), "--no-dashboard"], "the previous ones kept")]
    for name, args, kept in steps:
        left = end - time.monotonic() if end else None
        if "seasonal" not in sources or "seasonal" in failed:
            break
        if left is not None and left <= 0:
            print(f"crop: time limit reached; {name} not run, {kept}", flush=True)
            continue
        try:
            if subprocess.run([sys.executable, "-m"] + args, cwd=C.BASE, env=env, timeout=left).returncode:
                print(f"crop: {name} failed; {kept}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"crop: {name} stopped at the time limit; {kept}", flush=True)
    dashboard.write_index()
    dashboard.write()
    if failed:
        print(f"crop: failed: {', '.join(failed)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
