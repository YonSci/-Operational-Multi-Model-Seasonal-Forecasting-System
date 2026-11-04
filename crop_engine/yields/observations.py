"""
Measured yields of plots and trials in Kenya, in one table (yields.OBS_COLUMNS), from:

  IITA maize trials        entry means of the international maize trials (Kiboko 2013 and others): silking, yield
  Kenya soil health        Alliance Bioversity–CIAT compilation (2026) of fertilizer / management experiments
  N2Africa                 IITA legume agronomy trials (western Kenya, 2010–2011): bean phenology dates and yield
  published tables         yield tables transcribed from papers (yields/published/, see PUBLISHED_STUDIES)

Only the engine's crops (maize, sorghum, common bean) are kept. Each row keeps what the source states; derived
values (season, dry yield, days to flowering) say how they were derived, and gaps stay empty.
"""
import datetime as dt
import re

import numpy as np
import pandas as pd

from crop_engine.yields import ASSUMED_MOISTURE, OBS_COLUMNS, PUBLISHED, YIELD_DATA, doi_of, dry, season_of, season_year

IITA_FILES = ["IITA_kenya.csv", "international_maize_trial_regular_kenya.csv", "international_maize_trial_kenya_striga.csv"]


def _finish(df, source):
    df = df.copy()
    df["source"] = source
    df["moisture_assumed"] = df["moisture_pct"].isna()
    df["moisture_pct"] = df["moisture_pct"].fillna(df["crop"].map(ASSUMED_MOISTURE))
    df["grain_yield_dry_kg_ha"] = dry(df["grain_yield_kg_ha"], df["moisture_pct"]).round(1)
    implausible = df["grain_yield_kg_ha"] > 15000
    df.loc[implausible, "quality_flag"] = df.loc[implausible, "quality_flag"].fillna("").str.cat(
        pd.Series("yield > 15 t/ha (implausible)", index=df.index[implausible]), sep="; ").str.strip("; ")
    for c in OBS_COLUMNS:
        if c not in df:
            df[c] = np.nan
    return df[OBS_COLUMNS]


def _days(a, b):
    return (pd.to_datetime(b) - pd.to_datetime(a)).dt.days


# ── IITA international maize trials ─────────────────────────────────────────
def _iita_maturity(title):
    t = title.upper()
    if "EXTRA-EARLY" in t or "EXTRA EARLY" in t:
        return "extra-early", "maize_early"
    if "EARLY" in t or "-ESR" in t:
        return "early", "maize_early"
    if "-ISR" in t or "INTERMEDIATE" in t:
        return "intermediate", "maize_medium"
    if "-LSR" in t or "LATE" in t:
        return "late", "maize_medium"
    return None, None


def iita_maize(root=YIELD_DATA):
    d = root / "International_Institute_Tropical_Agriculture"
    rows = []
    for name in IITA_FILES:
        f = pd.read_csv(d / name, encoding="utf-8-sig")
        striga = "YLDUN" in f
        for _, r in f.iterrows():
            mclass, variety = _iita_maturity(str(r.TRL_TITL))
            yields = [("striga non-infested", r.YLDUN), ("striga infested", r.YLDIN)] if striga else \
                     [(None, r.YIELD), ("second-season planting", r.YIELD2)]
            for treat, y in yields:
                if pd.isna(y):
                    continue
                rows.append(dict(
                    obs_id=f"iita:{r.TRIAL_ID}:{r.ENTRYNO}" + (f":{treat}" if treat else ""),
                    study=f"IITA international maize trial: {r.TRL_TITL} ({r.TRIAL_ID})",
                    doi=None, location=str(r.LOCATION).title(), latitude=r.LATITUDE, longitude=r.LONGITUDE,
                    coord_quality="station (2 decimals)", crop="maize", engine_variety=variety, maturity_class=mclass,
                    cultivar=r.ENTRY, season=None, year=int(r.YEAR), date_quality="year only",
                    days_to_flowering=r.get("DY_SKUN" if striga else "DY_SK"), grain_yield_kg_ha=float(y),
                    moisture_pct=np.nan, treatment=treat, aggregation="entry mean of the trial",
                    use="calibration candidate: phenology (days to silking), yield potential",
                    quality_flag="no sowing date or season; management (fertilizer, irrigation) not given",
                    notes=f"agro-ecological zone: {r.AEZONE}; days_to_flowering = days to silking"))
    df = pd.DataFrame(rows).drop_duplicates("obs_id")
    return _finish(df, "IITA maize trials")


# ── Kenya soil health data (Alliance Bioversity–CIAT, 2026) ────────────────
def _num(s):
    return pd.to_numeric(s.astype(str).str.strip().str.replace(",", ".", regex=False), errors="coerce")


def _parse_date(s):
    """'20/09/2011' -> (date, 'day'); '2014-08' -> (1 Aug 2014, 'month'); '2015' -> (None, 'year only')."""
    s = str(s).strip()
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        try:
            return dt.date(int(m[3]), int(m[2]), int(m[1])), "day"
        except ValueError:
            return None, "unparsed"
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", s):
        return dt.date(int(m[1]), int(m[2]), 1), "month"
    if re.fullmatch(r"\d{4}", s):
        return None, "year only"
    return None, None if s in ("", "nan") else "unparsed"


def _fix_text(s):
    return s if not isinstance(s, str) else s.replace("Â\x92", "'").replace("Â’", "'").strip()


SOIL_HEALTH_CROPS = {"maize": "maize", "sorghum": "sorghum", "common bean": "bean"}


def kenya_soil_health(root=YIELD_DATA):
    f = pd.read_csv(root / "Kenya_soil_health_data" / "02a. Kenya soil health data.csv", sep=";", dtype=str,
                    encoding="utf-8-sig")
    f["crop"] = f.crop.str.strip().str.lower().map(SOIL_HEALTH_CROPS)
    f = f[f.crop.notna()].copy()
    lat, lon = _num(f.latitude), _num(f.longitude)
    bad = lat.abs().gt(5) | lon.lt(33) | lon.gt(42)
    lat[bad], lon[bad] = np.nan, np.nan
    parsed = f.planting_date.map(_parse_date)
    pdate = parsed.map(lambda p: p[0])
    dq = parsed.map(lambda p: p[1])
    pyear = pd.to_numeric(f.planting_date.str.extract(r"(\d{4})")[0], errors="coerce")
    pmonth = pdate.map(lambda d: d.month if d else None)
    season = f.Season.where(f.Season.isin(["LR", "SR"]), pmonth.map(season_of))
    year = [season_year(y, m) if pd.notna(y) else np.nan for y, m in zip(pyear, pmonth)]
    harvest = f.harvest_date.map(lambda s: _parse_date(s)[0])
    irrig = f.irrigated.str.upper().map({"TRUE": True, "FALSE": False})
    soil = f[["soil_type", "soil_texture"]].apply(lambda r: "; ".join(str(v) for v in r if pd.notna(v)) or None, axis=1)
    df = pd.DataFrame(dict(
        obs_id=[f"ksh:{i}" for i in f.index], study=f.Study_Source.map(_fix_text), doi=f.Study_Source.map(doi_of),
        location=(f.location.fillna(f.Area)).map(_fix_text), latitude=lat, longitude=lon,
        coord_quality=np.where(bad, "invalid in source", "as reported"),
        crop=f.crop, engine_variety=f.crop.map({"sorghum": "sorghum", "bean": "bean"}), cultivar=f.variety,
        season=season, year=year, planting_date=pdate.map(lambda d: d.isoformat() if d else None),
        date_quality=dq.where(dq.notna(), "not given"), harvest_date=harvest.map(lambda d: d.isoformat() if d else None),
        grain_yield_kg_ha=_num(f["Grain_yield(kg/ha)"]), moisture_pct=np.nan,
        n_kg_ha=_num(f.N_fertilizer), p_kg_ha=_num(f.P_fertilizer), irrigated=irrig,
        irrigation_mm=_num(f.irrigation_amount), soil=soil, treatment=f.treatment.map(_fix_text),
        replicate=_num(f.rep), aggregation="plot or treatment (as compiled)",
        use="calibration candidate: management (N, P, irrigation) response",
        quality_flag=None, notes=None))
    inoculated = f.inoculated.str.upper().eq("TRUE") & f.crop.ne("bean")
    df.loc[inoculated, "quality_flag"] = "rhizobium-inoculated non-legume: crop label doubtful"
    df.loc[f.intercrops.notna(), "notes"] = "intercropped with " + f.intercrops
    df.loc[df.grain_yield_kg_ha.isna(), "quality_flag"] = "no yield"
    df = df[df.grain_yield_kg_ha.notna()]
    return _finish(df, "Kenya soil health (Alliance Bioversity-CIAT 2026)")


# ── N2Africa agronomy trials (IITA) ─────────────────────────────────────────
def _dmy(f, stem):
    d, m, y = (pd.to_numeric(f[f"{stem}_{k}"], errors="coerce") for k in ("dd", "mm", "yyyy"))
    out = []
    for a, b, c in zip(d, m, y):
        try:
            out.append(dt.date(int(c), int(b), int(a)).isoformat() if min(a, b, c) > 0 else None)
        except (ValueError, TypeError):
            out.append(None)
    return pd.Series(out, index=f.index)


def n2africa(root=YIELD_DATA):
    d = root / "N2Africa_agronomy_trials"
    f = pd.read_csv(d / "data.csv", low_memory=False)
    kind = f.experiment_id.str.extract(r"_(BB|CB)_")[0]          # bush / climbing bean; soybean and maize left out
    f = f[kind.notna()].copy()
    kind = kind[f.index]
    s = pd.read_csv(d / "soil_properties.csv")
    s["base"] = s.experiment_id.str.replace(r"(_COPY|_\(2\)|_2)$", "", regex=True)
    s = s[s.gps_latitude_dec.notna()]
    coords = {**s.drop_duplicates("base").set_index("base")[["gps_latitude_dec", "gps_longitude_dec"]].T.to_dict("list"),
              **s.set_index("experiment_id")[["gps_latitude_dec", "gps_longitude_dec"]].T.to_dict("list")}
    base = f.experiment_id.str.replace(r"(_COPY|_\(2\)|_2)$", "", regex=True)
    ll = [coords.get(e) or coords.get(b) or (np.nan, np.nan) for e, b in zip(f.experiment_id, base)]
    site = s.set_index("experiment_id").action_site.to_dict()
    plant, flower = _dmy(f, "planting_date"), _dmy(f, "date_50_perc_flowering")
    mature, harvest = _dmy(f, "date_full_maturity"), _dmy(f, "date_harvest")
    pm = pd.to_datetime(plant).dt.month
    treat = f[["main_treatment", "sub_treatment_inoc", "sub_treatment_fert"]].astype(str).agg(" / ".join, axis=1)
    df = pd.DataFrame(dict(
        obs_id="n2a:" + f.experiment_id + ":" + f["id"].astype(str),
        study="N2Africa: " + f.experiment_id, location=f.experiment_id.map(site).fillna(f.experiment_id),
        latitude=[a for a, _ in ll], longitude=[b for _, b in ll], coord_quality="trial GPS (1 decimal)",
        crop="bean", engine_variety=np.where(kind == "BB", "bean", None),
        maturity_class=np.where(kind == "BB", "bush bean", "climbing bean"), cultivar=f.variety,
        season=f.experiment_id.str.extract(r"_(LR|SR)_")[0],
        year=pd.to_numeric(f.experiment_id.str.extract(r"_(20\d\d)")[0]),
        planting_date=plant, date_quality=np.where(plant.notna(), "day", "not given"),
        flowering_date=flower, maturity_date=mature, harvest_date=harvest,
        days_to_flowering=_days(plant, flower), days_to_maturity=_days(plant, mature),
        grain_yield_kg_ha=pd.to_numeric(f.grain_yield_ha_calc, errors="coerce"), moisture_pct=np.nan,
        treatment=treat, replicate=f.replication_no, aggregation="plot",
        use="calibration candidate: bean phenology (flowering, maturity); western Kenya, not at a monitored site",
        quality_flag=None, notes=None))
    bad = (df.days_to_maturity <= 30) | (df.days_to_maturity > 200) | (df.days_to_flowering <= 15)
    df.loc[bad, "quality_flag"] = "implausible phenology dates"
    df.loc[bad, ["days_to_flowering", "days_to_maturity"]] = np.nan
    df.loc[df.grain_yield_kg_ha.fillna(0) <= 0, "quality_flag"] = df.quality_flag.fillna("no yield")
    df = df[df.grain_yield_kg_ha > 0]
    df["season"] = df.season.fillna(pm[df.index].map(season_of))
    return _finish(df, "N2Africa agronomy trials (IITA)")


# ── yield tables transcribed from papers ───────────────────────────────────
# One entry per file in yields/published/: what the paper states about the trial, applied to every row.
PUBLISHED_STUDIES = {
    "koima2023_sorghum_kiboko_ithookwe.csv": dict(
        study="Koima et al. 2023, J. Fungi 9(1):100, Table 8 (anthracnose screening of 14 sorghum genotypes)",
        doi="10.3390/jof9010100", crop="sorghum", engine_variety="sorghum",
        locations={"KALRO Kiboko": (-2.21046, 37.719, "registered site (the paper's coordinates are garbled)"),
                   "KALRO Ithookwe": (-1.37611, 37.97861, "paper: 1°22'34\"S 37°58'43\"E, 1147 m")},
        season="SR+LR", year=2020, date_quality="onset of rains (date not reported)",
        days_to_maturity=105, moisture_pct=12.5, n_kg_ha=15.0, p_kg_ha=8.0, irrigated=False,
        n_obs=8, aggregation="genotype mean of 4 replicates x 2 seasons (SR 2020/21, LR 2021)",
        use="site check: sorghum yield at Kiboko (water + disease limited)",
        quality_flag="disease-screening trial: anthracnose spreader rows, yields include disease losses; "
                     "the two seasons are pooled",
        notes="RCBD, 4 reps, 0.60 m rows, 4 x 2.5 m plots, 8 kg/ha seed; DAP 40 kg/ha at sowing + CAN 30 kg/ha "
              "at 8th leaf (about 15 kg N, 8 kg P per ha); sown at the onset of the rains, 21 days after the "
              "spreader rows; physiological maturity scored at 105 days after sowing; yield at 12.5 % moisture; "
              "irrigation not mentioned (taken as rainfed). Seasons: Nov 2020–Mar 2021 and Apr–Aug 2021."),
}


def published(directory=PUBLISHED):
    frames = []
    for name, meta in PUBLISHED_STUDIES.items():
        t = pd.read_csv(directory / name)
        loc = t.location.map(meta["locations"])
        fixed = {k: v for k, v in meta.items() if k not in ("locations",)}
        frames.append(pd.DataFrame(dict(
            obs_id=f"pub:{name.split('.')[0]}:" + t.location.str.replace(" ", "_") + ":" + t.cultivar,
            location=t.location, latitude=loc.str[0], longitude=loc.str[1], coord_quality=loc.str[2],
            cultivar=t.cultivar, grain_yield_kg_ha=t.grain_yield_t_ha * 1000, harvest_index=t.harvest_index,
            **fixed)))
    return _finish(pd.concat(frames, ignore_index=True), "published tables")


LOADERS = {"iita": iita_maize, "soil_health": kenya_soil_health, "n2africa": n2africa, "published": None}


def load_all(root=YIELD_DATA, log=print):
    """Every source that is on disk (a missing download is reported and skipped)."""
    frames = []
    for key, fn in LOADERS.items():
        try:
            frames.append(published() if fn is None else fn(root))
            log(f"observations: {key}: {len(frames[-1])} rows")
        except FileNotFoundError as e:
            log(f"observations: {key}: skipped ({e.filename} not found)")
    return pd.concat(frames, ignore_index=True)
