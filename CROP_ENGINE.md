# Crop Model Engine (experimental)

The crop engine turns the platform's forecast rainfall ensembles into crop growth, yield and risk at the monitored
sites. It sits beside the climate pipeline: it reads that pipeline's outputs and never changes them, and a failure
in the crop engine does not affect the forecasts.

**Status:** pilot (phases P0–P2 of the integration plan). One crop model (AquaCrop-OSPy), the six Kenya monitored
sites, the 2026 Short Rains, four maturity classes, two planting rules. **Not calibrated, not verified:** results are
for development and discussion, not advice.

## What it does

For each forecast run — the seasonal forecast itself (ECMWF SEAS5, Oct 01 + latest observations) and the latest
run of every sub-seasonal and medium-range model — and for each site, variety and planting rule:

1. builds the run's **daily weather** for each of its 25 members (below);
2. takes each member's **sowing date** from the platform's own onset method (the dates the dashboard shows for that run);
3. simulates the crop with **AquaCrop** from 1 Aug to 31 Mar;
4. summarises the members: yield distribution, chance of crop failure, sowing and harvest dates, water-stress days,
   and the chance of a below- or above-normal yield compared with a **benchmark** — the same crop, rule and soil
   grown in the observed weather of 1993–2025 (terciles from 1993–2016, as the climate forecasts).

```
python -m crop_engine.run_outlook                       # all runs (2 worker processes)
python -m crop_engine.run_outlook --sources seasonal    # one run
python -m crop_engine.run_outlook --climatology --force # rebuild the benchmark and every run
python -m pytest crop_engine/tests                      # unit tests (synthetic data)
```

Outputs (not committed; `outputs/crop_engine/`): `weather/<run>.nc` (the daily inputs), `results/<run>.json` (every
member's outcome and the summaries), `results/index.json`, `climatology.json` (the benchmark).

## Inputs

| Input | Source | Notes |
| :--- | :--- | :--- |
| Rain 1–31 Aug | CHIRPS v2 observed (final, then preliminary) | |
| Rain 1 Sep – 31 Dec | the run's joined members (`scripts/forecast_runs.py`) | observed → gap days → weather forecast → SEAS5 |
| Rain 1 Jan – 28 Feb | SEAS5 member, quantile-mapped to CHIRPS (`onset_rules.EXT_CACHE`) | as the Agri rules |
| Rain 1–31 Mar | observed CHIRPS March of calibration year 1993 + (k mod 24) | the SEAS5 October files on disk end on 28 Feb |
| Tmax, Tmin | ERA5-Land at the site (Open-Meteo archive), then the 1993–2016 day-of-year climatology | |
| ET0 | the platform's ERA5-Land FAO-56 ET0, then its climatology | the same as the FAO water balance |
| Soil | SoilGrids 2.0, six layers to 200 cm, at the site's 0.25° cell (sand, clay, organic matter) | AquaCrop's pedotransfer |
| Soil water on 1 Aug | ERA5-Land root-zone soil moisture, as the FAO water balance starts | |
| Sowing date | Agri rule 1 onset; FAO agricultural onset | unchanged outputs of the platform's methods |

Every day carries its source (`precip_source`: obs_final, obs_prelim, gap, forecast, seasonal, climatology;
`tmax_source`, `et0_source`: era5land, climatology), so a result can always be traced to what drove it.
`crop_engine.data.weather.validate` checks each run's inputs (structure, no gaps, value ranges, Tmin ≤ Tmax,
provenance codes) before any simulation.

## Varieties (`crop_engine/varieties.yaml`)

Maturity classes built from AquaCrop's own growing-degree-day crop files, every phenological stage scaled to the
class's maturity at a daily mean of 21 °C (mid-altitude dryland Kenya, where these maturity days are quoted) (canopy growth and decline scaled inversely):

| Variety | AquaCrop crop | Days to maturity at 21 °C | Stands for |
| :--- | :--- | ---: | :--- |
| Early-maturing maize | MaizeGDD | 90 | Katumani / DH-series type dryland maize |
| Medium-maturing maize | MaizeGDD | 120 | mid-altitude hybrid type |
| Sorghum | SorghumGDD | 100 | Gadam type |
| Dry bean | DryBeanGDD | 75 | KAT-series type |

They are not calibrated cultivars. Calibration needs observed yields, sowing dates and crop stages (phase P3).

## Outcomes of a member

`ok` (sown, matured), `failed_establishment` (died before its canopy reached 5 %: a false start, the seedlings
dried out), `died` (an established crop that died before maturity: canopy collapse under water stress), `too_late`
(sown too late to mature by 31 Mar), `not_sown` (no onset by the rule's search end, 15 Jan). Members not sown or too
late count as zero yield in the risk figures. A crop failure is a yield below the variety's threshold (0.5 t/ha
grain; 0.2 t/ha bean). A water-stress day is a day with transpiration below half its potential.

Below / above normal compare a run's yields with the benchmark's terciles. They are left out (null) where a third or
more of the benchmark years are crop failures, since the terciles then do not separate yields; the run's chance of
crop failure is compared with the benchmark's instead (`benchmark_p_failure`).

## Limitations

- Yields are **water-limited**: no nutrient stress, pests, weeds or management losses, and AquaCrop's default plant
  density. They are an upper bound for smallholder fields.
- No forecast temperature or radiation yet: after the last ERA5-Land day both are climatology.
- Deterministic weather models are the same forecast in every member, so their near-term spread is zero.
- March rain is a climatological continuation, not a forecast.
- Establishment is very sensitive to the soil water on 1 Aug. ERA5-Land puts it at 4–20 % of the available water at
  most sites (the dry season), so a sowing rain followed by a dry spell often kills the seedlings. No re-sowing yet.
- Sowing dates in cool sites (Kapiti, Maralal): the maturity classes are defined at 21 °C, so a medium maize or
  sorghum sown in November there needs more heat than the season gives before 31 Mar and is counted as too late.
- Soil is a 0.25° average of SoilGrids estimates, not measured; coarse fragments are not yet used.
- The forecast runs have not been verified for crop outcomes; the benchmark comparison is the first step (P3).

## Next phases

P3: hindcast verification (crop forecasts against crops grown in the observed weather, 1993–2016) and calibration
with observed yields and phenology. P4: Crop Outlook tab. P5: PCSE/WOFOST, SEAS5 temperature and radiation, bulletins,
Ethiopia.
