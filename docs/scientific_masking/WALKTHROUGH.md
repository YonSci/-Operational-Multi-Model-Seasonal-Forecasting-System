# Walkthrough: Scientific Rainfall Regime & Operational Onset/Cessation System
**Dunning Harmonic Baseline with Ethiopia-Specific Climatological Regime Refinement (EMI Climatology)**

---

## Executive Summary & Scientific Architecture

Following peer review of the seasonal masking and regime classification methodology, the operational system implements a **regime-aware, scientifically defensible operational onset/cessation framework**. The architecture combines the objective harmonic seasonality diagnosis of **Dunning et al. (2016)** with the regional climatological regime definitions established by the **Ethiopian Meteorological Institute (EMI)**:

```
                       ┌────────────────────────────────────────────────────┐
                       │          CHIRPS Daily Climatology                  │
                       │           (WMO Standard Normal: 1991–2020;         │
                       │          Operational Calibration: 1993–2025)       │
                       └─────────────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                       ┌────────────────────────────────────────────────────┐
                       │ Stage 0: Arid / Marginal Climatological Screening  │
                       │ P_ann < 200 mm or (P_ann < 300 mm & P_ond < 30 mm) │
                       │    (Informed by Dunning Low-Rainfall Caution)      │
                       └─────────────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                       ┌────────────────────────────────────────────────────┐
                       │ Stage 1: Dunning Harmonic Decomposition Baseline   │
                       │                 r_H = C_2 / C_1                    │
                       │    (r_H >= 1.0: Biannual; r_H < 1.0: Annual)       │
                       └─────────────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                       ┌────────────────────────────────────────────────────┐
                       │ Stage 2: EMI Climatological Regime Refinement      │
                       │     Type 1: Minor MAM Peak + Major JA Peak         │
                       │     Type 2: Gu (MAM) Peak + Deyr (SON/OND) Peak    │
                       │     (Resolves Belg/Kiremt Amplitude Asymmetry)     │
                       └─────────────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
         ┌───────────────────────────────────────┴───────────────────────────────────────┐
         │                                                                               │
         ▼                                                                               ▼
┌─────────────────────────────────┐                             ┌─────────────────────────────────┐
│  Regime 1: Western Unimodal     │                             │  Regime 2: Bimodal Type 1       │
│  427 pixels (28.8% of land)     │                             │  416 pixels (28.0% of land)     │
│  Product: Annual Wet Season     │                             │  Products: Belg (FMAM) Early    │
│           (Mar/Apr to Oct/Nov)  │                             │            Kiremt (JJAS) Main   │
└─────────────────────────────────┘                             └─────────────────────────────────┘
         │                                                                               │
         ▼                                                                               ▼
┌─────────────────────────────────┐                             ┌─────────────────────────────────┐
│  Regime 3: Bimodal Type 2       │                             │  Regime 0: Arid / Marginal      │
│  578 pixels (38.9% of land)     │                             │  64 pixels (4.3% of land)       │
│  Products:                      │                             │  Status: Insufficient seasonal  │
│   • Spring: Gu/Ganna (MAM)      │                             │          rainfall; no reliable  │
│   • Autumn: Deyr/Hagaya (SON)   │                             │          onset/cessation metrics│
└─────────────────────────────────┘                             └─────────────────────────────────┘
```

---

## 1. Resolution of Peer Review Points

| Issue | Assessment & Context | Scientific Resolution Implemented |
| :--- | :--- | :--- |
| **Methodology Name** | Previous title implied the entire two-stage scheme originated from Dunning. Stage 2 is an Ethiopia-specific refinement. | Formally renamed to **“Dunning Harmonic Baseline with Ethiopia-Specific Climatological Regime Refinement (EMI Climatology)”**. |
| **“Strict $r_H \ge 1$ Fails” Wording** | Overly universal claim; result is specific to Ethiopia’s topography and CHIRPS. | Rephrased to: **“under-detects Type-1 bimodality in this Ethiopia/CHIRPS implementation”**. |
| **Stage-2 Decision Rule** | Hawassa has $r_H = 0.41$, below $0.8$, yet is promoted to Regime 2; promotion rules needed mathematical specification. | Formalized explicit logical formulas for Type 1 and Type 2 promotion based on smoothed dual peaks, prominence $\ge 15\text{ mm}$, and minimum separation $\ge 60\text{ days}$. |
| **Station Count & Terminology** | Previous text referenced 18 stations but table had 20; "100% validation" overstated diagnostic consistency. | Standardized to **20-site representative diagnostic agreement (20/20)**. Reserved "validation" for independent station observations. |
| **Repeated Station Extraction Values** | Identified duplicate values across geographically distant stations in previous synthetic script. | **Audited and rewritten**: Extracted actual CHIRPS grid pixels via nearest-neighbor $(i, j)$ indexing. All 20 stations now have unique, genuine coordinates, $P_{\text{ann}}$, $C_1$, $C_2$, and $r_H$. |
| **JJAS Pixel Arithmetic** | Regime 1 (427) + Regime 2 (416) = 843 eligible pixels, but national JJAS has 832 active pixels. | Clarified that **843 pixels are regime-eligible**, and **832 pixels remain after operational QC filtering** ($P_{\text{JJAS}} \ge 120\text{ mm}$, $R_{\text{JJAS}} \ge 0.20$, $\text{DR} \ge 0.60$, and morphological cleanup). |
| **Regime Mask vs Operational Mask** | Clarified whether secondary QC is applied or just regime membership. | Formally defined: $\text{Operational Mask} = \text{Regime Valid} \land \text{Rainfall Significance} \land \text{DR Valid} \land \text{Spatial QC}$. |
| **Arid Threshold Attribution** | $200/300\text{ mm}$ thresholds are project-defined, not prescribed by Dunning. | Explicitly attributed thresholds to **project-defined screening informed by Dunning’s caution against low-rainfall harmonic instability**. |
| **Climatological Baseline** | CHIRPS 1993–2025 used rather than WMO standard normal. | Documented **WMO standard normal (1991–2020)** as the reference baseline, explaining that **1993–2025** is used operationally to match the ECMWF SEAS5 hindcast archive. |
| **Pastoral Terminology** | "Gu" and "Deyr" are Somali terms; Borana and southern areas use distinct terminology. | Updated UI labels to **“Spring rains — Gu/Ganna (MAM)”** and **“Autumn rains — Deyr/Hagaya (SON–OND)”**, preserving `gu` and `deyr` backend codes. |

---

## 2. Sensitivity Analysis: Dunning Baseline ($r_H \ge 1.0$) vs Two-Stage Refinement

![Sensitivity Analysis: Strict Dunning vs Two-Stage Calibration](figures/sensitivity_rh_comparison.png)

### Why Strict $r_H \ge 1.0$ Under-Detects Type-1 Bimodality in Ethiopia/CHIRPS
Dunning et al. (2016) define annual regimes by $r_H = C_2 / C_1 < 1.0$ and biannual regimes by $r_H \ge 1.0$. In equatorial and pastoral southern/southeastern Ethiopia (Regime 3), the two rainy seasons (Gu/Ganna and Deyr/Hagaya) are relatively symmetric ($P_{\text{Gu}} \sim 100\text{ mm/mo}$, $P_{\text{Deyr}} \sim 80\text{ mm/mo}$). Here, the second harmonic ($C_2$) dominates, yielding $r_H = 1.65 - 35.76$, which Dunning’s criterion detects with high fidelity.

However, in the central and eastern Ethiopian Highlands (Regime 2):
- **Belg Early Peak (April/May)**: $\sim 70 - 140\text{ mm/month}$
- **Kiremt Main Monsoon Peak (July/August)**: $\sim 220 - 320\text{ mm/month}$

Because the Kiremt monsoon delivers 3 to 4 times more rainfall than the Belg season, the annual Fourier fundamental ($C_1$, 12-month period) heavily overshadows the semi-annual harmonic ($C_2$, 6-month period). Consequently, the harmonic ratio drops to $r_H \approx 0.40 - 0.85$. Under a strict $r_H \ge 1.0$ rule, the entire Ethiopian agricultural heartland (Addis Ababa, Wollo, Kombolcha, Tigray, Hawassa) is misdiagnosed as unimodal, which would erroneously suppress the Belg early rainy season.

### Formal Stage-2 Decision Logic
To resolve this asymmetry, the system employs a two-stage classification:
1. **Stage 1 (Harmonic Baseline)**: Computes $C_1, C_2,$ and $r_H = C_2 / C_1$ from 365-day CHIRPS daily climatology. Pixels with $r_H \ge 1.0$ are designated as biannual candidates.
2. **Stage 2 (Climatological Peak Timing & Water-Season Detection)**:
   For transition pixels ($r_H < 1.0$) exhibiting dual climatological peaks:

$$\text{Type 1 (Belg + Kiremt)} = \left[ r_H \ge 0.80 \;\lor\; N_{\text{peaks}} \ge 2 \right] \land [P_1 \in \text{MAM}] \land [P_2 \in \text{JJA/JA}] \land [P_{\text{FMAM}} \ge 50\text{ mm}, R_{\text{FMAM}} \ge 0.10] \land [P_{\text{JJAS}} \ge 120\text{ mm}, R_{\text{JJAS}} \ge 0.25]$$

$$\text{Type 2 (Gu + Deyr)} = \left[ r_H \ge 1.00 \;\lor\; N_{\text{peaks}} \ge 2 \right] \land [P_1 \in \text{MAM}] \land [P_2 \in \text{SON/OND}] \land [P_{\text{JJA}} < 1.3 \cdot P_{\text{OND}}] \land [P_{\text{OND}} \ge 30\text{ mm}, R_{\text{OND}} \ge 0.08]$$

**Peak Detection & Prominence Criteria:**
- **Filtering**: Climatological monthly rainfall is filtered with a 3-month triangular filter ($w = [0.25, 0.50, 0.25]$) to eliminate sub-seasonal synoptic noise.
- **Prominence**: Local maxima require a minimum prominence of $\ge 15\text{ mm/month}$ above the adjacent troughs.
- **Separation**: Primary and secondary peaks must be separated by at least 2 calendar months ($\ge 60\text{ days}$).
- **Hawassa Example**: Hawassa exhibits $r_H = 0.41$ (due to very strong May and July rains), yet possesses dual robust peaks (May: $136.4\text{ mm}$, July: $134.0\text{ mm}$) separated by a distinct June lull ($101.2\text{ mm}$). With $P_{\text{FMAM}} = 379.3\text{ mm}$ ($R_{\text{FMAM}} = 36.1\%$) and $P_{\text{JJAS}} = 491.2\text{ mm}$ ($R_{\text{JJAS}} = 46.8\%$), Hawassa satisfies all Stage-2 criteria and is correctly classified into Regime 2.

---

## 3. Audited 20-Site Representative Diagnostic Agreement

To verify that the classification matches Ethiopian Meteorological Institute (EMI) climatological regimes across the country, 20 representative sites spanning all 4 regimes were audited. Climatology was sampled directly from the nearest CHIRPS 0.25° grid cell:

![20-Site Representative Diagnostic Agreement](figures/station_validation_profiles.png)

### Audited Site Diagnostics (CHIRPS 1993–2025 Nearest Pixel Extraction)

| Station | Requested Coord | Nearest Grid Coord | Grid $(i, j)$ | $P_{\text{ann}}$ | $C_1$ | $C_2$ | $r_H$ | Climatological Regime | Diagnostic Agreement |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Gambella** | 8.25°N, 34.58°E | 8.125°N, 34.625°E | (20, 06) | 1,189 mm | 3.39 | 0.11 | 0.03 | **Regime 1: Western Unimodal** | **Agrees (20/20)** |
| **Assosa** | 10.07°N, 34.53°E | 10.125°N, 34.625°E | (28, 06) | 1,197 mm | 4.21 | 0.60 | 0.14 | **Regime 1: Western Unimodal** | **Agrees (20/20)** |
| **Jimma** | 7.67°N, 36.83°E | 7.625°N, 36.875°E | (18, 15) | 1,599 mm | 3.62 | 0.37 | 0.10 | **Regime 1: Western Unimodal** | **Agrees (20/20)** |
| **Bahir Dar** | 11.60°N, 37.38°E | 11.625°N, 37.375°E | (34, 17) | 1,385 mm | 5.57 | 2.46 | 0.44 | **Regime 1: Western Unimodal** | **Agrees (20/20)** |
| **Gondar** | 12.60°N, 37.47°E | 12.625°N, 37.375°E | (38, 17) | 1,198 mm | 4.57 | 1.77 | 0.39 | **Regime 1: Western Unimodal** | **Agrees (20/20)** |
| **Bedele** | 8.45°N, 36.35°E | 8.375°N, 36.375°E | (21, 13) | 1,811 mm | 5.10 | 0.35 | 0.07 | **Regime 1: Western Unimodal** | **Agrees (20/20)** |
| **Addis Ababa**| 9.03°N, 38.74°E | 9.125°N, 38.625°E | (24, 22) | 1,181 mm | 4.07 | 2.25 | 0.55 | **Regime 2: Bimodal Type 1** | **Agrees (20/20)** |
| **Kombolcha** | 11.08°N, 39.73°E | 11.125°N, 39.625°E | (32, 26) | 1,150 mm | 3.38 | 2.50 | 0.74 | **Regime 2: Bimodal Type 1** | **Agrees (20/20)** |
| **Mekelle** | 13.50°N, 39.47°E | 13.375°N, 39.375°E | (41, 25) | 690 mm | 2.91 | 2.01 | 0.69 | **Regime 2: Bimodal Type 1** | **Agrees (20/20)** |
| **Dire Dawa** | 9.60°N, 41.87°E | 9.625°N, 41.875°E | (26, 35) | 626 mm | 1.21 | 1.01 | 0.84 | **Regime 2: Bimodal Type 1** | **Agrees (20/20)** |
| **Jijiga** | 9.35°N, 42.80°E | 9.375°N, 42.875°E | (25, 39) | 545 mm | 1.21 | 0.77 | 0.64 | **Regime 2: Bimodal Type 1** | **Agrees (20/20)** |
| **Hawassa** | 7.05°N, 38.48°E | 7.125°N, 38.375°E | (16, 21) | 1,050 mm | 1.84 | 0.76 | 0.41 | **Regime 2: Bimodal Type 1** | **Agrees (20/20)** |
| **Arba Minch** | 6.03°N, 37.55°E | 6.125°N, 37.625°E | (12, 18) | 1,002 mm | 0.98 | 1.61 | 1.65 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Goba / Bale**| 7.00°N, 39.98°E | 6.875°N, 39.875°E | (15, 27) | 1,127 mm | 1.07 | 1.88 | 1.76 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Negelle Borana**| 5.33°N, 39.58°E | 5.375°N, 39.625°E | (09, 26) | 667 mm | 0.88 | 2.59 | 2.94 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Yabello** | 4.88°N, 38.09°E | 4.875°N, 38.125°E | (07, 20) | 644 mm | 0.88 | 2.03 | 2.31 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Moyale** | 3.53°N, 39.05°E | 3.625°N, 39.125°E | (02, 24) | 629 mm | 0.70 | 2.16 | 3.08 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Kebri Dehar**| 6.73°N, 44.28°E | 6.625°N, 44.375°E | (14, 45) | 426 mm | 0.06 | 1.99 | 35.76 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Gode** | 5.95°N, 43.58°E | 5.875°N, 43.625°E | (11, 42) | 281 mm | 0.06 | 1.33 | 23.04 | **Regime 3: Bimodal Type 2** | **Agrees (20/20)** |
| **Semera** | 11.79°N, 41.00°E | 11.875°N, 40.875°E | (35, 31) | 264 mm | 0.57 | 0.55 | 0.97 | **Regime 0: Arid / Marginal**| **Agrees (20/20)** |

**Diagnostic Consistency:** 20 / 20 representative sites show diagnostic agreement with documented EMI regional climate regimes.

---

## 4. Operational Masks vs Regime Membership (Pixel Arithmetic)

A key scientific distinction is made between **climatological regime eligibility** and the **final operational masks**:

$$\text{Operational Mask} = \text{Regime Valid} \land \text{Rainfall Significance} \land \text{Detection Rate (DR) Valid} \land \text{Spatial QC}$$

| Product Name | Season Code | Eligible Regime Pixels | Operational Pixels | Active % | Operational Definition & Screening |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Annual Wet Season** | `annual` | Regime 1: **427** | **426 / 1,485** | **28.7%** | Confined strictly to Regime 1 (Western Unimodal). 1 isolated border pixel removed by spatial QC. |
| **Belg Early Rains** | `belg` | Regime 2: **416** | **416 / 1,485** | **28.0%** | $\text{Regime 2} \land P_{\text{FMAM}} \ge 50\text{ mm} \land R_{\text{FMAM}} \ge 0.10 \land \text{DR}_{\text{FMAM}} \ge 0.55$. All 416 pixels meet criteria. |
| **Kiremt Bimodal Onset** | `kiremt` | Regime 2: **416** | **416 / 1,485** | **28.0%** | $\text{Regime 2} \land P_{\text{JJAS}} \ge 120\text{ mm} \land R_{\text{JJAS}} \ge 0.20 \land \text{DR}_{\text{Kiremt}} \ge 0.60$. Bimodal onset domain. |
| **National JJAS Rainfall** | `jjas` | R1 (427) + R2 (416) = **843** | **832 / 1,485** | **56.0%** | $(\text{R1} \lor \text{R2}) \land P_{\text{JJAS}} \ge 120\text{ mm} \land R_{\text{JJAS}} \ge 0.20 \land \text{DR} \ge 0.60$. **11 transitional pixels removed** by rainfall/DR/spatial filtering ($843 - 11 = 832$). |
| **Spring Rains (Gu/Ganna)** | `gu` | Regime 3: **578** | **578 / 1,485** | **38.9%** | $\text{Regime 3} \land P_{\text{FMAM}} \ge 40\text{ mm} \land R_{\text{FMAM}} \ge 0.10 \land \text{DR}_{\text{FMAM}} \ge 0.50$. All 578 pixels meet criteria. |
| **Autumn Rains (Deyr/Hagaya)**| `deyr` | Regime 3: **578** | **578 / 1,485** | **38.9%** | $\text{Regime 3} \land P_{\text{OND}} \ge 30\text{ mm} \land R_{\text{OND}} \ge 0.08 \land \text{DR}_{\text{Bega}} \ge 0.50$. All 578 pixels meet criteria. |
| **Arid / Marginal** | `regime_0` | Regime 0: **64** | **64 / 1,485** | **4.3%** | Screened out: $P_{\text{ann}} < 200\text{ mm}$ or $(P_{\text{ann}} < 300\text{ mm} \land P_{\text{OND}} < 30\text{ mm})$. Flagged: *"No reliable onset/cessation detected"*. |

---

## 5. Climatological Baseline: WMO Standard Normal (1991–2020) vs Operational (1993–2025)

The World Meteorological Organization (WMO) formally defines the period **1991–2020** as the current climatological standard normal. 

In this operational forecast system:
1. **Reference Normal**: 1991–2020 serves as the official baseline for long-term climatological comparison and regime diagnosis.
2. **Operational Calibration Window (1993–2025)**: The operational forecast calibration window spans 1993–2025 because the ECMWF SEAS5 dynamical seasonal hindcast archive commences in January 1993. Aligning the CHIRPS observation window to 1993–2025 ensures an exact one-to-one, 33-year pairing between model hindcast members and observational truth, eliminating artificial sampling bias in onset/cessation bias correction and anomaly estimation.

---

## 6. UI Enhancements & Scientific Transparency

1. **Refined Pastoral Labels**:
   - `Spring rains — Gu/Ganna (MAM)`
   - `Autumn rains — Deyr/Hagaya (SON–OND)`
   Recognizes terminology across both Somali and Borana/southern communities.
2. **Arid / Marginal Screening Tooltip**:
   Clicking or hovering over Semera or any Danakil pixel presents the calibrated scientific advisory:
   > 🏜️ **Arid / Marginal Alert:** Project-defined rainfall screening indicates insufficient and/or unreliable seasonal rainfall for robust onset/cessation estimation. Low-rainfall regions are excluded because harmonic seasonality measures may become unstable or misleading.
3. **Western Unimodal Guidance**:
   Clicking on Jimma or Gambella while viewing Belg or Kiremt displays:
   > 🌾 **Western Unimodal Guidance:** Climatologically an extended Annual Wet Season from spring to autumn (Mar/Apr to Oct/Nov), not a separate Belg early onset. View under Annual Wet Season product.
