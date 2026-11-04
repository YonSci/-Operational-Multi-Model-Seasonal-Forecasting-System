#!/usr/bin/env python3
"""
Build the two yield databases from data/Yield/, link them to the monitored sites, and compare the crop engine's
observed-weather benchmark (Short Rains 1993–2025, frontend/public/tracker/data/crop/benchmark.json) with them.

Outputs (not committed; outputs/crop_engine/yields/):
  observations.csv       measured plot and trial yields (yields.OBS_COLUMNS), each linked to its nearest site
  statistics.csv         county, national and gridded yields (yields.STAT_COLUMNS)
  sites.csv              each monitored site's county (HarvestStat boundaries) and 0.25° cell
  compare_county.csv     benchmark vs the site's county Short Rains yields, year by year (HarvestStat)
  compare_sites.csv      benchmark vs the trials at the sites (same crop, year and season)
  levels.csv             per site and crop: benchmark median vs county, MapSPAM and national yields
  targets.csv            calibration targets per site and crop: the trials' typical and high-input yields, HI, days
  report.md             inventory of both databases and the two comparisons

Usage:
  python -m crop_engine.yields.build
  python -m crop_engine.yields.build --data D:/other/checkout/data/Yield
"""
import argparse
import json
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")   # one BLAS thread: a few small tables, and memory is short

import numpy as np                                    # noqa: E402
import pandas as pd                                   # noqa: E402
import yaml                                           # noqa: E402

from crop_engine.config import DASHBOARD_OUT, VARIETIES_FILE  # noqa: E402
from crop_engine.data.sites import registered_sites   # noqa: E402
from crop_engine.yields import (CROPS, NEAR_SITE_KM, YIELD_DATA, YIELD_OUT, haversine_km,  # noqa: E402
                                observations, statistics)

FAILURE_T_HA = {k: v["failure_t_ha"] for k, v in
                yaml.safe_load(VARIETIES_FILE.read_text(encoding="utf-8"))["varieties"].items()}
MIN_YEARS = 8                                         # fewer overlapping years: no correlation reported


def link_sites(obs, sites):
    """Nearest monitored site of each observation, and its distance; site_id only within NEAR_SITE_KM."""
    km = np.full((len(obs), len(sites)), np.nan)
    for j, s in enumerate(sites):
        km[:, j] = [haversine_km(a, b, s.lat, s.lon) if pd.notna(a) and pd.notna(b) else np.nan
                    for a, b in zip(obs.latitude, obs.longitude)]
    has = ~np.isnan(km).all(axis=1)
    near = np.where(has, np.nanargmin(np.where(np.isnan(km), np.inf, km), axis=1), -1)
    dist = np.where(has, km[np.arange(len(obs)), near], np.nan)
    obs = obs.copy()
    obs["site_km"] = np.round(dist, 1)
    obs["site_id"] = [sites[n].id if h and d <= NEAR_SITE_KM else None for n, h, d in zip(near, has, dist)]
    return obs


def load_benchmark():
    b = json.loads((DASHBOARD_OUT / "benchmark.json").read_text(encoding="utf-8"))
    rows = []
    for site, by_var in b["sites"].items():
        for var, by_rule in by_var.items():
            for rule, s in by_rule.items():
                for year, plant, harvest, y, status in s["seasons"]:
                    rows.append(dict(site_id=site, engine_variety=var, rule=rule, year=year, planting=plant,
                                     harvest=harvest, model_t_ha=y, status=status))
    return pd.DataFrame(rows)


def _detrended(v, years):
    a, b = np.polyfit(years, v, 1)
    return v - (a * years + b)


def compare_county(bench, stats, counties):
    """Per site, variety and rule: the benchmark's sown seasons against the county's Short Rains yields."""
    hv = stats[(stats.source.str.startswith("HarvestStat")) & (stats.season == "SR")]
    out = []
    for (site, var, rule), g in bench.groupby(["site_id", "engine_variety", "rule"]):
        crop = next(c for c, vs in CROPS.items() if var in vs)
        county = counties.get(site)
        obs = hv[(hv.admin_1 == county) & (hv.crop == crop)].set_index("year").yield_dry_kg_ha / 1000
        sown = g[g.status != "not_sown"].set_index("year").model_t_ha
        both = pd.concat([sown.rename("model"), obs.rename("obs")], axis=1, join="inner").dropna()
        n = len(both)
        row = dict(site_id=site, county=county, crop=crop, engine_variety=var, rule=rule,
                   county_years=len(obs), overlap_years=n,
                   not_sown_in_overlap=int(g[(g.status == "not_sown") & g.year.isin(obs.index)].shape[0]),
                   county_dry_t_ha=round(both.obs.mean(), 2) if n else np.nan,
                   model_t_ha=round(both.model.mean(), 2) if n else np.nan)
        row["model_over_county"] = round(row["model_t_ha"] / row["county_dry_t_ha"], 1) if n and row["county_dry_t_ha"] else np.nan
        if n >= MIN_YEARS and both.model.std() > 0 and both.obs.std() > 0:
            yrs = both.index.values.astype(float)
            row["r_detrended"] = round(float(np.corrcoef(_detrended(both.model.values, yrs),
                                                         _detrended(both.obs.values, yrs))[0, 1]), 2)
            row["spearman"] = round(float(both.model.rank().corr(both.obs.rank())), 2)
        out.append(row)
    return pd.DataFrame(out)


def compare_sites(bench, obs):
    """Trials at a monitored site against the benchmark season of the same crop and year (Short Rains only)."""
    at = obs[obs.site_id.notna() & obs.crop.isin(CROPS) & obs.quality_flag.fillna("").str.contains("doubtful").eq(False)]
    keys = ["source", "site_id", "crop", "maturity_class", "year", "season", "irrigated", "n_kg_ha"]
    g = (at.assign(**{k: at[k].astype(object).where(at[k].notna(), "") for k in keys})
           .groupby(keys).agg(n=("obs_id", "size"), obs_dry_t_ha=("grain_yield_dry_kg_ha", "mean"),
                              obs_dry_max_t_ha=("grain_yield_dry_kg_ha", "max"),
                              engine_variety=("engine_variety", "first")).reset_index())
    g[["obs_dry_t_ha", "obs_dry_max_t_ha"]] = (g[["obs_dry_t_ha", "obs_dry_max_t_ha"]] / 1000).round(2)
    rows = []
    for _, r in g.iterrows():
        variants = [r.engine_variety] if isinstance(r.engine_variety, str) else CROPS[r.crop]
        note = ("Long Rains: not simulated" if r.season == "LR" else
                "year not given" if r.year == "" else
                "season not given: compared with the Short Rains" if r.season == "" else
                "Short Rains + Long Rains pooled: compared with the Short Rains" if r.season == "SR+LR" else "")
        for var in variants:
            row = dict(r.drop("engine_variety"), engine_variety=var)
            for rule, b in bench[(bench.site_id == r.site_id) & (bench.engine_variety == var)].groupby("rule"):
                m = b[b.year == r.year] if r.year != "" and r.season != "LR" else b.iloc[0:0]
                row[f"model_t_ha_{rule}"] = round(m.model_t_ha.iloc[0], 2) if len(m) else np.nan
                row[f"status_{rule}"] = (m.status.iloc[0] + (f", sown {m.planting.iloc[0]}" if m.planting.iloc[0] else "")
                                         if len(m) else "")
            rows.append(dict(row, note=note))
    return pd.DataFrame(rows)


def levels(bench, stats, counties):
    """Yield levels per site and crop (dry t/ha): benchmark median against county, gridded and national yields."""
    st = stats.assign(t=stats.yield_dry_kg_ha / 1000)
    hv = st[st.source.str.startswith("HarvestStat") & st.qc_flag.isna()]
    fao = st[st.source.str.startswith("FAOSTAT") & st.year.between(2015, 2024)].groupby("crop").t.mean()
    spam = st[st.source.str.startswith("MapSPAM") & (st.technology == "rainfed")].set_index(["site_id", "crop"]).t
    out = []
    for site, county in counties.items():
        for crop, variants in CROPS.items():
            c = hv[(hv.admin_1 == county) & (hv.crop == crop)]
            ref = dict(county_SR=round(c[c.season == "SR"].t.mean(), 2),
                       county_annual_2010_2020=round(c[(c.season == "annual") & c.year.between(2010, 2020)].t.mean(), 2),
                       mapspam_2020_rainfed=round(spam.get((site, crop), np.nan), 2),
                       faostat_kenya_2015_2024=round(fao.get(crop, np.nan), 2))
            for var in variants:
                row = dict(site_id=site, county=county, engine_variety=var)
                for rule, b in bench[(bench.site_id == site) & (bench.engine_variety == var)].groupby("rule"):
                    sown = b[b.status != "not_sown"]
                    row[f"bench_{rule}"] = round(float(sown.model_t_ha.median()), 2) if len(sown) else np.nan
                    row[f"not_matured_{rule}"] = f"{(sown.status != 'ok').mean():.0%}" if len(sown) else ""
                    row[f"failure_{rule}"] = f"{(b.model_t_ha < FAILURE_T_HA[var]).mean():.0%}"
                out.append(dict(row, **ref))
    return pd.DataFrame(out)


def targets(obs):
    """Calibration targets per monitored site and crop (dry t/ha): the trials' median (typical management) and 90th
    percentile (high input: the level a crop model without nutrient stress should reach when water allows), with the
    harvest index and days to maturity where measured. Irrigated plots are kept apart (`irrigated`)."""
    at = obs[obs.site_id.notna() & obs.crop.isin(CROPS) & obs.quality_flag.fillna("").str.contains("doubtful").eq(False)]
    at = at.assign(irrigated=at.irrigated.map({True: "yes", False: "no"}).fillna("not stated"),
                   t=at.grain_yield_dry_kg_ha / 1000)
    g = (at.groupby(["site_id", "crop", "irrigated"])
           .agg(n=("obs_id", "size"), studies=("study", "nunique"),
                years=("year", lambda y: ", ".join(f"{v:.0f}" for v in sorted(y.dropna().unique()))),
                median_t_ha=("t", "median"), p90_t_ha=("t", lambda x: x.quantile(0.9)), max_t_ha=("t", "max"),
                n_kg_ha=("n_kg_ha", lambda x: f"{x.min():.0f}–{x.max():.0f}" if x.notna().any() else ""),
                harvest_index=("harvest_index", "median"), days_to_maturity=("days_to_maturity", "median"))
           .reset_index())
    return g.round(2)


def _md(df, cols=None):
    df = df if cols is None else df[cols]
    head = "| " + " | ".join(map(str, df.columns)) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "".join("| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |\n" for r in df.itertuples(index=False))


def report(obs, stats, sites_df, cc, cs, lv, tg):
    inv_o = (obs.assign(at_site=obs.site_id.notna())
             .groupby(["source", "crop"]).agg(rows=("obs_id", "size"), years=("year", lambda y: f"{y.min():.0f}–{y.max():.0f}" if y.notna().any() else ""),
                                               at_sites=("at_site", "sum"), with_sowing_date=("date_quality", lambda q: int((q == "day").sum())),
                                               with_flowering=("days_to_flowering", lambda d: int(d.notna().sum())),
                                               median_dry_t_ha=("grain_yield_dry_kg_ha", lambda y: round(y.median() / 1000, 2)))
             .reset_index())
    inv_s = (stats.groupby(["source", "level", "crop", "season"])
             .agg(rows=("yield_kg_ha", "size"), years=("year", lambda y: f"{y.min():.0f}–{y.max():.0f}")).reset_index())
    sel = cc[cc.overlap_years > 0].sort_values(["site_id", "engine_variety", "rule"])
    return "\n".join([
        "# Crop engine yield data: inventory and first comparison", "",
        "Two databases, kept apart: **observations** (measured plot and trial yields: calibration and site checks) and "
        "**statistics** (county, national and gridded yields: regional validation only). Yields in the comparisons are "
        "dry matter (t/ha), the basis AquaCrop reports; sources' moisture is used where stated, otherwise assumed and flagged.", "",
        "## Monitored sites", "", _md(sites_df), "",
        "## Observations", "", _md(inv_o), "",
        "## Statistics", "", _md(inv_s), "",
        "## Yield levels (dry t/ha)", "",
        "Median benchmark yield of the sown Short Rains seasons (1993–2025) per variety and planting rule "
        "(`not_matured_`: share of the sown seasons that did not reach maturity, though some still yield; "
        "`failure_`: share of all seasons below the variety's failure yield, unsown ones included, as on the "
        "dashboard), against "
        "the county Short Rains mean, the county annual mean of 2010–2020 (HarvestStat, QC-flagged years left out), "
        "MapSPAM 2020 rainfed yield over the site's 0.25° cell and FAOSTAT's Kenya mean of 2015–2024.", "",
        _md(lv), "",
        "## Benchmark vs county Short Rains yields (HarvestStat)", "",
        "`model_over_county`: the simulated water-limited yield over the county average (all farmers' fields). "
        f"`r_detrended`: year-to-year correlation after removing each series' linear trend (>= {MIN_YEARS} years).", "",
        _md(sel), "",
        "## Calibration targets (trials at the sites, dry t/ha)", "",
        "Median: typical trial management; p90: high input, the level the engine (no nutrient stress) should reach in "
        "a season when water is not limiting.", "",
        _md(tg) if len(tg) else "No trials at the monitored sites.", "",
        "## Benchmark vs trials at the sites", "",
        "AquaCrop here has no nutrient stress, so it should be compared with the well-fertilized plots.", "",
        _md(cs) if len(cs) else "No trials at the monitored sites.", ""])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(YIELD_DATA), help="folder of the yield downloads (default data/Yield)")
    a = ap.parse_args()
    from pathlib import Path
    root = Path(a.data)
    sites = registered_sites("kenya")
    counties = statistics.site_counties(sites, root)
    sites_df = pd.DataFrame([dict(site_id=s.id, name=s.name, lat=s.lat, lon=s.lon, county=counties[s.id],
                                  cell=f"{statistics.cell_of(s.lat, s.lon)[0]:.3f}, {statistics.cell_of(s.lat, s.lon)[1]:.3f}")
                             for s in sites])
    obs = link_sites(observations.load_all(root), sites)
    stats = statistics.load_all(sites, root)
    bench = load_benchmark()
    cc, cs, lv = compare_county(bench, stats, counties), compare_sites(bench, obs), levels(bench, stats, counties)
    tg = targets(obs)

    YIELD_OUT.mkdir(parents=True, exist_ok=True)
    for name, df in (("observations", obs), ("statistics", stats), ("sites", sites_df),
                     ("compare_county", cc), ("compare_sites", cs), ("levels", lv), ("targets", tg)):
        df.to_csv(YIELD_OUT / f"{name}.csv", index=False)
    (YIELD_OUT / "report.md").write_text(report(obs, stats, sites_df, cc, cs, lv, tg), encoding="utf-8")
    print(f"observations {len(obs)} rows ({obs.site_id.notna().sum()} at monitored sites), statistics {len(stats)} rows")
    print(f"written to {YIELD_OUT}")


if __name__ == "__main__":
    main()
