# Crop Model Engine (experimental)

The crop engine turns the platform's forecast rainfall ensembles into crop growth, yield and risk at the monitored
sites. It sits beside the climate pipeline: it reads that pipeline's outputs and never changes them, and a failure
in the crop engine does not affect the forecasts.

**Status:** pilot (phases P0–P2 of the integration plan, and the P4 Crop outlook tab). One crop model (AquaCrop-OSPy), the six Kenya monitored
sites, the 2026 Short Rains, four maturity classes, two planting rules. **Early maize calibrated (phenology and harvest
index, calibration sets kiboko_v2 and kiboko_v3), the other classes set against the Kiboko trials; not verified:** results are for development and discussion, not advice.

## What it does

For each forecast run — the seasonal forecast itself (ECMWF SEAS5, Oct 01 + latest observations) and the latest
run of every sub-seasonal and medium-range model — and for each site, variety and planting rule:

1. builds the run's **daily weather** for each of its 25 members (below);
2. takes each member's **sowing date** from the platform's own onset method (the dates the dashboard shows for that run);
3. simulates the crop with **AquaCrop** from 1 Aug to 28 Feb (the FAO water balance's season: its cessation search end);
4. summarises the members: yield distribution, chance of crop failure, sowing and harvest dates, water-stress days,
   the share re-sown, the yield without water stress (AquaCrop's potential), the weekly canopy cover of the sown
   crops (median and 10th–90th percentiles), and the chance of a below- or above-normal yield compared with a **benchmark** — the same crop, rule and soil
   grown in the observed weather of 1993–2025 (terciles from 1993–2016, as the climate forecasts).

```
python -m crop_engine.run_outlook                       # all runs (2 worker processes)
python -m crop_engine.run_outlook --sources seasonal    # one run
python -m crop_engine.run_outlook --climatology --force # rebuild the benchmark and every run
python -m pytest crop_engine/tests                      # unit tests (synthetic data)
python -m crop_engine.calibration.run --set kiboko_v1 --benchmark   # a calibration set (see Calibration sets)
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
sub-seasonal or medium-range run). The tab starts from the dashboard's own choices — the forecast type and model,
the onset method when it is also a sowing rule (Agri rule 1, FAO agricultural), the map's site — and says so in a
notice whenever it cannot follow one: a seasonal run other than Oct 01 + latest obs (the only one simulated), a
climate onset method (Dunning, rules 2–3), a forecast without a crop run, another season, or a map location that is
not a crop site (the nearest site is shown, with its distance). It shows:

- headline figures, each against the **simulated past seasons** (AquaCrop in the observed weather of 1993–2025, not
  measured yields): the chance of a **sowing opportunity** under the rule (with the sowing dates and the share
  re-sown), the **yield if sown** (median, 8 in 10 sown crops, and the yields **measured** in trials at the site),
  the **crop failure if sown** (and the share that failed to establish), and the harvest; then the all-members
  figures (no crop counted as no yield), model errors, and what water stress costs the sown crops (their yield
  against AquaCrop's yield without water stress);
- the chance of more than each yield, for the forecast members and for the simulated past seasons;
- what happens to the crop: matured, died before maturity, failed to establish, not grown;
- how the canopy develops: the sown crops' canopy cover week by week (median and 8 in 10 band) against the past
  seasons' median;
- every forecast side by side for the same site and crop (sowing opportunity, yield and failure if sown, yield
  without water stress), with the simulated past seasons and the measured trials as reference rows; each member's
  outcome (re-sown members marked); and the inputs behind the result.

## Inputs

| Input | Source | Notes |
| :--- | :--- | :--- |
| Rain 1–31 Aug | CHIRPS v2 observed (final, then preliminary) | |
| Rain 1 Sep – 31 Dec | the run's joined members (`scripts/forecast_runs.py`) | observed → gap days → weather forecast → SEAS5 |
| Rain 1 Jan – 28 Feb | SEAS5 member, quantile-mapped to CHIRPS (`onset_rules.EXT_CACHE`) | as the Agri rules |
| (Rain 1–31 Mar) | not simulated: the season ends on 28 Feb | the SEAS5 October files on disk end on 28 Feb |
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
| Early-maturing maize | MaizeGDD | 115 (calibrated, kiboko_v2: about 100 at Kiboko) | Katumani / DH-series type dryland maize |
| Medium-maturing maize | MaizeGDD | 120 | mid-altitude hybrid type |
| Sorghum | SorghumGDD | 100 | Gadam type |
| Dry bean | DryBeanGDD | 75 | KAT-series type |

They are maturity classes, not cultivars. Maize and sorghum carry Kenyan practice and the trials at the sites
(`parameters` in `varieties.yaml`, used as given after the phenology scaling):

| Variety | Plants /ha | Max. canopy (CCx) | Reference harvest index (HI0) | Basis |
| :--- | ---: | ---: | ---: | :--- |
| Early maize | 44,444 (75 x 30 cm) | 0.75 | 0.324 (kiboko_v3) | Duma 43 well watered at Kiboko, 7.76 t/ha (shared HI0) |
| Medium maize | 44,444 (75 x 30 cm) | 0.75 | 0.48 (AquaCrop) | Kiboko maize trials: median 4.5, high-input 6.1 dry t/ha |
| Sorghum | 66,667 (75 x 20 cm) | 0.75 | 0.30 | Kiboko 2020 sorghum: median 1.75, best 3.15 dry t/ha, measured HI 0.28 |
| Dry bean | 131,579 (AquaCrop) | 0.99 (AquaCrop) | 0.40 (AquaCrop) | no bean trials near the sites |

AquaCrop's own densities (maize 75,000, sorghum 200,000 /ha) are high-input ones, and its density sets only the
initial canopy, so the maximum canopy is set with it.

## Outcomes of a member

`ok` (sown, matured), `failed_establishment` (died before its canopy reached 5 %: a false start, the seedlings
dried out), `died` (an established crop that died before maturity: canopy collapse under water stress), `too_late`
(sown too late to mature by 28 Feb), `not_sown` (no onset by the rule's search end, 15 Jan), `error` (AquaCrop
failed for the member).

**Outcome figures, each with its own denominator** (`run_outlook.outcome_rates`, the same for the forecast members
and the benchmark seasons; model errors are in none of them and are counted apart, `n_error`):

| Figure | Of | Meaning |
| :--- | :--- | :--- |
| `p_sowing_opportunity` | valid members | an onset by the rule's search end (sown, or sowable but too late): the rule's outcome, not a farmer's |
| `yield_if_sown_t_ha` | sown crops | median, 10th and 90th percentile of the yield |
| `p_establishment_failure` | sown crops | failed to establish |
| `p_failure_if_sown` | sown crops | yield below the variety's failure threshold |
| `p_failure`, `yield_t_ha` | valid members | no crop (no sowing opportunity, too late) or a failed one: the overall figures, no crop counted as no yield |

**Re-sowing.** After a failed establishment the member is sown again at the next day that meets Agri rule 1's onset
criteria after the seedlings died (`config.RESOW_RULE`, at most `RESOW_MAX` = 1 more sowing, by 15 Jan), as a farmer
re-sows after the next good rain, provided the variety can still mature by 28 Feb. The outcome is then the re-sown
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
- The season ends on 28 Feb: a crop sown so late that it cannot mature by then counts as too late (no March rain is
  simulated; the SEAS5 runs on disk end on 28 Feb, and a March from past years would not be a forecast).
- Establishment is very sensitive to the soil water on 1 Aug. ERA5-Land puts it at 4–20 % of the available water at
  most sites (the dry season), so a sowing rain followed by a dry spell often kills the seedlings (re-sown once).
  At Kiboko a fixed 50 % would roughly halve the failures; without soil moisture measurements it is left as is.
- Agri rule 1 finds no onset by 15 Jan in many seasons at the drier sites (Kiboko 15 of 33, Kapiti and El Karama
  12): its "no 7-day dry spell in 21 days" criterion is rarely met there. Farmers sow anyway, so the rule-1 figures
  overstate failure there; the FAO agricultural onset sows every year.
- Sowing dates in cool sites (Kapiti, Maralal): the maturity classes are defined at 21 °C, so a medium maize or
  sorghum sown in November there needs more heat than the season gives before 28 Feb and is counted as too late.
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

## Calibration sets (`crop_engine/calibration/`)

A **calibration set** (`calibration/sets/<version>.yaml`) names the observations of the yield database
(`outputs/crop_engine/yields/observations.csv`, by site and obs_id prefix) that **train** a variety's parameters,
those **held out** to test them, those only **checked** against the model, and those **excluded**, each with the
reason, and the sowing windows assumed where a trial gives no date. A set is not edited once reported: a change is
a new version, so a fitted parameter can always be traced to its observations. An observation's value of a target
is in one group only (`run.validate` refuses a set that breaks this). A group can also carry **published values**
not in the database (`observed`, with their source; obs_id `lit:<set>:<group>:<n>`) and a **location** of its own
(a trial away from the site: its ERA5-Land temperatures are fetched once and cached in
`outputs/crop_engine/calibration/temps/`). Yield checks run AquaCrop in the observed weather of a season
(`model: yield` or `potential`, as the benchmark) or **under full irrigation** (`model: potential_irrigated`,
`calibration/potential.py`: net irrigation, no rain, Hargreaves ET0, a loam soil), for well-watered trials.
`fit.parameter` is `maturity_days` (phenology) or an AquaCrop crop parameter such as `HI0`, fitted by bisection to
the training groups' yields under full irrigation (`fit.share` gives another variety the same value). A set can
start from an earlier set's proposals (`base`): "before" is then `varieties.yaml`, "after" the base and the fit.

`python -m crop_engine.calibration.run --set <version> [--benchmark]` fits each variety's `maturity_days` (every
phenological stage scaled together) to the training trials' median days to silking or maturity, in the site's
ERA5-Land temperatures over every sowing date of the windows; scores the training and held-out groups before and
after (bias, MAE, range); runs the yield checks with AquaCrop in the observed weather of their seasons; and, with
`--benchmark`, the site's 1993–2025 benchmark before and after. It writes `outputs/crop_engine/calibration/
<version>/` (`report.md`, `results.json`, `fitted_varieties.yaml`). **`varieties.yaml` is never changed by it**: a
fitted value is adopted by hand, citing the set.

### kiboko_v1 (November 2026): result and decision

Training: IITA RUVT Early (25 entries, maize_early) and Evt-Lsr-W (20, maize_medium) 2013, days to silking;
Koima et al. 2023 sorghum, maturity (a weak target: one scoring date, 105 days, for every genotype). Held out: IITA
RUVT Extra-early (22) and the Striga-resistant hybrids (21). No sowing dates: Long Rains, dry season (irrigated)
and Short Rains 2013 windows.

| Variety | Days to silking / maturity at Kiboko: observed | model now | fitted | held out: bias now → fitted |
| :--- | ---: | ---: | ---: | ---: |
| maize_early (silking) | 61 (train), 59 (held out) | 41 | 61 (`maturity_days` 90 → 134) | −18 → **+2** days |
| maize_medium (silking) | 70.9 (train), 70.3 (held out) | 54 | 71 (120 → 157) | −16 → **+0.7** days |
| sorghum (maturity) | 105 | 84 | 105 (100 → 124) | none held out |

The current classes develop **16–21 days too fast** for every Kiboko trial: Kiboko (ERA5-Land, 23.3 °C) is warmer
than the classes' 21 °C reference. The fit removes the bias, and holds on the held-out trials. **It was not
adopted**, because in the Short Rains at Kiboko the fitted crops cannot be grown (benchmark 1993–2025, FAO
agricultural onset): medium maize is too late in 32 of 33 seasons, early maize fails in 61 % of seasons
(42 % now) with 8 too late, and sorghum fails in 70 % (52 %). The IITA lines are later germplasm than the
early dryland maize (Katumani, KDV, DH types) and Gadam-type sorghum that the classes stand for, and that farmers
grow in the Short Rains for exactly this reason. Next set (kiboko_v2): days to silking and maturity of the Kenyan
dryland varieties (KALRO National Performance Trials, release data) for maize_early and sorghum, keeping the IITA
trials as a held-out check of maize_medium.

The yield checks were not informative: the Short Rains 2013 killed both maize classes in the model, and
AquaCrop's yield potential stops when the crop dies, so it is not a no-stress yield there. kiboko_v2 checks yield
potential with full irrigation instead.

### kiboko_v2 (November 2026): the Kenyan varieties train the classes

Training: the **local Katumani composite** (maize_early) and **Duma 43** (maize_medium), checks of the KARI Kiboko
2012 dry-season trial under full irrigation (Ngugi, Collins & Muchira 2013, *Aust. J. Crop Sci.* 7(13), Table 5:
days to anthesis plus the anthesis–silking interval); **Gadam** at the University of Embu farm, 2020 (Shinda et al.
2021, *J. Exp. Biol. Agric. Sci.* 9(4), Table 2: flowering and maturity). Held out: the IITA 2013 trials (kiboko_v1)
and the Koima sorghum trial.

| Variety | Training: observed → model now → fitted | `maturity_days` | Held out: bias now → fitted |
| :--- | :--- | ---: | ---: |
| maize_early | Katumani silking 53 → 41 → 53 days | 90 → 115 (100 days at Kiboko) | IITA early: −19 → **−8** days |
| maize_medium | Duma 43 silking 64.7 → 55 → 65 | 120 → 142 (122 at Kiboko) | IITA late: −16.6 → **−6.6** |
| sorghum | Gadam flowering 65.3 → 65 → 56; maturity 97.7 → 117 → 100 | 100 → 87 | Koima: −21 → −32 (weak) |

- **Maize**: the fit matches the Kenyan checks at Kiboko and brings the independent IITA trials from 17–19 to
  7–8 days, the remaining gap in the direction expected (IITA lines are later germplasm).
- **Sorghum: the evidence conflicts, not fitted.** Gadam's flowering at Embu matches the current class, its
  maturity needs a shorter one; with one parameter (AquaCrop's flowering-to-maturity ratio) both cannot be met,
  and the Koima trial's single scoring date (105 days at the warmer Kiboko) contradicts both.
- **Yield level**: the classes' yield under full irrigation (fitted: early 9.4, medium 11.3 t/ha) is three times
  the Katumani check's well-watered yield (3.0) and above Duma 43's (7.8) and the IITA trials' (median 4.5, best
  7.4): every upper-bound check passes, by far too much. The harvest index and water productivity need their own
  calibration step.
- **Benchmark at Kiboko** (1993–2025, FAO agricultural onset, before → after): early maize fails in 42 → 48 % of
  seasons, none too late, matured crops 4.8 → 7.8 t/ha; **medium maize is too late in 21 of 33 seasons**: a crop
  of 122 days sown in November matures in March, after the season's end on 28 Feb. Medium maize needs the season
  past 28 Feb (P1 weather forcing) before its phenology can be adopted.

Status: proposed, not adopted (`outputs/crop_engine/calibration/kiboko_v2/`). Adopting maize_early 115 changes
the published outlook (and rebuilds every crop result on the next daily update).

### kiboko_v3 (November 2026): the maize yield level

Starts from kiboko_v2's maize phenology and fits the reference harvest index **HI0** (water productivity stays
AquaCrop's: FAO treats it as conservative for a crop) so that medium maize under full irrigation, at the trial's
density, yields what **Duma 43** yielded well watered at Kiboko in 2012 (7.76 t/ha, Ngugi et al. 2013). Early
maize takes the same value.

| | HI0 | Full irrigation, Kiboko dry season: medium / early (t/ha) | Trials: Duma 43 / Katumani / IITA median, best |
| :--- | ---: | ---: | ---: |
| varieties.yaml | 0.48 | 9.9 / 7.7 | 7.76 / 3.02 / 4.5, 7.4 |
| kiboko_v2 phenology | 0.48 | 11.5 / 9.4 | |
| **kiboko_v3** | **0.324** | **7.75 / 6.5** | |

- The fit leaves early maize at twice the Katumani check's well-watered yield (6.5 against 3.0) and above the IITA
  early trials' median (4.5): a local composite in a breeding trial is not a high-input reference, so it is checked,
  not fitted. An improved early variety's well-watered yield (KDV, DH series) would train the early class.
- A harvest index of 0.32 is low for a hybrid under full irrigation; it also carries what the model cannot see in
  the trial (fertilizer, grain moisture, plant stand). Yield alone cannot separate biomass from harvest index.
- **Benchmark at Kiboko** (1993–2025, FAO agricultural onset; varieties.yaml → kiboko_v2 phenology and v3 HI0):
  early maize fails in 42 → 52 % of seasons (yield below 0.5 t/ha), matured crops 4.8 → 5.3 t/ha; medium maize as in
  kiboko_v2 (too late in 21 of 33 seasons with the 28 Feb season end).

Status: **early maize adopted** (November 2026, `varieties.yaml`: `maturity_days` 115, `HI0` 0.324); medium
maize waits for a season past 28 Feb (its proposals stay in `outputs/crop_engine/calibration/kiboko_v3/`).

## Testing

`python -m pytest crop_engine/tests` (also in CI: `.github/workflows/crop-engine-tests.yml`, on every pull request
and push that touches the engine): the weather contract and provenance, variety scaling and parameters, sites and
soil, the AquaCrop adapter (statuses, re-sowing, canopy, potential yield), the outcome rates, the dashboard export,
the yield databases, the calibration sets and the phenology fit, and a **regression** check of fixed synthetic seasons against stored outputs
(`tests/reference/aquacrop_synthetic.json`: regenerate it deliberately, and say why, when the adapter, AquaCrop or
`varieties.yaml` change them).

## Next phases

Priorities after the November 2026 review (software MVP in place; the next milestone is scientific credibility):

- **P1 Calibration and independent validation**, Kiboko first (early maize and sorghum): versioned calibration
  sets, phenology fit, held-out scores and full-irrigation yield checks are in place (*Calibration sets*):
  kiboko_v1 not adopted; kiboko_v2 fits the maize phenology to Kenyan checks and kiboko_v3 the maize harvest index
  to Duma 43; early maize adopted. Next: medium maize after the season runs past 28 Feb; an improved early
  variety's well-watered yield; then the other sites as trials are found.
- **P1 Hindcast verification**: crop forecasts from past forecast runs against the crops simulated in the observed
  weather of the same seasons (1993–2016), and against county yields: does the crop simulation add information
  beyond the onset, cessation, season length and FAO water balance forecasts?
- **P1 Weather forcing**: forecast temperature and radiation (SEAS5) with source metadata per day; a season past
  28 Feb only with March rain from a forecast or a declared climatological ensemble.
- **P1 Management scenarios**: sowing-date offsets and fixed dates, plant density, initial soil water.
- **P1 PCSE/WOFOST** as a second engine on the same weather, soil and observations — after AquaCrop's calibration.
- **P2**: DSSAT or SARRA-Py adapters where partner data support them; the Long Rains (MAM) and Ethiopia; crop
  bulletins and gridded regional yield forecasts.
