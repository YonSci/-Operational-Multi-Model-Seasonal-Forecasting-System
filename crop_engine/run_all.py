#!/usr/bin/env python3
"""
Crop outlook for every source, each in its own process (crop_engine.run_outlook --sources <one>): the memory of a run
is released before the next, and this parent imports nothing heavy. The first child also builds the benchmark and
tops up the ERA5-Land temperatures. The gridded regional outlook of the seasonal run (crop_engine/grid.py) runs right
after the seasonal source, before the weather-model runs: they can take the whole time limit, and with the grid last
it was not run at all (13-18 Nov 2026). Then, in the time left, the management scenarios (weekly) and DSSAT's nitrogen
levels (weekly, crop_engine/run_nitrogen.py), and the results index and the Crop outlook tab's data are rewritten.

Used by the daily update (scripts/update_forecast.py):
  python -m crop_engine.run_all --workers 1 --minutes 240
  python -m crop_engine.run_all --sources seasonal s2s-ecmwf --force
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time

from crop_engine import config as C
from crop_engine import dashboard


POLL = 15     # s: how often a running child is checked against the deadline


def run_until(cmd, env, end):
    """Run a child until it ends or the wall clock passes `end` (time.time(); None: no limit). Returns its exit code,
    or None when it was stopped, with every process it started (the venv's python.exe on Windows is a launcher that
    starts a second python).

    The deadline is wall-clock time, checked every POLL seconds: subprocess.run(timeout=...) waits with Windows timers
    that pause while the PC is in sleep or Modern Standby, so on 24 Nov 2026 a 240-minute limit set at 14:13 had not
    expired at 20:10 (the laptop was in standby 17:42-19:57). After a standby the child is stopped at the first check."""
    flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen(cmd, cwd=C.BASE, env=env, **flags)
    while True:
        try:
            return p.wait(timeout=POLL)
        except subprocess.TimeoutExpired:
            if end is not None and time.time() >= end:
                break
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    return None


def regional_outlook(a, env, end):
    """The gridded regional outlook of the seasonal run (crop_engine/grid.py: it writes its own tab data, grid.json;
    its benchmark is rebuilt only when its configuration changes), within the time left."""
    if end is not None and time.time() >= end:
        print("crop: time limit reached; regional outlook not run, the previous one kept", flush=True)
        return
    cmd = [sys.executable, "-m", "crop_engine.grid", "--workers", str(max(a.workers, 2))]
    rc = run_until(cmd, env, end)
    if rc is None:
        print("crop: regional outlook stopped at the time limit; the previous one kept", flush=True)
    elif rc:
        print("crop: regional outlook failed; the previous one kept", flush=True)


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
    end = time.time() + a.minutes * 60 if a.minutes else None     # wall clock (run_until)
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
        if end is not None and time.time() >= end:
            failed += sources[k:]
            print(f"crop: time limit reached; not run: {', '.join(sources[k:])}", flush=True)
            break
        cmd = child + ["--sources", s, "--workers", str(a.workers), "--no-dashboard"] + (["--force"] if a.force else []) + \
              (["--climatology"] if a.climatology and k == 0 else []) + (["--no-refresh"] if k or a.no_refresh else [])
        rc = run_until(cmd, env, end)
        if rc is None:                                                   # the child is stopped; its previous results stay
            failed.append(s)
            print(f"crop: {s} stopped at the time limit", flush=True)
        elif rc:
            failed.append(s)
        if s == "seasonal" and "seasonal" not in failed:
            regional_outlook(a, env, end)
    # management scenarios of the seasonal run in the time left (weekly; crop_engine.run_scenarios)
    if "seasonal" in sources and "seasonal" not in failed and (end is None or time.time() < end):
        cmd = [sys.executable, "-m", "crop_engine.run_scenarios", "--max-age-days", "7", "--workers",
               str(max(a.workers, 2)), "--no-dashboard"]
        rc = run_until(cmd, env, end)
        if rc is None:
            print("crop: management scenarios stopped at the time limit; the previous ones kept", flush=True)
        elif rc:
            print("crop: management scenarios failed; the previous ones kept", flush=True)
    # DSSAT's nitrogen levels of the seasonal run in the time left (weekly; crop_engine.run_nitrogen; skipped without DSSAT)
    if "seasonal" in sources and "seasonal" not in failed and (end is None or time.time() < end):
        cmd = [sys.executable, "-m", "crop_engine.run_nitrogen", "--max-age-days", "7", "--workers",
               str(max(a.workers, 2)), "--no-dashboard"]
        rc = run_until(cmd, env, end)
        if rc is None:
            print("crop: nitrogen levels stopped at the time limit; the previous ones kept", flush=True)
        elif rc:
            print("crop: nitrogen levels failed; the previous ones kept", flush=True)
    dashboard.write_index()
    dashboard.write()
    if failed:
        print(f"crop: failed: {', '.join(failed)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
