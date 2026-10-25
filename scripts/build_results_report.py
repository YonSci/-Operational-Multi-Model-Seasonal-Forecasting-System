#!/usr/bin/env python3
"""
build_results_report.py
───────────────────────
Self-contained local HTML report of the latest Short Rains results (no network, images embedded):
site status, per-site outlook figures, Kenya maps, satellite product comparison, verification,
and the Kapiti initialization tracker.

Reads outputs/dashboard/*.csv (export_dashboard_data.py), outputs/site_reports/<latest>/*.png,
outputs/realtime_rain/verification_*.csv, outputs/site_tracker/Kapiti_Research_Station_Farm/inits_compare.png
Writes outputs/results_report_<date>.html
"""
import base64
import glob
import html
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
D = BASE / "outputs" / "dashboard"


def img(path_or_fig):
    if isinstance(path_or_fig, (str, Path)):
        b = Path(path_or_fig).read_bytes()
    else:
        buf = io.BytesIO()
        path_or_fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        plt.close(path_or_fig)
        b = buf.getvalue()
    return f'<img src="data:image/png;base64,{base64.b64encode(b).decode()}" alt="">'


def table(df, cols, fmt=None, cls=None):
    fmt = fmt or {}
    h = "".join(f"<th>{html.escape(lab)}</th>" for _, lab in cols)
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c, _ in cols:
            v = r.get(c)
            s = "—" if v is None or (isinstance(v, float) and np.isnan(v)) or v == "" else (fmt[c](v) if c in fmt else str(v))
            tds.append(f"<td{(' class=' + chr(34) + cls(c, v) + chr(34)) if cls and cls(c, v) else ''}>{html.escape(s)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="scroll"><table><thead><tr>{h}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def maps(grid, sites):
    specs = [("chirps_pct_normal", "Rain since 1 Oct, % of normal (CHIRPS)", "BrBG", 0, 200, "%"),
             ("ens_p_event_7d", "Chance of planting rains within 7 days (ECMWF)", "Blues", 0, 1, "p"),
             ("season_p_early", "Seasonal chance of an early planting onset", "Purples", 0, 0.7, "p")]
    lat = np.sort(grid.lat.unique()); lon = np.sort(grid.lon.unique())
    fig, axes = plt.subplots(1, 3, figsize=(15, 6), constrained_layout=True)
    for ax, (f, title, cmap, vmin, vmax, kind) in zip(axes, specs):
        z = grid.pivot_table(index="lat", columns="lon", values=f).reindex(index=lat, columns=lon).values
        zone = grid.pivot_table(index="lat", columns="lon", values="in_zone").reindex(index=lat, columns=lon).values
        m = ax.pcolormesh(lon, lat, np.where(zone == 1, z, np.nan), cmap=cmap, vmin=vmin, vmax=vmax, shading="nearest")
        ax.pcolormesh(lon, lat, np.where(zone == 1, np.nan, z), cmap=cmap, vmin=vmin, vmax=vmax, shading="nearest", alpha=0.25)
        bpath = D / "boundaries.json"
        if bpath.exists():
            import json
            for f_ in json.loads(bpath.read_text()):
                g = f_["geometry"]
                polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
                for rings in polys:
                    for ring in rings:
                        xy = np.array(ring)
                        ax.plot(xy[:, 0], xy[:, 1], color="k" if f_["level"] == "country" else "0.45",
                                lw=1.2 if f_["level"] == "country" else 0.4, zorder=2)
        ax.scatter(sites.lon, sites.lat, s=30, c="k", edgecolors="w", zorder=3)
        for _, s in sites.iterrows():
            ax.annotate(s.site.split(",")[0].replace(" Farm", "").replace("Genco LTD ", "").replace(" Research Station", ""),
                        (s.lon, s.lat), xytext=(4, 3), textcoords="offset points", fontsize=7)
        ax.set_title(title, fontsize=10); ax.set_aspect("equal"); ax.tick_params(labelsize=7)
        cb = fig.colorbar(m, ax=ax, shrink=0.7)
        if kind == "p":
            cb.ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    return fig


def site_charts(rain, ens, seas, site):
    fig, axes = plt.subplots(1, 3, figsize=(16, 3.8), constrained_layout=True, gridspec_kw={"width_ratios": [1.2, 1, 1.1]})
    ax = axes[0]
    r = rain[rain.site == site]
    for p, c in zip(["chirps", "arc2", "tamsat", "pdirnow"], ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]):
        s = r[r["product"] == p]
        if len(s):
            ax.plot(pd.to_datetime(s.date), s.mm, lw=1.6, color=c, label=p.upper() if p != "pdirnow" else "PDIR-Now")
    ax.axvline(pd.Timestamp("2026-10-01"), color="grey", ls="--", lw=1)
    ax.set_title("Daily rainfall by satellite product (mm)", fontsize=10); ax.legend(fontsize=7)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d %b")); ax.tick_params(labelsize=7)
    ax = axes[1]
    e = ens[ens.site == site]
    x = pd.to_datetime(e.date).dt.strftime("%d %b")
    ax.bar(x, e.p_rain, color="#cbd5e1", label="Rain ≥1 mm"); ax.bar(x, e.p_10mm, color="#1d4ed8", label="Rain ≥10 mm")
    ax.plot(x, e.p_trigger, "o-", color="#b91c1c", label="Planting rains start")
    ax.set_ylim(0, 1); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("Next 15 days, ECMWF ensemble (share of members)", fontsize=10); ax.legend(fontsize=7, loc="upper right")
    ax.tick_params(axis="x", rotation=70, labelsize=7)
    ax = axes[2]
    s = seas[(seas.site == site) & (seas.variable != "lgp")].reset_index(drop=True)
    for i, row in s.iterrows():
        y = len(s) - 1 - i
        ax.add_patch(plt.Rectangle((row.t33_value, y - 0.35), row.t67_value - row.t33_value, 0.7, color="#e2e8f0"))
        ax.plot([row.p10_value, row.p90_value], [y, y], color="#0369a1", lw=1.5)
        ax.add_patch(plt.Rectangle((row.p25_value, y - 0.18), max(1, row.p75_value - row.p25_value), 0.36, color="#0369a1"))
        ax.plot(row.p50_value, y, "o", ms=7, mfc="w", mec="#0369a1", mew=2)
        ax.plot([row.normal_value] * 2, [y - 0.4, y + 0.4], color="k", lw=2)
    ax.axvline(pd.Timestamp.today().dayofyear, color="grey", ls="--", lw=1)
    ax.set_yticks(range(len(s))); ax.set_yticklabels(list(s.label)[::-1], fontsize=8)
    ticks = [274, 288, 305, 319, 335, 349, 365]
    ax.set_xticks(ticks); ax.set_xticklabels([(pd.Timestamp("2025-12-31") + pd.Timedelta(days=t)).strftime("%d %b") for t in ticks], fontsize=7)
    ax.set_xlim(272, 367); ax.set_title("Season outlook: bar 50%, line 80%, ○ most likely, | normal", fontsize=10)
    return fig


def main():
    sites = pd.read_csv(D / "sites.csv"); seas = pd.read_csv(D / "seasonal.csv")
    ens = pd.read_csv(D / "ens_daily.csv"); rain = pd.read_csv(D / "rain_daily.csv")
    zone = pd.read_csv(D / "zone.csv"); grid = pd.read_csv(D / "grid.csv")
    inits = pd.read_csv(D / "inits.csv") if (D / "inits.csv").exists() else None
    ver = {ref: pd.read_csv(p) for ref in ("chirps", "tamsat") if (p := BASE / "outputs" / "realtime_rain" / f"verification_{ref}.csv").exists()}
    issued = sites.issued.iloc[0]
    pct = lambda v: f"{float(v):.0%}"
    k = sites[sites.site.str.startswith("Kapiti")].iloc[0]
    dry = int((sites.rain_since_oct1_chirps_mm < 5).sum())

    parts = [f"<header><h1>Kenya Short Rains 2026 Tracker</h1><p class='take'>Issued {issued}. Satellite rainfall since 1 October: "
             f"<b>{dry} of {len(sites)}</b> monitored sites have had under 5 mm and no product shows a planting onset at any site. "
             f"The ECMWF ensemble of {k.ens_init} gives Kapiti a <b>{pct(k.p_event_7d)}</b> chance of planting rains within 7 days; "
             f"the seasonal outlook, given no onset yet, puts Kapiti's planting onset most likely on <b>{k.season_onset_median}</b> "
             f"({k.season_onset_likely}).</p></header>"]

    parts.append("<section><h2>Site status</h2><p class='note'>Planting rains = at least 20 mm within 1–3 days. Planting onset = planting rains "
                 "with no 10-day dry spell in the following 21 days.</p>" + table(sites, [
                     ("site", "Site"), ("obs_through", "CHIRPS to"), ("rain_since_oct1_chirps_mm", "CHIRPS since 1 Oct (mm)"),
                     ("rain_since_oct1_arc2_mm", "ARC2 (mm)"), ("rain_since_oct1_tamsat_mm", "TAMSAT (mm)"), ("pct_of_normal", "% normal"),
                     ("products_with_onset", "Products with onset"), ("p_event_7d", "Planting rains ≤7 d"), ("p_onset_15d", "Onset ≤15 d"),
                     ("ens_onset_median", "ENS+seasonal onset"), ("season_onset_median", "Seasonal onset"), ("season_onset_likely", "Likely range"),
                     ("season_skill", "Local skill")],
                     fmt={"p_event_7d": pct, "p_onset_15d": pct, "pct_of_normal": lambda v: f"{v:.0f}%", "season_skill": lambda v: f"{v} skill",
                          "products_with_onset": lambda v: f"{int(v)}"},
                     cls=lambda c, v: ("dry" if c == "rain_since_oct1_chirps_mm" and float(v) < 5 else ("sk-" + str(v) if c == "season_skill" else ""))) + "</section>")

    parts.append("<section><h2>Site detail</h2>")
    for site in sites.site:
        s = seas[seas.site == site]
        cond = sites[sites.site == site].condition.iloc[0]
        parts.append(f"<article><h3>{html.escape(site)}</h3>" + img(site_charts(rain, ens, seas, site)) +
                     (f"<p class='note'>Given no onset yet: {html.escape(str(cond))}.</p>" if isinstance(cond, str) and cond else "") +
                     table(s, [("label", "Variable"), ("median", "Most likely"), ("likely_from", "Likely from"), ("likely_to", "to"),
                               ("wide_from", "Wide from"), ("wide_to", "to"), ("p_low", "Early/short"), ("p_mid", "Normal"), ("p_high", "Late/long"),
                               ("normal", "Normal (avg)"), ("skill", "Local skill"), ("mae_days", "Typical error (d)"), ("corr", "r"), ("rpss_val", "RPSS")],
                           fmt={"p_low": pct, "p_mid": pct, "p_high": pct, "mae_days": lambda v: f"±{v:.0f}", "corr": lambda v: f"{v:.2f}",
                                "rpss_val": lambda v: f"{v:+.2f}", "skill": lambda v: f"{v} skill"},
                           cls=lambda c, v: "sk-" + str(v) if c == "skill" else "") + "</article>")
    parts.append("</section>")

    parts.append("<section><h2>Kenya short-rains zone</h2><p class='note'>Faded cells are outside the short-rains zone; dots are the monitored sites.</p>"
                 + img(maps(grid, sites)) + table(zone, [("label", "Product"), ("last_day", "Data to"), ("ond_zone_mean_mm", "Zone mean (mm)"),
                                                          ("ond_zone_normal_mm", "Normal (mm)"), ("ond_zone_pct_normal", "% of normal"),
                                                          ("ond_zone_pct_onset_detected", "Zone with planting onset")],
                                                    fmt={"ond_zone_pct_normal": lambda v: f"{v:.0f}%", "ond_zone_pct_onset_detected": lambda v: f"{v:.0f}%"}) + "</section>")

    vcols = [("product", "Product"), ("period", "Period"), ("days", "Days"), ("bias_pct", "Total bias"), ("corr_daily", "r daily"),
             ("corr_pentad", "r 5-day"), ("pod_1mm", "POD ≥1"), ("far_1mm", "FAR ≥1"), ("pod_10mm", "POD ≥10"), ("far_10mm", "FAR ≥10"),
             ("onset_mad_days", "Onset diff. (d)")]
    vf = {"bias_pct": lambda v: f"{v:+.0f}%", **{c: (lambda v: f"{v:.2f}") for c in ("corr_daily", "corr_pentad", "pod_1mm", "far_1mm", "pod_10mm", "far_10mm")},
          "onset_mad_days": lambda v: f"{v:.0f}", "period": lambda v: v.replace(":", " – ")}
    parts.append("<section><h2>Real-time products against reference data</h2><p class='note'>Daily rainfall over the short-rains zone. "
                 "Oct–Dec 2025 is the main test (final CHIRPS); October 2026 compares against preliminary CHIRPS. POD = share of reference rain days "
                 "the product caught; FAR = share of the product's rain days the reference did not have; onset diff = mean difference in planting-onset date.</p>")
    for ref, df in ver.items():
        parts.append(f"<h3>Reference: {ref.upper()}</h3>" + table(df, vcols, fmt=vf))
    parts.append("</section>")

    if inits is not None:
        parts.append("<section><h2>Kapiti forecast by initialization</h2>" +
                     img(BASE / "outputs" / "site_tracker" / "Kapiti_Research_Station_Farm" / "inits_compare.png") +
                     table(inits, [("init", "Run"), ("variable", "Variable"), ("median_date", "Most likely"), ("anomaly", "vs normal (d)"),
                                   ("p_bn", "Early/short"), ("p_nn", "Normal"), ("p_an", "Late/long")],
                           fmt={"p_bn": pct, "p_nn": pct, "p_an": pct, "anomaly": lambda v: f"{v:+.0f}"}) + "</section>")

    css = """
:root{--bg:#f7f8f6;--fg:#1d2420;--muted:#5d6862;--panel:#fff;--line:#dde2dd;--dry:#b4532a;--ok:#2f7d4f;--warn:#a26b06;--bad:#b4532a}
@media (prefers-color-scheme:dark){:root{--bg:#141815;--fg:#e8ece8;--muted:#a3ada6;--panel:#1c211d;--line:#2e3530}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px max(16px,4vw)}
h1{font:400 30px Georgia,serif;margin:0} h2{font-size:19px;margin:32px 0 8px} h3{font-size:15px;margin:16px 0 6px}
.take{max-width:80ch;color:var(--muted)} .take b{color:var(--fg)} .note{color:var(--muted);font-size:12px;max-width:90ch}
article{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin:12px 0}
img{max-width:100%;background:#fff;border-radius:6px} .scroll{overflow-x:auto}
table{border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums;margin:8px 0}
th{text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:4px 8px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:4px 8px;white-space:nowrap} td.dry{color:var(--dry);font-weight:600}
td.sk-useful{color:var(--ok)} td.sk-limited{color:var(--warn)} td.sk-no{color:var(--bad)}
"""
    out = BASE / "outputs" / f"results_report_{issued}.html"
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                   f"<title>Kenya Short Rains 2026 Tracker</title><style>{css}</style></head><body>{''.join(parts)}</body></html>", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
