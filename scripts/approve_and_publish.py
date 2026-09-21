#!/usr/bin/env python3
"""
scripts/approve_and_publish.py
──────────────────────────────
Human-in-the-Loop Review and Approval CLI.
Inspect staged forecast runs, review dominant category statistics,
and approve promotion to the live dashboard.

Usage:
  # List all staged runs awaiting review
  python scripts/approve_and_publish.py --list

  # Approve and publish a specific run
  python scripts/approve_and_publish.py --run-id RUN-KENYA-SHORT_RAINS2026-20260921_143000
"""

import sys
import argparse
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from pipeline.publisher import publish_run, list_staged_runs

def main():
    parser = argparse.ArgumentParser(description="Human-in-the-Loop Approval & Publishing CLI")
    parser.add_argument("--run-id", type=str, help="Run ID of the staged forecast to approve and publish")
    parser.add_argument("--token", type=str, default=None, help="Optional approval token from notification email")
    parser.add_argument("--list", action="store_true", help="List all staged runs and their current status")
    args = parser.parse_args()

    if args.list or not args.run_id:
        runs = list_staged_runs()
        if not runs:
            print("\n  No staged forecast runs found in outputs/staging/.")
            return

        print("\n" + "=" * 80)
        print("  STAGED FORECAST RUNS")
        print("=" * 80)
        for r in runs:
            m = r.get("metrics", {})
            status_tag = "[PUBLISHED]" if r.get("status") == "PUBLISHED" else "[PENDING APPROVAL]"
            print(f"\n  {status_tag} Run ID: {r.get('run_id')}")
            print(f"    Target   : {r.get('country', '').title()} • {r.get('season_label')} ({r.get('forecast_year')})")
            print(f"    Status   : {r.get('status')}")
            print(f"    Created  : {r.get('created_at')}")
            if "anomaly_pct" in m:
                print(f"    Signal   : Anomaly {m['anomaly_pct']:+.1f}% | Above Normal: {m['above_cells']} px ({m['above_pct']}%)")
            print(f"    Command  : python scripts/approve_and_publish.py --run-id {r.get('run_id')}")
        print("\n" + "=" * 80)
        return

    # Approve and publish
    try:
        res = publish_run(args.run_id, token=args.token)
        print("\n" + "=" * 80)
        print(f"  [SUCCESS] Forecast run '{args.run_id}' has been published!")
        print(f"  Destination : {res.get('target_dir')}")
        print(f"  Files       : {', '.join(res.get('promoted_files', []))}")
        print(f"  Published At: {res.get('published_at')}")
        print("=" * 80 + "\n")
    except Exception as e:
        print(f"\n  [ERROR] Failed to publish run '{args.run_id}': {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
