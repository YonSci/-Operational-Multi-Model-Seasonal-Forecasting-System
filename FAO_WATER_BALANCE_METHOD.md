# FAO water balance: onset, cessation and length of growing period

The platform's fifth onset method for the Kenya Short Rains, next to Dunning and Agri rules 1–3. It follows FAO
crop-water-requirement and soil-water-balance principles (FAO Irrigation and Drainage Paper 56): rainfall is set
against atmospheric demand (ET0), the crop's water need (ETc = Kc × ET0) and the water the root zone can hold,
instead of a fixed rainfall threshold.

Code: `scripts/fao_water_balance.py` · settings: `config/fao_water_balance.yaml` · validation: `scripts/fao_validate.py`

## Five dates, never interchangeable

| Output | Meaning | Test (defaults) |
|---|---|---|
| `rainfall_onset` | effective rainfall begins | first wet day (≥ 1 mm) from which rain over the next 10 days ≥ 0.5 × ET0 over them |
| `agricultural_onset` | sustained crop-available moisture begins | rain over 10 days ≥ 0.5 × ET0, **and** PAW/TAW ≥ 0.20 on that day and the next 4, **and** no run of 7 days with PAW/TAW < 0.20 in the following 21 days (otherwise the candidate is rejected as a false onset) |
| `rainfall_cessation` | effective rainfall ends | first day (from 1 Nov, after rainfall onset) from which rain < 0.5 × ET0 in two consecutive 10-day windows |
| `agricultural_cessation` | crop-available moisture can no longer sustain crop water demand | first day of 7 consecutive days with PAW/TAW < 0.20, ETa/ETc < 0.50 and a 10-day rain deficit (P < 0.5 × ET0 over the 10 days ending that day) |
| `crop_water_cessation` | agricultural end-of-season indicator: rain no longer meets the crop's requirement | first day after the climatological rainfall peak from which rain over 21 days < 0.5 × ETc over them, with PAW/TAW falling below 0.20 within them |

Season lengths, each from its own pair of dates:

- `rainfall_LGP_days` = rainfall cessation − rainfall onset + 1
- `agricultural_LGP_days` = agricultural cessation − agricultural onset + 1
- `crop_water_LGP_days` = crop-water cessation − agricultural onset + 1

The sequence the definitions follow:

- **Start of season:** effective rainfall begins → soil-water storage increases → the crop-establishment moisture
  threshold is reached → moisture persists → **agricultural onset**.
- **End of season:** rainfall deficit begins → P/ET0 falls below 0.5 (**rainfall cessation**) → soil-water reserves
  decline → crop water stress increases (Ks < 1) → ETa/ETc declines → PAW approaches critical levels →
  **agricultural cessation**.

A rainfall onset can be a false start that the agricultural onset ignores. Rainfall cessation usually comes before
agricultural cessation, because the soil keeps supplying water after the rains stop.

## Physics (FAO-56)

- **ET0:** FAO-56 Penman-Monteith (Eq. 6), from ERA5-Land daily Tmax and Tmin, dewpoint (ea), 10 m wind (converted to
  2 m, Eq. 47), solar radiation Rs and surface pressure (γ, Eq. 8).
  - Rn = 0.77 Rs − Rnl (Eqs. 38–39), with Rso from elevation (Eq. 37). G = 0 for daily steps.
  - T = (Tmax + Tmin)/2 (Eq. 9).
  - Checked against FAO-56 Example 18: 3.88 vs 3.9 mm/day.
- **ETc = Kc × ET0:** Kc by growth stage (initial, development, mid-season, late) from the planting day, which is the
  agricultural onset; Kc_ini applies before it.
- **TAW = 1000 (θFC − θWP) Zr:** θFC and θWP averaged over the rooting depth Zr. **RAW = p × TAW**, where p is
  adjusted for ETc (FAO-56 Table 22 note: p = p_table + 0.04 (5 − ETc), limited to 0.1–0.8).
- **Water stress:** Ks = 1 while the depletion Dr = TAW − SW ≤ RAW, and (TAW − Dr)/(TAW − RAW) beyond, kept in 0–1.
  ETa = Ks × ETc, with Ks from the previous day's depletion (FAO-56 ch. 8).
- **Daily bucket:** SW_t = SW_t−1 + P_eff − ETa − runoff − drainage, kept within 0 ≤ SW ≤ TAW.
  - Rain refills the root zone first; water above TAW leaves as drainage; ETa then depletes the store.
  - SW is the plant-available water above θWP, so PAW = SW and PAW_fraction = SW/TAW.
  - Runoff is off by default. A same-day infiltration cap can be configured (`water_balance.runoff`), and more
    advanced runoff or infiltration can be added in the same place.
- **Two passes per season:**
  1. With Kc_ini throughout, to find the agricultural onset. The 21-day false-onset look-ahead lies inside the
     crop's initial stage, so Kc_ini is the crop's own Kc there.
  2. With the crop Kc curve from that onset, giving ETc, ETa, Ks and PAW for the cessation tests.

All windows are forward-looking ([t, t+w−1]), except the 10-day rain deficit in the agricultural-cessation test, which
looks back over the days that caused the stress.

## Data

| Input | Source | Processing |
|---|---|---|
| Rainfall | **CHIRPS v3** daily (`scripts/fao_download_chirps_v3.py`) | Final `rnl` record (ERA5 used to split CHIRPS3 pentads into days), 1993 on, from Google Earth Engine (`UCSB-CHC/CHIRPS/V3/DAILY_RNL`, 0.05° averaged 5 × 5 onto the 0.25° cells). This is identical to CHC's own 0.25° files (checked: max difference 0.000), and it avoids the slow CHC server. Days after the final record come from the CHC preliminary `sat` 0.05° files, Kenya window only. |
| Meteorology | **ERA5-Land** via Google Earth Engine (`scripts/fao_era5land_gee.py`) | `ECMWF/ERA5_LAND/DAILY_AGGR`: Tmax, Tmin, dewpoint, Rs (daily sum), surface pressure, soil water layers 1–3. Wind speed from `ECMWF/ERA5_LAND/HOURLY` (speed each hour, then the daily mean; the daily-mean components underestimate it by ~8% over Kenya). Sampled on a 0.05° grid nested in the 0.25° cells; ET0 computed there, then averaged over land pixels. The same data from the Copernicus CDS: `scripts/fao_download_era5land.py` (slower when the CDS queue is long). |
| Soil | **SoilGrids 2.0** sand, clay, organic carbon, coarse fragments (`scripts/fao_soilgrids.py`) | SoilGrids has no water-retention layers, so θFC (−33 kPa) and θWP (−1500 kPa) come from the Saxton & Rawls (2006) pedotransfer equations per layer (0–5 … 100–200 cm), reduced for coarse fragments. Read at ~1 km and averaged to 0.25°. Kenya mean available water: ~100–108 mm per metre. |
| Initial soil water | ERA5-Land 0–100 cm soil moisture | On 1 Aug: relative wetness between the cell's 2nd and 98th percentiles (1993–2016) × TAW. |
| Forecast rainfall | ECMWF SEAS5 1 Oct members (25 hindcast, 51 operational; 25 used), 151 days to 28 Feb | Quantile-mapped to CHIRPS v3 per cell and day (CHIRPS pool: 1993–2016, ±7 days; model pool: same day, all members). |
| Forecast ET0 | ERA5-Land ET0 climatology, 1993–2016 per calendar day, ±7-day smoothed | The same for every member; ET0 varies far less from year to year than rainfall. |

All inputs are on the platform's 0.25° Kenya grid (42 × 34 cells; land cells only).

The other four methods use CHIRPS v2, and the SEAS5 members they use are calibrated to v2. This method uses
CHIRPS v3 throughout: its observations, its terciles and its own bias-corrected members.

## Crops

Set in `config/fao_water_balance.yaml`:

| Crop | Kc (initial / mid / end) | Stage days (initial / development / mid / late) | Zr | p | Source |
|---|---|---|---|---|---|
| `maize` (default) | 0.30 / 1.20 / 0.60 | 20 / 35 / 40 / 30 | 1.0 m | 0.55 | FAO-56 Tables 11, 12 and 22 |
| `rangeland_grass` | 0.30 / 0.75 / 0.75 | 10 / 20 / 90 / 30 | 1.0 m | 0.60 | FAO-56, extensive grazing |
| `reference` | 1.0 throughout | — | 1.0 m | 0.50 | generic reference-crop mode (ETc = ET0) |

## Modes

**Historical:** `python scripts/fao_water_balance.py historical`

- Runs CHIRPS v3, ERA5-Land and SoilGrids for every season from 1993.
- Writes `outputs/fao_wb/historical/fao_wb_seasons.nc`, with these per year and cell:
  - the five dates (`*_doy`) and the aliases `onset_DOY` and `cessation_DOY` (both agricultural);
  - the three LGPs, `false_onsets_rejected` and `flags`;
  - `TAW_mm`, `theta_FC`, `theta_WP` and `climatological_peak_doy`.
- Writes `daily_<year>.nc` with these daily fields: `PAW_mm`, `PAW_fraction`, `ET0_daily`, `ETc_daily`, `ETa_daily`,
  `Ks`, `Kc`, `drainage_mm`, `rainfall_to_ET0_ratio`, `rainfall_to_ETc_ratio` (10-day trailing) and `precip`.

**Forecast:** `python scripts/fao_water_balance.py forecast outputs/ecmwf_oct_obs_latest`

1. The observed water balance (CHIRPS v3, ERA5-Land ET0) runs from 1 Aug, initialised from ERA5-Land soil
   moisture, up to the day before the forecast starts: 30 Sep, or the latest CHIRPS v3 day for "+ latest obs".
2. Every member then continues the bucket with its own rainfall and the ET0 climatology:
   SW_t+1,m = SW_t,m + P_t,m − ETa_t,m − runoff_t,m − drainage_t,m.
3. Onset and cessation are found separately for each member.
4. Results go to `<run>/fao_wb_<agricultural|rainfall|cropwater>/`, in the same layout as the Agri rules:
   - members, terciles of the CHIRPS v3 record, calibrated probabilities, RPSS and hit rates;
   - `method.json`;
   - for the latest year, `paw_outlook.nc`: PAW/TAW 10th, 50th and 90th percentiles of the members, and
     P(PAW/TAW < 0.20) by day.

Members with no onset or cessation by the search end count as **later** than any date, not as missing. Medians,
percentiles and terciles therefore stay honest when many members have none.

Where the CHIRPS v3 record has no spread (33rd = 67th percentile), there is no tercile forecast: probabilities and
skill are left empty. This happens where the onset falls on the first search day (15 Aug) in most years, because the
soil is still wet from the long rains or August rains, as in western Kenya and on the coast. Those dates carry flag 512.

## Dashboard

Method selector: **FAO water balance**, with a **Definition** picker:

- **Agricultural** (default): agricultural onset, agricultural cessation and agricultural LGP.
- **Rainfall:** rainfall onset, rainfall cessation and rainfall LGP.
- **Crop-water:** agricultural onset, crop-water cessation and crop-water LGP.

The summary cards carry the definition's own names, for example "Agricultural onset". Maps, probabilities, skill and
the bulletin follow the selected definition.

A panel shows the chance that this definition's onset or cessation has happened by today and within 7, 14 and 21
days. It also shows the PAW/TAW outlook: the members' median and 10–90% range, with the 0.20 critical level. The
median date is a summary of the members, not a deterministic event date.

The Short Rains Tracker lists FAO agricultural, FAO rainfall and FAO crop-water next to Dunning and the Agri rules.

## Flags

The `flags` variable is a bitmask, also in the attribute `flags.meaning`:

| Bit | Flag |
|---|---|
| 1 | no rainfall onset |
| 2 | no agricultural onset |
| 4 | false onset rejected (at least one) |
| 8 | no rainfall cessation |
| 16 | no agricultural cessation |
| 32 | no crop-water cessation |
| 64 | insufficient input data (> 5% of days missing) |
| 128 | incomplete season (data end before 28 Feb) |
| 256 | soil parameters unavailable |
| 512 | onset on the first search day (15 Aug): the soil is already wet from the long rains or August rains, as in western Kenya and on the coast; the date marks a season already under way, not a short-rains onset |

## Validation

Run `python scripts/fao_validate.py`; it writes `outputs/fao_wb/validation/metrics.csv` and `validation_report.md`.
Each comparison reports bias, MAE, RMSE, correlation and the share within ±7 and ±14 days:

| Group | Comparison |
|---|---|
| A | SEAS5 hindcast ensemble median against the same definition on observed CHIRPS v3, CAL 1993–2016 and VAL 2017–2024 |
| B | FAO agricultural onset and cessation against the rainfall-only 20 mm rule (Agri rule 1) and against the FAO rainfall dates |
| C | the bucket's daily PAW/TAW against ERA5-Land 0–100 cm relative wetness; an ERA5-Land soil-moisture onset (same threshold and persistence) against the agricultural onset |
| D | share of onsets inside the FAO GIEWS short-rains maize planting window for Kenya (October–November) |
| E | dekadal ETa against WaPOR v3 AETI (300 m, 2018 on). WaPOR measures the actual land cover's ET, so correlation is the meaningful measure here. |
| F | your own reference dates: observed planting dates, station-derived onsets, KMD or ICPAC onset and cessation reports |

For group F, put the dates in `validation/reference_dates.csv` with columns
`lat,lon,year,onset_date,cessation_date,source`.

Not available in this setup:

- **Station rainfall and observed planting dates:** none on hand; use group F.
- **GLEAM:** needs a registered account.
- **SMAP root-zone soil moisture:** 9 km, 3-hourly files through Earthdata. Large, but it can be added the same way
  as group C.

## Operations

`scripts/update_forecast.py` (the daily task) runs these steps:

1. Fetch new CHIRPS v3 days.
2. Try an ERA5-Land top-up from Earth Engine, for at most 45 minutes. Days ERA5-Land doesn't have yet (it runs about
   5 days behind) use the ET0 climatology. The Earth Engine project comes from `EE_PROJECT`, else
   `~/.config/earthengine/project.txt`.
3. When CHIRPS v3 has advanced, re-run this season's observed water balance and the "+ latest obs" forecast.
4. Repack the methods for the hosted API (`pack_onset_rules.py`).

## Limitations

- **CHIRPS v3 daily:** a pentadal product split into days (ERA5 or IMERG timing), so single days are approximate.
  The 5–10-day windows are less affected.
- **Lag:** CHIRPS v3 preliminary runs about a week behind real time, so "+ latest obs" uses observations to that day.
- **Soil parameters:** θFC and θWP come from a pedotransfer function, not measured retention. Fixed Zr; no root
  growth, no capillary rise, no runoff by default.
- **Forecast ET0:** climatology, so year-specific heat or cloud anomalies in the forecast period are not represented.
- **Crop choice:** for the livestock sites (rangeland), set `crop: rangeland_grass` in the configuration.
