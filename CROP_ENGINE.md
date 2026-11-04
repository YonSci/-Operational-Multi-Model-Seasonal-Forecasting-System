# Crop Model Engine (experimental)

The crop engine turns the platform's forecast rainfall ensembles into crop growth, yield and risk at the monitored
sites. It sits beside the climate pipeline: it reads that pipeline's outputs and never changes them, and a failure
in the crop engine does not affect the forecasts.

**Status:** pilot (phases P0–P2 of the integration plan, and the P4 Crop outlook tab). One crop model (AquaCrop-OSPy), the six Kenya monitored
sites, the 2026 Short Rains, four maturity classes, two planting rules. **First calibration done (maize and sorghum
against the Kiboko trials), not verified:** results are for development and discussion, not advice.

## What it does

For each forecast run — the seasonal forecast itself (ECMWF SEAS5, Oct 01 + latest observations) and the latest
run of every sub-seasonal and medium-range model — and for each site, variety and planting rule:

1. builds the run's **daily weather** for each of its 25 members (below);
2. takes each member's **sowing date** from the platform's own onset method (the dates the dashboard shows for that run);
3. simulates the crop with **AquaCrop** from 1 Aug to 31 Mar;
4. summarises the members: yield distribution, chance of crop failure, sowing and harvest dates, water-stress days,
   the share re-sown, the yield without water stress (AquaCrop's potential), the weekly canopy cover of the sown
   crops (median and 10th–90th percentiles), and the chance of a below- or above-normal yield compared with a **benchmark** — the same crop, rule and soil
   grown in the observed weather of 1993–2025 (terciles from 1993–2016, as the climate forecasts).

```
python -m crop_engine.run_outlook                       # all runs (2 worker processes)
python -m crop_engine.run_outlook --sources seasonal    # one run
python -m crop_engine.run_outlook --climatology --force # rebuild the benchmark and every run
python -m pytest crop_engine/tests                      # unit tests (synthetic data)
```

Outputs (not committed; `outputs/crop_engine/`): `weather/<run>.nc` (the daily inputs), `results/<run>.json` (every
member's outcome: sowing and harvest dates, yield, yield without water stress, biomass, maximum canopy, water-stress
days, season rain, sowings; the summaries and the canopy band), `results/index.json`, `climatology.json` (the
benchmark, with the same canopy band over the observed seasons).

The daily update runs `python -m crop_engine.run_all --workers 1`: one process per source, so each run's memory is
released before the next. It then writes the **Crop outlook** tab's data, `frontend/public/tracker/data/crop/`
(`crop_engine/dashboard.py`: the latest run of each source and the benchmark, about 0.8 MB), which the daily publish
commits with the other tracker data.

## Crop outlook tab

`frontend/src/components/CropOutlookTab.jsx`, Kenya only. Pick a site, crop, sowing rule and forecast (seasonal,
sub-seasonal or medium-range run) to see:

- headline figures: median yield and the middle 8 in 10 members, the chance of crop failure, the sowing and harvest
  dates (with the share re-sown after a failed start), each against the past seasons, and what water stress costs
  the sown crops (their yield against AquaCrop's yield without water stress);
- the chance of more than each yield, for the forecast members and for the past seasons (1993–2025);
- what happens to the crop: matured, died before maturity, failed to establish, not grown;
- how the canopy develops: the sown crops' canopy cover week by week (median and 8 in 10 band) against the past
  seasons' median;
- every forecast side by side for the same site and crop (with the yield without water stress), each member's
  outcome (re-sown members marked), and the inputs behind the result.

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

They are maturity classes, not cultivars. Maize and sorghum carry Kenyan practice and the trials at the sites
(`parameters` in `varieties.yaml`, used as given after the phenology scaling):

| Variety | Plants /ha | Max. canopy (CCx) | Reference harvest index (HI0) | Basis |
| :--- | ---: | ---: | ---: | :--- |
| Maize (both classes) | 44,444 (75 x 30 cm) | 0.75 | 0.48 (AquaCrop) | Kiboko maize trials: median 4.5, high-input 6.1 dry t/ha |
| Sorghum | 66,667 (75 x 20 cm) | 0.75 | 0.30 | Kiboko 2020 sorghum: median 1.75, best 3.15 dry t/ha, measured HI 0.28 |
| Dry bean | 131,579 (AquaCrop) | 0.99 (AquaCrop) | 0.40 (AquaCrop) | no bean trials near the sites |

AquaCrop's own densities (maize 75,000, sorghum 200,000 /ha) are high-input ones, and its density sets only the
initial canopy, so the maximum canopy is set with it.

## Outcomes of a member

`ok` (sown, matured), `failed_establishment` (died before its canopy reached 5 %: a false start, the seedlings
dried out), `died` (an established crop that died before maturity: canopy collapse under water stress), `too_late`
(sown too late to mature by 31 Mar), `not_sown` (no onset by the rule's search end, 15 Jan). Members not sown or too
late count as zero yield in the risk figures.

**Re-sowing.** After a failed establishment the member is sown again at the next day that meets Agri rule 1's onset
criteria after the seedlings died (`config.RESOW_RULE`, at most `RESOW_MAX` = 1 more sowing, by 15 Jan), as a farmer
re-sows after the next good rain, provided the variety can still mature by 31 Mar. The outcome is then the re-sown
crop's; `sowings` and `first_planting` record it, and the summary's `resown` gives the share of members re-sown.
A `died` crop can still yield: AquaCrop ends the season when the canopy collapses, often late in grain filling. A crop failure is a yield below the variety's threshold (0.5 t/ha
grain; 0.2 t/ha bean). A water-stress day is a day with transpiration below half its potential.

Below / above normal compare a run's yields with the benchmark's terciles. They are left out (null) where a third or
more of the benchmark years are crop failures, since the terciles then do not separate yields; the run's chance of
crop failure is compared with the benchmark's instead (`benchmark_p_failure`).

## Limitations

- Yields are **water-limited**: no nutrient stress, pests, diseases, weeds or management losses. They are an upper
  bound for smallholder fields; the plant densities are the recommended ones, not farmers' (often lower).
- No forecast temperature or radiation yet: after the last ERA5-Land day both are climatology.
- Deterministic weather models are the same forecast in every member, so their near-term spread is zero.
- March rain is a climatological continuation, not a forecast.
- Establishment is very sensitive to the soil water on 1 Aug. ERA5-Land puts it at 4–20 % of the available water at
  most sites (the dry season), so a sowing rain followed by a dry spell often kills the seedlings (re-sown once).
  At Kiboko a fixed 50 % would roughly halve the failures; without soil moisture measurements it is left as is.
- Agri rule 1 finds no onset by 15 Jan in many seasons at the drier sites (Kiboko 15 of 33, Kapiti and El Karama
  12): its "no 7-day dry spell in 21 days" criterion is rarely met there. Farmers sow anyway, so the rule-1 figures
  overstate failure there; the FAO agricultural onset sows every year.
- Sowing dates in cool sites (Kapiti, Maralal): the maturity classes are defined at 21 °C, so a medium maize or
  sorghum sown in November there needs more heat than the season gives before 31 Mar and is counted as too late.
- Soil is a 0.25° average of SoilGrids estimates, not measured; coarse fragments are not yet used.
- The forecast runs have not been verified for crop outcomes; the benchmark comparison is the first step (P3).

## Yield data for calibration and validation (`crop_engine/yields/`)

Two databases, kept apart so a field-scale model is never calibrated against a county average or a modelled yield:

| Database | Sources (downloads in `data/Yield/`, not committed) | Use |
|---|---|---|
| **observations** (plots, trials) | IITA international maize trials (Kiboko 2013: early, extra-early, late entries, days to silking); Kenya soil health data (Alliance Bioversity–CIAT 2026: N-rate and management trials, incl. Kiboko); N2Africa bean trials (western Kenya 2011: sowing, flowering and maturity dates); published tables transcribed in `yields/published/` (Koima et al. 2023, sorghum at Kiboko and Ithookwe) | calibration, site checks |
| **statistics** (areas) | HarvestStat Africa v1.2 (county yields by Long / Short Rains); FAOSTAT (Kenya national, 1961–2024); MapSPAM 2020 (gridded, over each site's 0.25° cell) | regional validation and plausibility only |

```
python -m crop_engine.yields.build        # writes outputs/crop_engine/yields/ (CSV tables + report.md)
```

Each observation keeps what its source states (cultivar, sowing date and its precision, N and P, irrigation,
treatment, replicate) and is linked to its nearest monitored site (within 25 km). Yields are compared as dry matter,
the basis AquaCrop reports: the source's grain moisture where stated (12.5 % in the sorghum paper), otherwise an
assumed one (maize 15 %, sorghum 12.5 %, bean 13 %), flagged. Each site's county comes from the HarvestStat
boundaries. Each run of the build compares the engine's observed-weather benchmark with the county Short Rains
yields, year by year, and with the trials at the sites.

First comparison (November 2026):

- **Too many failed seasons.** 40–100 % of the sown benchmark seasons do not mature: sorghum at Kiboko, for
  example, fails 76–83 % of them, while the county averages about 1 t/ha in the Short Rains and the 2020–21 trial
  averaged 1.8 t/ha (dry). The two failure modes are failed establishment after a false start, which happens even
  in wet seasons (Kiboko, Short Rains 2019, sown 1 Oct), and death before maturity. Re-sowing after a failed
  establishment and a wetter starting soil are the first things to calibrate. (Not matured is not failed: a crop
  AquaCrop ends early under drought often still yields; the dashboard's failure is a yield below the threshold.)
- **Matured seasons yield too much.** Their median is 5–15 times the county average for maize and sorghum (2–4.5
  times for bean). Part of that is the missing nutrient stress: nitrogen trials at Kiboko (2013) range from 1.8 t/ha
  with no N to 7.2 t/ha at 160 kg N/ha. But matured maize medians of 5.4–12.4 t/ha exceed even the best fertilized
  plots there (7.2–7.4 t/ha), so AquaCrop's default maize and sorghum (biomass, harvest index, plant density) also
  need calibrating against the trials.
- **Year-to-year agreement with the county is weak** (detrended r from −0.7 to 0.5); only Kapiti early maize and
  Tana River medium maize (Agri rule 1) reach about 0.5. County averages are not point yields, so this is a
  plausibility check, not a score.
- What is still missing for calibration: sowing dates at the sites (the Kiboko trials give years only), Long Rains
  simulations (several trials are Long Rains), and the underlying plot data of the Kiboko sorghum and maize studies.

### First calibration (November 2026)

Re-sowing after a failed establishment, Kenyan plant densities with their maximum canopy, and a sorghum harvest
index from the Kiboko trial (see *Varieties*). Observed-weather benchmark, Short Rains 1993–2025, before → after
(failure: share of all seasons below the failure yield, as on the dashboard; matured: median of the seasons that
reached maturity, dry t/ha), FAO agricultural onset:

| Site | Early maize failure | Early maize matured | Sorghum failure | Sorghum matured | Trials at the site |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Kiboko | 48 → 42 % | 5.5 → 4.8 | 61 → 52 % | 5.4 → 3.9 | maize median 4.5, high-input 6.1; sorghum 2020 median 1.75, best 3.15 |
| Kapiti | 48 → 42 % | 6.7 → 5.8 | 61 → 64 % | 7.4 → 4.6 | maize 2015 median 0.8 (low-input on-farm trial) |
| El Karama | 39 → 27 % | 8.3 → 7.2 | 46 → 36 % | 9.4 → 5.8 | none |
| Tana River | 76 → 48 % | 2.9 → 4.6 | 76 → 52 % | 2.9 → 2.4 | none |
| Maralal | 33 → 33 % | 10.7 → 9.5 | 39 → 39 % | 8.7 → 5.6 | none |
| Memerush | 55 → 52 % | 4.7 → 4.3 | 64 → 58 % | 3.7 → 2.0 | none |

In the Kiboko trial year (2020) the benchmark sorghum now yields 2.6 t/ha (FAO onset; 2.8 with rule 1, against 4.2
and 4.7 before), between the trial's median and its best entry, as a model without nutrient or disease stress
should. Still open:

- **Medium maize and the cool, wet sites yield too much when they mature**: Kiboko medium maize about 8 t/ha
  against the best trial plot's 7.4; El Karama and Maralal maize 7–13 t/ha, where there are no trials to calibrate
  against. A lower maize harvest index (0.42 takes about an eighth off) needs trials from those sites to justify.
- **Starting soil water** remains ERA5-Land's (4–20 % of the available water on 1 Aug); it is the strongest
  remaining lever on failure (see *Limitations*), and needs soil moisture observations.
- **Agri rule 1 sows no crop in 12–15 of the 33 seasons** at Kiboko, Kapiti and El Karama (see *Limitations*).
- Re-sowing rescues few seasons (1–4 of 33 per site and variety): most failures are crops that die later, under
  mid-season drought, not failed establishments.

## Next phases

P3: hindcast verification (crop forecasts against crops grown in the observed weather, 1993–2016) and calibration
with observed yields and phenology. P5: PCSE/WOFOST, SEAS5 temperature and radiation, bulletins,
Ethiopia.
