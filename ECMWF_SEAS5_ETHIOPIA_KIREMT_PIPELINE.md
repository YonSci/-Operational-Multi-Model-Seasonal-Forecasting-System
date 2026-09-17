# ECMWF SEAS5 (May Initialized) Ethiopia Kiremt Operational Pipeline & Master Blueprint

This document provides the complete operational blueprint, algorithmic specification, master execution checklist, and comprehensive error/incident log for running **ECMWF SEAS5 initialized on May 01 (System 51)** for the **Ethiopia Kiremt Season (Main Rains: June–September)** for **Operational Year 2026**.

It incorporates all lessons learned, vectorized algorithms, memory optimizations, and production fixes from both the Kenya MAM/OND pipelines and the Ethiopia Kiremt experimental stages.

---

## 📋 Master Execution Checklist

### Phase 1: Environment Setup & Prerequisites
- [x] **1.1** Python environment verification: Ensure `.venv` has `xarray`, `netCDF4`, `scipy`, `geopandas`, `shapely`, `cdsapi`, and `matplotlib`.
- [x] **1.2** Verify Copernicus Climate Data Store (CDS) credentials in `~/.cdsapirc` (`url` and `key`).
- [x] **1.3** Verify Ethiopia administrative shapefiles in `data/shapefiles/eth/eth_admin0.shp` and `eth_admin1.shp` (regions/zones).
- [x] **1.4** Verify shared detection library `notebook/dunning_lib.py` with vectorized geopandas spatial joins and NumPy C-level array evaluations.

### Phase 2: Input Data Acquisition & Verification
- [x] **2.1** Ingest Ethiopia CHIRPS daily precipitation covering 1993–2025:
  - Path: `data/chirps_pr_et/et_chirps_pr_r25_1993_2025.nc`
  - Grid: Native 0.25° resolution ($48 \times 60$ grid, lat $3.125^\circ\text{N} - 14.875^\circ\text{N}$, lon $33.125^\circ\text{E} - 47.875^\circ\text{E}$).
  - No regridding required (native alignment with forecast files).
- [x] **2.2** Ingest/Download ECMWF SEAS5 May 01 initialization (1993–2026):
  - Hindcast: `1993–2025` (33 years, 215 lead days, 25/51 ensemble members).
  - Forecast: `2026` operational run (25 ensemble members).
  - Raw CDS files: `data/seasonal_pr_downloads_et/ecmwf/`

### Phase 3: Upstream Daily Bias Correction (Empirical Quantile Mapping)
- [x] **3.1** Define Kiremt forecast window:
  - Window: **DOY 122 (May 2) to DOY 304 (Oct 31)** = **183 lead days**.
  - Wet-day threshold: $0.1\text{ mm/day}$.
  - Transformation: Cube-root power transform ($P^{1/3}$) to handle extreme precipitation skewness.
  - Moving window: 15-day DOY pooling window for robust quantile estimation.
- [x] **3.2** Run vectorized member-wise EQM bias correction per grid cell and DOY across all 25 members.
- [x] **3.3** Export bias-corrected NetCDFs:
  - `data/bias-corrected/corrected_1993_2025.nc` (3.5 GB hindcast archive).
  - `data/bias-corrected/corrected_2026.nc` (52 MB operational 2026 forecast).

### Phase 4: Climatological Baselines & Ethiopia Sub-Masking
- [x] **4.1** Build Ethiopia land mask:
  - Spatial join between $48 \times 60$ bounding box cells and `data/shapefiles/eth/eth_admin0.shp`.
  - Result: 1,842 land pixels within Ethiopian sovereign borders.
- [x] **4.2** Compute CHIRPS Kiremt Climatology (1993–2016 calibration window, 24 years):
  - Daily mean precipitation curve: $Q_d(i, j) = \frac{1}{N_{\text{cal}}} \sum_{y \in \text{CAL}} R_{d,y}(i, j)$
  - Scalar seasonal window mean: $\bar{Q}(i, j) = \frac{1}{183} \sum_{d=122}^{304} Q_d(i, j)$
  - Cumulative anomaly curve: $C_{\text{clim}}(d) = \sum_{k=122}^d [Q_k(i, j) - \bar{Q}(i, j)]$
  - Climatological onset $d_s = \operatorname{argmin} C_{\text{clim}}(d)$ and cessation $d_e = \operatorname{argmax}_{d > d_s} C_{\text{clim}}(d)$.
- [x] **4.3** Ethiopia Kiremt-Dominant Regime Masking:
  - Identify unimodal Kiremt highlands vs. southern/southeastern bimodal (Belg/Deyr) pastoral lowlands (Borana, Somali region).
  - Pixels with climatological season length $d_e - d_s < 30\text{ days}$ flagged as non-Kiremt unimodal regimes (`FLAG_SHORT_SEASON`).

### Phase 5: Vectorized Dunning Cumulative Anomaly Event Detection
- [x] **5.1** Compute individual-year cumulative anomalous accumulation:
  $$A_y(D) = \sum_{j=122}^D [R_{j,y}(i, j) - \bar{Q}(i, j)]$$
  Buffer window: $\pm 50\text{ days}$ around climatological bounds $d_s$ and $d_e$.
- [x] **5.2** Detect season timing metrics for each member, pixel, and year:
  - **Onset DOY**: $\operatorname{argmin} A_y(D) + 1$ (first day rain consistently exceeds $\bar{Q}$).
  - **Cessation DOY**: $\operatorname{argmax}_{D > \text{Onset}} A_y(D)$.
  - **Season Length (LGP)**: $\text{Cessation} - \text{Onset}$ (days).
- [x] **5.3** Assign diagnostic quality flags:
  - `FLAG_VALID (0)`: Valid onset, cessation, and $\text{LGP} \ge 20\text{ days}$.
  - `FLAG_NO_ONSET (1)`: Minimum at window boundary ($D=122$ or $D=304$).
  - `FLAG_NO_CESSATION (2)`: No clear maximum found after onset.
  - `FLAG_SHORT_SEASON (3)`: $\text{LGP} < 20\text{ days}$ (critical drought/crop failure risk).

### Phase 6: Probabilistic Terciles, Skill Scores & Damping Optimization
- [x] **6.1** Calculate 33.3% ($T_{33}$) and 66.7% ($T_{67}$) tercile thresholds from CHIRPS 1993–2016 calibration.
  - Fallback to domain-median terciles for pixels with $< 12$ valid calibration years.
- [x] **6.2** Compute raw ensemble tercile probabilities ($P_{\text{BN}}, P_{\text{NN}}, P_{\text{AN}}$) across the 25 members.
- [x] **6.3** Evaluate validation skill on 2017–2025 independent verification years:
  - Ranked Probability Score ($\text{RPS}$) and Climatological $\text{RPS}_{\text{clim}}$.
  - Ranked Probability Skill Score ($\text{RPSS} = 1 - \text{RPS}/\text{RPS}_{\text{clim}}$).
  - Hit Rate ($\text{HR}$).
- [x] **6.4** Optimize linear pooling parameter $\alpha^*$ on grid $[0.00, 1.00]$ (step $0.01$):
  $$P_{\text{damped}} = \alpha^* P_{\text{raw}} + (1 - \alpha^*)/3$$
- [x] **6.5** Save calibrated 2026 operational probability fields:
  - `probs_op_2026_onset.nc`, `probs_op_2026_cessation.nc`, `probs_op_2026_lgp.nc`.

### Phase 7: NetCDF Output Assembly & Packaging
- [x] **7.1** Assemble standardized NetCDF files conforming to dashboard loader specifications in `outputs/ecmwf_kiremt/` (or `data/outputs_ETHIOPIA_KIREMT_v1/`):
  - `CHIRPS_onset_doy_1993_2026.nc`, `CHIRPS_cessation_doy_1993_2026.nc`, `CHIRPS_lgp_days_1993_2026.nc`
  - `chirps_Q_bar.nc`, `chirps_d_s.nc`, `chirps_d_e.nc`
  - `onset_doy_2026.nc`, `cessation_doy_2026.nc`, `lgp_days_2026.nc`
  - `onset_doy_hindcast_1993_2025.nc`, `cessation_doy_hindcast_1993_2025.nc`, `lgp_days_hindcast_1993_2025.nc`
  - `alpha_onset.nc`, `alpha_cessation.nc`, `alpha_lgp.nc`
  - `hitrate_onset_val.nc`, `rpss_onset_val.nc`
  - `probs_damped_onset.nc`, `probs_damped_cessation.nc`, `probs_damped_lgp.nc`

### Phase 8: Official ILRI Single-Model Publication Bulletin for Ethiopia
- [x] **8.1** Configure key monitored agricultural research stations in Ethiopia:
  - **Holetta Agricultural Research Center (EIAR)**: $9.06^\circ\text{N}, 38.50^\circ\text{E}$ (Central Highlands, barley/wheat).
  - **Debre Zeit / Bishoftu Station**: $8.75^\circ\text{N}, 38.98^\circ\text{E}$ (Teff/chickpea core zone).
  - **Melkassa Agricultural Research Center**: $8.41^\circ\text{N}, 39.32^\circ\text{E}$ (Rift Valley semi-arid maize/sorghum).
  - **Bako Agricultural Research Center**: $9.12^\circ\text{N}, 37.05^\circ\text{E}$ (Western sub-humid high-rainfall maize belt).
  - **Hawassa Farm Station**: $7.05^\circ\text{N}, 38.48^\circ\text{E}$ (Southern SNNPR transition zone).
- [x] **8.2** Verify bulletin layout:
  - Official ILRI/ICPAC header and ruleset.
  - Ethiopia administrative map overlay with selected site marker.
  - 25-member May-initialized precipitation plume (DOY 122–304).
  - Tercile probability bars (BN / NN / AN) and signal confidence.
  - Sowing readiness window (Earliest P10, Optimal P25–P75, Latest P90) with agronomic risk gauges.
  - 33-year CHIRPS historical time series (1993–2025) with 2026 forecast indicator.
- [x] **8.3** Generate and validate both publication A3 vector PDF and 100 DPI PNG outputs.

---

## ⚠️ Comprehensive Error, Gotchas & Incident Log

This section details every technical challenge, runtime error, and architectural trap encountered during execution, along with the exact root cause and verified resolution.

| ID | Component / Step | Error / Symptom | Root Cause | Verified Resolution / Fix Applied |
|---|---|---|---|---|
| **E01** | **CDS API Download** | `HTTP 401 Unauthorized` or timeout when requesting C3S SEAS5 May data. | Missing or outdated CDS API key in `~/.cdsapirc`, or migration to the new Copernicus Data Store portal. | Configured `url: https://cds.climate.copernicus.eu/api` and updated CDS API personal access token in `~/.cdsapirc`. Verified connection via Python handshake script. |
| **E02** | **Windows CLI / Python** | `UnicodeEncodeError: 'charmap' codec can't encode character '\u2500'` | Windows default terminal encoding (`cp1252`) cannot output UTF-8 box-drawing or checkmark characters. | Added `if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')` at the top of all CLI execution scripts. |
| **E03** | **CHIRPS Grid Alignment** | Latitudes inverted or offset between CHIRPS and ECMWF. | CHIRPS NetCDF stored latitudes in ascending order (`3.125 to 14.875`) whereas standard C3S GRIB/NetCDF is often descending (`14.875 to 3.125`). | Added automatic coordinate sorting `ds.sortby('lat')` and `ds.sortby('lon')` prior to array indexing, eliminating coordinate inversion errors. |
| **E04** | **Daily Bias Correction (EQM)** | Script execution estimated at $> 45\text{ minutes}$ on full Ethiopia domain. | Quadruple nested loops (`for lat in lats: for lon in lons: for m in members: np.interp(...)`) in Python space across $48 \times 60 = 2,880$ pixels. | Vectorized member-wise quantile mapping: Pre-computed quantile lookup transfer curves and evaluated array slices in C-level NumPy batches. Runtime reduced to $< 40\text{ seconds}$. |
| **E05** | **Dunning Accumulation** | Spurious Onset detected on Day 1 ($D=122$) across southern pastoral lowlands. | Southern Ethiopia (Borana, Somali region) has a bimodal regime where Kiremt (Jun–Sep) is dry; subtracting Kiremt $\bar{Q}$ caused immediate artificial accumulation minima. | Integrated Ethiopia Sub-Masking: Climatological bounds $d_s$ and $d_e$ check $d_e - d_s \ge 30\text{ days}$; pixels failing this condition are flagged with `FLAG_SHORT_SEASON` (3) and suppressed from unimodal crop onset advisories. |
| **E06** | **Tercile Estimation** | `RuntimeWarning: All-NaN slice encountered` when computing tercile boundaries. | Masked ocean or foreign-country pixels outside Ethiopia land mask passed into `np.nanpercentile`. | Filtered land mask before tercile calculation (`lm == True`). For pixels with $< 12$ valid calibration years, applied domain-median fallback ($T_{33}, T_{67}$) to prevent NaN propagation. |
| **E07** | **Optimal Damping ($\alpha^*$)** | Negative RPSS or overconfident probabilities in dry zones. | Uncalibrated raw ensemble spread over-predicting certainty in transitional climate zones. | Implemented linear pooling optimization ($\alpha^* \in [0, 1]$) minimizing calibration RPS, damping extreme terciles towards the $33.3\%$ climatological baseline. |
| **E08** | **NetCDF Variable Naming** | Frontend Mapbox layers and Backend APIs returned blank arrays. | NetCDF files exported by XArray with default name `__xarray_dataarray_variable__` instead of explicit standard variable keys (`onset`, `cessation`, `lgp`). | Added explicit NetCDF naming convention: `da.name = var_name; da.to_netcdf(..., encoding={var_name: {'zlib': True, 'complevel': 4}})`. |
| **E09** | **Mobile Recharts Collapse** | Analysis charts showed blank or collapsed on mobile screens. | In mobile flex layouts, `<ResponsiveContainer height="100%">` evaluated against unconstrained parent height, resolving to `height: 0px`. | Added explicit `minHeight={240}` to `PrecipPlume`, `minHeight={220}` to `ADPlume`, and explicit container classes `h-[260px] sm:h-[280px] lg:h-full min-h-[240px]`. |
| **E10** | **Mobile API Routing** | Mobile devices failed to fetch `/pixel` data (`Failed to fetch`). | Mobile clients called `http://127.0.0.1:8765`, which looped back to the mobile phone itself. | Implemented smart `resolveApiBase()` in `frontend/src/api/queries.js` that automatically routes mobile and remote clients to the live operational backend on Render (`https://operational-multi-model-seasonal-1t6w.onrender.com`). |
| **E11** | **Landing Page Fixed Viewport** | Landing page was locked/unscrollable on desktop and mobile viewports. | `html, body, #root` had global `overflow: hidden; height: 100%` in `index.html`. | Removed `overflow: hidden` from root HTML/body and scoped `lg:overflow-hidden` exclusively to the active dashboard view, giving the landing page native vertical scrolling. |

---

## 🛠️ Step-by-Step Command & Reproduction Reference

### 1. Download ECMWF SEAS5 May 01 Initialization (1993–2026)
```bash
python scripts/download_seasonal_forecasts_daily_c3s.py \
    --models ecmwf \
    --system ecmwf=51 \
    --months 5 \
    --init-day 1 \
    --year-start 1993 \
    --year-end 2026 \
    --variables total_precipitation \
    --north 15.0 --south 3.0 --west 33.0 --east 48.0 \
    --leadtime-days 215 \
    --outdir ./data/seasonal_pr_downloads_et/ecmwf \
    --merge
```

### 2. Run Operational Kiremt Bias Correction & Dunning Detection Pipeline
```bash
# Executes EQM-BC, Dunning Detection, Tercile Calculation, and Skill Calibration
python scripts/process_ecmwf_kiremt.py \
    --year 2026 \
    --members 25 \
    --outdir ./outputs/ecmwf_kiremt
```

### 3. Generate Official Publication Bulletin for Ethiopian Monitored Sites
```bash
# Example: Generate Holetta Agricultural Research Center 2026 Kiremt Bulletin
python -c "
from backend.bulletin_singlemodel_v1 import generate_single_model_bulletin
generate_single_model_bulletin(
    site_name='Holetta Agricultural Research Center',
    lat_q=9.06,
    lon_q=38.50,
    model_name='ECMWF SEAS5',
    season='kiremt',
    f_year=2026,
    out_dir='outputs/bulletins'
)
"
```

### 4. Build & Verify Frontend Production Distribution
```bash
cmd /c "npm --prefix frontend run build"
```

---

## 🗺️ System Parameters Quick Reference (Kenya OND vs. Ethiopia Kiremt)

| Parameter | Kenya Short Rains (OND) | Ethiopia Kiremt (Main Rains) |
|---|---|---|
| **Primary Model** | ECMWF SEAS5 (System 51) | ECMWF SEAS5 (System 51) |
| **Initialization Date** | **September 01** (`0901`) | **May 01** (`0501`) |
| **Forecast Window** | DOY 244–365 (Sep 1 – Dec 31, 122 days) | DOY 122–304 (May 2 – Oct 31, 183 days) |
| **Domain Grid** | $42 \times 34$ ($0.25^\circ$ res, 842 land pixels) | $48 \times 60$ ($0.25^\circ$ res, 1,842 land pixels) |
| **Bounding Box** | $5.5^\circ\text{S} - 5.5^\circ\text{N}$, $33.0^\circ\text{E} - 42.5^\circ\text{E}$ | $3.0^\circ\text{N} - 15.0^\circ\text{N}$, $33.0^\circ\text{E} - 48.0^\circ\text{E}$ |
| **Calibration Period** | 1993–2016 (24 years) | 1993–2016 (24 years) |
| **Validation Period** | 2017–2025 (9 years) | 2017–2025 (9 years) |
| **Ensemble Members** | 25 members | 25 members |
| **Dunning Buffer** | $\pm 30\text{ days}$ | $\pm 50\text{ days}$ |
| **Minimum LGP** | 20 days | 20 days |
| **Output Directory** | `outputs/ecmwf_sep/` | `outputs/ecmwf_kiremt/` (or `data/outputs_ETHIOPIA_KIREMT_v1/`) |
| **Primary Monitored Sites** | KALRO Kiboko, Kapiti, El Karama, Samburu | Holetta, Debre Zeit, Melkassa, Bako, Hawassa |
