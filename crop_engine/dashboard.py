"""
The Crop outlook tab's data (frontend/public/tracker/data/crop/, published with the daily update): compact copies of
the latest result of each forecast source and of the benchmark, read by frontend/src/components/CropOutlookTab.jsx.

  index.json        runs, every run's summaries (per site, variety, rule), sites, varieties, planting rules, outcomes,
                    caveats
  <source>.json     the source's latest run (one file per source, overwritten, so the published history does not
                    pile up): per site, variety and rule, the summary and every member as
                    [planting, harvest, yield t/ha, outcome, water-stress days, season rain mm]
  benchmark.json    per site, variety and rule: terciles, median, failure chance and every observed season as
                    [year, planting, harvest, yield t/ha, outcome]

Older runs are removed, so the published folder holds one run per source.
"""
import json

from crop_engine import config as C
from crop_engine.data.sites import registered_sites

OUTCOMES = [
    ("ok", "Matured", "Sown and reached maturity"),
    ("died", "Died before maturity", "Established, then died of water stress before maturity (yield so far counted)"),
    ("failed_establishment", "Failed to establish", "Died before its canopy reached 5 %: a false start, the seedlings dried out"),
    ("too_late", "Too late to mature", "Sown too late to reach maturity by 31 Mar (counted as no yield)"),
    ("not_sown", "No sowing opportunity", "No onset by the rule's search end, 15 Jan (counted as no yield)"),
]
MEMBER_KEYS = ("planting", "harvest", "yield_t_ha", "status", "stress_days", "rain_mm")


def _dump(path, obj):
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def write_index():
    """outputs/crop_engine/results/index.json: every run made, newest first."""
    runs = []
    for p in sorted(C.RESULTS_OUT.glob("*_????????.json")):
        meta = json.loads(p.read_text(encoding="utf-8"))["meta"]
        runs.append({k: meta[k] for k in ("id", "source", "model_label", "run", "obs_end", "members_kind", "created")})
    runs.sort(key=lambda r: (r["run"], r["source"]), reverse=True)
    (C.RESULTS_OUT / "index.json").write_text(json.dumps({"runs": runs}, indent=1), encoding="utf-8")


def write(log=print):
    idx = C.RESULTS_OUT / "index.json"
    if not idx.exists():
        return
    latest = {}
    for r in json.loads(idx.read_text(encoding="utf-8"))["runs"]:          # newest first
        latest.setdefault(r["source"], r)
    runs = sorted(latest.values(), key=lambda r: (r["source"] != "seasonal", r["source"]))
    C.DASHBOARD_OUT.mkdir(parents=True, exist_ok=True)
    meta0, sites, summaries = None, {}, {}
    for r in runs:
        d = json.loads((C.RESULTS_OUT / f"{r['id']}.json").read_text(encoding="utf-8"))
        meta0 = meta0 or d["meta"]
        summaries[r["id"]] = {sid: {vk: {rk: x["summary"] for rk, x in rs.items()} for vk, rs in s["results"].items()}
                              for sid, s in d["sites"].items()}
        out = {"meta": {k: d["meta"].get(k) for k in ("id", "source", "model_label", "run", "obs_end", "members_kind",
                                                       "segments", "created", "engine")}, "sites": {}}
        for sid, s in d["sites"].items():
            sites.setdefault(sid, {"name": s["name"], "cell": s["cell"], "soil_taw_100cm_mm": s["soil_taw_100cm_mm"],
                                   "topsoil": {k: round(v) for k, v in s["topsoil"].items()}})
            out["sites"][sid] = {
                "initial_water_fraction": s["initial_water_fraction"], "fao_reference": s["fao_reference"],
                "results": {vk: {rk: {"summary": x["summary"], "members": [[m.get(k) for k in MEMBER_KEYS] for m in x["members"]]}
                                 for rk, x in rs.items()} for vk, rs in s["results"].items()}}
        _dump(C.DASHBOARD_OUT / f"{r['source']}.json", out)
    if not meta0:
        return
    coords = {s.id: (s.lat, s.lon) for s in registered_sites()}
    for sid, s in sites.items():
        s["lat"], s["lon"] = coords.get(sid, (None, None))
    bench = json.loads((C.OUT / "climatology.json").read_text(encoding="utf-8"))
    _dump(C.DASHBOARD_OUT / "benchmark.json", {
        "years": bench["years"], "cal_years": bench["cal_years"],
        "sites": {sid: {vk: {rk: {**{k: b.get(k) for k in ("t33", "t67", "median", "cal_median", "p_failure")},
                                  "seasons": [[int(y), v["planting"], v["harvest"], v["yield_t_ha"], v["status"]]
                                              for y, v in sorted(b["years"].items())]}
                             for rk, b in rs.items()} for vk, rs in vs.items()} for sid, vs in bench["sites"].items()}})
    _dump(C.DASHBOARD_OUT / "index.json", {
        "runs": [{**{k: r[k] for k in ("id", "source", "model_label", "run", "obs_end", "members_kind", "created")},
                  "file": f"{r['source']}.json"} for r in runs],
        "summaries": summaries, "sites": sites, "varieties": meta0["varieties"], "planting_rules": meta0["planting_rules"],
        "outcomes": [{"id": i, "label": a, "title": t} for i, a, t in OUTCOMES], "member_keys": list(MEMBER_KEYS),
        "caveats": meta0["caveats"], "engine": meta0["engine"]})
    keep = {f"{r['source']}.json" for r in runs} | {"index.json", "benchmark.json"}
    for p in C.DASHBOARD_OUT.glob("*.json"):
        if p.name not in keep:
            p.unlink()
    size = sum(p.stat().st_size for p in C.DASHBOARD_OUT.glob("*.json")) / 1024
    log(f"dashboard: {len(runs)} runs → {C.DASHBOARD_OUT.relative_to(C.BASE)} ({size:.0f} kB)")


if __name__ == "__main__":
    write()
