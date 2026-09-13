#!/usr/bin/env python3
"""Merge yearly CHIRPS clipped NetCDF files into a single file.

Default behavior targets files like:
  data/chirps_pr_et/chirps-v2.0.1993.days_p25_clip.nc

Examples
--------
# Merge all clipped p25 files in the default ET folder
python scripts/merge_chirps_clips.py

# Merge a year subset
python scripts/merge_chirps_clips.py --start-year 2017 --end-year 2024

# Custom folder and output path
python scripts/merge_chirps_clips.py \
  --input-dir data/chirps_pr_ke \
  --output data/chirps_pr_ke/chirps-v2.0.1993-2025.days_p25_clip_merged.nc
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import xarray as xr


YEAR_RE = re.compile(r"chirps-v2\.0\.(\d{4})\.days_.*_clip\.nc$")


def extract_year(path: Path) -> int:
    """Extract year from standard CHIRPS yearly clipped file name."""
    match = YEAR_RE.search(path.name)
    if not match:
        raise ValueError(f"Cannot extract year from filename: {path.name}")
    return int(match.group(1))


def standardize_for_merge(ds: xr.Dataset) -> xr.Dataset:
    """Normalize coordinate names and latitude orientation before merge."""
    rename_map: dict[str, str] = {}
    if "latitude" in ds.dims:
        rename_map["latitude"] = "lat"
    if "longitude" in ds.dims:
        rename_map["longitude"] = "lon"
    if rename_map:
        ds = ds.rename(rename_map)

    if "lat" in ds.coords and ds["lat"].size > 1:
        if ds["lat"][0] > ds["lat"][-1]:
            ds = ds.reindex(lat=list(reversed(ds["lat"].values)))

    return ds


def discover_files(input_dir: Path, pattern: str) -> list[Path]:
    files = sorted(input_dir.glob(pattern))
    return [p for p in files if p.is_file()]


def build_default_output(input_dir: Path, files: list[Path]) -> Path:
    years = sorted(extract_year(p) for p in files)
    start_year, end_year = years[0], years[-1]
    out_name = f"chirps-v2.0.{start_year}-{end_year}.days_p25_clip_merged.nc"
    return input_dir / out_name


def merge_files(nc_paths: list[Path], output_path: Path) -> None:
    if not nc_paths:
        raise ValueError("No input files found to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    ds = xr.open_mfdataset(
        [str(p) for p in nc_paths],
        combine="by_coords",
        preprocess=standardize_for_merge,
        parallel=False,
    )

    data_vars = list(ds.data_vars)
    if not data_vars:
        raise ValueError("No data variables found in input datasets.")

    encoding = {name: {"zlib": True, "complevel": 3} for name in data_vars}
    ds.to_netcdf(output_path, encoding=encoding)
    ds.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge CHIRPS yearly clipped NetCDF files into one NetCDF."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/chirps_pr_et"),
        help="Folder containing yearly clipped CHIRPS NetCDF files.",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="chirps-v2.0.*.days_p25_clip.nc",
        help="Glob pattern used to discover files in --input-dir.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Optional inclusive lower year bound.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Optional inclusive upper year bound.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output merged NetCDF path. If omitted, a default file is created in --input-dir.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovered files and exit without merging.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input_dir.exists():
        print(f"[ERR] Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    files = discover_files(args.input_dir, args.pattern)
    if not files:
        print(f"[ERR] No files matched pattern '{args.pattern}' in {args.input_dir}")
        sys.exit(1)

    rows: list[tuple[int, Path]] = []
    for p in files:
        try:
            year = extract_year(p)
        except ValueError:
            continue
        rows.append((year, p))

    if not rows:
        print("[ERR] No CHIRPS yearly clipped files found after year parsing.")
        sys.exit(1)

    rows.sort(key=lambda item: item[0])

    if args.start_year is not None:
        rows = [row for row in rows if row[0] >= args.start_year]
    if args.end_year is not None:
        rows = [row for row in rows if row[0] <= args.end_year]

    if not rows:
        print("[ERR] No files left after applying year filters.")
        sys.exit(1)

    ordered_files = [p for _, p in rows]

    output_path = args.output if args.output else build_default_output(args.input_dir, ordered_files)

    print(f"[info] Input directory: {args.input_dir}")
    print(f"[info] Files to merge: {len(ordered_files)}")
    print(f"[info] Year range: {rows[0][0]}-{rows[-1][0]}")
    print(f"[info] Output: {output_path}")

    if args.dry_run:
        for _, p in rows:
            print(f"  - {p.name}")
        print("[ok] Dry run complete.")
        return

    merge_files(ordered_files, output_path)
    print("[ok] Merge complete.")


if __name__ == "__main__":
    main()
