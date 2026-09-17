"""Test FastAPI endpoints for Kenya MAM, Kenya OND, and Ethiopia Kiremt."""
import os, sys
sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from main import app
import mam_loader as dl

# Pre-load data
print("Loading data...")
dl.load(force=True)

client = TestClient(app)

print("\n--- 1. Testing GET /health ---")
r = client.get("/health")
assert r.status_code == 200, f"Health check failed: {r.text}"
print("Health OK:", r.json().get("status"))

print("\n--- 2. Testing GET /models for seasons ---")
for season in ["long_rains", "short_rains", "kiremt"]:
    r = client.get(f"/models?season={season}")
    assert r.status_code == 200, f"Failed models for {season}: {r.text}"
    models_dict = r.json().get("models", {})
    print(f"Models for {season}: {len(models_dict)} models -> {list(models_dict.keys())}")

print("\n--- 3. Testing GET /sites for country & season ---")
for country in ["kenya", "ethiopia"]:
    for season in ["long_rains", "short_rains", "kiremt"]:
        r = client.get(f"/sites?country={country}&season={season}")
        assert r.status_code == 200, f"Failed sites for {country}/{season}: {r.text}"
        sites = r.json().get("sites", [])
        print(f"Sites for {country} ({season}): {len(sites)} sites -> {[s['site_name'] for s in sites[:3]]}")

print("\n--- 4. Testing GET /pixel for Ethiopia Kiremt ---")
# Holetta: 9.06 N, 38.50 E
r = client.get("/pixel?lat=9.060&lon=38.500&season=kiremt&year=2026")
assert r.status_code == 200, f"Failed pixel for Kiremt: {r.text}"
px = r.json()
print("Kiremt Pixel OK:", {
    "glat": px.get("glat"),
    "glon": px.get("glon"),
    "delta_km": px.get("delta_km"),
    "season": px.get("season"),
    "models": list(px.get("models", {}).keys()),
    "chirps_clim": px.get("chirps_clim"),
})

print("\n--- 5. Testing GET /grid for Ethiopia Kiremt ---")
r = client.get("/grid?variable=onset&layer=median&season=kiremt&model=ECMWF%20SEAS5%20(Kiremt)")
assert r.status_code == 200, f"Failed grid for Kiremt: {r.text}"
grid = r.json()
meta = grid.get("meta", {})
features = grid.get("features", [])
print("Kiremt Grid OK:", {
    "variable": meta.get("variable"),
    "layer": meta.get("layer"),
    "n_pixels": meta.get("n_pixels"),
    "features_count": len(features),
    "sample_feature_val": features[0]["properties"]["map_val"] if features else None,
    "vmin": meta.get("vmin"),
    "vmax": meta.get("vmax"),
})

print("\n--- 6. Testing GET /pixel for Kenya OND (Short Rains) ---")
r = client.get("/pixel?lat=-2.210&lon=37.719&season=short_rains&year=2026")
assert r.status_code == 200, f"Failed pixel for OND: {r.text}"
px_ond = r.json()
print("Kenya OND Pixel OK:", {
    "glat": px_ond.get("glat"),
    "glon": px_ond.get("glon"),
    "models": list(px_ond.get("models", {}).keys()),
    "chirps_clim": px_ond.get("chirps_clim")
})

print("\n--- 7. Testing POST /bulletin for Ethiopia Kiremt (Single-Model) ---")
r = client.post("/bulletin", json={
    "site_name": "Holetta Agricultural Research Center",
    "lat": 9.060,
    "lon": 38.500,
    "fmt": "png",
    "bulletin_type": "single",
    "model_name": "ECMWF SEAS5",
    "season": "kiremt",
    "year": 2026
})
assert r.status_code == 200, f"Failed bulletin for Kiremt: {r.text}"
print(f"Kiremt Bulletin OK! Returned {len(r.content):,} bytes of PNG image.")

print("\n=======================================================")
print(">>> ALL FASTAPI ENDPOINT TESTS PASSED SUCCESSFULLY! <<<")
print("=======================================================")
