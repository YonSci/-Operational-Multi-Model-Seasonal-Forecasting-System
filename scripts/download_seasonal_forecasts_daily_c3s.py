#!/usr/bin/env python3
"""
download_seasonal_forecasts.py
──────────────────────────────
Download seasonal forecast data from the Copernicus Climate Data Store (CDS)
dataset  "seasonal-original-single-levels"  for multiple C3S models.

New in this version
───────────────────
  --variables      Choose one or more CDS variables to download
  --years          One or more years  OR  --year-start / --year-end  range
  --months         One or more initialisation months
  --system         Per-model system-number override  e.g.  ecmwf=5 ukmo=601
  --init-day       Initialisation day of month (default 1)
  --leadtime-days  Cap maximum lead time in days (overrides per-model default)

Supported models
────────────────
  dwd           GCFS2.2 (DWD)          (system 22,  max 180d, 30 hind / 50 oper mbr)
  eccc          GEM5.2-NEMO (ECCC)     (system 5,   max 214d, 20 hind / 20 oper mbr)
  cmcc          CMCC-SPS4 (CMCC)       (system 4,   max 184d, 30 hind / 50 oper mbr)
  meteo_france  System9 (Meteo-France) (system 9,   max 210d, 31 hind / 51 oper mbr)
  ecmwf         SEAS5 (ECMWF)          (system 51,  max 215d, 25 hind / 51 oper mbr)
  jma           MRI-CPS4 (JMA)         (system 4,   max 215d, 10 hind / 25 oper mbr)
  ukmo          GloSea6 (UK Met Office) (system 604, max 215d,  7 hind /  2 oper mbr)
  ncep          CFSv2 (NCEP)           (system 2,   max 215d,  4 hind / 28 oper mbr)
  bom           ACCESS-S2 (BOM)        (system 2,   max 217d,  3 hind / 11 oper mbr)

Usage examples
──────────────
  # All models (including BOM), MAM 2024, East-Africa bbox, merge output
  python download_seasonal_forecasts.py \
      --years 2024 --months 3 4 5 \
      --north 15 --west 33 --south 3 --east 48 \
      --outdir ./seasonal_data --merge

  # Year range 2020-2024, January only, temperature only
  python download_seasonal_forecasts.py \
      --year-start 2020 --year-end 2024 --months 1 \
      --variables 2m_temperature \
      --outdir ./t2m_data --merge

  # Override ECMWF to SEAS5 system 5, cap lead-time at 90 days
  python download_seasonal_forecasts.py \
      --years 2024 --months 2 \
      --models ecmwf --system ecmwf=5 --leadtime-days 90

  # Dry-run to inspect requests without downloading
  python download_seasonal_forecasts.py \
      --years 2024 --months 3 --dry-run

  # List available variables / models
  python download_seasonal_forecasts.py --list-variables
  python download_seasonal_forecasts.py --list-models

Requirements
────────────
  pip install cdsapi xarray netCDF4
  A valid ~/.cdsapirc (or CDSAPI_URL + CDSAPI_KEY env vars) is required.
"""

import argparse
import json
import sys
from pathlib import Path

import cdsapi
import xarray as xr


# ──────────────────────────────────────────────────────────────────────────────
# Static registries
# ──────────────────────────────────────────────────────────────────────────────

MODEL_REGISTRY: dict[str, dict] = {
    "dwd": {
        "label": "GCFS2.2 (DWD)", "short_name": "edzw",
        "originating_centre": "dwd", "system": "22",
        "model_id": "GCFS2.2", "native_res_deg": 1.0,
        "members_hindcast": 30, "members_oper": 50,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 180,
    },
    "eccc": {
        "label": "GEM5.2-NEMO (ECCC)", "short_name": "cwao",
        "originating_centre": "eccc", "system": "5",
        "model_id": "GEM5.2-NEMO-v20240611", "native_res_deg": 1.0,
        "members_hindcast": 20, "members_oper": 20,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 214,
    },
    "cmcc": {
        "label": "CMCC-SPS4 (CMCC)", "short_name": "cmcc",
        "originating_centre": "cmcc", "system": "4",
        "model_id": "CMCC-CM3-v20231101", "native_res_deg": 0.5,
        "members_hindcast": 30, "members_oper": 50,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 184,
    },
    "meteo_france": {
        "label": "System9 (Meteo-France)", "short_name": "lfpw",
        "originating_centre": "meteo_france", "system": "9",
        "model_id": "System9-v20250101", "native_res_deg": 0.5,
        "members_hindcast": 31, "members_oper": 51,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 210,
    },
    "ecmwf": {
        "label": "SEAS5 (ECMWF)", "short_name": "ecmf",
        "originating_centre": "ecmwf", "system": "51",
        "model_id": "SEAS5-v20171101", "native_res_deg": 0.4,
        "members_hindcast": 25, "members_oper": 51,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 215,
    },
    "jma": {
        "label": "MRI-CPS4 (JMA)", "short_name": "rjtd",
        "originating_centre": "jma", "system": "4",
        "model_id": "cps4-v20260101", "native_res_deg": 0.5,
        "members_hindcast": 10, "members_oper": 25,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 215,
    },
    "ukmo": {
        "label": "GloSea6 (UK Met Office)", "short_name": "egrr",
        "originating_centre": "ukmo", "system": "610",
        "model_id": "HadGEM3-GC3.2-v20200929", "native_res_deg": 0.6,
        "members_hindcast": 7, "members_oper": 2,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 215,
    },
    "ncep": {
        "label": "CFSv2 (NCEP)", "short_name": "kwbc",
        "originating_centre": "ncep", "system": "2",
        "model_id": "CFSv2-v20110310", "native_res_deg": 1.0,
        "members_hindcast": 4, "members_oper": 28,
        "hindcast_years": "1993\u20132016",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 215,
        "batch_years": True,  # CDS requires all years in one request for CFSv2
    },
    "bom": {
        "label": "ACCESS-S2 (BOM)", "short_name": "ammc",
        "originating_centre": "bom", "system": "2",
        "model_id": "ACCESS-S2-v20210821", "native_res_deg": 0.6,
        "members_hindcast": 3, "members_oper": 11,
        "hindcast_years": "1981\u20132020",
        "cal_years": "1993\u20132016", "val_years": "2017\u20132024",
        "max_lead_days": 217,
    },
}
# All variables available
# The key is the CLI name; the value is the exact CDS API string.
VARIABLE_REGISTRY: dict[str, str] = {
    "2m_temperature":                                  "2m_temperature",
    "total_precipitation":                             "total_precipitation",
    "precipitation_flux":                              "precipitation_flux",
    "10m_u_component_of_wind":                         "10m_u_component_of_wind",
    "10m_v_component_of_wind":                         "10m_v_component_of_wind",
    "mean_sea_level_pressure":                         "mean_sea_level_pressure",
    "sea_surface_temperature":                         "sea_surface_temperature",
    "surface_solar_radiation_downwards":               "surface_solar_radiation_downwards",
    "total_cloud_cover":                               "total_cloud_cover",
    "evaporation":                                     "evaporation",
    "runoff":                                          "runoff",
    "snow_depth":                                      "snow_depth",
    "soil_temperature_level_1":                        "soil_temperature_level_1",
    "surface_latent_heat_flux":                        "surface_latent_heat_flux",
    "surface_sensible_heat_flux":                      "surface_sensible_heat_flux",
    "surface_net_solar_radiation":                     "surface_net_solar_radiation",
    "surface_net_thermal_radiation":                   "surface_net_thermal_radiation",
    "maximum_2m_temperature_in_the_last_24_hours":     "maximum_2m_temperature_in_the_last_24_hours",
    "minimum_2m_temperature_in_the_last_24_hours":     "minimum_2m_temperature_in_the_last_24_hours",
}

DEFAULT_VARIABLES = ["2m_temperature", "total_precipitation"]
DATASET = "seasonal-original-single-levels"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def leadtime_hours(max_days: int, step_hours: int = 24) -> list[str]:
    """Return lead-time strings from step_hours up to max_days*24, at step_hours intervals."""
    return [str(h) for h in range(step_hours, max_days * 24 + 1, step_hours)]


def parse_system_overrides(raw: list[str] | None) -> dict[str, str]:
    """
    Parse --system values of the form  MODEL=NUMBER  into a dict.
    e.g. ["ecmwf=5", "ukmo=601"]  ->  {"ecmwf": "5", "ukmo": "601"}
    """
    overrides: dict[str, str] = {}
    if not raw:
        return overrides
    for item in raw:
        if "=" not in item:
            sys.exit(
                f"ERROR: --system value '{item}' must be MODEL=NUMBER "
                f"(e.g. ecmwf=5).  Available models: {', '.join(MODEL_REGISTRY)}"
            )
        model_key, system_num = item.split("=", 1)
        model_key = model_key.strip().lower()
        if model_key not in MODEL_REGISTRY:
            sys.exit(
                f"ERROR: unknown model key '{model_key}' in --system. "
                f"Available: {', '.join(MODEL_REGISTRY)}"
            )
        overrides[model_key] = system_num.strip()
    return overrides


def resolve_years(args: argparse.Namespace) -> list[int]:
    """Return the resolved list of years."""
    if args.years:
        return sorted(set(args.years))
    if args.year_start is None:
        sys.exit("ERROR: --year-start is required when using the range form.")
    if args.year_end is None:
        sys.exit("ERROR: --year-end is required when using --year-start.")
    if args.year_end < args.year_start:
        sys.exit("ERROR: --year-end must be >= --year-start.")
    return list(range(args.year_start, args.year_end + 1))


def resolve_variables(requested: list[str]) -> list[str]:
    """Validate and resolve requested variable names against the registry."""
    resolved, unknown = [], []
    for v in requested:
        if v in VARIABLE_REGISTRY:
            resolved.append(VARIABLE_REGISTRY[v])
        else:
            unknown.append(v)
    if unknown:
        sys.exit(
            f"ERROR: unknown variable(s): {', '.join(unknown)}\n"
            "Run --list-variables to see all available names."
        )
    return resolved


def apply_system_overrides(
    models: list[str],
    overrides: dict[str, str],
) -> dict[str, dict]:
    """
    Return shallow copies of MODEL_REGISTRY entries for the requested models,
    with system numbers replaced by any user-supplied overrides.
    """
    cfgs: dict[str, dict] = {}
    for key in models:
        cfg = dict(MODEL_REGISTRY[key])
        if key in overrides:
            original = cfg["system"]
            cfg["system"] = overrides[key]
            print(f"  [OVERRIDE] {key}: system {original} → {overrides[key]}")
        cfgs[key] = cfg
    return cfgs


def build_request(
    cfg: dict,
    year: int,
    month: int,
    init_day: int,
    area: list[float],
    variables: list[str],
    leadtime_days: int,
) -> dict:
    """Construct the CDS API request dict for one model/date combination."""
    step_hours = cfg.get("time_step_hours", 24)
    return {
        "originating_centre": cfg["originating_centre"],
        "system":             cfg["system"],
        "variable":           variables,
        "year":               str(year),
        "month":              f"{month:02d}",
        "day":                f"{init_day:02d}",
        "leadtime_hour":      leadtime_hours(leadtime_days, step_hours),
        "area":               area,          # CDS: [N, W, S, E]
        "format":             "netcdf",
    }


def output_filename(
    model_key: str,
    year: int,
    month: int,
    init_day: int,
    outdir: Path,
) -> Path:
    return outdir / f"{model_key}_{year}{month:02d}_d{init_day:02d}.nc"


def download_one(
    model_key: str,
    cfg: dict,
    year: int,
    month: int,
    init_day: int,
    area: list[float],
    variables: list[str],
    leadtime_days: int,
    outdir: Path,
    dry_run: bool = False,
) -> Path | None:
    """Download a single model/year/month combination."""
    outdir.mkdir(parents=True, exist_ok=True)
    out_file = output_filename(model_key, year, month, init_day, outdir)

    if out_file.exists():
        print(f"      [SKIP] already exists → {out_file.name}")
        return out_file

    request = build_request(cfg, year, month, init_day, area, variables, leadtime_days)

    if dry_run:
        print(f"      [DRY-RUN] target : {out_file.name}")
        print(f"      [DRY-RUN] request:\n{json.dumps(request, indent=8)}")
        return None

    print("      Submitting CDS request …", flush=True)
    client = cdsapi.Client(quiet=True)
    try:
        client.retrieve(DATASET, request).download(str(out_file))
        print(f"      ✓ saved → {out_file.name}")
        return out_file
    except Exception as exc:
        print(f"      ✗ ERROR: {exc}", file=sys.stderr)
        return None


def download_batch_ncep(
    model_key: str,
    cfg: dict,
    years: list[int],
    month: int,
    init_day: int,
    area: list[float],
    variables: list[str],
    leadtime_days: int,
    outdir: Path,
    dry_run: bool = False,
) -> list[Path]:
    """
    Download all years for NCEP CFSv2 in a single batched CDS request
    (CDS requires years as a list for this model), then split the returned
    multi-year NetCDF into individual per-year files so downstream scripts
    see the same {model}_{YYYYMM}_d{DD}.nc convention as all other models.
    """
    outdir.mkdir(parents=True, exist_ok=True)

    # Separate already-downloaded years from ones still needed
    years_needed = [y for y in years
                    if not output_filename(model_key, y, month, init_day, outdir).exists()]
    results: list[Path] = []
    for y in years:
        f = output_filename(model_key, y, month, init_day, outdir)
        if f.exists():
            print(f"      [SKIP] already exists -> {f.name}")
            results.append(f)

    if not years_needed:
        return results

    request = {
        "originating_centre": cfg["originating_centre"],
        "system":             cfg["system"],
        "variable":           variables,
        "year":               [str(y) for y in sorted(years_needed)],
        "month":              f"{month:02d}",
        "day":                f"{init_day:02d}",
        "leadtime_hour":      leadtime_hours(leadtime_days),  # 24-hourly
        "area":               area,
        "format":             "netcdf",
    }

    if dry_run:
        print(
            f"      [DRY-RUN] batch {len(years_needed)} years: "
            f"{years_needed[0]}-{years_needed[-1]}"
        )
        print(f"      [DRY-RUN] request:\n{json.dumps(request, indent=8)}")
        return results

    tmp_file = outdir / f"_{model_key}_tmp_{month:02d}_d{init_day:02d}.nc"
    print(
        f"      Submitting CDS batch request for {len(years_needed)} years "
        f"({years_needed[0]}-{years_needed[-1]}) ...",
        flush=True,
    )
    client = cdsapi.Client(quiet=True)
    try:
        client.retrieve(DATASET, request).download(str(tmp_file))
    except Exception as exc:
        print(f"      ERROR: {exc}", file=sys.stderr)
        if tmp_file.exists():
            tmp_file.unlink()
        return results

    # Split the multi-year file into per-year files.
    # CFSv2 has 4 sub-daily init times per day (00/06/12/18 UTC), so
    # forecast_reference_time holds 4 entries per year. Group them by
    # calendar year and stack as a 'member' dimension in one file per year.
    try:
        import pandas as pd
        import numpy as np

        ds = xr.open_dataset(tmp_file, engine="netcdf4")
        frt = "forecast_reference_time"

        if frt not in ds.sizes:
            # Single entry returned — rename tmp to the one year needed
            yr = years_needed[0]
            out_file = output_filename(model_key, yr, month, init_day, outdir)
            ds.close()
            tmp_file.rename(out_file)
            print(f"      saved -> {out_file.name}  (1 member)")
            results.append(out_file)
        else:
            frt_times = pd.DatetimeIndex(ds[frt].values)
            unique_years = sorted(set(frt_times.year))

            for yr in unique_years:
                indices = list(np.where(frt_times.year == yr)[0])
                if len(indices) == 1:
                    ds_yr = ds.isel({frt: indices[0]})
                else:
                    # Stack multiple init-times within the same year as members
                    ds_yr = xr.concat(
                        [ds.isel({frt: i}) for i in indices],
                        dim="member",
                    ).assign_coords(member=list(range(len(indices))))

                out_file = output_filename(model_key, yr, month, init_day, outdir)
                ds_yr.to_netcdf(out_file)
                print(f"      saved -> {out_file.name}  ({len(indices)} member(s))")
                results.append(out_file)

            ds.close()
            tmp_file.unlink(missing_ok=True)
    except Exception as exc:
        print(f"      ERROR splitting batch file: {exc}", file=sys.stderr)
        print(f"      Temp file kept for inspection: {tmp_file}", file=sys.stderr)

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Merge
# ──────────────────────────────────────────────────────────────────────────────

def merge_netcdfs(files: list[Path], outpath: Path) -> None:
    """
    Open each per-model NetCDF, attach a 'model' coordinate, concatenate along
    a new 'model' dimension, and save as a single NetCDF.
    """
    print(f"\n{'─'*64}")
    print(f"Merging {len(files)} file(s) → {outpath.name}")

    datasets: list[xr.Dataset] = []
    for f in files:
        print(f"  opening {f.name} …", end=" ", flush=True)
        try:
            ds = xr.open_dataset(f, engine="netcdf4")
            # Derive traceability coordinates from the filename pattern:
            # {model_key}_{YYYYMM}_d{DD}.nc
            parts = f.stem.split("_")
            model_key = parts[0]
            label = MODEL_REGISTRY.get(model_key, {}).get("label", model_key)
            if len(parts) >= 2:
                ym = parts[1]
                ds = ds.assign_coords(
                    init_year=int(ym[:4]),
                    init_month=int(ym[4:6]),
                )
            if len(parts) >= 3:
                ds = ds.assign_coords(init_day=int(parts[2].lstrip("d")))
            ds = ds.expand_dims(dim="model").assign_coords(model=[label])
            datasets.append(ds)
            print("OK")
        except Exception as exc:
            print(f"FAILED ({exc})", file=sys.stderr)

    if not datasets:
        print("  No valid datasets to merge — skipping.", file=sys.stderr)
        return

    merged = xr.concat(datasets, dim="model")
    merged.attrs.update({
        "models":     ", ".join(ds.model.values[0] for ds in datasets),
        "source":     f"Copernicus CDS — {DATASET}",
        "created_by": "download_seasonal_forecasts.py",
    })

    outpath.parent.mkdir(parents=True, exist_ok=True)
    merged.to_netcdf(outpath, mode="w")
    print(f"  ✓ merged NetCDF saved → {outpath}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="download_seasonal_forecasts.py",
        description=(
            "Download C3S seasonal forecast data for multiple models, years, "
            "and months from the CDS 'seasonal-original-single-levels' dataset."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Run with --list-variables to see all available CDS variable names.\n"
            "Run with --list-models   to see model keys, systems, and lead limits."
        ),
    )

    # ── Models ────────────────────────────────────────────────────────────────
    mg = parser.add_argument_group("Model selection")
    mg.add_argument(
        "--models",
        nargs="+",
        default=list(MODEL_REGISTRY.keys()),
        choices=list(MODEL_REGISTRY.keys()),
        metavar="MODEL",
        help=(
            "Model key(s) to download (space-separated). "
            f"Choices: {', '.join(MODEL_REGISTRY.keys())}. Default: all."
        ),
    )
    mg.add_argument(
        "--system",
        nargs="+",
        metavar="MODEL=NUMBER",
        default=None,
        help=(
            "Override the CDS system number for one or more models. "
            "Format: MODEL=NUMBER  (e.g. --system ecmwf=5 ukmo=601). "
            "Unspecified models keep their registry default."
        ),
    )

    # ── Variables ─────────────────────────────────────────────────────────────
    vg = parser.add_argument_group("Variables")
    vg.add_argument(
        "--variables",
        nargs="+",
        default=DEFAULT_VARIABLES,
        metavar="VAR",
        help=(
            "CDS variable name(s) to request. "
            f"Default: {' '.join(DEFAULT_VARIABLES)}. "
            "Run --list-variables for all available names."
        ),
    )

    # ── Time ─────────────────────────────────────────────────────────────────
    tg = parser.add_argument_group(
        "Time  (use --years OR --year-start/--year-end, not both)"
    )
    year_mx = tg.add_mutually_exclusive_group(required=True)
    year_mx.add_argument(
        "--years",
        nargs="+",
        type=int,
        metavar="YEAR",
        help="Explicit list of initialisation years (e.g. --years 2022 2023 2024 2026). Use 2026 for the operational forecast.",
    )
    year_mx.add_argument(
        "--year-start",
        type=int,
        metavar="YEAR",
        help="Start of an inclusive year range (requires --year-end). Hindcast: 1993, Validation: 2017, Operational: 2025 or 2026.",
    )
    tg.add_argument(
        "--year-end",
        type=int,
        metavar="YEAR",
        help="End of inclusive year range (used with --year-start).",
    )
    tg.add_argument(
        "--months",
        nargs="+",
        type=int,
        default=[3],
        choices=range(1, 13),
        metavar="MONTH",
        help="Initialisation month(s) 1-12 (e.g. --months 3 4 5 for MAM).",
    )
    tg.add_argument(
        "--init-day",
        type=int,
        default=1,
        metavar="DAY",
        help=(
            "Day-of-month for forecast initialisation (1–28). "
            "Most C3S models initialise on the 1st."
        ),
    )

    # ── Lead-time ─────────────────────────────────────────────────────────────
    lg = parser.add_argument_group("Lead-time")
    lg.add_argument(
        "--leadtime-days",
        type=int,
        default=None,
        metavar="DAYS",
        help=(
            "Cap the maximum lead time in days for all requested models. "
            "If omitted, each model uses its own registry maximum."
        ),
    )

    # ── Spatial bbox ──────────────────────────────────────────────────────────
    bg = parser.add_argument_group("Bounding box (degrees) [default = East Africa]")
    bg.add_argument("--north", type=float, default=15.0, help="North latitude")
    bg.add_argument("--west",  type=float, default=33.0, help="West longitude")
    bg.add_argument("--south", type=float, default=3.0,  help="South latitude")
    bg.add_argument("--east",  type=float, default=48.0, help="East longitude")

    # ── Output ────────────────────────────────────────────────────────────────
    og = parser.add_argument_group("Output")
    og.add_argument(
        "--outdir",
        type=str,
        default="./seasonal_downloads",
        help="Root directory where per-model NetCDF files are saved.",
    )
    og.add_argument(
        "--merge",
        action="store_true",
        help="Merge all downloaded files into one NetCDF after all downloads complete.",
    )
    og.add_argument(
        "--merge-output",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Path for the merged output file. "
            "Default: <outdir>/merged_<year_tag>_<month_tag>_d<DD>.nc"
        ),
    )

    # ── Misc ──────────────────────────────────────────────────────────────────
    xg = parser.add_argument_group("Misc")
    xg.add_argument(
        "--dry-run",
        action="store_true",
        help="Print CDS requests without downloading anything.",
    )
    xg.add_argument(
        "--list-models",
        action="store_true",
        help="Print model registry (keys, systems, lead limits) and exit.",
    )
    xg.add_argument(
        "--list-variables",
        action="store_true",
        help="Print all known CDS variable names and exit.",
    )

    return parser.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # ── Info-only flags ───────────────────────────────────────────────────────
    if args.list_models:
        hdr = f"  {'Key':<14}  {'Label':<28}  {'Centre':<16}  {'Sys':>5}  {'MaxLead':>8}  {'Hindcast':>10}  {'Oper':>7}"
        print("Available model keys  (CAL: 1993-2016 | VAL: 2017-2024 | OPER: 2025-2026)")
        print(hdr)
        print("  " + "-"*(len(hdr)-2))
        for key, cfg in MODEL_REGISTRY.items():
            print(
                f"  {key:<14}  {cfg['label']:<28}  "
                f"{cfg['originating_centre']:<16}  "
                f"{cfg['system']:>5}  "
                f"{str(cfg['max_lead_days'])+' d':>8}  "
                f"{str(cfg['members_hindcast'])+' mbr':>10}  "
                f"{str(cfg['members_oper'])+' mbr':>7}"
            )
        return

    if args.list_variables:
        print("Available --variables values:")
        for v in VARIABLE_REGISTRY:
            tag = "  ← default" if v in DEFAULT_VARIABLES else ""
            print(f"  {v}{tag}")
        return

    # ── Resolve all inputs ────────────────────────────────────────────────────
    years    = resolve_years(args)
    months   = sorted(set(args.months))
    variables = resolve_variables(args.variables)
    system_overrides = parse_system_overrides(args.system)
    model_cfgs = apply_system_overrides(args.models, system_overrides)

    if not 1 <= args.init_day <= 28:
        sys.exit("ERROR: --init-day must be between 1 and 28.")
    if args.leadtime_days is not None and args.leadtime_days < 1:
        sys.exit("ERROR: --leadtime-days must be >= 1.")
    if args.north <= args.south:
        sys.exit("ERROR: --north must be greater than --south.")
    if args.east <= args.west:
        sys.exit("ERROR: --east must be greater than --west.")

    area   = [args.north, args.west, args.south, args.east]
    outdir = Path(args.outdir)

    year_tag  = str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"
    month_tag = "-".join(f"{m:02d}" for m in months)
    total     = len(years) * len(months) * len(args.models)

    # ── Banner ────────────────────────────────────────────────────────────────
    W = 64
    print("=" * W)
    print("  C3S Seasonal Forecast Downloader")
    print("=" * W)
    print(f"  Dataset      : {DATASET}")
    def _yr_tag(y): return 'CAL' if y <= 2016 else ('VAL' if y <= 2024 else 'OPER')
    year_notes = ', '.join(f'{y}({_yr_tag(y)})' for y in years)
    print(f"  Years        : {year_notes}")
    print(f"  Months       : {', '.join(str(m) for m in months)}")
    print(f"  Init day     : {args.init_day}")
    print(f"  Variables    : {', '.join(args.variables)}")
    print(f"  Models       : {', '.join(args.models)}")
    lead_note = (
        f"{args.leadtime_days} days (user cap)"
        if args.leadtime_days
        else "per-model registry default"
    )
    print(f"  Lead-time    : {lead_note}")
    print(f"  BBox (N/W/S/E): {args.north} / {args.west} / {args.south} / {args.east}")
    print(f"  Out dir      : {outdir}")
    print(f"  Total files  : {total}  ({len(years)}y × {len(months)}mo × {len(args.models)} models)")
    if args.dry_run:
        print()
        print("  *** DRY-RUN — no files will be downloaded ***")
    print("=" * W)

    # ── Download loop ─────────────────────────────────────────────────────────
    downloaded: list[Path] = []
    failed: list[tuple[str, int, int]] = []

    batch_models   = [mk for mk in args.models if model_cfgs[mk].get("batch_years")]
    regular_models = [mk for mk in args.models if not model_cfgs[mk].get("batch_years")]

    # Batch models (e.g. NCEP): one CDS request per (month, init_day) with ALL years
    for month in months:
        for model_key in batch_models:
            cfg = model_cfgs[model_key]
            eff_lead = (
                min(args.leadtime_days, cfg["max_lead_days"])
                if args.leadtime_days
                else cfg["max_lead_days"]
            )
            print(
                f"\n-- {model_key} batch  month={month:02d}  init_day={args.init_day:02d}"
                f"  years={years[0]}-{years[-1]}  lead={eff_lead}d --"
            )
            results = download_batch_ncep(
                model_key=model_key,
                cfg=cfg,
                years=years,
                month=month,
                init_day=args.init_day,
                area=area,
                variables=variables,
                leadtime_days=eff_lead,
                outdir=outdir,
                dry_run=args.dry_run,
            )
            downloaded.extend(results)
            # Only flag years that were actually returned by CDS but have no
            # output file (missing = download or split error). Years absent
            # from the CDS response (e.g. hindcast not available) are not failures.
            if not args.dry_run:
                years_saved = {
                    int(p.stem.split("_")[1][:4])
                    for p in results if p.exists()
                }
                years_returned = years_saved  # proxy: years CDS gave us
                for y in years_returned:
                    if not output_filename(model_key, y, month, args.init_day, outdir).exists():
                        failed.append((model_key, y, month))

    # Regular models: one CDS request per (year, month)
    for year in years:
        for month in months:
            if not regular_models:
                continue
            print(f"\n── {year}-{month:02d}  (init day {args.init_day:02d}) ──")
            for model_key in regular_models:
                cfg = model_cfgs[model_key]
                # Effective lead-time: user cap takes priority over registry max
                eff_lead = (
                    min(args.leadtime_days, cfg["max_lead_days"])
                    if args.leadtime_days
                    else cfg["max_lead_days"]
                )
                print(
                    f"  [{cfg['label']}]"
                    f"  system={cfg['system']}"
                    f"  lead={eff_lead}d"
                    f"  ({eff_lead * 24} lead hours)"
                )
                result = download_one(
                    model_key=model_key,
                    cfg=cfg,
                    year=year,
                    month=month,
                    init_day=args.init_day,
                    area=area,
                    variables=variables,
                    leadtime_days=eff_lead,
                    outdir=outdir,
                    dry_run=args.dry_run,
                )
                if result is not None:
                    downloaded.append(result)
                elif not args.dry_run:
                    failed.append((model_key, year, month))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  Succeeded : {len(downloaded)} file(s)")
    if failed:
        print(f"  Failed    : {len(failed)} file(s)")
        for mk, y, m in failed:
            print(f"    • {mk}  {y}-{m:02d}")

    # ── Optional merge ────────────────────────────────────────────────────────
    if args.merge:
        if downloaded:
            default_name = f"merged_{year_tag}_{month_tag}_d{args.init_day:02d}.nc"
            merge_out = Path(args.merge_output or str(outdir / default_name))
            merge_netcdfs(downloaded, merge_out)
        elif args.dry_run:
            print("\n[DRY-RUN] Merge step skipped — no files were downloaded.")
        else:
            print("\nNothing to merge (all downloads failed).")

    print("\nDone.")


if __name__ == "__main__":
    main()
