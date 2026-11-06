#!/usr/bin/env python3
"""
Calibration of the crop engine against a versioned calibration set (crop_engine/calibration/sets/<set>.yaml): the
varieties' phenology (fit.parameter maturity_days) or an AquaCrop crop parameter (e.g. HI0, fitted to yields under
full irrigation) fitted to the set's training observations, scored on its held-out ones, and its yield checks run
before and after. A set may start from an earlier set's proposals (`base`); "after" is then the base and the fit.

varieties.yaml is not changed: the fitted values are proposed (fitted_varieties.yaml) and adopted by hand, with the
set's version cited, once the report has been reviewed.

Outputs (not committed; outputs/crop_engine/calibration/<set>/):
  results.json            everything below, machine-readable
  report.md               the fit, the held-out scores, the yield checks (and the benchmark, with --benchmark)
  fitted_varieties.yaml   the proposed maturity days per variety

Usage:
  python -m crop_engine.calibration.run --set kiboko_v1
  python -m crop_engine.calibration.run --set kiboko_v1 --benchmark     # also the site's 1993–2025 benchmark
"""
import argparse
import datetime as dt
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from crop_engine import config as C
from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.calibration import phenology as ph
from crop_engine.data import era5land
from crop_engine.data import sites as sites_mod
from crop_engine.yields import YIELD_OUT

SETS = Path(__file__).with_name("sets")
OUT = C.OUT / "calibration"
ROLES = ("train", "holdout", "check", "excluded")


# ── the set ─────────────────────────────────────────────────────────────────
def load_set(name):
    path = Path(name) if str(name).endswith(".yaml") else SETS / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")), path


def _as_list(x):
    return [] if x is None else list(x) if isinstance(x, (list, tuple)) else [x]


def select(obs, sel, site_id):
    """Rows of the observations a group's `select` names: obs_id prefixes (one or a list), at the set's site unless
    the selector names one."""
    m = obs.site_id == sel.get("site_id", site_id)
    pre = tuple(_as_list(sel.get("obs_id_prefix")))
    if pre:
        m &= obs.obs_id.str.startswith(pre)
    return obs[m]


def inline(cs, g):
    """A group's `observed` values (published figures, not in the yield database) as observation rows: obs_id
    lit:<set>:<group>:<n>, at the group's location (or the set's site); a yield_t_ha value becomes the dry yield."""
    o = g["observed"]
    rows = []
    for n, v in enumerate(o["values"], 1):
        r = {"obs_id": f"lit:{cs['version']}:{g['id']}:{n}", "site_id": (g.get("location") or {}).get("id", cs["site"]),
             "cultivar": v.get("entry"), "study": o["source"]}
        for k, x in v.items():
            if k == "yield_t_ha":
                r["grain_yield_dry_kg_ha"] = 1000 * float(x)
            elif k != "entry":
                r[k] = x
        rows.append(r)
    return pd.DataFrame(rows)


def validate(cs, obs):
    """The groups' observations, after checking the set: roles, fitted varieties with a training group, each
    observation's target in one group only, no empty group → {group id: DataFrame}."""
    errors, rows, seen = [], {}, {}
    fit = set(cs["fit"]["varieties"])
    for g in cs["groups"]:
        gid = g["id"]
        if g["role"] not in ROLES:
            errors.append(f"{gid}: unknown role {g['role']!r}")
        r = inline(cs, g) if "observed" in g else select(obs, g.get("select", {}), cs["site"])
        if g["role"] != "excluded":
            if g.get("target") in ph.STAGE:
                if g["target"] not in r.columns:
                    r = r.iloc[0:0].assign(**{g["target"]: []})
                r = r[r[g["target"]].notna()]
            if r.empty:
                errors.append(f"{gid}: selects no observations with a value of {g.get('target')}")
            for oid in r.obs_id:
                key = (oid, g["target"])
                if key in seen:
                    errors.append(f"{gid}: {oid} ({g['target']}) is already in {seen[key]}")
                seen[key] = gid
        rows[gid] = r
    for v in fit:
        if not any(g["role"] == "train" and g.get("variety") == v for g in cs["groups"]):
            errors.append(f"fitted variety {v} has no training group")
    if errors:
        raise ValueError("calibration set: " + "; ".join(errors))
    return rows


# ── temperatures ────────────────────────────────────────────────────────────
def location_temperature(loc):
    """ERA5-Land daily tmax, tmin at a trial location that is not a monitored site (cached with the calibration
    outputs, not in the engine's cache)."""
    path = OUT / "temps" / f"era5land_t2m_{loc['id']}_{loc['lat']:.4f}_{loc['lon']:.4f}.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        df = era5land._fetch(loc["lat"], loc["lon"], era5land.FIRST, dt.date.today() - dt.timedelta(days=10))
        df.to_csv(path, index=False, float_format="%.2f")
    return pd.read_csv(path, parse_dates=["date"]).set_index("date")


def temperatures_of(cs, site_temps):
    """group → (temps, latitude): the group's location's, else the set's site's."""
    cache = {}

    def get(g):
        loc = g.get("location")
        if not loc:
            return site_temps, cs["_site_lat"]
        if loc["id"] not in cache:
            cache[loc["id"]] = location_temperature(loc)
        return cache[loc["id"]], loc["lat"]
    return get


# ── phenology ───────────────────────────────────────────────────────────────
def phenology(cs, rows, varieties, ref, temps_of):
    groups = [g for g in cs["groups"] if g.get("target") in ph.STAGE and g["role"] in ("train", "holdout", "check")]
    data = {}
    for g in groups:
        v = varieties[g["variety"]]
        dates = ph.sowing_dates(g["windows"])
        data[g["id"]] = dict(target=g["target"], cum=ph.cumulative_gdd(temps_of(g)[0], v["aquacrop_crop"], dates),
                             dates=dates, observed=rows[g["id"]][g["target"]].astype(float).values)
    fitted, objective = {}, {}
    for vk in cs["fit"]["varieties"]:
        train = [data[g["id"]] for g in groups if g["variety"] == vk and g["role"] == "train"]
        fitted[vk], obj = ph.fit_maturity_days(train, varieties[vk], ref)
        objective[vk] = round(obj[fitted[vk]], 2)
    scores = []
    for g in groups:
        d, v = data[g["id"]], varieties[g["variety"]]
        out = {"group": g["id"], "role": g["role"], "variety": g["variety"], "target": g["target"],
               "weak": bool(g.get("weak"))}
        for when, md in (("before", v["maturity_days"]), ("after", fitted.get(g["variety"], v["maturity_days"]))):
            days = ph.days_to(d["cum"], ph.stage_gdd(v, ref, g["target"], md))
            s = ph.score(days, d["observed"])
            s["by_window"] = {w["label"]: float(np.nanmedian(days[(d["dates"] >= pd.Timestamp(w["start"]))
                                                               & (d["dates"] <= pd.Timestamp(w["end"]))]))
                              for w in g["windows"]}
            s["maturity_days"] = md
            out[when] = s
        scores.append(out)
    implied = {}
    for vk, md in fitted.items():               # days to maturity at the set's site with the fitted value
        d = next((data[g["id"]] for g in groups if g["variety"] == vk and not g.get("location")),
                 next(data[g["id"]] for g in groups if g["variety"] == vk and g["role"] == "train"))
        v = varieties[vk]
        implied[vk] = {when: float(np.nanmedian(ph.days_to(d["cum"], ph.stage_gdd(v, ref, "days_to_maturity", m))))
                       for when, m in (("before", v["maturity_days"]), ("after", md))}
    return {"fitted_maturity_days": fitted, "objective": objective, "scores": scores,
            "site_days_to_maturity": implied}


# ── yield checks and the benchmark (AquaCrop in the observed weather) ───────
def _with(v, ref, md=None):
    v = dict(v, maturity_days=md or v["maturity_days"])
    v["kw"], v["scale"] = aq.crop_parameters(v, ref)
    return v


def _set_value(v, key, value):
    """A variety with `key` set: maturity_days, or an AquaCrop crop parameter (in its `parameters`)."""
    v = dict(v, parameters=dict(v.get("parameters") or {}))
    if key == "maturity_days":
        v["maturity_days"] = value
    else:
        v["parameters"][key] = value
    return v


def _value(v, key):
    from aquacrop.entities.crop import crop_params
    if key == "maturity_days":
        return v["maturity_days"]
    return (v.get("parameters") or {}).get(key, crop_params[v["aquacrop_crop"]][key])


def based(cs, varieties):
    """The varieties with the set's `base` applied (the proposals of the earlier set it starts from)."""
    out = {k: dict(v) for k, v in varieties.items()}
    for vk, kv in ((cs.get("base") or {}).get("varieties") or {}).items():
        for k, x in kv.items():
            out[vk] = _set_value(out[vk], k, x)
    return out


def _irrigated_runs(g, v, ref, temps_of):
    """Yield under full irrigation at the group's location, every sowing date (the group's crop_overrides, e.g. the
    trial's plant density, applied to the run only)."""
    from crop_engine.calibration.potential import irrigated_potential
    temps, lat = temps_of(g)
    kw = dict(_with(v, ref)["kw"], **{k: float(x) for k, x in (g.get("crop_overrides") or {}).items()})
    return {lab: irrigated_potential(v["aquacrop_crop"], kw, temps, p, lat) for lab, p in _plants(g["sowing"]).items()}


def _median(runs, key="yield_t_ha"):
    vals = [r.get(key) for r in runs.values() if r.get(key) is not None and r["status"] != "too_late"]
    return round(float(np.median(vals)), 2) if vals else None


def fit_yield(cs, rows, base, ref, temps_of):
    """fit.parameter (an AquaCrop crop parameter) of each fitted variety, by bisection in fit.range, so that the
    median yield under full irrigation of its training groups matches their observed median; fit.share gives another
    variety the same value → (fitted {variety: value}, trace)."""
    key = cs["fit"]["parameter"]
    lo, hi = cs["fit"].get("range", [0.1, 0.7])
    fitted, trace = {}, {}
    for vk in cs["fit"]["varieties"]:
        groups = [g for g in cs["groups"] if g["role"] == "train" and g.get("target") == "yield"
                  and vk in _as_list(g["variety"])]
        obs = [float(np.median(rows[g["id"]].grain_yield_dry_kg_ha.dropna().astype(float))) / 1000 for g in groups]

        def err(x):
            v = _set_value(base[vk], key, x)
            return float(np.mean([_median(_irrigated_runs(g, v, ref, temps_of)) - o for g, o in zip(groups, obs)]))
        a, b = lo, hi
        ea, eb = err(a), err(b)
        if ea * eb > 0:
            raise ValueError(f"{vk}: no {key} in {lo}-{hi} matches the training yields (errors {ea:+.2f}, {eb:+.2f})")
        for _ in range(12):
            m = (a + b) / 2
            em = err(m)
            a, ea, b, eb = (a, ea, m, em) if ea * em <= 0 else (m, em, b, eb)
        fitted[vk] = round((a + b) / 2, 3)
        trace[vk] = {"parameter": key, "before": _value(base[vk], key), "after": fitted[vk],
                     "groups": [g["id"] for g in groups], "observed": [round(o, 2) for o in obs],
                     "model_before": round(err(_value(base[vk], key)) + float(np.mean(obs)), 2),
                     "model_after": round(err(fitted[vk]) + float(np.mean(obs)), 2)}
        print(f"  fit {vk} {key}: {trace[vk]['before']} -> {fitted[vk]} (yield {trace[vk]['model_before']} -> "
              f"{trace[vk]['model_after']} vs observed {trace[vk]['observed']})")
    for vk, src in (cs["fit"].get("share") or {}).items():
        fitted[vk] = fitted[src]
        trace[vk] = {"parameter": key, "before": _value(base[vk], key), "after": fitted[vk], "shared_from": src}
    return fitted, trace


def _plants(sow):
    return {f"{d:%d %b %Y}": d.date() for d in pd.date_range(sow["start"], sow["end"], freq=f"{sow.get('every_days', 7)}D")}


def _yield_runs_rainfed(g, v, plants_of, ctx):
    """AquaCrop in the observed weather of the group's season (the engine's adapter, as the benchmark)."""
    inp, site, k, layers, ds, dates, rain, y = ctx
    runs = {}
    for label, p in plants_of.items():
        if p is None:
            runs[label] = {"status": "not_sown"}
            continue
        r = aq.simulate(dict(dates=dates.values, rain=rain, tmax=ds.tmax_c.values[k], tmin=ds.tmin_c.values[k],
                             et0=ds.et0_mm.values[k], source=ds.precip_source.values, planting=[p], resow=None,
                             variety=v, kw=v["kw"], layers=layers, initial_frac=float(inp.initial_water(y)[k])))[0]
        runs[label] = {kk: r.get(kk) for kk in ("status", "planting", "harvest", "yield_t_ha", "potential_t_ha",
                                               "stress_days")}
    return runs


def yield_checks(cs, rows, before, after, ref, inp, temps_of):
    """Each yield check, before and after the fit. model: yield (rainfed, observed weather of season_year; needs
    the engine's inputs), potential (AquaCrop's potential in that rainfed run) or potential_irrigated (full
    irrigation at the group's location, crop_engine.calibration.potential)."""
    out = []
    for g in (g for g in cs["groups"] if g["role"] != "excluded" and g.get("target") == "yield"):
        model = g.get("model", "yield")
        ctx = plants = None
        if model != "potential_irrigated":
            from crop_engine.data import soil as soil_mod
            from crop_engine.scenarios import planting as pl
            import onset_rules as orl
            site = next(s for s in inp.sites if s.id == cs["site"])
            k = [s.id for s in inp.sites].index(site.id)
            y = int(g["season_year"])
            ds = inp.observed(y)
            dates = ds.time.to_index()
            rain = ds.precip_mm.values[:, k]
            ctx = (inp, site, k, soil_mod.profile(site), ds, dates, rain, y)
            if isinstance(g["sowing"], dict):
                plants = _plants(g["sowing"])
            else:
                pet = orl.load_pet(inp.lat, inp.lon, orl.EXT_DAYS)
                fao = pl.observed_fao_dates([site], [y])[site.id].get(y)
                plants = {r: (fao if r == "fao-agricultural" else
                              pl.observed_rule_date(rain[0], dates, pet[:, site.i, site.j], r)) for r in g["sowing"]}
        ob = rows[g["id"]].grain_yield_dry_kg_ha.dropna().astype(float).values / 1000
        res = {"group": g["id"], "role": g["role"], "season_year": g.get("season_year"), "expect": g.get("expect"), "model": model,
               "obs": {"n": int(len(ob)), "median": round(float(np.median(ob)), 2),
                       "p90": round(float(np.quantile(ob, 0.9)), 2), "max": round(float(ob.max()), 2)},
               "varieties": {}}
        for vk in _as_list(g["variety"]):
            per = {}
            for when, V in (("before", before), ("after", after)):
                v = _with(V.get(vk, before[vk]), ref)
                if model == "potential_irrigated":
                    runs = _irrigated_runs(g, v, ref, temps_of)
                    key = "yield_t_ha"
                else:
                    runs = _yield_runs_rainfed(g, v, plants, ctx)
                    key = "potential_t_ha" if model == "potential" else "yield_t_ha"
                vals = [r.get(key) for r in runs.values() if r.get(key) is not None and r["status"] != "too_late"]
                med = round(float(np.median(vals)), 2) if vals else None
                per[when] = {"runs": runs, "model_median": med,
                             "meets_expectation": (med is not None and med >= res["obs"]["median"])
                             if res["expect"] == "upper_bound" else None}
                print(f"  check {g['id']} {vk} {when}: model {med} vs observed median {res['obs']['median']}")
            res["varieties"][vk] = per
        out.append(res)
    return out


def benchmark(cs, before, after, ref, inp, workers):
    from crop_engine import run_outlook as ro
    from crop_engine.data import soil as soil_mod
    rep = [(s, [s.id]) for s, _ in ro.cells(inp.sites) if s.id == cs["site"]]
    soils = {s.id: soil_mod.profile(s) for s, _ in rep}
    out = {}
    for when, V in (("before", before), ("after", after)):
        vs = {vk: _with(V[vk], ref) for vk in after}
        b = ro.benchmark(inp, rep, vs, list(C.PLANTING_RULES), soils, workers)[cs["site"]]
        for vk, rs in b.items():
            for rk, r in rs.items():
                ys = list(r["years"].values())
                st = [x["status"] for x in ys]
                ok = [x["yield_t_ha"] for x in ys if x["status"] == "ok"]
                out.setdefault(vk, {}).setdefault(rk, {})[when] = {
                    "p_failure": r["p_failure"], "p_failure_if_sown": r["p_failure_if_sown"],
                    "yield_if_sown_median": r["yield_if_sown_t_ha"]["median"],
                    "matured_median": round(float(np.median(ok)), 2) if ok else None,
                    "too_late": st.count("too_late"), "died": st.count("died"), "ok": st.count("ok"),
                    "seasons": len(ys)}
    return out


# ── the report ──────────────────────────────────────────────────────────────
def _fmt(x, nd=1):
    return "–" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def report(cs, res):
    L = [f"# Calibration {cs['version']}: {cs['site']}", "",
         f"Run {res['run']} with {res['engine']}; observations {res['observations']}; temperatures ERA5-Land "
         f"(site series to {res['temps_end']}). The set: `crop_engine/calibration/sets/{cs['version']}.yaml`.", ""]
    if cs.get("base"):
        L += [f"Starts from **{cs['base']['from']}**'s proposals: " + "; ".join(
            f"{vk} " + ", ".join(f"{k} {x}" for k, x in kv.items()) for vk, kv in cs["base"]["varieties"].items())
            + ' ("before" is varieties.yaml; "after" is these and the fit).', ""]
    if res.get("yield_fit"):
        L += ["## Yield level: the fit", "",
              f"`{cs['fit']['parameter']}` fitted so the median yield under full irrigation (every sowing date of the "
              "training groups) matches their observed yield.", "",
              "| Variety | Before → after | Training groups | Observed (t/ha) | Model yield, before → after |",
              "| :--- | ---: | :--- | ---: | ---: |"]
        for vk, tr in res["yield_fit"].items():
            if "shared_from" in tr:
                L.append(f"| {vk} | {tr['before']} → **{tr['after']}** | the value of {tr['shared_from']} | | |")
            else:
                L.append(f"| {vk} | {tr['before']} → **{tr['after']}** | {', '.join(tr['groups'])} | "
                         f"{', '.join(map(str, tr['observed']))} | {tr['model_before']} → {tr['model_after']} |")
        L.append("")
    if res.get("phenology"):
        L += ["## Phenology: the fit", "",
         f"One parameter per variety, its `maturity_days` at {res['reference_tmean_c']} °C (every stage scaled "
         "together), fitted to the training trials' median days; the model's days are the median over every sowing "
         "date of the windows.", "",
         "| Variety | maturity_days before → after | days to maturity at the site, before → after |",
         "| :--- | ---: | ---: |"]
        p = res["phenology"]
        for vk, md in p["fitted_maturity_days"].items():
            im = p["site_days_to_maturity"][vk]
            L.append(f"| {vk} | {res['varieties'][vk]['maturity_days']} → **{md}** | {_fmt(im['before'], 0)} → "
                     f"{_fmt(im['after'], 0)} |")
        L += _phenology_scores(p)
    L += _yield_and_benchmark(res)
    return _groups_and_limits(cs, res, L)


def _phenology_scores(p):
    L = ["", "## Phenology: scores", "",
          "Bias: model median minus observed median (days); MAE: mean absolute difference of the entries from the "
          "model median; range: the model's over the sowing dates.", "",
          "| Group | Role | Target | n | Observed median (range) | Before: model (range), bias | "
          "After: model (range), bias, MAE |", "| :--- | :--- | :--- | ---: | ---: | ---: | ---: |"]
    for s in p["scores"]:
        b, a = s["before"], s["after"]
        L.append(f"| {s['group']}{' (weak)' if s['weak'] else ''} | {s['role']} | {s['target']} | {b['n_obs']} | "
                 f"{b['obs_median']} ({b['obs_min']}–{b['obs_max']}) | {b['model_median']} ({_fmt(b['model_min'], 0)}–"
                 f"{_fmt(b['model_max'], 0)}), {b['bias_days']:+} | {a['model_median']} ({_fmt(a['model_min'], 0)}–"
                 f"{_fmt(a['model_max'], 0)}), **{a['bias_days']:+}**, {a['mae_days']} |")
    L += ["", "By sowing window (model median days, after the fit):", ""]
    for s in p["scores"]:
        L.append(f"- {s['group']}: " + "; ".join(f"{k} {_fmt(v, 0)}" for k, v in s["after"]["by_window"].items()))
    return L


def _yield_and_benchmark(res):
    L = []
    if res.get("yield_checks"):
        L += ["", "## Yields (AquaCrop in the observed weather, or under full irrigation)", "",
              "| Group | Role | Variety | Observed median / p90 / max (t/ha) | Model before | Model after | "
              "Upper bound met (after) |", "| :--- | :--- | :--- | ---: | ---: | ---: | :--- |"]
        for c in res["yield_checks"]:
            o = c["obs"]
            for vk, per in c["varieties"].items():
                L.append(f"| {c['group']} ({c['model']}) | {c.get('role', 'check')} | {vk} | "
                         f"{o['median']} / {o['p90']} / {o['max']} | "
                         f"{_fmt(per['before']['model_median'], 2)} | {_fmt(per['after']['model_median'], 2)} | "
                         f"{per['after']['meets_expectation']} |")
        L += ["", "Runs (status, yield / potential t/ha), after the fit:", ""]
        for c in res["yield_checks"]:
            for vk, per in c["varieties"].items():
                L.append(f"- {c['group']} {vk}: " + "; ".join(
                    f"{lab} {r['status']} {_fmt(r.get('yield_t_ha'), 2)}/{_fmt(r.get('potential_t_ha'), 2)}"
                    for lab, r in per["after"]["runs"].items()))
    if res.get("benchmark"):
        L += ["", "## The site's benchmark, 1993–2025 (observed weather), before → after", "",
              "| Variety | Rule | Failure (all seasons) | Failure if sown | Too late | Died | Yield if sown, median | "
              "Matured, median |", "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for vk, rs in res["benchmark"].items():
            for rk, w in rs.items():
                b, a = w["before"], w["after"]
                L.append(f"| {vk} | {rk} | {b['p_failure']:.0%} → {a['p_failure']:.0%} | "
                         f"{_fmt(b['p_failure_if_sown'] and 100 * b['p_failure_if_sown'], 0)} → "
                         f"{_fmt(a['p_failure_if_sown'] and 100 * a['p_failure_if_sown'], 0)} % | {b['too_late']} → "
                         f"{a['too_late']} | {b['died']} → {a['died']} | {_fmt(b['yield_if_sown_median'], 2)} → "
                         f"{_fmt(a['yield_if_sown_median'], 2)} | {_fmt(b['matured_median'], 2)} → "
                         f"{_fmt(a['matured_median'], 2)} |")
    return L


def _groups_and_limits(cs, res, L):
    L += ["", "## The groups", ""]
    for g in cs["groups"]:
        src = f" Source: {g['observed']['source']}." if "observed" in g else ""
        loc = f" At {g['location']['name']} ({g['location']['lat']}, {g['location']['lon']})." if g.get("location") else ""
        L.append(f"- **{g['id']}** ({g['role']}, {res['counts'][g['id']]} observations): "
                 f"{' '.join(g['why'].split())}{loc}{src}")
    L += ["", "## Limits", "",
          "- Temperatures are ERA5-Land (0.1°) at the site, not the station's; a bias of 1 °C changes the days by "
          "about 6–7 % at Kiboko.",
          "- Trials without sowing dates are run over every plausible window; the windows' spread is in the ranges.",
          "- One parameter per variety: the ratio of flowering to maturity is AquaCrop's, not fitted (maize maturity "
          "is not observed at Kiboko).",
          "- The fitted values are proposed, not adopted: varieties.yaml changes only by hand, citing this set."]
    return "\n".join(L) + "\n"


def proposal(varieties, after):
    """What the set proposes to change in varieties.yaml, per variety: {key: {value, was}}."""
    out = {}
    for vk, v in after.items():
        d = {}
        if v["maturity_days"] != varieties[vk]["maturity_days"]:
            d["maturity_days"] = {"value": v["maturity_days"], "was": varieties[vk]["maturity_days"]}
        for k, x in (v.get("parameters") or {}).items():
            if (varieties[vk].get("parameters") or {}).get(k) != x:
                d[k] = {"value": x, "was": _value(varieties[vk], k)}
        if d:
            out[vk] = d
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="kiboko_v1")
    ap.add_argument("--benchmark", action="store_true", help="also the site's 1993–2025 benchmark, before and after")
    ap.add_argument("--no-yield", action="store_true", help="phenology only (no AquaCrop runs)")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()

    cs, path = load_set(a.set)
    obs_path = YIELD_OUT / "observations.csv"
    obs = pd.read_csv(obs_path, low_memory=False)
    rows = validate(cs, obs)
    cfg = yaml.safe_load(C.VARIETIES_FILE.read_text(encoding="utf-8"))
    ref, varieties = float(cfg["reference_tmean_c"]), cfg["varieties"]
    site = next(s for s in sites_mod.registered_sites() if s.id == cs["site"])
    temps = era5land.site_temperature(site, refresh=False)
    cs["_site_lat"] = site.lat
    temps_of = temperatures_of(cs, temps)

    res = {"set": cs["version"], "run": f"{dt.datetime.now():%Y-%m-%d %H:%M}", "engine": f"AquaCrop-OSPy {version('aquacrop')}",
           "observations": f"{obs_path.name} ({dt.datetime.fromtimestamp(obs_path.stat().st_mtime):%Y-%m-%d})",
           "temps_end": f"{temps.index.max():%Y-%m-%d}", "reference_tmean_c": ref,
           "varieties": {vk: {"maturity_days": varieties[vk]["maturity_days"],
                              "parameters": varieties[vk].get("parameters") or {}} for vk in varieties},
           "counts": {gid: int(len(r)) for gid, r in rows.items()}}
    param = cs["fit"].get("parameter", "maturity_days")
    base = based(cs, varieties)
    if param == "maturity_days":
        res["phenology"] = phenology(cs, rows, base, ref, temps_of)
        fitted = res["phenology"]["fitted_maturity_days"]
    else:
        fitted, res["yield_fit"] = fit_yield(cs, rows, base, ref, temps_of)
    after = {vk: base[vk] for vk in base if base[vk] != varieties[vk]}
    after.update({vk: _set_value(base[vk], param, x) for vk, x in fitted.items()})
    rainfed = any(g["role"] != "excluded" and g.get("target") == "yield" and g.get("model") != "potential_irrigated"
                  for g in cs["groups"])
    inp = None
    if (rainfed and not a.no_yield) or a.benchmark:
        from crop_engine.data import weather as W
        inp = W.Inputs(refresh=False)
    if not a.no_yield:
        res["yield_checks"] = yield_checks(cs, rows, varieties, after, ref, inp, temps_of)
    if a.benchmark:
        res["benchmark"] = benchmark(cs, varieties, after, ref, inp, a.workers)

    cs.pop("_site_lat", None)
    out = OUT / cs["version"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(report(cs, res), encoding="utf-8")
    (out / "fitted_varieties.yaml").write_text(
        f"# Proposed by calibration set {cs['version']} ({res['run']}); adopt by hand into varieties.yaml.\n"
        + yaml.safe_dump(proposal(varieties, after), sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"calibration {cs['version']}: {out}")
    for s in (res.get("phenology") or {}).get("scores", []):
        print(f"  {s['group']:30s} {s['role']:8s} obs {s['before']['obs_median']:6.1f}  model {s['before']['model_median']:6.1f}"
              f" → {s['after']['model_median']:6.1f}  bias {s['before']['bias_days']:+6.1f} → {s['after']['bias_days']:+6.1f}")


if __name__ == "__main__":
    main()
