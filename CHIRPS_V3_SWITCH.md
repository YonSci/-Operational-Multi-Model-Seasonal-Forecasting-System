# CHIRPS v2 → v3: the platform's observed rainfall record

From **26 Nov 2026** the Short Rains products use **CHIRPS v3.0** daily rainfall instead of CHIRPS v2.0. The Climate
Hazards Center (CHC) ends CHIRPS v2 production after December 2026. Its v2 preliminary feed was already running a
week behind v3's in late November 2026.

## Which CHIRPS v3

CHIRPS v3 is made as 5-day (pentad) totals. CHC's daily product splits each pentad into days, in two versions:

| Product | Daily timing from | Final record | Light-rain days |
|---|---|---|---|
| `sat` | IMERG (satellite) | 1998 on | fewer |
| `rnl` | ERA5 (reanalysis) | 1981 on | about twice v2's (OND, > 1 mm) |

The platform uses **`sat` from 1998** and **`rnl` for 1993–1997**, which `sat` does not cover. This keeps the
1993–2016 calibration period. Reasons for `sat`:
- Its preliminary days (the latest weeks) are `sat` in both products, so the record has one timing throughout.
- It has about a quarter fewer days above 1 mm than `rnl`.
- Both give the same totals and almost the same forecasts (see below).

A cell is the mean of its 0.05° land pixels. Before the switch, a preliminary day dropped a whole coastal cell when
one of its pixels was sea; that is now fixed.

## What changes

The comparison below runs the seasonal step on each record, with observations to 15 Nov 2026 (v2: CHIRPS v2; v3:
`rnl`, or `sat` with `rnl` before 1998). It covers 842 land cells.

| | v2 | v3 `rnl` | v3 `sat` |
|---|---|---|---|
| OND rain, 1998–2025 mean | 223 mm | 237 mm | 237 mm |
| OND days > 1 mm | 21% | 40% | 31% |
| OND days > 5 mm | 13% | 14% | 13% |
| Dunning onset found (cell-years) | 85% | 74% | 74% |
| Validation RPSS, onset / cessation / LGP | 0.75 / 0.08 / 0.24 | 0.88 / 0.07 / 0.34 | 0.88 / 0.07 / 0.34 |

- v3 is about 7–11% wetter than v2, and its season totals follow v2's from year to year (r = 0.93–0.95).
- v3 adds more rain in wet years than in dry ones: OND totals are +9% in a cell's wettest third of years and −4% in
  its driest third. This fits its gauge-undercatch correction, which grows with the rain.
- **Dunning finds fewer onsets.** A Dunning onset is the day after the minimum of the cumulative anomaly against the
  cell's climatological daily mean. In a dry year the anomaly can fall to the end of the window, and then there is
  no onset. v3's climatological mean is higher relative to dry years, so more dry years end that way (85% → 74% of
  cell-years). The climatological season start and end barely move (median shift 0 days). The rule-based methods
  use fixed thresholds instead, and with v3 they find more seasons, not fewer (below).
- Part of the higher RPSS may come from IMERG or ERA5 timing resembling model rain, rather than better forecasts.

What the switch does to the forecast of 23 Nov 2026 (observations to 20 Nov), live v2 against the branch on v3:

| Method | Same most likely category | Seasons found in the record (v2 → v3) | Validation RPSS (v2 → v3) |
|---|---|---|---|
| Dunning onset / cessation / LGP | 59% / 55% / 53% of cells | 85% → 74% | 0.80 → 0.91 / 0.10 → 0.09 / 0.27 → 0.36 |
| Planting onset (20 mm) | 52% | 70% → 74% | |
| Agri rule 1 onset / cessation / LGP | 56% / 48% / 58% | 48% → 64% | 0.78 → 0.92 / 0.46 → 0.50 / 0.76 → 0.70 |
| Agri rule 2 | 56% / 48% / 57% | 57% → 72% | 0.80 → 0.92 / 0.50 → 0.55 / 0.75 → 0.66 |
| Agri rule 3 | 58% / 55% / 56% | 62% → 70% | 0.77 → 0.90 / 0.65 → 0.65 / 0.67 → 0.66 |
| FAO water balance (agricultural) | 92% / 87% / 90% | 87% → 88% | 0.92 → 0.92 / 0.31 → 0.32 / 0.49 → 0.49 |

The FAO water balance changes least because it already used CHIRPS v3 (`rnl`).

## How it works

`scripts/regions.py` picks the record from the `CHIRPS_VERSION` environment variable: `v3` (the default) or `v2`.
Every script that reads CHIRPS takes its paths from there:

| | `v3` | `v2` |
|---|---|---|
| History, 1993–2025 | `data/chirps_v3_daily/chirps_v3_p25_<region>_1993_2025.nc` | `data/chirps_pr_<cc>/<cc>_chirps_pr_r25_1993_2025.nc` |
| This year's observed days | `data/chirps_v3_daily/chirps_v3_p25_<region>_<year>.nc` (final, then preliminary; `source` per day) | final p25 file + preliminary days |
| FAO water balance | the same record | its own `rnl` files, `data/chirps_v3/` |

- **Downloads.** `scripts/fao_download_chirps_v3.py` downloads every year from Earth Engine (`UCSB-CHC/CHIRPS/V3/DAILY_SAT`, `DAILY_RNL`), or from the CHC server with `--source chc`; `--history` writes the 1993–2025 file. The daily update fetches this year's file first, and its last day is the observation cut-off.
- **Rebuilds when the record changes.** The daily update rebuilds what was made from another record:
  - the latest-observations run;
  - the fixed 1 Oct runs `ecmwf_oct` and `ecmwf_oct_obs`, with their onset rules (`chirps_record.json` in each run);
  - every year of the FAO water balance (`outputs/fao_wb/run_meta.json`);
  - the Jan–Feb extension and the FAO SEAS5 bias correction, whose caches record their CHIRPS version.
- **Crop engine.** Its benchmark hashes include the record from `v3` on, so its climatologies and map benchmarks are rebuilt.
- **Data status.** `backend/data_status.json` names the record in use (`observations`).

**Rollback.** Set `CHIRPS_VERSION=v2` for the daily task. Every path and output is then as before the switch:
checked, all 504 output files of the daily steps are identical to `main`'s, and `rain_stats.npz` is too. The
products are rebuilt again on the next run.

## Not moved

These products still use CHIRPS v2 and keep their own consistent v2 climatologies:
- the Long Rains (MAM) products;
- the 1 Sep runs (`ecmwf_sep_demo`, `backend/demo_data.npz`);
- the one-off scripts (`process_method2_*`, `compute_seasonal_masks.py`, `generate_*`, Ethiopia's Kiremt/FMAM/Bega).

## Follow-up

- **Crop calibrations.** The bean calibration and the sites' soil nitrogen were fitted with v2 weather. Refit them on v3 (`crop_engine/calibration/bean.py` now reads the record in use).
- **Ethiopia.** Download Ethiopia's v3 record before the Deyr inputs are built (`fao_download_chirps_v3.py --region ethiopia_deyr --history`).
- **Dunning in dry years.** If the extra "no onset" years matter for users, report them as failed seasons on the maps.
