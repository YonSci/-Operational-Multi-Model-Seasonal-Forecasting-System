# ECMWF SEAS5 (September Initialized) Operational Pipeline & Verification Checklist

This document details the operational execution plan for downloading **ECMWF SEAS5 initialized in September** (System 51), performing daily bias correction against CHIRPS, running the Dunning et al. (2016) cumulative anomaly season detection (Onset, Cessation, and Season Length/LGP), calibrating probabilistic terciles, generating the **Single-Model Official ILRI Publication Bulletin**, and deploying the outputs.

---

## 📋 Master Execution Checklist

### Phase 1: Environment & Prerequisites
- [x] **1.1** Verify Python environment & install required packages (`cdsapi`, `geopandas`, `shapely`, `netCDF4`, `xarray`, `scipy`). *(Completed: installed cdsapi 0.7.7, geopandas 1.1.4, shapely 2.1.2 in .venv)*
- [x] **1.2** Verify Copernicus Climate Data Store (CDS) API credentials (`~/.cdsapirc` or environment variables `CDSAPI_URL` & `CDSAPI_KEY`). *(Completed: .cdsapirc verified & client connection validated)*
- [x] **1.3** Verify country boundary shapefile for Kenya land-mask generation (`data/shapefiles/ke/ken_admin0.shp` verified).

### Phase 2: Data Acquisition
- [x] **2.1** Download ECMWF SEAS5 September-initialized forecasts (1993–2026) using `scripts/download_seasonal_forecasts_daily_c3s.py`. *(Completed: All 33 files 1993–2025 downloaded, verified 215 lead days & coordinate bounds)*
- [x] **2.2** Verify CHIRPS daily high-resolution precipitation record covering Kenya domain. *(Completed: verified in data/chirps_pr_ke/ke_chirps_pr_r25_1993_2025.nc)*

### Phase 3: Upstream Daily Bias Correction
- [x] **3.1** Build empirical cumulative distribution functions (CDFs) for ECMWF SEAS5 and CHIRPS over calibration window. *(Completed: member-wise EQM in scripts/process_ecmwf_september.py)*
- [x] **3.2** Apply Empirical Quantile Mapping (EQM) per grid cell and DOY across all ensemble members. *(Completed: vectorized NumPy evaluation across all 842 land pixels)*
- [x] **3.3** Export bias-corrected daily NetCDF: `ECMWF_bc_daily_all_years.nc`. *(Completed: 574 MB file written)*

### Phase 4: Dunning Climatology & Dynamic Season Detection
- [x] **4.1** Compute CHIRPS baseline Short Rains climatology (Window DOY 244 [Sept 1] to DOY 365 [Dec 31]):
  - Daily mean precipitation curve $Q_d$
  - Seasonal window mean $\bar{Q}$
  - Cumulative anomaly curve $C_{\text{clim}}$
  - Climatological boundaries $d_s$ (onset) and $d_e$ (cessation) *(Completed: chirps_Q_bar.nc, chirps_C_clim.nc, chirps_d_s.nc, chirps_d_e.nc written)*
- [x] **4.2** Execute vectorized Dunning cumulative anomaly detection ($A(t)$) across all members, years, and land pixels:
  - Onset DOY: day after $\operatorname{argmin}(A)$
  - Cessation DOY: $\operatorname{argmax}_{t > \text{Onset}}(A)$
  - Season Length (LGP): $\text{Cessation} - \text{Onset}$ *(Completed: ECMWF_onset_doy_all_years.nc, ECMWF_cessation_doy_all_years.nc, ECMWF_lgp_days_all_years.nc)*
- [x] **4.3** Assign and validate quality flags (`FLAG_VALID`, `FLAG_NO_ONSET`, `FLAG_NO_CESSATION`, `FLAG_SHORT_SEASON`). *(Completed: Dunning buffer days 30, min LGP 20 days)*

### Phase 5: Probabilistic Terciles & Skill Calibration
- [x] **5.1** Compute 33.3% ($T_{33}$) and 66.7% ($T_{67}$) tercile boundaries from CHIRPS calibration (1993–2016). *(Completed: minimum 12 valid years threshold)*
- [x] **5.2** Compute raw ensemble tercile probabilities ($P_{\text{BN}}$, $P_{\text{NN}}$, $P_{\text{AN}}$). *(Completed)*
- [x] **5.3** Compute verification scores:
  - Ranked Probability Score (RPS) and Climatological RPS ($RPS_{\text{clim}}$)
  - Ranked Probability Skill Score (RPSS)
  - Hit Rate (HR) *(Completed: rpss_onset_val.nc, hitrate_onset_val.nc, etc.)*
- [x] **5.4** Optimize linear pooling parameter $\alpha^*$ via grid search minimizing mean RPS over calibration years. *(Completed: alpha_onset.nc, alpha_cessation.nc, alpha_lgp.nc)*
- [x] **5.5** Apply damping: $P_{\text{damped}} = \alpha^* P_{\text{raw}} + (1 - \alpha^*)/3$. *(Completed: probs_damped_onset.nc, probs_damped_cessation.nc, probs_damped_lgp.nc)*

### Phase 6: NetCDF Output Assembly & Storage
- [x] **6.1** Structure and save NetCDF files into `outputs/ecmwf_sep/` conforming to the dashboard loader specifications:
  - `CHIRPS_onset_doy_1981_2025.nc`, `CHIRPS_cessation_doy_1981_2025.nc`, `CHIRPS_lgp_days_1981_2025.nc`
  - `chirps_C_clim.nc`, `chirps_Q_bar.nc`, `chirps_d_s.nc`, `chirps_d_e.nc`
  - `ECMWF_bc_daily_all_years.nc`
  - `ECMWF_onset_doy_all_years.nc`, `ECMWF_cessation_doy_all_years.nc`, `ECMWF_lgp_days_all_years.nc`
  - `probs_damped_onset.nc`, `probs_damped_cessation.nc`, `probs_damped_lgp.nc`
  - `alpha_onset.nc`, `alpha_cessation.nc`, `alpha_lgp.nc`
  - `rpss_onset_val.nc`, `hitrate_onset_val.nc` *(Completed: all 26 files validated in outputs/ecmwf_sep/)*

### Phase 7: Single-Model Official ILRI Bulletin Generation
- [x] **7.1** Test `bulletin_singlemodel_v1.py` with the September-initialized ECMWF SEAS5 data for key monitored sites:
  - KALRO Kiboko, Makueni Farm *(Completed: PNG & PDF generated)*
  - Kapiti Research Station Farm *(Completed: PNG & PDF generated)*
  - Custom user coordinate point *(Completed: PNG & PDF generated)*
- [x] **7.2** Verify visual layout and data sections:
  - Official ILRI Header & ruleset metadata *(Completed: matches publication template)*
  - Locator map & Ensemble Timing Summary table *(Completed: dynamic site coordinates, anomaly, spread)*
  - 25-member cumulative precipitation plume with P10/P90 bands & threshold markers *(Completed: daily EQM-BC plume across DOY 244–365)*
  - Probabilistic tercile bars (BN/NN/AN) + signal confidence badge + season failure gauge *(Completed)*
  - Sowing readiness window (Earliest P10, Optimal P25–P75, Latest P90) + 8-metric agronomic risk matrix *(Completed)*
  - 44-year CHIRPS historical series (1981–2025) with 2025 forecast markers & calendar-date axes *(Completed)*
- [x] **7.3** Generate and verify both A3 vector PDF and 100 DPI PNG outputs. *(Completed: all PDF and PNG pairs validated in outputs/bulletins/)*

### Phase 8: Production Deployment & Live Verification
- [x] **8.1** Update backend loader (`mam_loader.py` or season-configurable loader) and configuration. *(Completed: dynamic ECMWF SEAS5 (Sep) alias, SOND metadata support, and API routing verified)*
- [x] **8.2** Build and verify frontend bundle (`npm run build`). *(Completed: built dist bundle in 42.9s with 0 errors)*
- [ ] **8.3** Deploy commit to GitHub `main` for automated Render & Vercel deployment.
- [ ] **8.4** Verify live API endpoints and download functionality on production URLs.

---

## ⚠️ Problem & Incident Log

| Date / Step | Issue Description | Root Cause | Resolution / Next Action | Status |
|---|---|---|---|---|
| **Step 1.1** | `cdsapi`, `geopandas`, `shapely` missing | Not installed in `.venv` | Installed `cdsapi-0.7.7`, `geopandas-1.1.4`, `shapely-2.1.2` in `.venv`. Verified imports. | ✅ Resolved |
| **Step 1.2** | Missing `~/.cdsapirc` | No CDS API key configured on host machine | Configured `~/.cdsapirc` via safe credentials protocol; CDS client verified. | ✅ Resolved |
| **Step 2.1** | Windows `cp1252` `UnicodeEncodeError` in download script | Box-drawing characters (`\u2500`) unencodable in standard Windows cmd/powershell encoding | Added `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` to `scripts/download_seasonal_forecasts_daily_c3s.py`. | ✅ Resolved |
| **Step 4.1** | Scalar EQM Python iteration loop caused high runtime (~30 min) | Nested loops over 842 pixels × 122 days × 825 members/years doing scalar `np.interp` | Vectorized `_build_qm_transfer` to evaluate `(25, 33)` arrays in single C-level calls and vectorized CHIRPS window slicing. Runtime dropped to <30 seconds. | ✅ Resolved |
| **Step 7.1** | Windows `cp1252` `UnicodeEncodeError` on `\u2713` in `bulletin_singlemodel_v1.py` | Terminal stdout encoding could not map Unicode checkmark | Added `sys.stdout.reconfigure` and replaced with standard ASCII indicators (`[OK]`). | ✅ Resolved |

---

## 🛠️ Step-by-Step Command Reference

### 1. Install Dependencies
```bash
pip install cdsapi geopandas shapely
```

### 2. Configure CDS Credentials (`C:\Users\Admin\.cdsapirc`)
```ini
url: https://cds.climate.copernicus.eu/api
key: <YOUR-CDS-API-KEY>
```

### 3. Run Download Script for September Initialization
```bash
python scripts/download_seasonal_forecasts_daily_c3s.py \
    --models ecmwf \
    --system ecmwf=51 \
    --months 9 \
    --init-day 1 \
    --year-start 1993 \
    --year-end 2026 \
    --variables total_precipitation \
    --north 5.5 --south -5.5 --west 33.0 --east 42.5 \
    --leadtime-days 215 \
    --outdir ./data/seasonal_ecmwf_sep \
    --merge
```
