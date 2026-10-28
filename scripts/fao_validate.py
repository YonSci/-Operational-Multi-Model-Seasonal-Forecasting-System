#!/usr/bin/env python3
"""
fao_validate.py
───────────────
Validation of the FAO water-balance onset / cessation / LGP (fao_water_balance.py). Every comparison reports, over
the cell-year pairs where both dates exist: n, bias (days, predicted − reference), MAE, RMSE, Pearson r and the
share within ±7 and ±14 days.

  A  Hindcast skill: SEAS5 ensemble median (members with a date) against the same definition on observed CHIRPS v3,
     CAL (1993–2016) and VAL (2017–2024) years, for each Oct run with FAO outputs.
  B  Definitions on observed rainfall: FAO agricultural onset / cessation against the rainfall-only 20-mm rule
     (Agri rule 1, onset_rules.py on CHIRPS v2) and against the FAO rainfall onset / cessation.
  C  Soil moisture (ERA5-Land 0–100 cm, independent model): daily correlation of the bucket's PAW/TAW with ERA5-Land
     relative wetness (Aug–Feb, per cell), and an ERA5-Land "soil-moisture onset" (relative wetness ≥ the onset
     threshold for the persistence days) against the FAO agricultural onset.
  D  Crop calendar: share of cell-years whose onset falls in the FAO GIEWS short-rains maize planting window for
     Kenya (October – November), for the FAO agricultural, FAO rainfall and Agri rule 1 onsets.
  E  WaPOR v3 actual ET (L1 AETI dekadal, 300 m, FAO; 2018 on): correlation and bias of dekadal ETa (Oct–Dec)
     against WaPOR AETI per cell. WaPOR is the actual land cover's ET; the bucket's is the configured crop's, so
     correlation of the year-to-year/dekad-to-dekad variations is the meaningful part.
  F  Reference dates supplied by the user (optional): validation/reference_dates.csv with columns
     lat, lon, year, onset_date, cessation_date, source (e.g. observed planting dates, station-derived onsets,
     KMD/ICPAC onset and cessation reports) → compared with the cell's FAO agricultural dates.

Not available here (documented in FAO_WATER_BALANCE_METHOD.md): station rainfall, GLEAM (registration), SMAP
root-zone soil moisture (Earthdata download of 9 km 3-hourly files; can be added through the same hook as C).

Output: outputs/fao_wb/validation/metrics.csv, validation_report.md, wapor_aeti_dekadal.nc (cache)

Usage:
  python scripts/fao_validate.py
  python scripts/fao_validate.py --no-wapor
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
import fao_water_balance as fw  # noqa: E402

OUT = BASE_DIR / "outputs" / "fao_wb" / "validation"
HIST = fw.OUT_HIST / "fao_wb_seasons.nc"
RUNS = ["outputs/ecmwf_oct", "outputs/ecmwf_oct_obs_latest"]
GIEWS_WINDOW = (274, 334)            # FAO GIEWS crop calendar, Kenya short-rains maize planting: October – November
WAPOR = "https://storage.googleapis.com/fao-gismgr-wapor-3-data/DATA/WAPOR-3/MAPSET/L1-AETI-D/WAPOR-3.L1-AETI-D.{y}-{m:02d}-D{d}.tif"


def metrics(pred, ref):
    p, r = np.asarray(pred, float).ravel(), np.asarray(ref, float).ravel()
    ok = np.isfinite(p) & np.isfinite(r)
    p, r = p[ok], r[ok]
    if len(p) < 3:
        return dict(n=int(len(p)), bias=np.nan, mae=np.nan, rmse=np.nan, r=np.nan, hit7=np.nan, hit14=np.nan)
    d = p - r
    return dict(n=int(len(p)), bias=float(d.mean()), mae=float(np.abs(d).mean()), rmse=float(np.sqrt((d ** 2).mean())),
                r=float(np.corrcoef(p, r)[0, 1]) if p.std() > 0 and r.std() > 0 else np.nan,
                hit7=float(np.mean(np.abs(d) <= 7)), hit14=float(np.mean(np.abs(d) <= 14)))


def hindcast(rows, cfg):
    (c0, c1), (v0, v1) = cfg["sources"]["calibration_years"], cfg["sources"]["validation_years"]
    for run in RUNS:
        for dname in fw.DEFINITIONS:
            d = BASE_DIR / run / f"fao_wb_{dname}"
            if not (d / "method.json").exists():
                continue
            for v in ("onset", "cessation", "lgp"):
                e = xr.open_dataarray(d / f"ECMWF_{v}_all_years.nc")
                c = xr.open_dataarray(d / f"CHIRPS_{v}.nc")
                yrs = np.intersect1d(e.year.values, c.year.values)
                with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
                    __import__("warnings").simplefilter("ignore")
                    med = np.nanmedian(e.sel(year=yrs).values, axis=0)
                obs = c.sel(year=yrs).values
                for tag, msk in (("CAL", np.isin(yrs, np.arange(c0, c1 + 1))), ("VAL", np.isin(yrs, np.arange(v0, v1 + 1)))):
                    rows.append(dict(group="A hindcast", run=Path(run).name, definition=dname, variable=v, period=tag,
                                     reference="CHIRPS v3 observed, same definition", **metrics(med[msk], obs[msk])))


def definitions(rows, hist):
    yrs = hist.year.values.astype(int)
    r1 = BASE_DIR / "outputs" / "ecmwf_oct" / "icpac_rule1"
    if (r1 / "CHIRPS_onset.nc").exists():
        for v, fao_v in (("onset", "agricultural_onset_doy"), ("cessation", "agricultural_cessation_doy")):
            rule = xr.open_dataarray(r1 / f"CHIRPS_{v}.nc")
            yy = np.intersect1d(yrs, rule.year.values)
            rows.append(dict(group="B definitions", run="observed", definition="FAO agricultural", variable=v, period="1993-2025",
                             reference="Agri rule 1 (20 mm / 3 days, CHIRPS v2)",
                             **metrics(hist[fao_v].sel(year=yy).values, rule.sel(year=yy).values)))
    for v, a, b in (("onset", "agricultural_onset_doy", "rainfall_onset_doy"),
                    ("cessation", "agricultural_cessation_doy", "rainfall_cessation_doy"),
                    ("cessation", "crop_water_cessation_doy", "agricultural_cessation_doy")):
        rows.append(dict(group="B definitions", run="observed", definition=f"FAO {a.removesuffix('_doy').replace('_', ' ')}", variable=v, period="1993-2025",
                         reference=f"FAO {b.removesuffix('_doy').replace('_', ' ')}", **metrics(hist[a].values, hist[b].values)))


def soil_moisture(rows, hist, cfg):
    lat, lon, lm = fw.grid()
    t0, T, b = fw.season_days(cfg)
    q = fw.ET0_DIR / "theta_rootzone_percentiles.nc"
    if not q.exists():
        return {}
    with xr.open_dataset(q) as ds:
        q02, q98 = ds["q02"].values, ds["q98"].values
    th_on, pers = cfg["onset"]["paw_fraction_threshold"], cfg["onset"]["persistence_days"]
    corrs, sm_on, fao_on = [], [], []
    for y in hist.year.values.astype(int):
        f = fw.OUT_HIST / f"daily_{y}.nc"
        if not f.exists():
            continue
        with xr.open_dataset(f) as ds:
            paw = ds["PAW_fraction"].values
        th = fw.era5_season(y, t0, T, lat, lon, "theta_rootzone")
        with np.errstate(invalid="ignore", divide="ignore"):
            rel = np.clip((th - q02) / (q98 - q02), 0, 1)
        a, e = paw[:, lm], rel[:, lm]
        ok = np.isfinite(a) & np.isfinite(e)
        for s in range(a.shape[1]):
            m = ok[:, s]
            if m.sum() > 60 and a[m, s].std() > 0 and e[m, s].std() > 0:
                corrs.append(np.corrcoef(a[m, s], e[m, s])[0, 1])
        on = fw.first_true(fw.fwd_all(e.T >= th_on, pers), b["on_lo"], b["on_hi"]) + t0
        sm_on.append(on); fao_on.append(hist["agricultural_onset_doy"].sel(year=y).values[lm])
    if corrs:
        rows.append(dict(group="C soil moisture", run="observed", definition="agricultural", variable="PAW/TAW daily",
                         period="Aug-Feb", reference="ERA5-Land 0-100 cm relative wetness", n=len(corrs),
                         r=float(np.median(corrs)), bias=np.nan, mae=np.nan, rmse=np.nan, hit7=np.nan, hit14=np.nan))
        rows.append(dict(group="C soil moisture", run="observed", definition="agricultural", variable="onset", period="1993-2025",
                         reference="ERA5-Land soil-moisture onset (same threshold and persistence)",
                         **metrics(np.concatenate(fao_on), np.concatenate(sm_on))))
    return {"median_daily_r": float(np.median(corrs)) if corrs else np.nan}


def crop_calendar(rows, hist):
    lo, hi = GIEWS_WINDOW
    def share(a):
        a = np.asarray(a, float); a = a[np.isfinite(a)]
        return float(np.mean((a >= lo) & (a <= hi))) if len(a) else np.nan
    cands = {"FAO agricultural onset": hist["agricultural_onset_doy"].values, "FAO rainfall onset": hist["rainfall_onset_doy"].values}
    r1 = BASE_DIR / "outputs" / "ecmwf_oct" / "icpac_rule1" / "CHIRPS_onset.nc"
    if r1.exists():
        cands["Agri rule 1 onset (CHIRPS v2)"] = xr.open_dataarray(r1).values
    for k, a in cands.items():
        rows.append(dict(group="D crop calendar", run="observed", definition=k, variable="onset", period="1993-2025",
                         reference="FAO GIEWS Kenya short-rains maize planting, Oct-Nov", n=int(np.isfinite(a).sum()),
                         r=np.nan, bias=np.nan, mae=np.nan, rmse=np.nan, hit7=np.nan, hit14=share(a)))


def wapor(rows, hist):
    """Dekadal WaPOR v3 AETI (mm/day, dekad mean) on the 0.25° grid, Oct–Dec 2018 on; cached."""
    import rasterio
    from rasterio.windows import from_bounds
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    lat, lon, lm = fw.grid()
    cache = OUT / "wapor_aeti_dekadal.nc"
    yrs = [y for y in hist.year.values.astype(int) if 2018 <= y <= 2025]
    dek = [(y, m, d) for y in yrs for m in (10, 11, 12) for d in (1, 2, 3)]
    have = {}
    if cache.exists():
        with xr.open_dataarray(cache) as da:
            have = {str(t): da.sel(dekad=t).values for t in da.dekad.values}
    for y, m, d in dek:
        key = f"{y}-{m:02d}-D{d}"
        if key in have:
            continue
        try:
            with rasterio.open("/vsicurl/" + WAPOR.format(y=y, m=m, d=d)) as src:
                a = src.read(1, window=from_bounds(33.5, -5.0, 42.0, 5.5, src.transform), out_shape=(210, 170)).astype(np.float32)
                a[a == src.nodata] = np.nan
                a *= src.scales[0]
            with np.errstate(invalid="ignore"):
                have[key] = np.nanmean(a[::-1].reshape(42, 5, 34, 5), axis=(1, 3))
        except Exception as exc:
            print(f"[validate] WaPOR {key}: {str(exc)[:100]}")
    if not have:
        return
    keys = sorted(have)
    da = xr.DataArray(np.stack([have[k] for k in keys]), dims=("dekad", "lat", "lon"), coords={"dekad": keys, "lat": lat, "lon": lon},
                      attrs={"units": "mm/day", "source": "WaPOR v3 L1 AETI dekadal (FAO), 300 m averaged to 0.25°"})
    OUT.mkdir(parents=True, exist_ok=True)
    da.to_netcdf(cache)
    model, ref = [], []
    for k in keys:
        y, m, d = int(k[:4]), int(k[5:7]), int(k[-1])
        f = fw.OUT_HIST / f"daily_{y}.nc"
        if not f.exists():
            continue
        start = pd.Timestamp(f"{y}-{m:02d}-01") + pd.Timedelta(days=10 * (d - 1))
        end = (start + pd.offsets.MonthEnd(0)) if d == 3 else start + pd.Timedelta(days=9)
        with xr.open_dataset(f) as ds:
            eta = ds["ETa_daily"].sel(time=slice(start, end)).mean("time").values
        model.append(eta[lm]); ref.append(da.sel(dekad=k).values[lm])
    if model:
        mo, re_ = np.stack(model), np.stack(ref)
        rs = [np.corrcoef(mo[:, s], re_[:, s])[0, 1] for s in range(mo.shape[1])
              if np.isfinite(mo[:, s]).all() and np.isfinite(re_[:, s]).all() and mo[:, s].std() > 0 and re_[:, s].std() > 0]
        ok = np.isfinite(mo) & np.isfinite(re_)
        rows.append(dict(group="E WaPOR", run="observed", definition="agricultural", variable="ETa dekadal (mm/day)",
                         period=f"Oct-Dec {keys[0][:4]}-{keys[-1][:4]}", reference="WaPOR v3 AETI", n=len(rs),
                         r=float(np.median(rs)) if rs else np.nan, bias=float((mo - re_)[ok].mean()),
                         mae=float(np.abs(mo - re_)[ok].mean()), rmse=float(np.sqrt(((mo - re_)[ok] ** 2).mean())), hit7=np.nan, hit14=np.nan))


def reference_dates(rows, hist):
    f = BASE_DIR / "validation" / "reference_dates.csv"
    if not f.exists():
        return
    ref = pd.read_csv(f)
    lat, lon = hist.lat.values, hist.lon.values
    for v, col in (("onset", "agricultural_onset_doy"), ("cessation", "agricultural_cessation_doy")):
        if f"{v}_date" not in ref:
            continue
        p, r = [], []
        for _, row in ref.dropna(subset=[f"{v}_date"]).iterrows():
            y = int(row["year"])
            if y not in hist.year.values:
                continue
            d = pd.Timestamp(row[f"{v}_date"])
            doy = fw.md_doy(f"{d:%m-%d}") + 365 * (d.year - y)          # no-leap-day DOY, as the outputs
            i, j = int(np.abs(lat - row["lat"]).argmin()), int(np.abs(lon - row["lon"]).argmin())
            p.append(float(hist[col].sel(year=y).values[i, j])); r.append(doy)
        rows.append(dict(group="F reference dates", run="observed", definition="agricultural", variable=v, period="as supplied",
                         reference=f"validation/reference_dates.csv ({', '.join(sorted(set(ref.get('source', pd.Series(['user'])).astype(str))))})",
                         **metrics(p, r)))


def report(df, extra):
    fmt = lambda x, k: "" if pd.isna(x) else (f"{x:.2f}" if k in ("r",) else f"{x:.0%}" if k in ("hit7", "hit14") else f"{x:+.1f}" if k == "bias" else f"{x:.1f}")
    lines = ["# FAO water balance – validation", "",
             "Metrics over cell-year pairs where both dates exist: bias = predicted − reference (days), hit7/hit14 = share within ±7/±14 days.",
             "Group D lists the share of onsets inside the GIEWS planting window (Oct–Nov) in the hit14 column.", ""]
    for g, sub in df.groupby("group", sort=True):
        lines += [f"## {g}", "", "| run | definition | variable | period | reference | n | bias | MAE | RMSE | r | ±7 d | ±14 d |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            lines.append(f"| {r.run} | {r.definition} | {r.variable} | {r.period} | {r.reference} | {r.n} | {fmt(r.bias, 'bias')} | "
                         f"{fmt(r.mae, 'mae')} | {fmt(r.rmse, 'rmse')} | {fmt(r.r, 'r')} | {fmt(r.hit7, 'hit7')} | {fmt(r.hit14, 'hit14')} |")
        lines.append("")
    (OUT / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-wapor", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = fw.load_config()
    OUT.mkdir(parents=True, exist_ok=True)
    hist = xr.open_dataset(HIST)
    rows = []
    hindcast(rows, cfg)
    definitions(rows, hist)
    extra = soil_moisture(rows, hist, cfg)
    crop_calendar(rows, hist)
    if not a.no_wapor:
        wapor(rows, hist)
    reference_dates(rows, hist)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "metrics.csv", index=False)
    report(df, extra)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(df.round(2).to_string(index=False))
    print(f"[validate] → {OUT}")


if __name__ == "__main__":
    main()
