# ECMWF SEAS5 (January Initialized) Ethiopia Belg (FMAM) Operational Pipeline & Master Blueprint

This document provides the complete operational blueprint, algorithmic specification, master execution checklist, agro-climatic regime documentation, and error/incident log for running **ECMWF SEAS5 initialized on January 01 (System 51)** for the **Ethiopia Belg Season (Spring Rains: February–May / FMAM)** for **Operational Year 2026**.

It incorporates all operational patterns, vectorized algorithms, memory optimizations, and production fixes from the Kenya MAM/OND pipelines and the Ethiopia Kiremt pipeline.

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
  - Full daily calendar coverage (1993-01-01 to 2025-12-31, 12,053 days).
- [x] **2.2** Ingest/Generate ECMWF SEAS5 January 01 initialization (1993–2026):
  - Hindcast: `1993–2025` (33 years, 25 ensemble members).
  - Operational Forecast: `2026` run (25 ensemble members).
  - Target output directory: `outputs/ecmwf_fmam/`.

### Phase 3: Daily Bias Correction & Seasonal Calibration Window
- [x] **3.1** Define Belg / FMAM seasonal window:
  - Window: **DOY 32 (Feb 01) to DOY 166 (Jun 15)** = **135 lead days**.
  - Wet-day threshold: $0.1\text{ mm/day}$.
  - Transformation: Cube-root power transform ($P^{1/3}$) to handle dry season precipitation skewness.
  - Moving window: 15-day DOY pooling window for robust quantile estimation.
  - Justification: Captures early southern Belg onset (Feb in Borana/Gu-Genna) through late highland Belg cessation (late May to mid-June in North Shewa and South Wollo).
- [x] **3.2** Run vectorized member-wise EQM bias correction per grid cell and DOY across all 25 members.
- [x] **3.3** Export bias-corrected daily NetCDFs:
  - `ECMWF_bc_daily_all_years.nc` (34 years: 1993–2026, 25 members, 135 lead days).
  - `ECMWF_bc_daily_2026.nc` (Operational 2026, 25 members, 135 lead days).

### Phase 4: Climatological Baselines & Agro-Climatic Sub-Masking
- [x] **4.1** Build Ethiopia land mask:
  - Spatial join between $48 \times 60$ bounding box cells and `data/shapefiles/eth/eth_admin0.shp`.
  - Result: 1,594 – 1,842 land pixels within Ethiopian sovereign borders.
- [x] **4.2** Compute CHIRPS Belg Climatology (1993–2016 calibration window, 24 years):
  - Daily mean precipitation curve: $Q_d(i, j) = \frac{1}{N_{\text{cal}}} \sum_{y \in \text{CAL}} R_{d,y}(i, j)$
  - Scalar seasonal window mean: $\bar{Q}(i, j) = \frac{1}{135} \sum_{d=32}^{166} Q_d(i, j)$
  - Cumulative anomaly curve: $C_{\text{clim}}(d) = \sum_{k=32}^d [Q_k(i, j) - \bar{Q}(i, j)]$
  - Climatological onset $d_s = \operatorname{argmin} C_{\text{clim}}(d)$ and cessation $d_e = \operatorname{argmax}_{d > d_s} C_{\text{clim}}(d)$.
- [x] **4.3** Ethiopia Agro-Climatic Sub-Regimes for Belg:
  - **Eastern / Central Highlands Belg**: High reliance for short-cycle cereals (barley, wheat, teff) and long-cycle crop land preparation (sorghum, maize).
  - **Southern Pastoral Lowlands (Borana / Gu-Genna)**: Bimodal spring first rains (March–May), vital for rangeland pasture and livestock water points.
  - **Western Unimodal Transition (Gambella / Benishangul-Gumuz)**: Early rains leading into Kiremt.

### Phase 5: Vectorized Dunning Cumulative Anomaly Event Detection
- [x] **5.1** Compute individual-year cumulative anomalous accumulation:
  $$A_y(D) = \sum_{j=32}^D [R_{j,y}(i, j) - \bar{Q}(i, j)]$$
  Buffer window: $\pm 35\text{ days}$ around climatological bounds $d_s$ and $d_e$.
- [x] **5.2** Detect season timing metrics for each member, pixel, and year:
  - **Onset DOY**: $\operatorname{argmin} A_y(D) + 1$ (first day rain consistently exceeds $\bar{Q}$).
  - **Cessation DOY**: $\operatorname{argmax}_{D > \text{Onset}} A_y(D)$.
  - **Season Length (LGP)**: $\text{Cessation} - \text{Onset}$ (days).
- [x] **5.3** Assign diagnostic quality flags:
  - `FLAG_VALID (0)`: Valid onset, cessation, and $\text{LGP} \ge 20\text{ days}$.
  - `FLAG_NO_ONSET (1)`: Minimum at window boundary ($D=32$ or $D=166$).
  - `FLAG_NO_CESSATION (2)`: No clear maximum found after onset.
  - `FLAG_SHORT_SEASON (3)`: $\text{LGP} < 20\text{ days}$ (Belg crop failure risk).

### Phase 6: Probabilistic Terciles, Skill Scores & Damping Optimization
- [x] **6.1** Calculate 33.3% ($T_{33}$) and 66.7% ($T_{67}$) tercile thresholds from CHIRPS 1993–2016 calibration.
  - Domain-median fallback for pixels with $< 12$ valid calibration years.
- [x] **6.2** Compute raw ensemble tercile probabilities ($P_{\text{BN}}, P_{\text{NN}}, P_{\text{AN}}$) across 25 members.
- [x] **6.3** Evaluate validation skill on 2017–2025 independent verification years:
  - Ranked Probability Score ($\text{RPS}$) and Climatological $\text{RPS}_{\text{clim}}$.
  - Ranked Probability Skill Score ($\text{RPSS} = 1 - \text{RPS}/\text{RPS}_{\text{clim}}$).
  - Hit Rate ($\text{HR}$).
- [x] **6.4** Optimize linear pooling parameter $\alpha^*$ on grid $[0.00, 1.00]$ (step $0.01$):
  $$P_{\text{damped}} = \alpha^* P_{\text{raw}} + (1 - \alpha^*)/3$$
- [x] **6.5** Save calibrated 2026 operational probability fields:
  - `probs_op_2026_onset.nc`, `probs_op_2026_cessation.nc`, `probs_op_2026_lgp.nc`.

### Phase 7: NetCDF Output Assembly & Packaging
- [x] **7.1** Assemble 47 standardized NetCDF files in `outputs/ecmwf_fmam/`:
  - `CHIRPS_onset_doy_1993_2026.nc`, `CHIRPS_cessation_doy_1993_2026.nc`, `CHIRPS_lgp_days_1993_2026.nc`, `CHIRPS_quality_flag_1993_2026.nc`
  - `chirps_C_clim.nc`, `chirps_Q_bar.nc`, `chirps_d_s.nc`, `chirps_d_e.nc`
  - `onset_doy_2026.nc`, `cessation_doy_2026.nc`, `lgp_days_2026.nc`
  - `onset_doy_hindcast_1993_2025.nc`, `cessation_doy_hindcast_1993_2025.nc`, `lgp_days_hindcast_1993_2025.nc`
  - `ECMWF_onset_doy_all_years.nc`, `ECMWF_cessation_doy_all_years.nc`, `ECMWF_lgp_days_all_years.nc`
  - `alpha_onset.nc`, `alpha_cessation.nc`, `alpha_lgp.nc`
  - `hitrate_onset_cal.nc`, `hitrate_onset_val.nc`, `hitrate_cessation_cal.nc`, `hitrate_cessation_val.nc`, `hitrate_lgp_cal.nc`, `hitrate_lgp_val.nc`
  - `rpss_onset_cal.nc`, `rpss_onset_val.nc`, `rpss_cessation_cal.nc`, `rpss_cessation_val.nc`, `rpss_lgp_cal.nc`, `rpss_lgp_val.nc`
  - `t33_onset_doy.nc`, `t67_onset_doy.nc`, `t33_cessation_doy.nc`, `t67_cessation_doy.nc`, `t33_lgp_days.nc`, `t67_lgp_days.nc`
  - `probs_damped_onset.nc`, `probs_damped_cessation.nc`, `probs_damped_lgp.nc`
  - `probs_op_2026_onset.nc`, `probs_op_2026_cessation.nc`, `probs_op_2026_lgp.nc`
  - `ECMWF_bc_daily_all_years.nc`, `ECMWF_bc_daily_2026.nc`, `model_years.nc`
- [x] **7.2** Duplicate terciles to `calibration_params/` subdirectory.

### Phase 8: Official Publication Bulletin & Frontend Integration
- [x] **8.1** Monitored Ethiopian Agricultural & Pastoral Research Stations:
  - **Holetta Agricultural Research Center (EIAR)**: $9.06^\circ\text{N}, 38.50^\circ\text{E}$ (Central Highlands).
  - **Debre Zeit / Bishoftu Station**: $8.75^\circ\text{N}, 38.98^\circ\text{E}$ (Belg pulses / teff zone).
  - **Melkassa Agricultural Research Center**: $8.41^\circ\text{N}, 39.32^\circ\text{E}$ (Rift Valley semi-arid zone).
  - **Bako Agricultural Research Center**: $9.12^\circ\text{N}, 37.05^\circ\text{E}$ (Western maize belt).
  - **Hawassa Farm Station**: $7.05^\circ\text{N}, 38.48^\circ\text{E}$ (Southern SNNPR bimodal zone).
  - **Yabello Pastoral Research Center (Borana)**: $4.88^\circ\text{N}, 38.09^\circ\text{E}$ (Southern rangeland Gu-Genna rains).
  - **Kobo Agricultural Research Center (North Wollo)**: $12.14^\circ\text{N}, 39.63^\circ\text{E}$ (Eastern Amhara Belg belt).
- [x] **8.2** Dual-season selector in frontend:
  - Ethiopia: **Belg (FMAM: Feb–May)** (Initialized Jan 01) and **Kiremt (Jun–Sep)** (Initialized May 01).
- [x] **8.3** Colorbar legend and threshold scaling:
  - Dedicated Belg onset color scale (DOY 45 to 115) and cessation scale (DOY 115 to 170).

---

## ⚠️ Comprehensive Error, Gotchas & Incident Log

| ID | Component / Step | Error / Symptom | Root Cause | Verified Resolution / Fix Applied |
|---|---|---|---|---|
| **E12** | **Belg Window Definition** | Onset detected prematurely at DOY 32 across central highlands. | Standard 120-day window (Feb–May) with zero buffer caused false edge minimizations in dry winter-to-spring transitions. | Extended window to DOY 32–166 (135 days) with $\pm 35\text{ days}$ Dunning search buffer; required minimum 20 days LGP to filter false winter rains. |
| **E13** | **Dual Season UI State** | Switching between Belg and Kiremt kept stale colorbar ranges and DOY dates. | Single `season` key assumed 1-to-1 country mapping without handling season switches within Ethiopia. | Implemented dynamic season state in `App.jsx` and `MapPanel.jsx` with automatic `CS_FMAM` / `CS_KIREMT` scale switching and month label recalculation (`DOY_MONTHS_FMAM`). |
| **E14** | **Demo Data Memory Budget** | Adding Belg raw daily NetCDF swelled `demo_data.npz` beyond 50 MB, causing memory exhaustion on free-tier Render instances. | Storing 34 years of 25-member daily fields for all pixels consumes 1.8 GB. | Packed only operational 2026 daily plume (`fmam_ecmwf_bc_daily_2026`) in `float16`, while precomputing all terciles, skill maps, and probabilities into 2D/3D float32 grids. Total package size remains well under 45 MB. |
| **E15** | **Bimodal Lowland Masking** | Arid Afar and Somali triangle pixels produced irregular noisy onset predictions. | Annual rainfall $< 150\text{ mm}$ with no clear seasonal peak causes Dunning cumulative anomaly curve to flatten. | Assigned `FLAG_SHORT_SEASON` (3) to pixels with climatological duration $< 20\text{ days}$, displaying them with hatch patterns and advisory notes in the UI. |

---

## 🗺️ Multi-Season Parameters Comparison

| Parameter | Kenya Short Rains (OND) | Kenya Long Rains (MAM) | Ethiopia Kiremt (Main) | Ethiopia Belg (Spring) |
|---|---|---|---|---|
| **Model** | ECMWF SEAS5 (Sys 51) | Multi-Model (7 Models) | ECMWF SEAS5 (Sys 51) | ECMWF SEAS5 (Sys 51) |
| **Init Date** | **September 01** (`0901`) | **February 01** (`0201`) | **May 01** (`0501`) | **January 01** (`0101`) |
| **Forecast Window** | DOY 244–365 (122 days) | DOY 32–213 (182 days) | DOY 122–304 (183 days) | DOY 32–166 (135 days) |
| **Domain Grid** | $42 \times 34$ ($0.25^\circ$ res) | $42 \times 34$ ($0.25^\circ$ res) | $48 \times 60$ ($0.25^\circ$ res) | $48 \times 60$ ($0.25^\circ$ res) |
| **Land Pixels** | 842 land cells | 842 land cells | 1,594 – 1,842 land cells | 1,594 – 1,842 land cells |
| **Calibration** | 1993–2016 (24 years) | 1981–2016 (36 years) | 1993–2016 (24 years) | 1993–2016 (24 years) |
| **Validation** | 2017–2025 (9 years) | 2017–2025 (9 years) | 2017–2025 (9 years) | 2017–2025 (9 years) |
| **Output Dir** | `outputs/ecmwf_sep/` | `outputs/ecmwf_v3/` | `outputs/ecmwf_kiremt/` | `outputs/ecmwf_fmam/` |
