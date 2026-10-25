#!/usr/bin/env python3
"""
site_report.py
──────────────
Per-site Short Rains status & outlook report: observed rainfall to date, the ECMWF ENS 1–15 day
outlook, and the seasonal forecast as ranges with tercile probabilities and a local skill note.

Inputs (defaults pick the latest available):
  --seasonal-dir  seasonal output folder updated with observations (with agro_onset/ inside)
  --ens-outlook   outputs/ecmwf_ens/ens_outlook_<init>.nc
Observations: CHIRPS final 2026 p25 + preliminary p25 (data/chirps_2026, data/chirps_prelim_2026)

Writes outputs/site_reports/<issue-date>/<site>.{json,md,png} and index.md.
"""
import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.path.insert(0, str(BASE_DIR / "backend"))
import agro_onset as ao  # noqa: E402

CAL = (1993, 2016)
CHIRPS_REC = BASE_DIR / "data" / "chirps_pr_ke" / "ke_chirps_pr_r25_1993_2025.nc"
CHIRPS_FINAL = BASE_DIR / "data" / "chirps_2026" / "chirps-v2.0.2026.days_p25.nc"
CHIRPS_PRELIM = BASE_DIR / "data" / "chirps_prelim_2026" / "chirps_prelim_2026_p25_kenya.nc"
CATS = ("early", "normal", "late")


# ── helpers ─────────────────────────────────────────────────────────────────
def d2s(doy, year=2026):
    if doy is None or not np.isfinite(doy):
        return "—"
    return (dt.date(year, 1, 1) + dt.timedelta(days=int(round(doy)) - 1)).strftime("%d %b")


def latest(pattern):
    files = sorted(glob.glob(str(BASE_DIR / pattern)))
    return Path(files[-1]) if files else None


def skill_note(var_label, rpss, hr, corr, mae, unit="days"):
    """Plain-language local skill category from hindcast verification at the pixel."""
    if np.isfinite(rpss) and rpss >= 0.10 and np.isfinite(corr) and corr >= 0.5:
        cat, text = "useful", "Forecasts here have been reliably better than the long-term average"
    elif (np.isfinite(rpss) and rpss > 0.0) or (np.isfinite(corr) and corr >= 0.3):
        cat, text = "limited", "Forecasts here have been only slightly better than the long-term average; treat as a tendency"
    else:
        cat, text = "no", "Forecasts here have not beaten the long-term average; rely on climatology and observations"
    nums = []
    if np.isfinite(mae):
        nums.append(f"typical error ±{mae:.0f} {unit}")
    if np.isfinite(corr):
        nums.append(f"correlation {corr:.2f}")
    if np.isfinite(rpss):
        nums.append(f"RPSS {rpss:+.2f}")
    if np.isfinite(hr):
        nums.append(f"hit rate {hr:.0%} (chance 33%)")
    return cat, f"{var_label}: **{cat} skill** — {text} ({', '.join(nums)})."


def corr_mae(ens_med, obs):
    ok = np.isfinite(ens_med) & np.isfinite(obs)
    if ok.sum() < 8:
        return np.nan, np.nan
    return float(np.corrcoef(ens_med[ok], obs[ok])[0, 1]), float(np.mean(np.abs(ens_med[ok] - obs[ok])))


def observed_series(lat, lon, year):
    """Observed daily rain for `year` from final + preliminary CHIRPS at the nearest 0.25° cell."""
    parts = []
    if CHIRPS_FINAL.exists():
        f = xr.open_dataset(CHIRPS_FINAL).precip.sel(latitude=lat, longitude=lon, method="nearest").to_series()
        parts.append(f[f.index.year == year])
    if CHIRPS_PRELIM.exists():
        p = xr.open_dataset(CHIRPS_PRELIM).precip.sel(lat=lat, lon=lon, method="nearest").to_series()
        parts.append(p[p.index.year == year])
    s = pd.concat(parts) if parts else pd.Series(dtype=float)
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s


# ── per-site report ─────────────────────────────────────────────────────────
def build(site, lat, lon, seasonal_dir, ens_file, issue):
    year = 2026
    sel = dict(lat=lat, lon=lon, method="nearest")
    meta_path = seasonal_dir / "run_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    R = {"site": site, "lat": lat, "lon": lon, "issued": issue.isoformat(),
         "seasonal_run": seasonal_dir.name, "seasonal_meta": meta,
         "ens_run": ens_file.stem if ens_file else None}

    # ── Observed to date ──
    obs = observed_series(lat, lon, year)
    rec = xr.open_dataset(CHIRPS_REC).precip.sel(**sel).to_series()
    oct_obs = obs[obs.index >= f"{year}-10-01"]
    obs_end = obs.index.max()
    n = len(oct_obs)
    # same calendar days (1 Oct + n days) in each past year
    normals = pd.Series({y: rec[(rec.index >= f"{y}-10-01") & (rec.index < pd.Timestamp(f"{y}-10-01") + pd.Timedelta(days=n))].sum()
                         for y in range(1993, 2026)})
    normal = float(normals.loc[CAL[0]:CAL[1]].mean())
    wet = oct_obs[oct_obs >= 1.0]
    q_bar = float(xr.open_dataarray(seasonal_dir / "chirps_Q_bar.nc").sel(**sel))
    win_obs = obs[(obs.index >= f"{year}-09-01")]
    A = np.cumsum(win_obs.values - q_bar)
    dunning_started = bool(len(A) > 5 and np.argmin(A) < len(A) - 5 and A[-1] - A.min() > 10)
    a_daily = win_obs.values.astype(np.float32)
    s_idx = ao.RULE["search_start_doy"] - 244
    rule = {k: v for k, v in ao.RULE.items() if k != "search_start_doy"}
    a_idx, a_prov = ao.detect(a_daily, s_idx, **rule)
    agro_obs = None if not np.isfinite(a_idx) else (pd.Timestamp(f"{year}-09-01") + pd.Timedelta(days=int(a_idx))).date()
    R["observed"] = {
        "through": str(obs_end.date()), "oct_total_mm": round(float(oct_obs.sum()), 1), "days": n,
        "normal_same_days_mm": round(normal, 1), "pct_of_normal": round(100 * oct_obs.sum() / normal) if normal > 0 else None,
        "rank_driest": int((normals < oct_obs.sum()).sum()) + 1, "rank_of": len(normals) + 1,
        "tied_years": [int(y) for y in normals.index[np.isclose(normals.values, oct_obs.sum(), atol=0.5)]],
        "wet_days": int(len(wet)), "last_wet_day": str(wet.index.max().date()) if len(wet) else None,
        "dunning_onset_started": dunning_started,
        "agro_onset_observed": str(agro_obs) if agro_obs else None, "agro_onset_provisional": bool(a_prov) if agro_obs else None,
    }

    # ── Real-time satellite products (realtime_rain.py) ──
    try:
        import realtime_rain as rr
        df = rr.site_series(lat, lon, f"{year}-09-01")
    except Exception:
        df = pd.DataFrame()
    prods = {}
    for p in df.columns:
        s_ = df[p].dropna()
        if s_.empty:
            continue
        d_oct = s_[s_.index >= f"{year}-10-01"]
        wet_p = d_oct[d_oct >= 1.0]
        full = s_.reindex(pd.date_range(f"{year}-09-01", s_.index.max())).values.astype(np.float32)
        on_i, on_prov = ao.detect(full, s_idx, **rule)
        prods[p] = {"label": rr.LABELS[p], "through": str(s_.index.max().date()), "oct_total_mm": round(float(d_oct.sum()), 1),
                    "last_wet_day": str(wet_p.index.max().date()) if len(wet_p) else None,
                    "last7": [round(float(v), 1) for v in s_.iloc[-7:].values],
                    "planting_onset": str((pd.Timestamp(f"{year}-09-01") + pd.Timedelta(days=int(on_i))).date()) if np.isfinite(on_i) else None,
                    "planting_onset_provisional": bool(on_prov) if np.isfinite(on_i) else None}
    R["products"] = prods
    R["observed"]["products_with_onset"] = [p for p, v in prods.items() if v["planting_onset"]]

    # ── ENS 1–15 day outlook ──
    if ens_file:
        e = xr.open_dataset(ens_file).sel(**sel)
        times = pd.DatetimeIndex(e.time.values)
        comp = e.composite_onset_doy.values
        comp_f = comp[np.isfinite(comp)]
        R["ens"] = {
            "init": str(times[0].date()),
            "daily": [{"date": str(t.date()), "p_rain": round(float(e.p_wet.values[i]), 2),
                       "p_10mm": round(float(e.p_ge10mm.values[i]), 2), "median_mm": round(float(e.median_mm.values[i]), 1),
                       "p_trigger": round(float(e.p_trigger_start.values[i]), 2)} for i, t in enumerate(times)],
            "p_trigger_7d": round(float(e.p_trigger_7d), 2), "p_trigger_15d": round(float(e.p_trigger_15d), 2),
            "p_onset_15d": round(float(e.p_onset_15d), 2),
            "composite_onset": {"median": d2s(np.median(comp_f)) if comp_f.size else "—",
                                "p25": d2s(np.percentile(comp_f, 25)) if comp_f.size else "—",
                                "p75": d2s(np.percentile(comp_f, 75)) if comp_f.size else "—",
                                "p_none": round(float(np.mean(~np.isfinite(comp))), 2)},
        }

    # ── Seasonal ranges, probabilities, skill ──
    # If onset has not been observed, members whose onset falls before the condition date (issue / ENS
    # start date — days not yet covered by observations) are dropped and probabilities recomputed with
    # the calibrated alpha. Cessation / LGP use the same surviving members as their onset definition.
    c_years = slice(1993, 2025)
    cond = None
    if (not R["observed"]["agro_onset_observed"] and not R["observed"]["dunning_onset_started"]
            and not R["observed"]["products_with_onset"]):
        cond = pd.Timestamp(R["ens"]["init"]) if R.get("ens") else pd.Timestamp(issue)
    newest = max([R["observed"]["through"]] + [v["through"] for v in R.get("products", {}).values()])
    gap = (pd.Timestamp(cond) - pd.Timestamp(newest)).days - 1 if cond is not None else 0
    R["condition"] = (f"members with onset before {cond:%d %b} removed (no onset in any satellite product up to {newest}"
                      + (f"; the last {gap} day(s) before {cond:%d %b} are assumed dry" if gap > 0 else "") + ")") if cond is not None else None
    keep = {}
    for grp, f_on in (("dunning", "ECMWF_onset_doy_all_years.nc"), ("agro", "agro_onset/ECMWF_agro_onset_doy_all_years.nc")):
        on = xr.open_dataarray(seasonal_dir / f_on).sel(**sel).sel(year=year).values if (seasonal_dir / f_on).exists() else None
        keep[grp] = None if (on is None or cond is None) else (~np.isfinite(on)) | (on >= cond.dayofyear)
    seas = {}
    specs = [
        ("onset", "Onset (Dunning)", "ECMWF_onset_doy_all_years.nc", "CHIRPS_onset_doy_1981_2025.nc", "probs_op_2026_onset.nc",
         "calibration_params/t33_onset_doy.nc", "calibration_params/t67_onset_doy.nc", "rpss_onset_val.nc", "hitrate_onset_val.nc",
         "alpha_onset.nc", "dunning", True),
        ("agro_onset", "Planting onset (20 mm rule)", "agro_onset/ECMWF_agro_onset_doy_all_years.nc", "agro_onset/CHIRPS_agro_onset_doy.nc",
         "agro_onset/probs_op_2026_agro_onset.nc", "agro_onset/t33_agro_onset.nc", "agro_onset/t67_agro_onset.nc",
         "agro_onset/rpss_val_agro_onset.nc", "agro_onset/hitrate_val_agro_onset.nc", "agro_onset/alpha_agro_onset.nc", "agro", True),
        ("cessation", "Cessation", "ECMWF_cessation_doy_all_years.nc", "CHIRPS_cessation_doy_1981_2025.nc", "probs_op_2026_cessation.nc",
         "calibration_params/t33_cessation_doy.nc", "calibration_params/t67_cessation_doy.nc", "rpss_cessation_val.nc", "hitrate_cessation_val.nc",
         "alpha_cessation.nc", "dunning", True),
        ("lgp", "Season length", "ECMWF_lgp_days_all_years.nc", "CHIRPS_lgp_days_1981_2025.nc", "probs_op_2026_lgp.nc",
         "calibration_params/t33_lgp_days.nc", "calibration_params/t67_lgp_days.nc", "rpss_lgp_val.nc", "hitrate_lgp_val.nc",
         "alpha_lgp.nc", "dunning", False),
    ]
    for key, label, f_e, f_c, f_p, f_t33, f_t67, f_r, f_h, f_a, grp, is_date in specs:
        if not (seasonal_dir / f_e).exists():
            continue
        E = xr.open_dataarray(seasonal_dir / f_e).sel(**sel)
        C = xr.open_dataarray(seasonal_dir / f_c).sel(**sel).sel(year=c_years)
        mem = E.sel(year=year).values
        if keep[grp] is not None and keep[grp].any():
            mem = mem[keep[grp]]
        fin = mem[np.isfinite(mem)]
        p = xr.open_dataarray(seasonal_dir / f_p).sel(**sel).values
        if keep[grp] is not None and keep[grp].any():
            t33_, t67_ = (float(xr.open_dataarray(seasonal_dir / f).sel(**sel)) for f in (f_t33, f_t67))
            m_ = np.where(np.isfinite(mem), mem, ao.NO_ONSET) if key == "agro_onset" else mem[np.isfinite(mem)]
            p_raw = np.array([np.mean(m_ < t33_), np.mean((m_ >= t33_) & (m_ < t67_)), np.mean(m_ >= t67_)]) if m_.size else np.full(3, 1 / 3)
            alpha = float(xr.open_dataarray(seasonal_dir / f_a).sel(**sel))
            p = alpha * p_raw + (1 - alpha) / 3
        t33 = float(xr.open_dataarray(seasonal_dir / f_t33).sel(**sel))
        t67 = float(xr.open_dataarray(seasonal_dir / f_t67).sel(**sel))
        rp = float(xr.open_dataarray(seasonal_dir / f_r).sel(**sel))
        hr = float(xr.open_dataarray(seasonal_dir / f_h).sel(**sel))
        yrs = np.intersect1d(E.year.values, C.year.values)
        med_hist = np.array([np.nanmedian(E.sel(year=y).values) for y in yrs])
        r, mae = corr_mae(med_hist, C.sel(year=yrs).values)
        cat, note = skill_note(label, rp, hr, r, mae)
        cv = C.values[np.isfinite(C.values)]
        fmt = d2s if is_date else (lambda v: f"{v:.0f} d" if np.isfinite(v) else "—")
        q = lambda pc: fmt(np.percentile(fin, pc)) if fin.size else "—"
        flags = []
        if is_date and fin.size and cv.size:
            if np.median(fin) < cv.min():
                flags.append(f"forecast median is earlier than any observed {label.lower()} since 1993 (earliest {d2s(cv.min())})")
            if np.median(fin) > cv.max():
                flags.append(f"forecast median is later than any observed {label.lower()} since 1993 (latest {d2s(cv.max())})")
        names = ("short", "normal", "long") if key == "lgp" else CATS
        seas[key] = {
            "label": label, "median": q(50), "likely_range": f"{q(25)} – {q(75)}", "wide_range": f"{q(10)} – {q(90)}",
            "p": {names[i]: round(float(p[i]), 2) for i in range(3)},
            "normal": fmt(np.mean(C.sel(year=slice(*CAL)).values[np.isfinite(C.sel(year=slice(*CAL)).values)])),
            "normal_band": f"{fmt(t33)} – {fmt(t67)}", "observed_range": f"{fmt(cv.min())} – {fmt(cv.max())}" if cv.size else "—",
            "p_no_event": round(float(np.mean(~np.isfinite(mem))), 2), "n_members": int(mem.size),
            "skill": {"category": cat, "rpss_val": round(rp, 2), "hitrate_val": round(hr, 2),
                      "corr": round(r, 2) if np.isfinite(r) else None, "mae": round(mae, 1) if np.isfinite(mae) else None},
            "skill_note": note, "flags": flags, "_members": fin.tolist(),
            "num": {**{f"p{pc}": round(float(np.percentile(fin, pc)), 1) if fin.size else None for pc in (10, 25, 50, 75, 90)},
                    "normal": round(float(np.nanmean(C.sel(year=slice(*CAL)).values)), 1), "t33": round(t33, 1), "t67": round(t67, 1),
                    "obs_min": round(float(cv.min()), 1) if cv.size else None, "obs_max": round(float(cv.max()), 1) if cv.size else None},
        }
    R["seasonal"] = seas
    R["advice"] = advice(R)
    return R


def advice(R):
    o, s, e = R["observed"], R["seasonal"], R.get("ens")
    lines = []
    P = R.get("products", {})
    if P:
        newest = max(v["through"] for v in P.values())
        wet = [f"{v['label'].split(' ')[0]} {v['oct_total_mm']} mm to {v['through'][5:]}" for v in P.values()]
        n_on = len(o["products_with_onset"])
        lines.append(f"Satellite products since 1 Oct: {'; '.join(wet)}. Planting onset detected by {n_on} of {len(P)} products"
                     + (f" ({', '.join(P[p]['label'].split(' ')[0] + ' ' + P[p]['planting_onset'][5:] for p in o['products_with_onset'])})" if n_on else "")
                     + f"; latest satellite day {newest}.")
    if o["agro_onset_observed"]:
        lines.append(f"Planting rains detected on {o['agro_onset_observed']}" + (" (still to be confirmed: dry-spell check incomplete)." if o["agro_onset_provisional"] else "."))
    else:
        others = [y for y in o["tied_years"]]
        rank = "driest" if o["rank_driest"] == 1 else f"#{o['rank_driest']} driest"
        tie = f", tied with {', '.join(map(str, others))}" if others else ""
        lines.append(f"Rains have not started yet: {o['oct_total_mm']} mm since 1 Oct ({o['pct_of_normal']}% of normal; "
                     f"{rank} start since 1993{tie}) — satellite data to {o['through']}.")
    if e:
        lines.append(f"Next 15 days (ECMWF ENS {e['init']}): {e['p_trigger_7d']:.0%} chance of a planting-rain event (≥20 mm in ≤3 days) "
                     f"within 7 days, {e['p_trigger_15d']:.0%} within 15 days; {e['p_onset_15d']:.0%} chance that planting onset "
                     f"(with no 10-day dry spell after) occurs within 15 days.")
        lines.append("ENS rainfall is raw (not bias-corrected) and tends to overstate light-rain days; "
                     "weigh the ≥10 mm and 3-day-total signals more than daily rain chances.")
    if "agro_onset" in s:
        a = s["agro_onset"]
        lines.append(f"Seasonal outlook for planting onset{' (' + R['condition'] + ')' if R.get('condition') else ''}: "
                     f"most likely {a['median']}, likely {a['likely_range']} "
                     f"(P early/normal/late {a['p']['early']:.0%}/{a['p']['normal']:.0%}/{a['p']['late']:.0%}; normal {a['normal']}). {a['skill_note']}")
    lines.append("Plant only after confirmed rain on site (≥20 mm in 1–3 days) and check the next 10-day outlook for dry spells.")
    return lines


# ── outputs ─────────────────────────────────────────────────────────────────
def write_md(R, path):
    o = R["observed"]
    L = [f"# {R['site']} — Short Rains 2026 status & outlook",
         f"*Issued {R['issued']} · pixel {R['lat']:.2f}, {R['lon']:.2f} · seasonal: {R['seasonal_run']}"
         f"{' (obs to ' + R['seasonal_meta'].get('obs_end', '?') + ')' if R['seasonal_meta'] else ''} · ENS: {R.get('ens_run') or '—'}*", "",
         "## Summary", *[f"- {x}" for x in R["advice"]], "",
         "## Observed rainfall (CHIRPS final + preliminary)",
         f"- 1 Oct – {o['through']}: **{o['oct_total_mm']} mm** in {o['days']} days (normal {o['normal_same_days_mm']} mm, {o['pct_of_normal']}%); "
         f"wet days {o['wet_days']}; last day ≥1 mm: {o['last_wet_day'] or 'none since 1 Oct'}",
         f"- Rank: {o['rank_driest']} of {o['rank_of']} (1 = driest since 1993)"
         + (f"; tied with {', '.join(map(str, o['tied_years']))}" if o["tied_years"] else ""),
         f"- Seasonal onset (Dunning) started: {'yes' if o['dunning_onset_started'] else 'no'} · planting onset (20 mm rule): "
         f"{o['agro_onset_observed'] or 'not yet'}", ""]
    if R.get("products"):
        L += ["## Real-time satellite rainfall", "| Product | Data to | Rain since 1 Oct | Last day ≥1 mm | Last 7 days (mm) | Planting onset (20 mm rule) |",
              "|---|---|---|---|---|---|",
              *[f"| {v['label']} | {v['through']} | {v['oct_total_mm']} mm | {v['last_wet_day'] or '—'} | {' · '.join(map(str, v['last7']))} | "
                f"{(v['planting_onset'] + (' (provisional)' if v['planting_onset_provisional'] else '')) if v['planting_onset'] else 'not yet'} |"
                for v in R["products"].values()], ""]
    if R.get("ens"):
        e = R["ens"]
        L += [f"## Next 15 days — ECMWF ENS ({e['init']}, 50 members, raw)",
              "| Date | P(rain ≥1 mm) | P(≥10 mm) | Median mm | P(planting-rain event starts) |", "|---|---|---|---|---|",
              *[f"| {d['date']} | {d['p_rain']:.0%} | {d['p_10mm']:.0%} | {d['median_mm']} | {d['p_trigger']:.0%} |" for d in e["daily"]],
              "", f"- P(planting-rain event within 7 d / 15 d): **{e['p_trigger_7d']:.0%} / {e['p_trigger_15d']:.0%}**",
              f"- P(planting onset — event + no 10-day dry spell — within 15 d): **{e['p_onset_15d']:.0%}**; "
              f"combined ENS+seasonal planting onset: median {e['composite_onset']['median']} "
              f"(likely {e['composite_onset']['p25']} – {e['composite_onset']['p75']}), none by 31 Dec {e['composite_onset']['p_none']:.0%}", ""]
    L += ["## Season outlook (ranges, probabilities, local skill)",
          *([f"*Conditioned: {R['condition']}.*", ""] if R.get("condition") else []),
          "| Variable | Most likely | Likely range (50%) | Wide range (80%) | P(early·short / normal / late·long) | Normal (CAL mean; normal band) | Local skill |",
          "|---|---|---|---|---|---|---|"]
    for v in R["seasonal"].values():
        p = list(v["p"].values())
        L.append(f"| {v['label']} | {v['median']} | {v['likely_range']} | {v['wide_range']} | {p[0]:.0%} / {p[1]:.0%} / {p[2]:.0%} | "
                 f"{v['normal']}; {v['normal_band']} | {v['skill']['category']} |")
    L += ["", "### Skill notes", *[f"- {v['skill_note']}" for v in R["seasonal"].values()]]
    flags = [f for v in R["seasonal"].values() for f in v["flags"]]
    if flags:
        L += ["", "### ⚠ Flags", *[f"- {f}" for f in flags]]
    L += ["", "*Skill = hindcast verification at this pixel (1993–2025; RPSS/hit rate on 2017–2024). "
              "ENS rainfall is not bias-corrected. Seasonal members are EQM bias-corrected and include observed rainfall up to the date shown.*"]
    path.write_text("\n".join(L), encoding="utf-8")


def plot(R, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.2), constrained_layout=True, gridspec_kw={"width_ratios": [1.1, 1]})
    if R.get("ens"):
        d = R["ens"]["daily"]
        x = [pd.Timestamp(z["date"]).strftime("%d %b") for z in d]
        ax = axes[0]
        ax.bar(x, [z["p_rain"] for z in d], color="#93c5fd", label="P(rain ≥1 mm)")
        ax.bar(x, [z["p_10mm"] for z in d], color="#1d4ed8", label="P(≥10 mm)")
        ax.plot(x, [z["p_trigger"] for z in d], "o-", color="#b91c1c", label="P(planting-rain event starts)")
        ax.set_ylim(0, 1); ax.set_ylabel("probability"); ax.tick_params(axis="x", rotation=60, labelsize=8)
        ax.set_title(f"Next 15 days — ECMWF ENS {R['ens']['init']}", fontsize=10); ax.legend(fontsize=8, loc="upper left")
    ax = axes[1]
    rows = [(k, v) for k, v in R["seasonal"].items() if k != "lgp"]
    for i, (k, v) in enumerate(rows):
        y = len(rows) - 1 - i
        m = np.array(v["_members"])
        ax.scatter(m, np.full(len(m), y) + np.random.default_rng(i).uniform(-0.12, 0.12, len(m)), s=12, color="#0369a1", alpha=0.6)
        if m.size:
            ax.scatter([np.median(m)], [y], marker="D", s=50, color="#0c4a6e", zorder=3)
    ax.axvline(pd.Timestamp(R["issued"]).dayofyear, color="#64748b", ls="--", lw=1)
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([v["label"] for _, v in rows][::-1])
    ticks = [274, 288, 305, 319, 335, 349, 365]
    ax.set_xticks(ticks); ax.set_xticklabels([d2s(t) for t in ticks], fontsize=8)
    ax.set_title("Season — ensemble members (◆ median, dashed = issue date)", fontsize=10)
    fig.suptitle(f"{R['site']} ({R['lat']:.2f}, {R['lon']:.2f}) — issued {R['issued']}", fontsize=11)
    fig.savefig(path, dpi=110); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasonal-dir", default=None)
    ap.add_argument("--ens-outlook", default=None)
    ap.add_argument("--site", action="append", help="'Name,lat,lon' (repeatable); default: Kenya monitored sites")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sd = Path(a.seasonal_dir) if a.seasonal_dir else next(
        p for p in [BASE_DIR / "outputs" / "ecmwf_oct_obs_latest", BASE_DIR / "outputs" / "ecmwf_oct_obs1020"] if p.exists())
    ens = Path(a.ens_outlook) if a.ens_outlook else latest("outputs/ecmwf_ens/ens_outlook_*.nc")
    if a.site:
        sites = [(s.split(",")[0], float(s.split(",")[1]), float(s.split(",")[2])) for s in a.site]
    else:
        import mam_loader
        sites = [(s["site_name"], s["lat"], s["lon"]) for s in mam_loader.SITES if s["country"] == "kenya"]
    issue = dt.date.today()
    out = BASE_DIR / "outputs" / "site_reports" / issue.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    index = [f"# Short Rains 2026 site reports — {issue}", f"Seasonal: `{sd.name}` · ENS: `{ens.stem if ens else '—'}`", "",
             "| Site | Rain since 1 Oct (% normal) | P(planting event ≤7 d) | Planting onset: most likely (likely range) | P early/normal/late | Planting-onset skill |",
             "|---|---|---|---|---|---|"]
    for name, lat, lon in sites:
        R = build(name, lat, lon, sd, ens, issue)
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
        (out / f"{slug}.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
        write_md(R, out / f"{slug}.md")
        plot(R, out / f"{slug}.png")
        ag = R["seasonal"].get("agro_onset", {})
        o = R["observed"]
        index.append(f"| [{name}]({slug}.md) | {o['oct_total_mm']} mm ({o['pct_of_normal']}%) | "
                     f"{R['ens']['p_trigger_7d']:.0%} | {ag.get('median', '—')} ({ag.get('likely_range', '—')}) | "
                     f"{'/'.join(f'{v:.0%}' for v in ag.get('p', {}).values())} | {ag.get('skill', {}).get('category', '—')} |"
                     if R.get("ens") else f"| {name} | {o['oct_total_mm']} mm | — | — | — | — |")
        print(f"  {name}: {R['advice'][0]}")
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
