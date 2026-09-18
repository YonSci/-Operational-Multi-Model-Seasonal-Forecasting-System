# Implementation Plan: Dunning Harmonic Baseline with Ethiopia-Specific Climatological Regime Refinement (EMI Climatology)

Implement a physically and climatologically grounded seasonal masking and classification system combining **Dunning et al. (2016)** harmonic seasonality diagnosis with **Ethiopian Meteorological Institute (EMI)** regional rainfall regimes:
1. Classifying rainfall regimes via Fourier harmonic baseline ($r_H = C_2 / C_1$) with Stage-2 climatological peak timing refinement **before** masking.
2. Decoupling the Western Ethiopia unimodal wet season from artificial Belg/Kiremt boundaries into an Annual Wet Season product.
3. Resolving the Belg overextension into a genuine Type-1 bimodal highland Belg domain.
4. Restructuring pastoral seasons to **Spring rains — Gu/Ganna (MAM)** and **Autumn rains — Deyr/Hagaya (SON–OND)**, confined to the southeastern lowlands (Regime 3).
5. Establishing a genuine Arid / Marginal category (Regime 0) in Danakil/Afar based on project-defined screening informed by Dunning's caution on low-rainfall harmonic instability.
6. Providing full interactive frontend toggling, regime badges, and contextual tooltips.

---

## User Review & Methodological Framework

> [!IMPORTANT]
> **Key Methodological and Terminology Realignment**:
> 1. **Dunning Harmonic Baseline with Ethiopia-Specific Climatological Refinement**:
>    - Stage 1: Every grid cell is decomposed into annual ($C_1$) and semi-annual ($C_2$) Fourier harmonics to compute $r_H = C_2 / C_1$.
>    - Stage 2: Climatological peak timing and water-season detection resolve the Belg/Kiremt amplitude asymmetry where strict $r_H \ge 1.0$ under-detects Type-1 bimodality.
>    - Cells are categorized into:
>      - **Regime 0 (Arid / Marginal)**: Insufficient/unreliable seasonal rainfall.
>      - **Regime 1 (Western Unimodal)**: Single extended wet season (Feb/Mar to Oct/Nov).
>      - **Regime 2 (Bimodal Type 1 Highlands)**: Belg early rains + June pause + Kiremt main rains.
>      - **Regime 3 (Bimodal Type 2 Pastoral Lowlands)**: Gu/Ganna (MAM) + dry summer (JJA) + Deyr/Hagaya (SON–OND).
> 2. **Belg Mask Correction**:
>    - Restricts Belg onset/cessation strictly to Regime 2 highlands, eliminating the Western unimodal ramp-up and Southern Gu equatorial rains from the Belg mask.
> 3. **Pastoral Terminology Refinement**:
>    - Labels updated to **"Spring rains — Gu/Ganna (MAM)"** and **"Autumn rains — Deyr/Hagaya (SON–OND)"** across backend, frontend, and bulletins.
>    - Confines the Deyr mask to the southern and southeastern pastoral domain (Regime 3), removing western unimodal tail contamination and northern dry harvest plateaus.

---

## Architecture & Code Structure

### 1. Data Pipeline & Mask Computation Engine

#### [`scripts/compute_seasonal_masks.py`](../../scripts/compute_seasonal_masks.py)
- Ingest daily CHIRPS 1993–2025 (`et_chirps_pr_r25_1993_2025.nc`).
- Compute daily climatology $Q(d)$ for $d = 1, \dots, 365$.
- Compute Fourier harmonics:
  $$A_1, B_1, C_1 = \sqrt{A_1^2 + B_1^2} \quad \text{and} \quad A_2, B_2, C_2 = \sqrt{A_2^2 + B_2^2} \quad \Rightarrow \quad r_H = \frac{C_2}{C_1}$$
- Delineate Regimes 1, 2, and 3 across Ethiopia:
  - **Regime 3 (Southern/SE Lowlands)**: $r_H \ge 0.8$, $P_{\text{OND}} \ge 40\text{ mm}$, $R_{\text{OND}} \ge 12\%$, dry summer ($P_{\text{JJA}} < 1.2 \times P_{\text{OND}}$).
  - **Regime 1 (Western Unimodal)**: $r_H < 0.8$ or $(\text{lon} < 37.8^\circ\text{E} \land P_{\text{JJAS}} \ge 250\text{ mm})$, continuous season without dry June drop.
  - **Regime 2 (Bimodal Highlands)**: Central/Northeastern/Eastern highlands with distinct Belg + Kiremt separated by a June drop ($P_{\text{Jun}} / P_{\text{May}} \le 0.6$).
- Construct the refined seasonal masks:
  - `mask_kiremt`: Regime 2 + Regime 1 highlands ($P_{\text{JJAS}} \ge 150\text{ mm}, R_{\text{JJAS}} \ge 25\%, DR \ge 65\%$).
  - `mask_belg`: Regime 2 Highlands *only* ($P_{\text{FMAM}} \ge 70\text{ mm}, R_{\text{FMAM}} \ge 15\%, DR \ge 65\%$).
  - `mask_deyr` (aliased as `mask_bega`): Regime 3 Lowlands *only* ($P_{\text{OND}} \ge 40\text{ mm}, R_{\text{OND}} \ge 12\%, DR \ge 60\%$).
  - `mask_kenya_mam` & `mask_kenya_ond`: Kenya Long & Short Rains masks.
  - `regime_map`: 2D integer map (1: Unimodal West, 2: Bimodal Highlands, 3: Bimodal Lowlands, 0: Arid/Marginal).
- Apply morphological cleanup (`scipy.ndimage.binary_opening` / `label`) to purge isolated single-pixel noise.
- Save to `outputs/masks/seasonal_masks.npz`.

#### [`scripts/update_demo_data.py`](../../scripts/update_demo_data.py)
- Package `mask_kiremt`, `mask_belg`, `mask_deyr`, `mask_bega` (alias for backward compatibility), `mask_kenya_mam`, `mask_kenya_ond`, and `regime_map` (as `int8`) into `backend/demo_data.npz`.
- Ensure total NPZ file size remains strictly $< 75\text{ MB}$ (achieved 73.24 MB).

---

### 2. Backend API & Loader

#### [`backend/mam_loader.py`](../../backend/mam_loader.py)
- Support `"deyr"` season parameter (with `"bega"` and `"ondj"` as aliases).
- Load `regime_map` into `_state["regime_map"]`.
- In `get_pixel_stats(lat, lon, season)`:
  - Look up regime from `regime_map`:
    - `1`: `"Western Unimodal (Single Extended Season)"`
    - `2`: `"Bimodal Type 1 (Belg & Kiremt Highlands)"`
    - `3`: `"Bimodal Type 2 (Gu & Deyr Pastoral Lowlands)"`
    - `0`: `"Arid / Marginal"`
  - Return `regime_id`, `regime_name`, and `is_in_seasonal_zone`.
- In `get_grid_stats()`:
  - Route `"deyr"` / `"bega"` / `"ondj"` to `mask_deyr`.
  - Route `"belg"` / `"fmam"` to the refined `mask_belg`.
  - Route `"kiremt"` / `"jjas"` to `mask_kiremt`.

#### [`backend/kenya_api/grid.py`](../../backend/kenya_api/grid.py)
- Attach `regime_id`, `regime_name`, and `in_season_mask` to each GeoJSON feature's `properties`.
- Include `regime_counts` in the `meta` response.

---

### 3. Frontend UI & Experience

#### [`frontend/src/components/MapPanel.jsx`](../../frontend/src/components/MapPanel.jsx)
- Update tooltip `fmtTip()`:
  - Display rainfall regime badge: e.g. `🏔️ Regime: Bimodal Highlands (Belg & Kiremt)` or `🌾 Regime: Western Unimodal`.
  - Provide tailored advisory when outside the seasonal envelope:
    - In Belg: *"Outside Belg Highland Domain (Belg is specific to Central/Eastern Highlands; Western Ethiopia is Unimodal, Southern is Gu/MAM)"*.
    - In Deyr: *"Outside Deyr Pastoral Envelope (Deyr rainfall is confined to Southern/SE Lowlands; Northern Ethiopia is in dry Bega harvest)"*.
- Interactive Toggle:
  - Label: `🎯 Seasonal Domain Only` vs `🌐 All Domain`.
  - Badge: displays active pixels and regime context.

#### [`frontend/src/App.jsx`](../../frontend/src/App.jsx)
- In `ForecastingTab`:
  - Show a regime badge (`Unimodal`, `Bimodal Highlands`, or `Bimodal Pastoral`).
  - Render a clear climatological notice when selected site is outside the seasonal regime.
- Update headers, navigation, and chart titles to display `Deyr (SON-OND)` instead of `Bega (ONDJ)`.

#### [`frontend/src/components/BulletinModal.jsx`](../../frontend/src/components/BulletinModal.jsx)
- Update season label for Deyr: `Deyr (SON-OND) Pastoral Rains`.

---

## Verification Summary

1. **Regime & Mask Verification**:
   - Sovereign Ethiopia Land Mask: 1,485 pixels.
   - Regime 1 (Western Unimodal): 427 pixels (28.8%).
   - Regime 2 (Bimodal Type 1 Highlands): 416 pixels (28.0%).
   - Regime 3 (Bimodal Type 2 Pastoral Lowlands): 578 pixels (38.9%).
   - Regime 0 (Arid / Marginal): 64 pixels (4.3%).
   - Belg Mask: 416 / 1,485 pixels (28.0%), resolving the previous 86.6% overextension.
   - Kiremt Bimodal Onset Mask: 416 / 1,485 pixels (28.0%).
   - National JJAS Rainfall Mask: 832 / 1,485 pixels (56.0%, 843 eligible minus 11 filtered by rainfall/DR/spatial QC).
   - Spring Rains (Gu/Ganna): 578 / 1,485 pixels (38.9%).
   - Autumn Rains (Deyr/Hagaya): 578 / 1,485 pixels (38.9%).
   - Annual Wet Season: 426 / 1,485 pixels (28.7%).
2. **Audited Station Diagnostic Consistency**:
   - 20 / 20 representative sites show diagnostic agreement with documented EMI regional climate regimes using nearest-pixel CHIRPS climatology.
3. **Demo Data Packaging**:
   - `backend/demo_data.npz` size: **73.24 MB** ($< 80\text{ MB}$ repository limit).
4. **Frontend Build**:
   - Production bundle compiled with zero syntax errors (`built in 11.11s`).
