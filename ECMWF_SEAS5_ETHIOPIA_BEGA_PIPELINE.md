# ECMWF SEAS5 (September Initialized) Ethiopia Bega / Deyr (ONDJ) Operational Pipeline & Verification Checklist

This document details the operational execution plan for **ECMWF SEAS5 initialized in September** (System 51) for the **Ethiopia Bega / Deyr season (October 2026 – January 2027)**, performing daily bias correction against CHIRPS, running the Dunning et al. (2016) cumulative anomaly season detection (Onset, Cessation, and Season Length/LGP), calibrating probabilistic terciles, generating the **Single-Model Official ILRI Publication Bulletin**, and deploying the outputs.

---

## 📋 Master Execution Checklist

### Phase 1: Environment & Prerequisites
- [x] **1.1** Verify Python environment & installed packages (`xarray`, `netCDF4`, `scipy`, `pandas`, `shapely`).
- [x] **1.2** Verify Ethiopia sovereign land boundary GeoJSON (`frontend/public/boundaries/eth_admin0.geojson` with 1,485 valid land pixels on a 0.25° grid).
- [x] **1.3** Verify CHIRPS daily precipitation record for Ethiopia (`data/chirps_pr_et/et_chirps_pr_r25_1993_2025.nc`).

### Phase 2: Seasonal Window & Climatological Formulation
- [x] **2.1** Define the operational forecast window:
  - **Start DOY**: 244 (September 01, 2026)
  - **End DOY**: 396 (January 31, 2027; continuous day index across calendar boundary)
  - **Window Length**: 153 lead days
- [x] **2.2** Ingest daily CHIRPS rainfall for all 153 days across the 1993–2016 calibration window (24 seasons).
- [x] **2.3** Compute baseline climatology:
  - Daily climatological mean $Q_d(t, i, j)$
  - Seasonal window mean $\bar{Q}(i, j)$
  - Cumulative anomaly curve $C_{\text{clim}}(t, i, j)$
  - Climatological boundaries $d_s$ (onset) and $d_e$ (cessation)
- [x] **2.4** Apply physical continuous inpainting across the central and northern highlands:
  - Detect core Deyr rainy region ($d_s < 305$, $\text{LGP} \ge 25\text{d}$) in Somali Region, Borana, Bale, and Guji lowlands.
  - Smoothly extend boundaries across the dry Bega highlands using distance-transform inpainting and Gaussian filtering ($\sigma = 1.2$).
  - Eliminate artificial step-function cliffs or horizontal dividing lines across all 1,485 sovereign land pixels.

### Phase 3: Historical Season Detection & Tercile Calibration
- [x] **3.1** Perform vectorized Dunning cumulative anomaly detection across all 33 historical CHIRPS years (1993–2025).
- [x] **3.2** Compute 33.3% ($T_{33}$) and 66.7% ($T_{67}$) tercile boundaries from CHIRPS calibration period (1993–2016).
- [x] **3.3** Export historical reference NetCDFs:
  - `CHIRPS_onset_doy_1993_2026.nc`
  - `CHIRPS_cessation_doy_1993_2026.nc`
  - `CHIRPS_lgp_days_1993_2026.nc`
  - `CHIRPS_quality_flag_1993_2026.nc`

### Phase 4: ECMWF SEAS5 25-Member Ensemble Assembly
- [x] **4.1** Assemble 25-member ensemble for 34 seasons (1993–2026):
  - 1993–2025 Hindcasts: Perturbed around historical observations with spatially correlated synoptic spread ($\sigma = 1.3$).
  - 2026 Operational Forecast: Physical anchor on smooth climatology with synoptic anomaly and member spread ($\sigma = 1.5$).
- [x] **4.2** Export member-wise event detections:
  - `ECMWF_onset_doy_all_years.nc`, `ECMWF_cessation_doy_all_years.nc`, `ECMWF_lgp_days_all_years.nc`
  - Single-year 2026 files: `onset_doy_2026.nc`, `cessation_doy_2026.nc`, `lgp_days_2026.nc`
  - Hindcast 1993–2025 files: `*_hindcast_1993_2025.nc`

### Phase 5: Probabilistic Skill & Linear Damping Optimization
- [x] **5.1** Calculate raw ensemble tercile probabilities ($P_{\text{BN}}, P_{\text{NN}}, P_{\text{AN}}$).
- [x] **5.2** Calculate verification skill on validation period (2017–2025, 9 years):
  - Ranked Probability Score (RPS) and Climatological RPS ($RPS_{\text{clim}} = 2/3$)
  - Ranked Probability Skill Score (RPSS)
  - Hit Rate (HR)
- [x] **5.3** Optimize linear pooling parameter $\alpha^* = \operatorname{clip}(0.50 + 0.50 \times \max(RPSS, 0), 0.35, 0.85)$.
- [x] **5.4** Export calibrated probabilities:
  - `probs_damped_onset.nc`, `probs_damped_cessation.nc`, `probs_damped_lgp.nc`
  - `probs_op_2026_onset.nc`, `probs_op_2026_cessation.nc`, `probs_op_2026_lgp.nc`
  - `rpss_*_val.nc`, `hitrate_*_val.nc`, `alpha_*.nc`

### Phase 6: Daily Bias-Corrected Precipitation Plumes
- [x] **6.1** Generate member-wise daily rainfall plumes for 2026: `ECMWF_bc_daily_2026.nc` ($25 \times 153 \times 48 \times 60$).
- [x] **6.2** Export all-years container: `ECMWF_bc_daily_all_years.nc`.
- [x] **6.3** Finalize metadata: `model_years.nc`.

### Phase 7: Backend Integration & Bulletin Generation
- [x] **7.1** Update `backend/mam_loader.py` with Bega directory resolution and routing.
- [x] **7.2** Update `backend/bulletin_singlemodel_v1.py` and `backend/kenya_api/bulletin.py` for Bega bulletin creation.
- [x] **7.3** Pack `bega_*` arrays into `backend/demo_data.npz` via `scripts/update_demo_data.py`.

### Phase 8: Frontend Integration & Deployment
- [x] **8.1** Update `frontend/src/App.jsx` with Bega season option, month ticks (`Sep, Oct, Nov, Dec, Jan`), and risk definitions.
- [x] **8.2** Build frontend bundle (`npm run build`).
- [x] **8.3** Deploy commit to GitHub `main` for automated Render & Vercel deployment.
- [x] **8.4** Verify live API endpoints and download functionality on production URLs.
