#!/usr/bin/env python3
"""
inspect_netcdf.py
-----------------
Print a structured summary of one or more NetCDF files:
dimensions, coordinates, data variables (units, shape, range), and
global attributes.

Usage
-----
    # Single file
    python inspect_netcdf.py joined/ecmwf_cal_m03_d01.nc

    # Glob pattern  (quote on Windows to prevent shell expansion)
    python inspect_netcdf.py "joined/ecmwf_*.nc"

    # Multiple explicit files
    python inspect_netcdf.py a.nc b.nc c.nc

    # Skip data stats (faster for large files)
    python inspect_netcdf.py ecmwf_cal_m03_d01.nc --no-stats

    # Show full coordinate arrays instead of just min/max
    python inspect_netcdf.py ecmwf_cal_m03_d01.nc --full-coords

    # Write summary to a text file instead of stdout
    python inspect_netcdf.py "*.nc" --output summary.txt

Requirements
------------
    pip install xarray netCDF4
"""

import argparse
import glob
import os
import sys
from pathlib import Path

import numpy as np
import xarray as xr


# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------

W = 72  # line width

def hr(char="-"):
    return char * W

def section(title: str):
    print(f"\n{hr('=')}")
    print(f"  {title}")
    print(hr("="))

def subsection(title: str):
    print(f"\n  {hr('-')}")
    print(f"  {title}")
    print(f"  {hr('-')}")

def fmt_val(v) -> str:
    """Format a scalar value cleanly."""
    if isinstance(v, float):
        if np.isnan(v):
            return "NaN"
        if abs(v) >= 1e6 or (abs(v) < 1e-3 and v != 0):
            return f"{v:.4e}"
        return f"{v:.4f}"
    return str(v)

def fmt_arr(arr: np.ndarray, full: bool = False) -> str:
    """Summarise a 1-D coordinate array."""
    arr = np.asarray(arr)
    if arr.size == 0:
        return "(empty)"
    if full or arr.size <= 8:
        return str(arr.tolist())
    # Show first 4, last 4
    head = ", ".join(fmt_val(v) for v in arr[:4])
    tail = ", ".join(fmt_val(v) for v in arr[-4:])
    return f"[{head}, ..., {tail}]  ({arr.size} values)"

def attr_str(attrs: dict) -> list[str]:
    lines = []
    for k, v in attrs.items():
        vstr = str(v)
        if len(vstr) > 60:
            vstr = vstr[:57] + "..."
        lines.append(f"    {k:<24} {vstr}")
    return lines


# -----------------------------------------------------------------------------
# Core inspection
# -----------------------------------------------------------------------------

def inspect_file(path: Path, args: argparse.Namespace) -> None:
    section(f"FILE: {path.name}")
    print(f"  Path : {path.resolve()}")
    size_mb = path.stat().st_size / 1024**2
    print(f"  Size : {size_mb:.2f} MB")

    try:
        ds = xr.open_dataset(path, engine="netcdf4")
    except Exception as exc:
        print(f"\n  ERROR: could not open file: {exc}", file=sys.stderr)
        return

    # ── Global attributes ────────────────────────────────────────────────────
    subsection("Global Attributes")
    if ds.attrs:
        for line in attr_str(ds.attrs):
            print(line)
    else:
        print("    (none)")

    # ── Dimensions ───────────────────────────────────────────────────────────
    subsection("Dimensions")
    for name, size in ds.dims.items():
        print(f"    {name:<30} size={size}")

    # ── Coordinates ──────────────────────────────────────────────────────────
    subsection("Coordinates")
    for name, coord in ds.coords.items():
        dtype  = str(coord.dtype)
        shape  = str(coord.shape)
        units  = coord.attrs.get("units", "")
        lname  = coord.attrs.get("long_name", "")
        print(f"    {name:<28} dtype={dtype:<10} shape={shape}")
        if lname:
            print(f"    {'':28} long_name : {lname}")
        if units:
            print(f"    {'':28} units     : {units}")
        if coord.ndim == 1:
            try:
                arr = coord.values
                print(f"    {'':28} values    : {fmt_arr(arr, args.full_coords)}")
            except Exception:
                pass
        elif coord.ndim == 0:
            print(f"    {'':28} value     : {coord.values}")

    # ── Data variables ───────────────────────────────────────────────────────
    subsection("Data Variables")
    col = f"  {'Name':<26} {'Dims':<36} {'dtype':<10} {'Shape'}"
    print(col)
    print(f"  {hr()}")
    for name, var in ds.data_vars.items():
        dims_str  = str(var.dims)
        dtype_str = str(var.dtype)
        shape_str = str(var.shape)
        print(f"  {name:<26} {dims_str:<36} {dtype_str:<10} {shape_str}")

        units  = var.attrs.get("units", "")
        lname  = var.attrs.get("long_name", "")
        sname  = var.attrs.get("standard_name", "")
        fv     = var.attrs.get("_FillValue", var.attrs.get("missing_value", None))

        if lname:  print(f"    {'':4}long_name    : {lname}")
        if sname:  print(f"    {'':4}standard_name: {sname}")
        if units:  print(f"    {'':4}units        : {units}")
        if fv is not None:
            print(f"    {'':4}fill_value   : {fmt_val(float(fv))}")

        # Extra variable attributes (skip ones already printed)
        skip = {"units", "long_name", "standard_name", "_FillValue", "missing_value",
                 "scale_factor", "add_offset"}
        extra = {k: v for k, v in var.attrs.items() if k not in skip}
        for k, v in extra.items():
            print(f"    {'':4}{k:<16}: {v}")

        if args.no_stats:
            continue

        # Compute min / max / NaN count
        try:
            data = var.values.astype(float)
            total = data.size
            n_nan = int(np.sum(np.isnan(data)))
            n_valid = total - n_nan
            if n_valid > 0:
                vmin = float(np.nanmin(data))
                vmax = float(np.nanmax(data))
                vmean = float(np.nanmean(data))
                print(f"    {'':4}min={fmt_val(vmin)}  max={fmt_val(vmax)}  "
                      f"mean={fmt_val(vmean)}  "
                      f"NaN={n_nan}/{total}")
            else:
                print(f"    {'':4}all NaN  ({total} values)")
        except Exception as exc:
            print(f"    {'':4}(stats error: {exc})")

    ds.close()
    print()


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="inspect_netcdf.py",
        description="Inspect NetCDF file structure: dims, coords, variables, stats.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help=(
            "NetCDF file path(s) or glob pattern(s). "
            "Quote patterns on Windows to avoid shell expansion."
        ),
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="Skip min/max/NaN statistics (much faster for large files).",
    )
    parser.add_argument(
        "--full-coords",
        action="store_true",
        help="Print full coordinate arrays instead of head+tail summary.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Write output to this file instead of stdout.",
    )
    return parser.parse_args()


def resolve_paths(raw: list[str]) -> list[Path]:
    """Expand globs and collect unique paths, sorted."""
    seen: set[Path] = set()
    paths: list[Path] = []
    for item in raw:
        expanded = glob.glob(item, recursive=True)
        if expanded:
            for p in sorted(expanded):
                pp = Path(p)
                if pp not in seen:
                    seen.add(pp)
                    paths.append(pp)
        else:
            pp = Path(item)
            if pp not in seen:
                seen.add(pp)
                paths.append(pp)
    return paths


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args.files)

    if not paths:
        sys.exit("ERROR: no files matched the given pattern(s).")

    # Redirect stdout to file if requested
    orig_stdout = sys.stdout
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(out_path, "w", encoding="utf-8")

    try:
        print(f"Inspecting {len(paths)} file(s)")
        print(f"Stats: {'disabled' if args.no_stats else 'enabled'}")

        missing = [p for p in paths if not p.exists()]
        if missing:
            for p in missing:
                print(f"  WARNING: file not found: {p}", file=sys.stderr)

        for path in paths:
            if path.exists():
                inspect_file(path, args)
            else:
                print(f"\n  SKIP (not found): {path}")

        if args.output:
            sys.stdout.close()
            sys.stdout = orig_stdout
            print(f"Summary written to: {args.output}")

    except Exception:
        sys.stdout = orig_stdout
        raise


if __name__ == "__main__":
    main()
