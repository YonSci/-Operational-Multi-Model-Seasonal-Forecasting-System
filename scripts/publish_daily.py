#!/usr/bin/env python3
"""
publish_daily.py
────────────────
Publish the day's refreshed data to the live platform: commit the files that update_forecast.py regenerates
and push them to origin/main, which redeploys the dashboard (GitHub Pages) and the hosted API (Render).

  frontend/public/tracker/data/        Near real-time rainfall tracking data (observations, 10–16 day forecasts, outlooks)
  backend/demo_short_rains_extra.npz   Oct 01 + latest obs seasonal run for the hosted API
  backend/demo_short_rains_rules.npz   Agri rules 1–3 for every Short Rains run
  backend/rain_stats.npz               seasonal rainfall statistics (Rainfall Terciles view)
  backend/forecast_runs/               forecast runs joining each weather model (Forecast tab, Sub-seasonal and
                                       Medium-range views), one small file per model and run date
  backend/data_status.json             when the daily update last completed (shown in the dashboard)

Only data is published. The commit is made in a separate worktree (outputs/publish_worktree, detached at
origin/main), so the branch checked out here is never touched. Nothing is published when this checkout's code
differs from origin/main (a feature branch with unmerged changes), so data never goes live ahead of its code.
After publishing, a checkout on main is fast-forwarded to the new commit (its data files already match it).

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
DATA_PATHS = ["frontend/public/tracker/data", "backend/demo_short_rains_extra.npz", "backend/demo_short_rains_rules.npz",
              "backend/rain_stats.npz", "backend/data_status.json", "backend/forecast_runs"]
CODE_PATHS = ["scripts", "backend/*.py", "frontend/src", "frontend/tracker"]     # code that writes or reads the data
# Folders whose files the pipeline removes on purpose: the Crop outlook tab's data (crop_engine/dashboard.py) keeps
# only its current files and deletes the rest (scenarios.json and nitrogen.json when they were made with another
# configuration, older runs' files). Copying alone would leave the deleted files live, so a file of these folders
# that is gone here is removed from the published copy too. (folder, pattern, a file that must be here for that)
MIRRORED = [("frontend/public/tracker/data/crop", "*.json", "index.json")]


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] publish: {msg}", flush=True)


def mirror_removals(base=BASE, wt=None):
    """Remove from the publish worktree the files of MIRRORED folders that the pipeline has deleted here. Skipped for
    a folder whose required file is missing here (the crop step did not run), so nothing is removed by accident."""
    wt = wt or WT
    removed = []
    for folder, pattern, required in MIRRORED:
        src, dst = Path(base) / folder, Path(wt) / folder
        if not (src / required).exists() or not dst.is_dir():
            continue
        for f in sorted(dst.glob(pattern)):
            if f.is_file() and not (src / f.name).exists():
                f.unlink()
                removed.append(f"{folder}/{f.name}")
    return removed


def git(*args, cwd=BASE, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def sync_checkout():
    """Fast-forward this checkout (when on main) to the published commit. Its data files already hold that content
    but would block the next morning's `git pull`, leaving the checkout behind and later publishes skipped."""
    if git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "main":
        return
    git("fetch", "--quiet", "origin", "main")
    if git("diff", "--quiet", "origin/main", "--", *DATA_PATHS, check=False).returncode:
        log("checkout left as is: its data differ from origin/main")
        return
    for p in DATA_PATHS:                                            # same content as origin/main, restored by the merge
        git("checkout", "--quiet", "HEAD", "--", p, check=False)    # (a path new in origin/main is not in HEAD yet)
    # new data files (a forecast run per model and day) are untracked here and would block the merge; they were just
    # published, so origin/main brings them back
    git("clean", "--quiet", "-fd", "--", *DATA_PATHS)
    if git("merge", "--quiet", "--ff-only", "origin/main", check=False).returncode:
        git("checkout", "--quiet", "origin/main", "--", *DATA_PATHS)
        log("checkout could not be fast-forwarded (local commits?); data kept")
    else:
        log("checkout fast-forwarded to origin/main")


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
    for f in mirror_removals():
        log(f"removed {f} (no longer produced)")
    git("add", "--all", "--", *DATA_PATHS, cwd=WT)
    stat = git("diff", "--cached", "--stat", cwd=WT).stdout.strip()
    if not stat:
        log("live data already current")
        sync_checkout()
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
            sync_checkout()
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
