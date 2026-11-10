"""
The bulletin's crop page (Kenya, Short Rains): the platform's crop outlook at the crop site nearest the bulletin's
location, drawn from the Crop outlook tab's own published data (tracker/data/crop/, crop_engine/dashboard.py), so the
page and the tab always agree.

  crop_page_png(lat, lon, out_dir)  → the page as a PNG (1650 px wide, as the bulletin), or None when no crop site is
                                      within MAX_KM or the crop data cannot be read
  crop_page_pdf(lat, lon, path)     → the same page as a small vector PDF (the Crop outlook tab's download)
  site_pdfs(out_dir)                → one PDF per crop site (crop_engine/dashboard.py, every daily update)

Contents: the season at the site so far (rain since 1 Oct from the rainfall tracking table, soil water from the FAO
water balance), the outlook for every crop (AquaCrop, the published outlook, and WOFOST, the second model, with the
simulated past seasons as the normal and the two models' agreement), what management could change (the scenarios'
change in median yield, both models), how past forecasts did (the hindcast skill), and where to answer the partners'
questions. The data are read from the repository (frontend/public/tracker/data/) when it is there, else from the live
platform (CROP_DATA_URL).

The agreement rule is the tab's (frontend/src/components/CropOutlookTab.jsx, CROP_ENGINE.md): the models agree when
their yields if sown are within AGREE_T t/ha and their chances of failure if sown within AGREE_P; the outcome depends
on the model when either differs by more than twice that.
"""
import csv
import io
import json
import math
import os
import statistics
import textwrap
import time
import urllib.request
from pathlib import Path

LOCAL = Path(__file__).resolve().parent.parent / "frontend" / "public" / "tracker" / "data"
REMOTE = os.environ.get("CROP_DATA_URL", "https://operational-multi-model-seasonal-fo.vercel.app/tracker/data/")
PLATFORM = "https://operational-multi-model-seasonal-fo.vercel.app/"
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeSm0ZhEjV3MhBCayBJEdrwtgLh2iBfyzd-b90o56vXo9B9vw/viewform"
MAX_KM = 25
AGREE_T, AGREE_P = 1.0, 0.15
SIMULATED = ("ok", "died", "failed_establishment")
RULE = "fao-agricultural"                    # the page's sowing rule (every member is sown; Agri rule 1 is on the tab)
SCEN_ROWS = ["sow_minus14", "sow_plus14", "irr_supplementary", "mulch", "ridges", "density_high", "irr_full"]
_CACHE = {}
_TTL = 1800


def _read(name):
    """A published data file (JSON, or CSV as a list of dicts), local first, else the live platform; None if neither."""
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    text = None
    p = LOCAL / name
    if p.exists():
        text = p.read_text(encoding="utf-8")
    else:
        try:
            with urllib.request.urlopen(urllib.request.Request(REMOTE + name, headers={"User-Agent": "ocl-fs-bulletin"}), timeout=20) as r:
                text = r.read().decode("utf-8")
        except Exception:
            text = None
    val = None
    if text:
        try:
            val = list(csv.DictReader(io.StringIO(text))) if name.endswith(".csv") else json.loads(text)
        except ValueError:
            val = None                                                   # e.g. the site's HTML fallback page
    _CACHE[name] = (time.time(), val)
    return val


def _km(a, b, c, d):
    r = math.pi / 180
    x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def agreement(a, w):
    """'agree' | 'partly' | 'differ' | None, from two summaries of the same members (module doc)."""
    try:
        dy = w["yield_if_sown_t_ha"]["median"] - a["yield_if_sown_t_ha"]["median"]
        dp = w["p_failure_if_sown"] - a["p_failure_if_sown"]
    except (KeyError, TypeError):
        return None
    if abs(dy) <= AGREE_T and abs(dp) <= AGREE_P:
        return "agree"
    return "differ" if abs(dy) > 2 * AGREE_T or abs(dp) > 2 * AGREE_P else "partly"


AGREE_LABEL = {"agree": "agree", "partly": "partly agree", "differ": "depends on the model", None: "—"}


def _t(v):
    return "—" if v is None else ("0" if v < 0.05 else f"{v:.1f}")


def _p(v):
    return "—" if v is None else f"{round(v * 100)}%"


def _d(iso):
    if not iso:
        return "—"
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return f"{d} {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1]}"


def past_stats(bench_cell, thr):
    """(yield if sown median, failure if sown) of the simulated past seasons (benchmark.json rows)."""
    rows = [s for s in (bench_cell or {}).get("seasons", []) if s[4] in SIMULATED]
    if not rows:
        return None, None
    ys = [s[3] or 0.0 for s in rows]
    return statistics.median(ys), sum(y < thr for y in ys) / len(ys)


def nearest_site(index, lat, lon):
    best = None
    for sid, s in (index.get("sites") or {}).items():
        if s.get("lat") is None:
            continue
        d = _km(lat, lon, s["lat"], s["lon"])
        if best is None or d < best[1]:
            best = (sid, d)
    return best


def page_data(lat, lon):
    """Everything the page shows, or None (module doc)."""
    ix = _read("crop/index.json")
    if not ix:
        return None
    near = nearest_site(ix, lat, lon)
    if not near or near[1] > MAX_KM:
        return None
    sid = near[0]
    run = next((r for r in ix.get("runs", []) if r["source"] == "seasonal"), None)
    if not run:
        return None
    rule = RULE if RULE in ix.get("planting_rules", {}) else next(iter(ix.get("planting_rules", {})), None)
    seas = _read("crop/seasonal.json") or {}
    bench = (_read("crop/benchmark.json") or {}).get("sites", {}).get(sid, {})
    site = ix["sites"][sid]
    crops = []
    for vk, v in ix.get("varieties", {}).items():
        a = ix.get("summaries", {}).get(run["id"], {}).get(sid, {}).get(vk, {}).get(rule)
        if not a:
            continue
        w = ix.get("wofost", {}).get(run["id"], {}).get(sid, {}).get(vk, {}).get(rule)
        py, pf = past_stats(bench.get(vk, {}).get(rule), v.get("failure_t_ha", 0.5))
        crops.append({"key": vk, "label": v.get("label", vk), "a": a, "w": w, "past_yield": py, "past_fail": pf,
                      "agree": agreement(a, w) if w else None})
    tr = next((r for r in (_read("sites.csv") or []) if r.get("site") == site.get("name")), None)
    sc = _read("crop/scenarios.json")
    scen = []
    if sc and sc.get("meta", {}).get("run_id", run["id"]) == run["id"]:
        for vk in ("maize_early", "sorghum"):
            cell = sc.get("sites", {}).get(sid, {}).get("results", {}).get(vk, {}).get(rule)
            if not cell:
                continue
            base, bw = cell["baseline"]["yield_t_ha"]["median"], (cell.get("baseline_wofost") or {}).get("yield_t_ha", {}).get("median")
            rows = []
            for k in SCEN_ROWS:
                if k not in cell:
                    continue
                x = cell[k]
                wy = (x.get("wofost") or {}).get("yield_t_ha", {}).get("median")
                rows.append({"key": k, "label": sc["meta"]["scenarios"][k]["label"], "dA": x["yield_t_ha"]["median"] - base,
                             "dW": None if wy is None or bw is None else wy - bw, "irr": x.get("irrigation_mm_median")})
            scen.append({"key": vk, "label": ix["varieties"][vk]["label"], "rows": rows})
    skill = (_read("crop/skill.json") or {}).get("seasonal", {})
    return {"site": site, "sid": sid, "km": near[1], "run": run, "rule": ix["planting_rules"].get(rule, rule), "rule_key": rule,
            "crops": crops, "tracker": tr, "soil": (seas.get("sites", {}).get(sid) or {}).get("soil_water"),
            "initial": (seas.get("sites", {}).get(sid) or {}).get("initial_water_fraction"), "scenarios": scen,
            "skill": skill.get("sites", {}).get(sid, {}), "skill_made": skill.get("made", {})}


def crop_page_png(lat, lon, out_dir, dpi=150):
    """The crop page as a PNG in out_dir, or None (module doc)."""
    data = page_data(lat, lon)
    if not data or not data["crops"]:
        return None
    plt = _plt()
    fig, _ = _draw(data)
    out = Path(out_dir) / f"crop_page_{data['sid']}.png"
    fig.savefig(out, dpi=dpi, facecolor="white")
    plt.close(fig)
    _trim_bottom(out, keep_px=round(0.03 * PAGE_H * dpi))
    return str(out)


def crop_page_pdf(lat, lon, out_path):
    """The crop page as a one-page vector PDF (small: text and lines, no image), cut to its content, or None."""
    data = page_data(lat, lon)
    if not data or not data["crops"]:
        return None
    plt = _plt()
    from matplotlib.transforms import Bbox
    fig, y_end = _draw(data)
    bottom = max(0.0, (y_end - 0.03) * PAGE_H)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format="pdf", facecolor="white", bbox_inches=Bbox([[0, bottom], [PAGE_W, PAGE_H]]),
                metadata={"Title": f"Crop outlook, {data['site']['name']}", "Subject": "OCL-FS crop outlook (experimental)"})
    plt.close(fig)
    return str(out_path)


def site_pdfs(out_dir, log=print):
    """One crop bulletin PDF per crop site (<site id>.pdf in out_dir), from the published data; the others removed."""
    ix = _read("crop/index.json") or {}
    out_dir = Path(out_dir)
    made = set()
    for sid, site in (ix.get("sites") or {}).items():
        if site.get("lat") is None:
            continue
        try:
            if crop_page_pdf(site["lat"], site["lon"], out_dir / f"{sid}.pdf"):
                made.add(f"{sid}.pdf")
        except Exception as exc:                                        # one site never stops the others
            log(f"crop bulletin: {sid} not made ({type(exc).__name__}: {str(exc)[:120]})")
    for f in out_dir.glob("*.pdf") if out_dir.exists() else []:
        if f.name not in made:
            f.unlink()
    return sorted(made)


PAGE_W, PAGE_H = 11, 14.5


def _plt():
    """pyplot on the Agg backend (no display: the backend and the daily update)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _draw(data):
    """The page's figure and the lowest point drawn (a figure fraction)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    INK, MUTED, LINE, ACCENT, WARN = "#0f172a", "#475569", "#cbd5e1", "#1d4ed8", "#9a3412"
    fig = plt.figure(figsize=(PAGE_W, PAGE_H), facecolor="white")
    W = lambda s, n=118: textwrap.fill(s, n)                                           # noqa: E731
    y = 0.975

    def text(x, yy, s, **kw):
        fig.text(x, yy, s, va="top", ha="left", color=kw.pop("color", INK), **kw)

    site, run = data["site"], data["run"]
    text(0.05, y, f"CROP OUTLOOK  ·  {site['name']}", fontsize=19, fontweight="bold")
    y -= 0.032
    text(0.05, y, W(f"Kenya, Short Rains {run['run'][:4]} · experimental · AquaCrop (the published outlook) and WOFOST (a second crop model) "
                    f"grown in every member of {run['model_label']}, observations to {_d(run['obs_end'])}; crops sown by {data['rule']}"
                    + (f" · {round(data['km'])} km from the bulletin's location" if data["km"] >= 2 else ""), 125), fontsize=10.5, color=MUTED)
    y -= 0.05

    # ── the season so far
    tr, soil = data["tracker"], data["soil"]
    parts = []
    if tr and tr.get("rain_since_oct1_chirps_mm"):
        parts.append(f"Rain since 1 Oct: {round(float(tr['rain_since_oct1_chirps_mm']))} mm"
                     + (f" ({tr['pct_of_normal']}% of normal)" if tr.get("pct_of_normal") else "")
                     + f", CHIRPS to {_d(tr.get('through_chirps') or tr.get('obs_through'))}")
    if soil:
        parts.append(f"soil water {_p(soil['paw_fraction'])} of the available water on {_d(soil['date'])} (FAO water balance)")
    elif data["initial"] is not None:
        parts.append(f"soil water {_p(data['initial'])} of the available water on 1 Aug")
    text(0.05, y, "The season so far", fontsize=13, fontweight="bold")
    y -= 0.022
    text(0.05, y, W("; ".join(parts) + "." if parts else "Not available.", 112), fontsize=11)
    y -= 0.04

    # ── the outlook by crop
    text(0.05, y, "Outlook by crop", fontsize=13, fontweight="bold")
    y -= 0.012
    head = ["Crop", "Sowing\n(median)", "Yield if sown\nAquaCrop (8 in 10)", "Yield if sown\nWOFOST", "Failure if sown\nAquaCrop / WOFOST",
            "Past seasons\nyield / failure", "Crop models"]
    rows = []
    for c in data["crops"]:
        a, w = c["a"], c["w"] or {}
        ya = a.get("yield_if_sown_t_ha") or {}
        rows.append([c["label"], _d((a.get("planting") or {}).get("median")),
                     f"{_t(ya.get('median'))} t/ha ({_t(ya.get('p10'))}–{_t(ya.get('p90'))})",
                     f"{_t((w.get('yield_if_sown_t_ha') or {}).get('median'))} t/ha" if w else "no WOFOST",
                     f"{_p(a.get('p_failure_if_sown'))} / {_p(w.get('p_failure_if_sown')) if w else '—'}",
                     f"{_t(c['past_yield'])} t/ha / {_p(c['past_fail'])}", AGREE_LABEL[c["agree"]]])
    h = 0.021 * (len(rows) + 1.6)
    ax = fig.add_axes([0.05, y - h, 0.9, h])
    ax.axis("off")
    tb = ax.table(cellText=rows, colLabels=head, loc="upper left", cellLoc="left", colLoc="left",
                  colWidths=[0.19, 0.09, 0.17, 0.11, 0.16, 0.15, 0.13])
    tb.auto_set_font_size(False)
    tb.set_fontsize(10)
    tb.scale(1, 1.75)
    for (r, k), cell in tb.get_celld().items():
        cell.set_edgecolor(LINE)
        cell.set_linewidth(0.6)
        if r == 0:
            cell.set_text_props(fontweight="bold", color=MUTED, fontsize=9)
            cell.set_height(cell.get_height() * 1.5)
        elif k == 6 and data["crops"][r - 1]["agree"] == "differ":
            cell.set_text_props(color=WARN, fontweight="bold")
    y -= h + 0.008
    text(0.05, y, W("Yield if sown: median of the sown crops (8 in 10 in brackets); failure: a yield below the crop's threshold (0.5 t/ha, bean "
                    "0.2). Simulated past seasons: the same model in the observed weather of 1993–2025 (the normal). Crop models: agree when "
                    f"the yields are within {AGREE_T:g} t/ha and the failure chances within {round(AGREE_P * 100)} points; depends on the model "
                    "beyond twice that. Water-limited yields (no nutrient, pest or management losses): an upper bound for most fields.", 140),
         fontsize=9, color=MUTED)
    y -= 0.055

    # ── what management could change
    text(0.05, y, "What management could change (change in median yield, AquaCrop / WOFOST)", fontsize=13, fontweight="bold")
    y -= 0.022
    if not data["scenarios"]:
        text(0.05, y, "The management scenarios come with the next weekly crop run.", fontsize=11, color=MUTED)
        y -= 0.03
    for g in data["scenarios"]:
        rows = [[r["label"] + (f" ({round(r['irr'])} mm)" if r.get("irr") else ""),
                 f"{r['dA']:+.1f} t/ha", "—" if r["dW"] is None else f"{r['dW']:+.1f} t/ha"] for r in g["rows"]]
        cand = [r for r in g["rows"] if r["key"] != "irr_full"]
        best = max(cand, key=lambda r: r["dA"]) if cand else None
        head_ = (g["label"] + (f": the largest gain short of full irrigation is {best['label'].lower()} "
                                    f"({best['dA']:+.1f} t/ha AquaCrop" + ("" if best["dW"] is None else f", {best['dW']:+.1f} WOFOST") + ")"
                                    if best and best["dA"] > 0.05 else ""))
        text(0.05, y, W(head_, 105), fontsize=11, fontweight="bold")
        y -= 0.012 + 0.017 * (len(W(head_, 105).splitlines()) - 1)
        h = 0.0145 * (len(rows) + 1.3)
        ax = fig.add_axes([0.05, y - h, 0.78, h])
        ax.axis("off")
        tb = ax.table(cellText=rows, colLabels=["Choice", "AquaCrop", "WOFOST"], loc="upper left", cellLoc="left", colLoc="left",
                      colWidths=[0.66, 0.17, 0.17])
        tb.auto_set_font_size(False)
        tb.set_fontsize(9.5)
        tb.scale(1, 1.35)
        for (r, k), cell in tb.get_celld().items():
            cell.set_edgecolor(LINE)
            cell.set_linewidth(0.6)
            if r == 0:
                cell.set_text_props(fontweight="bold", color=MUTED)
        y -= h + 0.018
    text(0.05, y, W("Each choice changes one thing for every member of the same seasonal forecast; plant density is AquaCrop's only "
                    "(WOFOST has no plant population). The amounts (100 mm of water, half the soil under residues, ridges that let no rain "
                    "run off) are assumptions until the site's managers answer the questions below.", 140), fontsize=9, color=MUTED)
    y -= 0.045

    # ── how past forecasts did
    sk = data["skill"].get(data["crops"][0]["key"], {}).get(data["rule_key"]) if data["skill"] else None
    text(0.05, y, "How past forecasts did", fontsize=13, fontweight="bold")
    y -= 0.022
    if sk and sk.get("aquacrop"):
        m = data["skill_made"].get("aquacrop", {})
        yrs = "–".join(str(x) for x in m.get("years", []))
        f = lambda x: "—" if x is None else f"{x:.2f}"                                  # noqa: E731
        text(0.05, y, W(f"{data['crops'][0]['label']}, {data['rule']}: the 1 Oct SEAS5 forecasts of {yrs} ranked the years' crops with a correlation of "
                        f"{f(sk['aquacrop'].get('r'))} (AquaCrop)" + (f" and {f(sk['wofost'].get('r'))} (WOFOST)" if sk.get("wofost") else "")
                        + f" against each model's crop in the observed weather; the platform's season-length forecast alone {f((sk.get('lgp') or {}).get('r'))}, "
                        f"its Oct–Dec rain {f((sk.get('rain') or {}).get('r'))}. 1 is a perfect ranking, 0 none; with {sk['aquacrop'].get('n')} years a value is "
                        "uncertain by about ±0.2.", 120), fontsize=10.5)
    else:
        text(0.05, y, "No hindcast for this site and crop yet.", fontsize=10.5, color=MUTED)
    y -= 0.06

    # ── footer
    fig.add_artist(plt.Line2D([0.05, 0.95], [y + 0.01, y + 0.01], color=LINE, lw=0.8))
    text(0.05, y, W("First calibration only (maize and sorghum, against trials at Kiboko), not verified against farm yields: for discussion, "
                    "not advice. The full outlook, its members and the other forecasts: " + PLATFORM + "#/crop", 138), fontsize=9.5, color=MUTED)
    y -= 0.03
    text(0.05, y, W("Farm managers and agronomists at this site: tell us how much water, residue and ridging farmers use, and the scenarios "
                    "will be set to match:", 138), fontsize=9.5, color=INK)
    y -= 0.016 * (len(W("Farm managers and agronomists at this site: tell us how much water, residue and ridging farmers use, and the "
                        "scenarios will be set to match:", 138).splitlines()) - 1)
    y -= 0.016
    text(0.05, y, FORM_URL, fontsize=9.5, color=ACCENT, url=FORM_URL)
    return fig, y - 0.02


def _trim_bottom(path, keep_px=60):
    """Crop the page's unused white space at the bottom (the layout is drawn top-down)."""
    from PIL import Image, ImageChops
    with Image.open(path) as im:
        im = im.convert("RGB")
        box = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
        if box:
            im = im.crop((0, 0, im.width, min(im.height, box[3] + keep_px)))
        im.save(path)


def combine(main_png, crop_png, out_png):
    """The bulletin PNG with the crop page below it (the same width), as one image."""
    from PIL import Image
    with Image.open(main_png) as a, Image.open(crop_png) as b:
        a, b = a.convert("RGB"), b.convert("RGB")
        if b.width != a.width:
            b = b.resize((a.width, round(b.height * a.width / b.width)))
        img = Image.new("RGB", (a.width, a.height + b.height), (255, 255, 255))
        img.paste(a, (0, 0))
        img.paste(b, (0, a.height))
        img.save(out_png)
    return out_png
