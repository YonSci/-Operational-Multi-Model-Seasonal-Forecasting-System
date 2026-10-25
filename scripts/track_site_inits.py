#!/usr/bin/env python3
"""
track_site_inits.py
───────────────────
Compare Short Rains onset / cessation / season length (LGP) at one site across every
ECMWF SEAS5 initialization the backend has loaded (Sep, Oct, Oct+Obs, ...).

Writes to outputs/site_tracker/<site>/:
  inits_summary.csv   one row per initialization x variable (median, P10-P90, terciles, anomaly)
  inits_members.csv   every ensemble member's onset / cessation / LGP per initialization
  inits_compare.png   ensemble distributions per initialization against CHIRPS climatology

Usage:
  python scripts/track_site_inits.py --name "Kapiti Research Station Farm" --lat -1.63209 --lon 37.1479
"""
import argparse
import csv
import datetime as dt
import os
import re
import sys
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))
import mam_loader as dl  # noqa: E402

# Initialization label -> backend model name, in issue order
INITS = [
    ("Sep 01", "ECMWF SEAS5 (Sep)"),
    ("Oct 01", "ECMWF SEAS5 (Oct)"),
    ("Oct 01 + Sep obs", "ECMWF SEAS5 (Oct+Obs)"),
    ("Oct 01 + latest obs", "ECMWF SEAS5 (Oct+Obs latest)"),
]
VARS = [("onset", "on_v", "Onset"), ("cessation", "cs_v", "Cessation"), ("lgp", "lg_v", "Season length")]
CATS = ["BN", "NN", "AN"]
P_KEY = {"onset": "p_on", "cessation": "p_cs", "lgp": "p_lgp"}


def doy_to_date(doy, year):
    if doy is None or not np.isfinite(doy):
        return ""
    return (dt.date(year, 1, 1) + dt.timedelta(days=int(round(doy)) - 1)).strftime("%d %b")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="Kapiti Research Station Farm")
    ap.add_argument("--lat", type=float, default=-1.63209)
    ap.add_argument("--lon", type=float, default=37.1479)
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dl.configure()
    dl.load()
    loaded = dl.get_state()["MODELS"]

    out_dir = BASE_DIR / "outputs" / "site_tracker" / re.sub(r"[^A-Za-z0-9]+", "_", a.name).strip("_")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary, members, plot_data = [], [], []
    for label, model in INITS:
        if model not in loaded:
            print(f"  skip {label}: {model} not loaded")
            continue
        px = dl.get_pixel_stats(a.lat, a.lon, season="short_rains", model=model, year=a.year)
        st = px["models"][model]
        for var, vkey, title in VARS:
            vals = np.asarray(st[vkey], dtype=float)
            clim = float(px["chirps_clim"][var])
            p = st[P_KEY[var]]
            med = float(np.median(vals)) if len(vals) else float("nan")
            row = dict(
                init=label, model=model, variable=var, window=f"DOY {px['win_doy_start']}-{px['win_doy_end']}",
                n_valid=len(vals), n_members=st["nm"],
                median=round(med, 1), p10=round(st.get(f"{vkey[:2]}_p10", np.nan), 1), p90=round(st.get(f"{vkey[:2]}_p90", np.nan), 1),
                chirps_clim=round(clim, 1), anomaly=round(med - clim, 1),
                t33=round(px["t33"][var], 1), t67=round(px["t67"][var], 1),
                p_bn=round(p[0], 2), p_nn=round(p[1], 2), p_an=round(p[2], 2), dominant=CATS[int(np.argmax(p))],
                median_date="" if var == "lgp" else doy_to_date(med, a.year),
                clim_date="" if var == "lgp" else doy_to_date(clim, a.year),
                p_fail=round(st["p_fail"], 3),
            )
            summary.append(row)
            for i, v in enumerate(vals):
                members.append(dict(init=label, variable=var, member_rank=i + 1, value=v))
            plot_data.append((label, var, vals, clim, px["t33"][var], px["t67"][var], p))

    with open(out_dir / "inits_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    with open(out_dir / "inits_members.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["init", "variable", "member_rank", "value"])
        w.writeheader()
        w.writerows(members)

    _plot(plot_data, a, out_dir / "inits_compare.png")

    print(f"\n{a.name} ({a.lat:.3f}, {a.lon:.3f})  —  Short Rains {a.year}")
    for r in summary:
        unit = "d" if r["variable"] == "lgp" else ""
        when = f" ({r['median_date']}, clim {r['clim_date']})" if r["median_date"] else f" (clim {r['chirps_clim']}d)"
        print(f"  {r['init']:<17} {r['variable']:<9} median {r['median']}{unit}{when}  anom {r['anomaly']:+}d  "
              f"P(BN/NN/AN) {r['p_bn']:.2f}/{r['p_nn']:.2f}/{r['p_an']:.2f}  [{r['window']}]")
    print(f"\n  wrote {out_dir}")


def _plot(plot_data, a, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    inits = list(dict.fromkeys(d[0] for d in plot_data))
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), constrained_layout=True)
    for ax, (var, _, title) in zip(axes, VARS):
        rows = [d for d in plot_data if d[1] == var]
        for k, (label, _, vals, clim, t33, t67, p) in enumerate(rows):
            y = len(rows) - 1 - k
            ax.plot([t33, t67], [y, y], color="#cbd5e1", lw=10, solid_capstyle="butt", zorder=1)
            ax.scatter(vals, np.full(len(vals), y) + np.random.default_rng(k).uniform(-0.12, 0.12, len(vals)),
                       s=12, color="#0369a1", alpha=0.6, zorder=2)
            if len(vals):
                ax.plot([np.percentile(vals, 10), np.percentile(vals, 90)], [y, y], color="#0c4a6e", lw=1.5, zorder=3)
                ax.scatter([np.median(vals)], [y], marker="D", s=50, color="#0c4a6e", zorder=4)
            ax.scatter([clim], [y], marker="|", s=300, color="#b91c1c", zorder=5)
            ax.text(1.01, y, f"BN {p[0]:.2f}\nNN {p[1]:.2f}\nAN {p[2]:.2f}", transform=ax.get_yaxis_transform(),
                    va="center", fontsize=7, color="#334155")
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows][::-1])
        ax.set_title(title)
        ax.set_xlabel("days" if var == "lgp" else "day of year")
        ax.grid(axis="x", color="#e2e8f0")
        if var != "lgp":
            ticks = [274, 288, 305, 319, 335, 349, 365]
            ax.set_xticks(ticks)
            ax.set_xticklabels([doy_to_date(t, a.year) for t in ticks], fontsize=7)
    fig.suptitle(f"{a.name} ({a.lat:.2f}, {a.lon:.2f}) — Short Rains {a.year} by ECMWF SEAS5 initialization\n"
                 "dots: members · ◆ median · line: P10–P90 · grey band: CHIRPS near-normal tercile · red |: CHIRPS mean",
                 fontsize=10)
    fig.savefig(path, dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
