#!/usr/bin/env python3
"""
publish_daily.py
────────────────
Publish the day's refreshed data to the live platform: commit the files that update_forecast.py regenerates
and push them to origin/main, which redeploys the dashboard (GitHub Pages) and the hosted API (Render).

  frontend/public/tracker/data/        Short Rains Tracker data (observations, 10–16 day forecasts, outlooks)
  backend/demo_short_rains_extra.npz   Oct 01 + latest obs seasonal run for the hosted API
  backend/demo_short_rains_rules.npz   Agri rules 1–3 for every Short Rains run

Only data is published. The commit is made in a separate worktree (outputs/publish_worktree, detached at
origin/main), so the branch checked out here is never touched. Nothing is published when this checkout's code
differs from origin/main (a feature branch with unmerged changes), so data never goes live ahead of its code.

Usage:
  python scripts/publish_daily.py              # commit and push when the data changed
  python scripts/publish_daily.py --dry-run    # show what would be published
"""
import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
WT = BASE / "outputs" / "publish_worktree"
DATA_PATHS = ["frontend/public/tracker/data", "backend/demo_short_rains_extra.npz", "backend/demo_short_rains_rules.npz"]
CODE_PATHS = ["scripts", "backend/*.py", "frontend/src", "frontend/tracker"]     # code that writes or reads the data


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] publish: {msg}", flush=True)


def git(*args, cwd=BASE, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--note", default="", help="added to the commit message (e.g. the observation date)")
    a = ap.parse_args()

    git("fetch", "--quiet", "origin", "main")
    if git("diff", "--quiet", "origin/main", "--", *CODE_PATHS, check=False).returncode:
        changed = git("diff", "--name-only", "origin/main", "--", *CODE_PATHS).stdout.split()
        log(f"not published: this checkout's code differs from origin/main ({len(changed)} file(s), e.g. "
            f"{', '.join(changed[:3])}); merge it or check out main first")
        return 0

    if not (WT / ".git").exists():
        git("worktree", "prune")
        git("worktree", "add", "--detach", str(WT), "origin/main")
    git("checkout", "--quiet", "--detach", "--force", "origin/main", cwd=WT)
    git("clean", "--quiet", "-fd", "--", *DATA_PATHS, cwd=WT)

    for p in DATA_PATHS:
        src, dst = BASE / p, WT / p
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, dst)
    git("add", "--", *DATA_PATHS, cwd=WT)
    stat = git("diff", "--cached", "--stat", cwd=WT).stdout.strip()
    if not stat:
        log("live data already current")
        return 0
    log("changes:\n" + stat)
    if a.dry_run:
        git("reset", "--quiet", cwd=WT)
        return 0

    msg = f"Daily data update {dt.date.today():%Y-%m-%d}" + (f" ({a.note})" if a.note else "")
    git("commit", "--quiet", "-m", msg, cwd=WT)
    for attempt in range(2):
        r = git("push", "--quiet", "origin", "HEAD:main", cwd=WT, check=False)
        if not r.returncode:
            log(f"pushed to origin/main: {msg}")
            return 0
        log(f"push rejected ({r.stderr.strip()[:200]}); rebasing on the new origin/main")
        git("fetch", "--quiet", "origin", "main")
        if git("rebase", "--quiet", "origin/main", cwd=WT, check=False).returncode:
            git("rebase", "--abort", cwd=WT, check=False)
            break
    log("push failed; the data stays local until the next run")
    return 1


if __name__ == "__main__":
    sys.exit(main())
