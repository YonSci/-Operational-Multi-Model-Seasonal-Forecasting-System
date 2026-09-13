#!/usr/bin/env python3
"""
join_seasonal_forecasts.py
--------------------------
Concatenate per-year C3S seasonal forecast NetCDF files (produced by
download_seasonal_forecasts_daily_c3s.py) into period-based merged files.

Four output periods:
    cal  -- calibration years  (default 1993-2016)
    val  -- validation years   (default 2017-2024)
    oper -- operational years  (default 2025+)
    all  -- all years combined

Input filename convention:
    {model_key}_{YYYYMM}_d{DD}.nc

Output filename convention:
    {model_key}_{period}_m{MM}_d{DD}.nc

Usage examples
--------------
    # Join all files found in ./seasonal_downloads, write to ./joined
    python join_seasonal_forecasts.py --indir ./seasonal_downloads --outdir ./joined

    # Only write the all-years file (skip individual period files)
    python join_seasonal_forecasts.py --indir ./seasonal_downloads --periods all

    # Single model, March init only, custom boundaries
    python join_seasonal_forecasts.py --indir ./seasonal_downloads \
        --models ecmwf --months 3 \
        --cal-end 2018 --val-start 2019 --val-end 2023 --oper-start 2024

    # See what would be produced without writing anything
    python join_seasonal_forecasts.py --indir ./seasonal_downloads --dry-run

Requirements
------------
    pip install xarray netCDF4
"""

import argparse
import re
import sys
from pathlib import Path

import xarray as xr

# Default period boundaries (match MODEL_REGISTRY in download script)
CAL_START_DEFAULT  = 1993
CAL_END_DEFAULT    = 2016
VAL_START_DEFAULT  = 2017
VAL_END_DEFAULT    = 2024
OPER_START_DEFAULT = 2025

# Filename pattern: {model_key}_{YYYYMM}_d{DD}.nc
FILENAME_RE = re.compile(
    r"^(?P<model>[^_]+)_(?P<year>\d{4})(?P<month>\d{2})_d(?P<day>\d{2})\.nc$"
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def classify_year(
    year: int,
    cal_start: int, cal_end: int,
    val_start: int, val_end: int,
    oper_start: int,
) -> set[str]:
    """Return the set of period labels this year belongs to (always includes 'all')."""
    periods = {"all"}
    if cal_start <= year <= cal_end:
        periods.add("cal")
    elif val_start <= year <= val_end:
        periods.add("val")
    elif year >= oper_start:
        periods.add("oper")
    return periods


def scan_files(
    indir: Path,
    model_filter: list[str] | None,
    month_filter: list[int] | None,
) -> dict[tuple[str, int, int], dict[int, Path]]:
    """
    Walk indir for files matching {model}_{YYYYMM}_d{DD}.nc.

    Returns:
        { (model_key, month, init_day) : { year : Path } }
    """
    groups: dict[tuple[str, int, int], dict[int, Path]] = {}
    n_skipped = 0
    for f in sorted(indir.glob("*.nc")):
        m = FILENAME_RE.match(f.name)
        if not m:
            n_skipped += 1
            continue
        model = m.group("model")
        year  = int(m.group("year"))
        month = int(m.group("month"))
        day   = int(m.group("day"))

        if model_filter and model not in model_filter:
            continue
        if month_filter and month not in month_filter:
            continue

        key = (model, month, day)
        groups.setdefault(key, {})[year] = f

    if n_skipped:
        print(f"  (skipped {n_skipped} file(s) that did not match naming pattern)")
    return groups


# -----------------------------------------------------------------------------
# Core join logic
# -----------------------------------------------------------------------------

def join_group(
    key: tuple[str, int, int],
    year_files: dict[int, Path],
    periods_wanted: list[str],
    outdir: Path,
    args: argparse.Namespace,
) -> tuple[int, int]:
    """
    Join files for one (model, month, init_day) group.
    Returns (n_written, n_skipped) counts.
    """
    model_key, month, init_day = key
    sorted_years = sorted(year_files)

    # Classify each year into its period(s)
    period_years: dict[str, list[int]] = {p: [] for p in ["cal", "val", "oper", "all"]}
    for year in sorted_years:
        for period in classify_year(
            year,
            args.cal_start, args.cal_end,
            args.val_start, args.val_end,
            args.oper_start,
        ):
            period_years[period].append(year)

    n_written = n_skipped = 0

    for period in periods_wanted:
        years = period_years[period]
        if not years:
            print(
                f"  [{model_key}] m{month:02d} d{init_day:02d} | "
                f"{period:4s}: no files in this period -- skipping"
            )
            continue

        year_range = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
        out_name  = f"{model_key}_{period}_m{month:02d}_d{init_day:02d}.nc"
        out_path  = outdir / out_name

        if out_path.exists() and not args.overwrite:
            print(
                f"  [{model_key}] m{month:02d} d{init_day:02d} | "
                f"{period:4s}: {out_name} already exists (use --overwrite)"
            )
            n_skipped += 1
            continue

        print(
            f"  [{model_key}] m{month:02d} d{init_day:02d} | "
            f"{period:4s}: {len(years)} years ({year_range}) -> {out_name}"
        )

        if args.dry_run:
            for y in years:
                print(f"      {year_files[y].name}")
            continue

        datasets: list[xr.Dataset] = []
        for year in years:
            fpath = year_files[year]
            try:
                ds = xr.open_dataset(fpath, engine="netcdf4")
                ds = ds.assign_coords(
                    init_year=year,
                    init_month=month,
                    init_day=init_day,
                )
                ds = ds.expand_dims("init_year")
                datasets.append(ds)
            except Exception as exc:
                print(
                    f"      WARNING: could not open {fpath.name}: {exc}",
                    file=sys.stderr,
                )

        if not datasets:
            print(f"      No valid datasets -- skipping {out_name}", file=sys.stderr)
            n_skipped += 1
            continue

        merged = xr.concat(datasets, dim="init_year")
        merged.attrs.update({
            "model":      model_key,
            "period":     period,
            "years":      year_range,
            "cal_years":  f"{args.cal_start}-{args.cal_end}",
            "val_years":  f"{args.val_start}-{args.val_end}",
            "oper_years": f"{args.oper_start}+",
            "created_by": "join_seasonal_forecasts.py",
        })

        outdir.mkdir(parents=True, exist_ok=True)
        merged.to_netcdf(out_path, mode="w")
        print(f"      saved -> {out_path}")
        n_written += 1

        for ds in datasets:
            ds.close()

    return n_written, n_skipped


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="join_seasonal_forecasts.py",
        description=(
            "Concatenate per-year C3S seasonal forecast NetCDF files into "
            "period-based merged files: cal / val / oper / all."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # I/O
    parser.add_argument(
        "--indir",
        type=str,
        required=True,
        help="Directory containing per-year NetCDF files ({model}_{YYYYMM}_d{DD}.nc).",
    )
    parser.add_argument(
        "--outdir",
        type=str,
        default=None,
        help="Output directory for joined files. Defaults to --indir.",
    )

    # Filtering
    parser.add_argument(
        "--periods",
        nargs="+",
        default=["cal", "val", "oper", "all"],
        choices=["cal", "val", "oper", "all"],
        metavar="PERIOD",
        help="Which period files to produce. Choices: cal val oper all. Default: all four.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        metavar="MODEL",
        help="Restrict to specific model key(s). Default: all found in --indir.",
    )
    parser.add_argument(
        "--months",
        nargs="+",
        type=int,
        default=None,
        metavar="MONTH",
        help="Restrict to specific init month(s) 1-12. Default: all found.",
    )

    # Year boundaries
    yg = parser.add_argument_group("Year boundaries")
    yg.add_argument(
        "--cal-start", type=int, default=CAL_START_DEFAULT, metavar="YEAR",
        help="First calibration year (inclusive).",
    )
    yg.add_argument(
        "--cal-end", type=int, default=CAL_END_DEFAULT, metavar="YEAR",
        help="Last calibration year (inclusive).",
    )
    yg.add_argument(
        "--val-start", type=int, default=VAL_START_DEFAULT, metavar="YEAR",
        help="First validation year (inclusive).",
    )
    yg.add_argument(
        "--val-end", type=int, default=VAL_END_DEFAULT, metavar="YEAR",
        help="Last validation year (inclusive).",
    )
    yg.add_argument(
        "--oper-start", type=int, default=OPER_START_DEFAULT, metavar="YEAR",
        help="First operational year (inclusive, open-ended).",
    )

    # Behaviour
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be joined without writing any files.",
    )

    return parser.parse_args()


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    indir  = Path(args.indir)
    outdir = Path(args.outdir) if args.outdir else indir

    if not indir.exists():
        sys.exit(f"ERROR: --indir '{indir}' does not exist.")
    if args.cal_end >= args.val_start:
        sys.exit(f"ERROR: --cal-end ({args.cal_end}) must be < --val-start ({args.val_start}).")
    if args.val_end >= args.oper_start:
        sys.exit(f"ERROR: --val-end ({args.val_end}) must be < --oper-start ({args.oper_start}).")

    W = 64
    print("=" * W)
    print("  Seasonal Forecast Period Joiner")
    print("=" * W)
    print(f"  Input dir    : {indir}")
    print(f"  Output dir   : {outdir}")
    print(f"  Cal period   : {args.cal_start}-{args.cal_end}")
    print(f"  Val period   : {args.val_start}-{args.val_end}")
    print(f"  Oper period  : {args.oper_start}+")
    print(f"  Periods      : {', '.join(args.periods)}")
    if args.models:
        print(f"  Models       : {', '.join(args.models)}")
    if args.months:
        print(f"  Months       : {', '.join(str(m) for m in args.months)}")
    if args.dry_run:
        print("\n  *** DRY-RUN -- no files will be written ***")
    print("=" * W)

    groups = scan_files(indir, args.models, args.months)

    if not groups:
        sys.exit("No matching files found in --indir. Check the naming convention.")

    print(f"\nFound {len(groups)} group(s) (model x month x init_day combinations)\n")

    total_written = total_skipped = 0
    for key in sorted(groups):
        nw, ns = join_group(key, groups[key], args.periods, outdir, args)
        total_written += nw
        total_skipped += ns

    print(f"\n{'─' * W}")
    if args.dry_run:
        print("  DRY-RUN complete -- no files written.")
    else:
        print(f"  Written  : {total_written} file(s)")
        print(f"  Skipped  : {total_skipped} file(s)")
    print("\nDone.")


if __name__ == "__main__":
    main()
