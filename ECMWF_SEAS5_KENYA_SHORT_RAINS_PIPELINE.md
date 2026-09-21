# ECMWF SEAS5 Kenya Short Rains (OND: Oct–Dec 2026) Rainfall Terciles Pipeline

## 1. Operational Overview
- **Country Target**: Kenya
- **Variable**: 🌧️ Seasonal Rainfall Terciles ($P(\text{BN}), P(\text{NN}), P(\text{AN})$)
- **Season**: Short Rains (OND: October–December) 2026
- **Valid Period**: October–December 2026
- **Initialization**: September 01, 2026 (ECMWF SEAS5, System 51)
- **Downscaling Strategy**: **Method 2 (Empirical Quantile Mapping against GCM Historical Hindcast Climatology 1993–2016)**
- **Spatial Resolution**: Sovereign $0.25^\circ \times 0.25^\circ$ Kenya Grid ($42 \text{ lats} \times 34 \text{ lons}$, $-4.875^\circ\text{ to }5.375^\circ\text{N}$, $33.625^\circ\text{ to }41.875^\circ\text{E}$)
- **Active Pastoral & Agricultural Domain**: 757 active pixels (`mask_kenya_ond`), 842 total land pixels.

---

## 2. Master Execution Checklist

- [ ] **Phase 1: Environment & Baseline Ingestion**
  - [ ] **1.1** Ingest sovereign Kenya $0.25^\circ$ coordinates and land mask (`chirps_Q_bar.nc` / `lm`: 842 pixels).
  - [ ] **1.2** Load seasonal mask (`outputs/masks/mask_kenya_ond.nc`: 757 active OND pixels).
  - [ ] **1.3** Ingest CHIRPS daily high-resolution precipitation record (`data/chirps_pr_ke/ke_chirps_pr_r25_1993_2025.nc`).
  - [ ] **1.4** Extract calibration period OND (Oct 1–Dec 31, 92 days) totals across 24 historical baseline years (1993–2016).
  - [ ] **1.5** Compute observed tercile thresholds $T_{33}$ and $T_{67}$ for each grid cell.

- [ ] **Phase 2: GCM Ensemble Processing & Method 2 Downscaling**
  - [ ] **2.1** Ingest 51-member ECMWF SEAS5 operational forecast for 2026 (`data/seasonal_pr_downloads_ke/ecmwf_sep/ecmwf_202609_d01.nc`).
  - [ ] **2.2** Ingest 24 historical hindcast years (1993–2016, 25 members/yr = 600 members) from `data/seasonal_pr_downloads_ke/ecmwf_sep/ecmwf_*09_d01.nc`.
  - [ ] **2.3** Extract cumulative precipitation for OND window (lead days 30 to 122) in mm ($tp \times 1000.0$).
  - [ ] **2.4** Spatially regrid both 2026 forecast and historical hindcasts to the Kenya $42 \times 34$ target grid via bilinear interpolation.
  - [ ] **2.5** Compute non-parametric Empirical Quantiles:
    $$q_m = F_{\text{GCM}}^{\text{hist}}(R_{m, 2026}) \quad \text{for } m = 1 \dots 51$$
  - [ ] **2.6** Map quantiles to CHIRPS calibration distribution:
    $$R_{m,\text{corr}} = F_{\text{CHIRPS}}^{-1}(q_m)$$
  - [ ] **2.7** Classify each corrected member against local $T_{33}$ and $T_{67}$ thresholds to derive raw probabilities $P(\text{BN}), P(\text{NN}), P(\text{AN})$.
  - [ ] **2.8** Apply Bayesian linear skill shrinkage ($\alpha^* \approx 0.70$) and normalize to $1.000$:
    $$P^* = \alpha^* P + \frac{1 - \alpha^*}{3}$$
  - [ ] **2.9** Export NetCDF datasets to `outputs/ecmwf_sep/`:
    - `probs_op_2026_rainfall.nc`
    - `probs_damped_rainfall.nc`
    - `t33_rainfall.nc`
    - `t67_rainfall.nc`
  - [ ] **2.10** Repack `backend/demo_data.npz` with keys `ke_ecmwf_p_rf` and `sep_ecmwf_p_rf` (shape: `(3, 42, 34)`).

- [ ] **Phase 3: Backend & API Routing**
  - [ ] **3.1** In `backend/mam_loader.py`, register `"rainfall"` under `MODELS["ECMWF SEAS5 (Sep)"]`.
  - [ ] **3.2** In `backend/mam_loader.py` `get_grid_stats()`, ensure candidate search includes `outputs/ecmwf_sep/probs_op_2026_rainfall.nc`.
  - [ ] **3.3** Verify `/api/grid?variable=rainfall&layer=tercile&season=short_rains` serves valid GeoJSON polygons with `dominant_cat`, `max_prob`, `p_bn`, `p_nn`, `p_an`.

- [ ] **Phase 4: Frontend UI Alignment & Verification**
  - [ ] **4.1** Ensure `🌧️ Rainfall Terciles` layer button activates layer `tercile_rainfall` (`variable='rainfall'`, `layer='tercile'`).
  - [ ] **4.2** Verify Map Legend renders:
    - Title: `ECMWF SEAS5 OND 2026 Probabilistic Forecast`
    - Period: `Valid period: October–December 2026`
    - Neutral note: `No dominant tercile / probabilities below 40%`
    - Non-seasonal note: `Dry Season (Non-Seasonal / Masked)`
  - [ ] **4.3** Compile production frontend bundle (`npm.cmd run build`).

- [ ] **Phase 5: Documentation & Validation Summary**
  - [ ] **5.1** Record categorical breakdown (% Above, % Normal, % Below, % Neutral).
  - [ ] **5.2** Update project `walkthrough.md`.
