# ECMWF SEAS5 (October Initialized) Kenya Short Rains Pipeline & Verification Checklist

This document records the operational run of **ECMWF SEAS5 System 51 initialized 01 October 2026** for the Kenya Short Rains (OND 2026): download, daily EQM bias correction against CHIRPS, Dunning et al. (2016) onset / cessation / season length (LGP) detection, calibrated tercile probabilities, dashboard integration and single-model bulletins. It follows the same procedure as [ECMWF_SEAS5_SEPTEMBER_PIPELINE.md](ECMWF_SEAS5_SEPTEMBER_PIPELINE.md).

An October initialization has no forecast for September, while the September product's window starts on 01 Sep (DOY 244). Two variants were therefore produced:

| Variant | Model name (dashboard) | Window | September days | Output folder |
|---|---|---|---|---|
| **(a) OND window** | `ECMWF SEAS5 (Oct)` — Init "Oct 01" | DOY 274–365 (01 Oct – 31 Dec) | not used; CHIRPS climatology, terciles and skill recomputed on the Oct–Dec window | `outputs/ecmwf_oct/` |
| **(b) Observed September + forecast** | `ECMWF SEAS5 (Oct+Obs)` — Init "Oct 01 + Sep obs" | DOY 244–365 (01 Sep – 31 Dec), same as the Sep product | observed CHIRPS (identical for all members, not bias-corrected); 1993–2025 from the CHIRPS record, 2026 from `chirps-v2.0.2026.days_p25.nc` (complete to 30 Sep 2026) | `outputs/ecmwf_oct_obs/` |

---

## 📋 Master Execution Checklist

### Phase 1: Environment & Prerequisites
- [x] **1.1** Fresh clone of `main` at `07879e4` into `D:\Operational-Multi-Model-Seasonal-Forecasting-System`; Python 3.13 `.venv` (system site-packages + `h5py`, `python-multipart`, `reportlab`); `npm ci` in `frontend/`.
- [x] **1.2** CDS credentials (`~/.cdsapirc`) verified.
- [x] **1.3** Data inputs (`data/chirps_pr_ke`, other `data/*`, `outputs/ecmwf_v3`, …) linked as directory junctions from `D:\dashboard_ons_cess_sl` (disk space); October downloads and outputs are real folders in the clone.

### Phase 2: Data Acquisition
- [x] **2.1** ECMWF SEAS5 System 51, 01 Oct init, daily `total_precipitation`, Kenya box N5.5/W33/S-5.5/E42.5, 1993–2026 → `data/seasonal_pr_downloads_ke/ecmwf_oct/ecmwf_<YYYY>10_d01.nc` (34 files; 25 members for 1993–2016 and as used by the pipeline, 51 members delivered for 2017–2026).
  - 1993, 1994, 1997, 2015: 215 lead days (single-year requests); all other years: 92 lead days (batched requests). Both cover the 92 forecast days (01 Oct – 31 Dec) the pipeline reads.
- [x] **2.2** CHIRPS 2026 daily p25 (`data/chirps_2026/chirps-v2.0.2026.days_p25.nc`, 01 Jan – 30 Sep 2026) for variant (b).

### Phase 3–5: Bias Correction, Dunning Detection, Terciles & Calibration
- [x] **3.1** Member-wise EQM (cube-root transform, ±15-day CHIRPS pool, CAL 1993–2016) on forecast days only.
- [x] **4.1** CHIRPS Dunning climatology per variant window (`chirps_Q_bar/C_clim/d_s/d_e.nc`).
- [x] **4.2** Onset / cessation / LGP for CHIRPS (1993–2025) and all ECMWF members/years (1993–2026); buffer 30 days, min LGP 20 days.
- [x] **5.1** Terciles from CHIRPS CAL 1993–2016; raw ensemble probabilities; α* optimised on CAL; damped probabilities; RPSS / hit rate for CAL and VAL (2017–2024).

### Phase 6: Outputs
- [x] **6.1** Both folders contain 39 NetCDF files in the `outputs/ecmwf_sep/` layout (incl. `probs_op_2026_{onset,cessation,lgp}.nc`, `ECMWF_bc_daily_all_years.nc`, `calibration_params/`). Sizes: 444 MB (a), 583 MB (b).
- [ ] **6.2** No `probs_damped_rainfall.nc` (seasonal rainfall terciles are a separate product); the dashboard's Rainfall Terciles layer shows 1/3 for October inits.

### Phase 7: Bulletins
- [x] **7.1** Single-model A3 PDF + PNG bulletins for the six Kenya monitored sites, both variants → `outputs/bulletins_oct/OND2026_{OctInit,OctInit_SepObs}_<site>.{png,pdf}` (24 files). Header shows Init 01 October 2026 and the variant window; CHIRPS history panels use the variant's own window.

### Phase 8: Dashboard (local only)
- [x] **8.1** Backend loads both variants from NetCDF (raw and demo mode) and routes `/pixel`, `/grid`, `/bulletin`, `/chirps_historical` by model; Sep remains the default.
- [x] **8.2** Frontend: Short Rains **Init** selector (Sep 01 / Oct 01 / Oct 01 + Sep obs); plume axes use the API window. `npm run build` passes.
- [ ] **8.3** Not committed, not pushed, not deployed (Render / GitHub Pages unchanged).

---

## 📊 OND 2026 Forecast Summary (01 Oct 2026 initialization)

Domain values are means over the 757 pixels of `mask_kenya_ond`. Onset/cessation "BN" = earlier than normal. Dominant share = pixels whose top tercile probability is ≥ 40 %.

| Variable | Variant | Ensemble median | CHIRPS CAL mean | Anomaly | Dominant tercile share | Mean P(BN / NN / AN) |
|---|---|---|---|---|---|---|
| Onset | (a) | DOY 294 (21 Oct) | DOY 314 | **−20.5 d (early)** | BN 84 % | 0.56 / 0.19 / 0.24 |
| Onset | (b) | DOY 288 (15 Oct) | DOY 307 | **−19.0 d (early)** | BN 79 % | 0.58 / 0.21 / 0.21 |
| Cessation | (a) | DOY 341 (07 Dec) | DOY 340 | +0.7 d | no clear signal | 0.34 / 0.31 / 0.35 |
| Cessation | (b) | DOY 344 (10 Dec) | DOY 339 | +4.6 d | AN 24 % | 0.33 / 0.31 / 0.37 |
| LGP | (a) | 38 d | 26 d | **+11.8 d (longer)** | AN 71 % | 0.23 / 0.30 / 0.48 |
| LGP | (b) | 48 d | 32 d | **+15.5 d (longer)** | AN 75 % | 0.19 / 0.28 / 0.53 |

P(season failure, no onset detected): 5.3 % (a), 2.2 % (b). The September-initialized product also indicates an early onset (e.g. KALRO Kiboko −12 d); the October run strengthens that signal.

### Monitored sites (ensemble median)

| Site | (a) Onset (clim) | (a) Cessation | (a) LGP | (b) Onset (clim) | (b) Cessation | (b) LGP |
|---|---|---|---|---|---|---|
| KALRO Kiboko, Makueni | 28 Oct (18 Nov) | 18 Dec | 45 d | 21 Oct (12 Nov) | 26 Dec | 58 d |
| Kapiti Research Station | 22 Oct (13 Nov) | 14 Dec | 44 d | 20 Oct (12 Nov) | 14 Dec | 51 d |
| El Karama Sahiwals | 28 Oct (21 Nov) | 18 Dec | 40 d | 21 Oct (15 Nov) | 26 Dec | 57 d |
| Genco Tana River | 13 Oct (07 Nov) | 06 Dec | 41 d | 13 Oct (08 Nov) | 08 Dec | 48 d |
| Genco Maralal, Samburu | 16 Oct (14 Nov) | 01 Dec | 42 d | 17 Oct (09 Nov) | 03 Dec | 46 d |

> [!IMPORTANT]
> Forecast median onsets fall before the 25 Oct 2026 issue date. Confirm against observed October rainfall (CHIRPS preliminary / station data) before communicating onset advice.

### Hindcast skill (OND-mask mean)

| Variable | Variant | RPSS CAL 1993–2016 | RPSS VAL 2017–2024 | Hit rate VAL | α* | Pixels RPSS VAL > 0 |
|---|---|---|---|---|---|---|
| Onset | (a) | +0.185 | +0.248 | 0.577 | 0.69 | 89 % |
| Onset | (b) | +0.215 | +0.230 | 0.581 | 0.73 | 88 % |
| Cessation | (a) | +0.045 | −0.022 | 0.344 | 0.28 | 28 % |
| Cessation | (b) | +0.026 | −0.030 | 0.362 | 0.33 | 34 % |
| LGP | (a) | +0.147 | +0.195 | 0.566 | 0.70 | 82 % |
| LGP | (b) | +0.164 | +0.181 | 0.552 | 0.79 | 81 % |

Onset and LGP are skilful; cessation is not, and calibration damps its probabilities toward climatology. Bias-corrected model onset climatology matches CHIRPS (median DOY 310 vs 309, variant a).

---

## 🔄 Update 25 Oct 2026 — observed rainfall to 20 Oct (variant c)

Kapiti Research Station reported no rain or cloud by ~24 Oct, against a forecast median onset of 22 Oct.

**Direct check (CHIRPS preliminary daily p05 → 0.25°, 1–20 Oct):** Kapiti pixel received **0.0 mm on all 20 days** (September 8.5 mm) — the driest 1–20 Oct in 1993–2026 (tied with 2020). The Dunning cumulative anomaly was still falling on 20 Oct (−102.5 mm): no onset yet. Across the OND zone, 1–20 Oct rain averaged 12.7 mm vs a 29.6 mm normal (76 % of the zone below half of normal). Historically (1993–2025) Kapiti's earliest CHIRPS onset is 23 Oct (median 06 Nov); the seven years as dry by 20 Oct had onsets between 27 Oct and 17 Dec.

**Variant (c) `ECMWF SEAS5 (Oct+Obs 20 Oct)` → `outputs/ecmwf_oct_obs1020/`:** window DOY 244–365, observed CHIRPS 01 Sep – 20 Oct (final p25 + preliminary) for every year, 01 Oct-init members from 21 Oct (leads 20–91), EQM on forecast days only.

| | Onset | Cessation | LGP |
|---|---|---|---|
| Kapiti, all 25 members | median 27 Oct (P25 22 Oct – P75 06 Nov, P90 02 Dec); P(early/normal/late) 0.40/0.30/0.30 | 14 Dec | 50 d |
| Kapiti, 16 members with onset ≥ 25 Oct (consistent with no rain to ~24 Oct) | median **02 Nov** (P25 28 Oct – P75 20 Nov, P90 13 Dec) | | |
| OND zone | median 25 Oct vs clim 03 Nov (−8.7 d) | | |
| OND-zone skill (RPSS VAL) | +0.43 | −0.01 | +0.22 |

**Local skill at Kapiti is weak** (variant a hindcast 1993–2025: onset correlation +0.39, MAE 14.5 d, α* 0.44) — far below the zone mean. A single median date should not be communicated for this site; use the range and tercile probabilities.

```powershell
# refresh preliminary CHIRPS (daily tifs → data/chirps_prelim_2026), then:
.\.venv\Scripts\python.exe scripts\chirps_prelim_to_p25.py data\chirps_prelim_2026 data\chirps_prelim_2026\chirps_prelim_2026_p25_kenya.nc
.\.venv\Scripts\python.exe scripts\process_ecmwf_september.py --init-month 10 --win-doy-start 244 --win-doy-end 365 `
    --obs-lead-doy 274 --obs-end-doy 293 `
    --chirps-extra data\chirps_2026\chirps-v2.0.2026.days_p25.nc data\chirps_prelim_2026\chirps_prelim_2026_p25_kenya.nc `
    --ecmwf-dir data\seasonal_pr_downloads_ke\ecmwf_oct --out-dir outputs\ecmwf_oct_obs1020
.\.venv\Scripts\python.exe scripts\track_site_inits.py --name "Kapiti Research Station Farm" --lat -1.63209 --lon 37.1479
```

---

## 🔁 Operational update loop (from 25 Oct 2026)

`scripts/update_forecast.py` (wrapped by `scripts/run_update_forecast.bat`, intended to run daily at 12:00 EAT) does:

| Step | Script | Output |
|---|---|---|
| CHIRPS final 2026 (re-download when CHC updates it) + preliminary daily p05 GeoTIFFs after it, kept gzipped and read via `/vsigzip/` | `update_forecast.py`, `chirps_prelim_to_p25.py` | `data/chirps_2026/`, `data/chirps_prelim_2026/` |
| SEAS5 01 Oct init re-run with observed CHIRPS spliced to the latest day (all years) | `process_ecmwf_september.py --obs-end-doy` | `outputs/ecmwf_oct_obs_latest/` + `run_meta.json` (dashboard model `ECMWF SEAS5 (Oct+Obs latest)`, Init "Oct 01 + latest obs") |
| Planting onset rule: ≥20 mm in ≤3 days (first day ≥1 mm), no ≥10-day dry spell (<1 mm/day) in the next 21 days, searched from 01 Oct; CHIRPS + all members, terciles (no onset = late), α*, RPSS, hit rate, median correlation/MAE | `agro_onset.py seasonal` | `<seasonal>/agro_onset/` |
| ECMWF IFS ENS open data (50 members, 0.25°, days 1–15, tp only via byte ranges, ~0.5 GB, CC-BY-4.0) | `fetch_ecmwf_ens.py` | `data/ecmwf_ens/ens_tp_<init>_kenya.nc` |
| 1–15 day outlook: daily P(≥1 mm), P(≥10 mm), P(planting-rain event starts), P(event within 7/15 d), composite planting onset (ENS days 1–15 + paired seasonal member to 31 Dec for the dry-spell check) | `agro_onset.py ens` | `outputs/ecmwf_ens/ens_outlook_<init>.nc` |
| Site reports (Kenya monitored sites): observed status, ENS table, seasonal ranges (50 %/80 %) + tercile probabilities + local skill note + out-of-record flags; onset members before the ENS start are dropped when no onset has been observed (probabilities recomputed with α*) | `site_report.py` | `outputs/site_reports/<date>/` (`index.md`, `<site>.md/.json/.png`) |
| Backend hot reload | `POST /api/pipeline/reload` | — |

Skill note categories (pixel hindcast 1993–2025): **useful** = RPSS(VAL) ≥ 0.10 and correlation ≥ 0.5; **limited** = RPSS > 0 or correlation ≥ 0.3; **no** otherwise. The single-model bulletin footer now shows the local onset skill and the P25–P75 onset range.

Caveats: ENS precipitation is raw (no reforecast-based calibration available) and over-forecasts light-rain days over the Kenyan highlands — weigh ≥10 mm and 3-day totals. Bulletins use all seasonal members; the "no onset yet" conditioning is applied only in site reports.

Register the daily task (one-off, user action):
```powershell
schtasks /Create /TN "OND Forecast Update" /TR "D:\Operational-Multi-Model-Seasonal-Forecasting-System\scripts\run_update_forecast.bat" /SC DAILY /ST 12:00
```

---

## ⚠️ Problem & Incident Log

| Step | Issue | Root Cause | Resolution | Status |
|---|---|---|---|---|
| 1.1 | `git clone` failed repeatedly (`early EOF`, connection reset) | ~280 MB tip incl. 77 MB `demo_data.npz` over an unstable link | Partial clone `--filter=blob:limit=2m`, large blobs fetched lazily; tree verified clean at `07879e4` | ✅ Resolved |
| 1.1 | `pip install` stalled (DNS failures to PyPI) | Intermittent network | venv with `--system-site-packages`; only 3 missing packages installed | ✅ Resolved |
| 1.3 | Cannot copy 7.5 GB of inputs | 6 GB free on D: | Directory junctions to `D:\dashboard_ons_cess_sl` (read-only use) | ✅ Resolved |
| 2.1 | Single-year CDS requests queued 2–5 h each | CDS load | Batched multi-year requests (1995–2016, 2017–2025, 2026) with 92 lead days; per-year split | ✅ Resolved |
| 2.1 | `Maximum number queued requests for this dataset has been reached` | Parallel downloaders; stopping a client does not cancel its queued CDS job | One request per batch, ≤ 3 in flight; recovered completed orphan jobs (1994, 1997, 2015) via the CDS jobs API | ✅ Resolved |
| 3.1 | `process_ecmwf_september.py` hard-coded to September | `09` file pattern, DOY 244 window | Added `--init-month`, `--win-doy-start/end`, `--ecmwf-dir`, `--out-dir`, `--obs-lead-doy`, `--chirps-extra` (defaults unchanged) | ✅ Resolved |
| 8.1 | Short Rains routes always used the Sep model and Sep CHIRPS climatology | `"ECMWF SEAS5 (Sep)"` hard-coded | Routes honour a requested Short Rains model; extra inits registered in `_EXTRA_SHORT_RAINS` (`backend/mam_loader.py`) | ✅ Resolved |
| 8.2 | Plume charts assumed window start DOY 244 | Hard-coded | Use `pixelData.win_doy_start` | ✅ Resolved |
| Update | Kapiti: forecast onset 22 Oct, no rain observed | Median communicated as a date; local skill weak (r 0.39, ±14.5 d); median earlier than any observed onset | Observation-updated runs, range + probability + skill note per site, planting-onset rule, ENS 1–15 d outlook | ✅ Addressed |
| Update | ecCodes assertion in threaded ENS decode | ecCodes not thread-safe | Download in threads, decode on main thread | ✅ Resolved |
| Update | D: drive full (NetCDF HDF error) | Unpacked global p05 GeoTIFFs ~69 MB each | Keep `.tif.gz`, read via `/vsigzip/` (1.1 GB → 51 MB) | ✅ Resolved |

---

## 🛠️ Command Reference

```powershell
# Processing (from repo root, .venv)
# (a) OND window
.\.venv\Scripts\python.exe scripts\process_ecmwf_september.py --init-month 10 --win-doy-start 274 --win-doy-end 365 `
    --ecmwf-dir data\seasonal_pr_downloads_ke\ecmwf_oct --out-dir outputs\ecmwf_oct

# (b) observed September CHIRPS + October-initialized forecast
.\.venv\Scripts\python.exe scripts\process_ecmwf_september.py --init-month 10 --win-doy-start 244 --win-doy-end 365 `
    --obs-lead-doy 274 --chirps-extra data\chirps_2026\chirps-v2.0.2026.days_p25.nc `
    --ecmwf-dir data\seasonal_pr_downloads_ke\ecmwf_oct --out-dir outputs\ecmwf_oct_obs

# Dashboard (local)
cd backend;  ..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765
cd frontend; npm run dev        # http://127.0.0.1:5173 → Kenya → Short Rains → Init
```

Bulletins: `POST /bulletin` with `model_name` = `ECMWF SEAS5 (Oct)` or `ECMWF SEAS5 (Oct+Obs)`, `season=short_rains`, `year=2026` (or the Bulletin button in the dashboard with the desired Init selected).
