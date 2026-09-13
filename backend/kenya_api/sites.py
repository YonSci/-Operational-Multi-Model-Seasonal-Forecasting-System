"""GET/POST/DELETE /sites"""
import os, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import mam_loader as dl

router = APIRouter()

_SITES_FILE = os.path.join(os.path.dirname(__file__), "..", "sites.json")

def _load():
    if os.path.exists(_SITES_FILE):
        try:
            with open(_SITES_FILE) as f: return json.load(f)
        except Exception: pass
    return list(dl.SITES)   # default from mam_loader

def _save(sites):
    try:
        with open(_SITES_FILE,"w") as f: json.dump(sites, f, indent=2)
    except Exception as e:
        print(f"  WARNING: could not persist sites.json: {e}")

_SITES = _load()

class SiteIn(BaseModel):
    site_name: str; lat: float; lon: float

@router.get("")
def list_sites():
    result = []
    for s in _SITES:
        entry = dict(s)
        if dl.is_loaded():
            try:
                px = dl.get_pixel_stats(s["lat"], s["lon"])
                entry.update(pi=int(px["pi"]), pj=int(px["pj"]),
                             glat=float(px["glat"]), glon=float(px["glon"]),
                             dkm=float(px["delta_km"]))
            except Exception: pass
        result.append(entry)
    return {"sites": result, "count": len(result)}

@router.post("")
def add_site(site: SiteIn):
    if not (-5.0 <= site.lat <= 5.0 and 33.0 <= site.lon <= 42.5):
        raise HTTPException(400, f"({site.lat},{site.lon}) outside Kenya domain.")
    if any(s["site_name"].lower()==site.site_name.lower() for s in _SITES):
        raise HTTPException(409, f"'{site.site_name}' already registered.")
    new = {"site_name":site.site_name,"lat":site.lat,"lon":site.lon}
    _SITES.append(new); _save(_SITES)
    return {"status":"added","site":new,"total":len(_SITES)}

@router.delete("/{site_name}")
def delete_site(site_name: str):
    global _SITES
    before = len(_SITES)
    _SITES = [s for s in _SITES if s["site_name"].lower()!=site_name.lower()]
    if len(_SITES)==before:
        raise HTTPException(404, f"'{site_name}' not found.")
    _save(_SITES)
    return {"status":"deleted","remaining":len(_SITES)}
