#!/usr/bin/env python3
"""
scripts/run_automated_pipeline.py
─────────────────────────────────
Master Automation Pipeline for Country and Seasonal Climate Forecasting.
Downloads C3S operational forecasts, performs Method 2 dynamical EQM downscaling,
stages results, dispatches email reminder/digest with preview map, and awaits approval.

Usage Examples:
  # Run Kenya Short Rains (OND 2026) using existing downloaded data
  python scripts/run_automated_pipeline.py --country kenya --season short_rains --year 2026 --skip-download

  # Run Ethiopia Deyr (OND 2026)
  python scripts/run_automated_pipeline.py --country ethiopia --season deyr --year 2026 --skip-download

  # Auto-approve for testing or automated scheduled runs
  python scripts/run_automated_pipeline.py --country kenya --season short_rains --year 2026 --auto-approve
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from pipeline.config import get_season_config, SEASON_REGISTRY
from pipeline.downloader import download_forecast
from pipeline.analyzer import run_analysis
from pipeline.notifier import send_notification
from pipeline.publisher import publish_run

def parse_args():
    parser = argparse.ArgumentParser(description="Operational Multi-Country Seasonal Forecasting Automation Pipeline")
    parser.add_argument("--country", type=str, default="kenya", help="Target country (e.g. kenya, ethiopia)")
    parser.add_argument("--season", type=str, default="short_rains", help="Target season (e.g. short_rains, deyr, long_rains, belg, kiremt)")
    parser.add_argument("--year", type=int, default=2026, help="Forecast operational year (default: 2026)")
    parser.add_argument("--skip-download", action="store_true", help="Skip CDS download and use local raw file if available")
    parser.add_argument("--force-download", action="store_true", help="Force re-download from Copernicus CDS")
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve and publish results to dashboard immediately")
    parser.add_argument("--dry-run", action="store_true", help="Simulate pipeline without modifying live data or sending real emails")
    parser.add_argument("--all", action="store_true", help="Run pipeline across all configured active seasons for the year")
    return parser.parse_args()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def process_target(country: str, season: str, year: int, skip_download: bool, force_download: bool, auto_approve: bool, dry_run: bool):
    cfg = get_season_config(country, season)
    print("\n" + "#" * 78)
    print(f"# RUNNING OPERATIONAL PIPELINE: {cfg.country.upper()} • {cfg.label.upper()} • {year}")
    print("#" * 78)

    # 1. Download / Verify Raw Forecast
    print(f"\n>>> [Stage 1/4] Acquiring GCM Data for Init {year}-{cfg.init_month:02d}-01...")
    target_raw_file = cfg.raw_download_dir / f"ecmwf_{year}{cfg.init_month:02d}_d01.nc"
    if not target_raw_file.exists():
        month_tag = "sep" if cfg.init_month == 9 else "feb" if cfg.init_month == 2 else "may"
        fallback_file = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / f"ecmwf_{month_tag}" / f"ecmwf_{year}{cfg.init_month:02d}_d01.nc"
        if fallback_file.exists():
            target_raw_file = fallback_file

    if skip_download and target_raw_file.exists():
        print(f"  Using existing local file (--skip-download): {target_raw_file}")
        gcm_file = target_raw_file
    else:
        gcm_file = download_forecast(cfg, year=year, force=force_download, dry_run=dry_run)

    # 2. Method 2 Downscaling & Staging
    print("\n>>> [Stage 2/4] Running Method 2 Dynamical Post-Processing & Staging...")
    manifest = run_analysis(cfg, year=year, gcm_file=gcm_file)

    # 3. Notification & Email Dispatch
    print("\n>>> [Stage 3/4] Dispatching Notification & Review Digest...")
    notif_res = send_notification(manifest, dry_run=dry_run)

    # 4. Approval / Publishing
    if auto_approve:
        print("\n>>> [Stage 4/4] Auto-Approval requested: Promoting to Live Dashboard...")
        publish_res = publish_run(manifest["run_id"])
        print("  ✓ Live publication complete!")
    else:
        print("\n>>> [Stage 4/4] Forecast successfully staged and awaiting human approval.")
        print(f"  To approve: python scripts/approve_and_publish.py --run-id {manifest['run_id']}")

    print("\n" + "=" * 78)
    print(f"  COMPLETED: {cfg.country.title()} {cfg.label} ({year})")
    print(f"  Run ID: {manifest['run_id']}")
    print(f"  Staging Folder: {Path(manifest['target_output_dir']).parent / 'staging' / manifest['run_id']}")
    print("=" * 78)

def main():
    args = parse_args()
    if args.all:
        active_seasons = [
            ("kenya", "short_rains"),
            ("ethiopia", "deyr"),
        ]
        for country, season in active_seasons:
            process_target(country, season, args.year, args.skip_download, args.force_download, args.auto_approve, args.dry_run)
    else:
        process_target(args.country, args.season, args.year, args.skip_download, args.force_download, args.auto_approve, args.dry_run)

if __name__ == "__main__":
    main()
