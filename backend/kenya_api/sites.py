"""GET/POST/DELETE /sites"""
import os, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import mam_loader as dl

router = APIRouter()

_SITES_FILE = os.path.join(os.path.dirname(__file__), "..", "sites.json")

DEFAULT_SITES = [
    # Kenya Research Farms
    {"site_name": "Kapiti Research Station Farm",   "lat": -1.63209, "lon": 37.1479, "county": "Machakos",   "country": "kenya"},
    {"site_name": "KALRO Kiboko, Makueni Farm",     "lat": -2.21046, "lon": 37.7190, "county": "Makueni",    "country": "kenya"},
    {"site_name": "El Karama Sahiwals Farm",         "lat": -2.38710, "lon": 37.4851, "county": "Kajiado",    "country": "kenya"},
    {"site_name": "LiveMo LTD, Memerush, Kajiado",  "lat": -2.38726, "lon": 37.4850, "county": "Kajiado",    "country": "kenya"},
    {"site_name": "Genco LTD Maralal Samburu Farm", "lat":  0.92730, "lon": 36.5690, "county": "Samburu",    "country": "kenya"},
    {"site_name": "Genco LTD Tana River Farm",      "lat": -2.21314, "lon": 40.0517, "county": "Tana River", "country": "kenya"},
    # Ethiopia Agricultural Research Centers
    {"site_name": "Holetta Agricultural Research Center", "lat": 9.060, "lon": 38.500, "county": "Oromia", "country": "ethiopia"},
    {"site_name": "Debre Zeit / Bishoftu Station",        "lat": 8.750, "lon": 38.980, "county": "Oromia", "country": "ethiopia"},
    {"site_name": "Melkassa Agricultural Research Center", "lat": 8.410, "lon": 39.320, "county": "Oromia", "country": "ethiopia"},
    {"site_name": "Bako Agricultural Research Center",     "lat": 9.120, "lon": 37.050, "county": "Oromia", "country": "ethiopia"},
    {"site_name": "Hawassa Farm Station",                  "lat": 7.050, "lon": 38.480, "county": "Sidama", "country": "ethiopia"},
]

def _load():
    if os.path.exists(_SITES_FILE):
        try:
            with open(_SITES_FILE) as f: return json.load(f)
        except Exception: pass
    return list(DEFAULT_SITES)

def _save(sites):
    try:
        with open(_SITES_FILE,"w") as f: json.dump(sites, f, indent=2)
    except Exception as e:
        print(f"  WARNING: could not persist sites.json: {e}")

_SITES = _load()

class SiteIn(BaseModel):
    site_name: str; lat: float; lon: float; country: str = "kenya"

@router.get("")
def list_sites():
    result = []
    for s in _SITES:
        entry = dict(s)
        if dl.is_loaded():
            try:
                is_eth = (s.get("country") == "ethiopia" or s["lat"] > 5.0 or s["lon"] > 42.5)
                m_season = "kiremt" if is_eth else "long_rains"
                px = dl.get_pixel_stats(s["lat"], s["lon"], season=m_season)
                entry.update(pi=int(px["pi"]), pj=int(px["pj"]),
                             glat=float(px["glat"]), glon=float(px["glon"]),
                             dkm=float(px["delta_km"]))
            except Exception: pass
        result.append(entry)
    return {"sites": result, "count": len(result)}

@router.post("")
def add_site(site: SiteIn):
    is_eth = (site.country == "ethiopia" or site.lat > 5.0 or site.lon > 42.5)
    if is_eth:
        if not (3.0 <= site.lat <= 15.0 and 33.0 <= site.lon <= 48.0):
            raise HTTPException(400, f"({site.lat},{site.lon}) outside Ethiopia domain.")
    else:
        if not (-5.0 <= site.lat <= 5.0 and 33.0 <= site.lon <= 42.5):
            raise HTTPException(400, f"({site.lat},{site.lon}) outside Kenya domain.")
    if any(s["site_name"].lower()==site.site_name.lower() for s in _SITES):
        raise HTTPException(409, f"'{site.site_name}' already registered.")
    new = {"site_name": site.site_name, "lat": site.lat, "lon": site.lon, "country": "ethiopia" if is_eth else "kenya"}
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
