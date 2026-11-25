"""Saved farms and the farm diary (My farms), and the daily farm crop runs' queue.

A farm is saved here only when its owner asks for it (consent): its outline, name, crop and diary. Like a watch, a
farm is anonymous: saving returns its id and a private key that stays in the user's browser; only the key's hash is
stored, and the key is needed to read, change or delete the farm. Deleting a farm deletes its diary and crop runs.

The diary records what happened on the farm (sowing, irrigation, fertiliser, weeding, pests, crop stage, rain,
harvest, costs, notes). The sowing date, crop, irrigation and nitrogen go into the daily farm crop run (crop_engine,
on the PC that runs the daily update): it reads the queue of farms to simulate and posts each result back, both with
the batch token (FARM_BATCH_TOKEN). Harvests are kept to check the models against later.

Tables: farms, farm_diary, farm_sims (supabase_schema.sql).
"""
import datetime as dt
import hashlib
import math
import secrets

from . import store

TABLE, DIARY, SIMS = "farms", "farm_diary", "farm_sims"
MAX_HA = 10000
MAX_VERTICES = 5000
CROPS = {"maize_early": "Early-maturing maize", "maize_medium": "Medium-maturing maize", "sorghum": "Sorghum", "bean": "Dry bean"}
STAGES = ("emerged", "vegetative", "flowering", "grain filling", "mature")

# diary entry type -> (label, fields: name -> (kind, required, limits or choices)); every entry also has its date
ENTRY_TYPES = {
    "sowing": ("Sowing", {"crop": ("choice", True, tuple(CROPS)), "variety_note": ("text", False, 120),
                          "area_ha": ("number", False, (0, MAX_HA))}),
    "irrigation": ("Irrigation", {"mm": ("number", True, (0, 300)), "note": ("text", False, 200)}),
    "fertiliser": ("Fertiliser", {"product": ("text", False, 80), "n_kg_ha": ("number", False, (0, 400)),
                                  "p_kg_ha": ("number", False, (0, 200)), "note": ("text", False, 200)}),
    "weeding": ("Weeding", {"note": ("text", False, 200)}),
    "pest_disease": ("Pest or disease", {"what": ("text", True, 120), "severity": ("choice", True, ("mild", "moderate", "severe")),
                                         "note": ("text", False, 300)}),
    "crop_stage": ("Crop stage", {"stage": ("choice", True, STAGES)}),
    "rainfall": ("Rain on the farm", {"mm": ("number", True, (0, 500)), "measured_by": ("choice", True, ("rain gauge", "estimate"))}),
    "harvest": ("Harvest", {"yield_t_ha": ("number", False, (0, 25)), "area_ha": ("number", False, (0, MAX_HA)),
                            "note": ("text", False, 300)}),
    "cost": ("Cost or income", {"item": ("text", True, 80), "amount": ("number", True, (-1e9, 1e9)), "currency": ("text", False, 8)}),
    "note": ("Note", {"text": ("text", True, 500)}),
}


def schema():
    return {"crops": CROPS, "entry_types": {k: {"label": lab, "fields": {
        f: {"kind": kd, "required": rq, **({"choices": list(lim)} if kd == "choice" else {"limits": lim} if lim else {})}
        for f, (kd, rq, lim) in fs.items()}} for k, (lab, fs) in ENTRY_TYPES.items()}, "storage": store.status()}


def _hash(key):
    return hashlib.sha256(str(key).encode()).hexdigest()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------- geometry
R = 6371008.8


def _polygons(g):
    if g.get("type") == "Polygon":
        return [g["coordinates"]]
    return (g.get("coordinates") or []) if g.get("type") == "MultiPolygon" else []


def _ring_area(ring):
    """m2 on the sphere (Chamberlain and Duquette 2007, as in the frontend's farmGeo.js)"""
    n = len(ring)
    if n < 4:
        return 0.0
    a = 0.0
    for i in range(n - 1):
        p1, p2, p3 = ring[i], ring[(i + 1) % (n - 1)], ring[(i + 2) % (n - 1)]
        a += (math.radians(p3[0]) - math.radians(p1[0])) * math.sin(math.radians(p2[1]))
    return abs(a * R * R / 2)


def check_geometry(g) -> dict:
    """The outline, cleaned (closed rings of [lon, lat]), with its area (ha) and centre; ValueError when unusable."""
    if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("the farm outline must be a GeoJSON Polygon or MultiPolygon")
    polys, nv = [], 0
    for poly in _polygons(g):
        rings = []
        for ring in poly:
            r = [[float(p[0]), float(p[1])] for p in ring]
            if r and r[0] != r[-1]:
                r.append(list(r[0]))
            if any(not (-180 <= x <= 180 and -90 <= y <= 90) or not (math.isfinite(x) and math.isfinite(y)) for x, y in r):
                raise ValueError("the outline must be in longitude and latitude (WGS84)")
            nv += len(r)
            rings.append(r)
        if not rings or len(rings[0]) < 4:
            raise ValueError("a farm outline needs at least three corners")
        polys.append(rings)
    if not polys:
        raise ValueError("the farm outline is empty")
    if nv > MAX_VERTICES:
        raise ValueError(f"the outline has {nv} corners; at most {MAX_VERTICES}")
    m2 = sum(max(0.0, _ring_area(p[0]) - sum(_ring_area(h) for h in p[1:])) for p in polys)
    if m2 < 100:
        raise ValueError("the outline encloses almost no area")
    if m2 / 1e4 > MAX_HA:
        raise ValueError(f"the farm covers {m2 / 1e4:,.0f} ha; at most {MAX_HA:,} ha")
    xs = [x for p in polys for x, _ in p[0]]
    ys = [y for p in polys for _, y in p[0]]
    geom = {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}
    # the centre of the outline's corners' box is close enough for a farm (it picks the weather and soil cell)
    return {"geometry": geom, "area_ha": round(m2 / 1e4, 3), "lat": round((min(ys) + max(ys)) / 2, 5), "lon": round((min(xs) + max(xs)) / 2, 5)}


# ---------------------------------------------------------------------------- validation
def _date(v, name="date"):
    try:
        d = dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError(f"{name}: not a date (YYYY-MM-DD)")
    if d.year < 2000 or d > dt.date.today() + dt.timedelta(days=370):
        raise ValueError(f"{name}: date out of range")
    return d.isoformat()


def _fields(kind_fields, src):
    out = {}
    for name, (kind, required, lim) in kind_fields.items():
        v = (src or {}).get(name)
        if v in (None, ""):
            if required:
                raise ValueError(f"{name} is required")
            continue
        if kind == "number":
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name}: not a number")
            if not math.isfinite(x) or (lim and not lim[0] <= x <= lim[1]):
                raise ValueError(f"{name}: out of range {lim}")
            out[name] = x
        elif kind == "choice":
            if v not in lim:
                raise ValueError(f"{name} must be one of {list(lim)}")
            out[name] = v
        else:
            s = str(v).strip()
            if lim and len(s) > lim:
                raise ValueError(f"{name}: at most {lim} characters")
            out[name] = s
    return out


def validate_entry(e: dict) -> dict:
    t = e.get("entry_type")
    if t not in ENTRY_TYPES:
        raise ValueError(f"entry_type must be one of {sorted(ENTRY_TYPES)}")
    on = _date(e.get("date"), "date")
    if t in ("harvest", "crop_stage", "rainfall", "pest_disease") and on > (dt.date.today() + dt.timedelta(days=1)).isoformat():
        raise ValueError(f"a {ENTRY_TYPES[t][0].lower()} is recorded once it has happened")
    return {"entry_type": t, "entry_date": on, "payload": _fields(ENTRY_TYPES[t][1], e.get("payload"))}


# ---------------------------------------------------------------------------- farms
def create(spec: dict) -> dict:
    if spec.get("consent") is not True:
        raise ValueError("saving a farm needs the owner's consent")
    g = check_geometry(spec.get("geometry"))
    name = str(spec.get("name") or "My farm").strip()[:60]
    crop = spec.get("crop")
    if crop is not None and crop not in CROPS:
        raise ValueError(f"crop must be one of {sorted(CROPS)}")
    key = secrets.token_urlsafe(24)
    row = store.insert(TABLE, {"key_hash": _hash(key), "name": name, **g, "crop": crop, "simulate": bool(spec.get("simulate", True)),
                               "country": spec.get("country") or "kenya", "updated_at": _now()})
    return {"id": row["id"], "key": key, "storage": store.status()}


def _own(fid, key) -> dict:
    rows = store.select(TABLE, eq={"id": fid}, limit=1)
    if not rows or not key or rows[0].get("key_hash") != _hash(key):
        raise PermissionError("farm not found")             # the same answer for a wrong key: ids are not revealed
    return rows[0]


def _public(row) -> dict:
    return {k: v for k, v in row.items() if k != "key_hash"}


def get(fid, key) -> dict:
    f = _own(fid, key)
    diary = sorted(store.select(DIARY, eq={"farm_id": fid}, limit=1000), key=lambda e: (e.get("entry_date") or "", e.get("created_at") or ""))
    sims = store.select(SIMS, eq={"farm_id": fid}, limit=1)
    return {"farm": _public(f), "diary": diary, "simulation": sims[0] if sims else None, "season": season_inputs(f, diary),
            "storage": store.status()}


def edit(fid, key, patch: dict) -> dict:
    _own(fid, key)
    out = {}
    if "name" in patch:
        out["name"] = str(patch["name"] or "My farm").strip()[:60]
    if "geometry" in patch:
        out.update(check_geometry(patch["geometry"]))
    if "crop" in patch:
        if patch["crop"] is not None and patch["crop"] not in CROPS:
            raise ValueError(f"crop must be one of {sorted(CROPS)}")
        out["crop"] = patch["crop"]
    if "simulate" in patch:
        out["simulate"] = bool(patch["simulate"])
    if not out:
        raise ValueError("nothing to change (name, geometry, crop, simulate)")
    out["updated_at"] = _now()
    return _public(store.update(TABLE, fid, out))


def remove(fid, key) -> None:
    _own(fid, key)
    for t in (DIARY, SIMS):
        for r in store.select(t, eq={"farm_id": fid}, limit=5000):
            store.delete(t, r["id"])
    store.delete(TABLE, fid)


def add_entry(fid, key, entry: dict) -> dict:
    _own(fid, key)
    e = validate_entry(entry)
    row = store.insert(DIARY, {"farm_id": fid, **e})
    store.update(TABLE, fid, {"updated_at": _now()})
    return row


def remove_entry(fid, key, eid) -> None:
    _own(fid, key)
    rows = store.select(DIARY, eq={"id": eid}, limit=1)
    if not rows or rows[0].get("farm_id") != fid:
        raise PermissionError("entry not found")
    store.delete(DIARY, eid)
    store.update(TABLE, fid, {"updated_at": _now()})


# ---------------------------------------------------------------------------- the daily farm crop runs
def season_start(today=None) -> str:
    """Short Rains season of a date: sowings from 1 Aug of the year (to 31 Jan of the next) belong to it."""
    d = today or dt.date.today()
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-08-01"


def season_inputs(farm: dict, diary: list, today=None) -> dict | None:
    """What this season's farm crop run needs from the diary: the latest sowing since the season start (its crop,
    else the farm's), and the irrigation and nitrogen after it. None without a sowing this season."""
    s0 = season_start(today)
    day = lambda e: str(e.get("entry_date") or "")[:10]
    sow = [e for e in diary if e.get("entry_type") == "sowing" and day(e) >= s0]
    if not sow:
        return None
    last = max(sow, key=lambda e: (day(e), e.get("created_at") or ""))
    after = [e for e in diary if day(e) >= day(last)]
    return {"sowing_date": day(last), "crop": (last.get("payload") or {}).get("crop") or farm.get("crop"),
            "irrigation": [{"date": day(e), "mm": e["payload"]["mm"]} for e in after if e["entry_type"] == "irrigation"],
            "nitrogen": [{"date": day(e), "kg_ha": e["payload"]["n_kg_ha"]} for e in after
                         if e["entry_type"] == "fertiliser" and (e.get("payload") or {}).get("n_kg_ha") is not None],
            "harvested": any(e["entry_type"] == "harvest" for e in after)}


def queue(today=None) -> list:
    """Farms to simulate: simulate on, sown this season and not yet harvested."""
    out = []
    for f in store.select(TABLE, eq={"simulate": True}, limit=5000):
        diary = store.select(DIARY, eq={"farm_id": f["id"]}, limit=1000)
        s = season_inputs(f, diary, today)
        if s and not s["harvested"] and s["crop"] in CROPS:
            out.append({"id": f["id"], "lat": f["lat"], "lon": f["lon"], "area_ha": f.get("area_ha"), "country": f.get("country"),
                        "updated_at": f.get("updated_at"), **s})
    return out


def post_simulation(fid, result: dict, inputs: dict) -> dict:
    if not store.select(TABLE, eq={"id": fid}, limit=1):
        raise PermissionError("farm not found")
    old = store.select(SIMS, eq={"farm_id": fid}, limit=50)
    row = store.insert(SIMS, {"farm_id": fid, "result": result, "inputs": inputs})
    for r in old:                                               # keep the latest run only
        store.delete(SIMS, r["id"])
    return {"id": row["id"]}
