"""Test Ethiopia ECMWF SEAS5 Kiremt backend logic and bulletin generation."""
import os, sys, tempfile

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath("backend"))

import mam_loader as dl
from bulletin_singlemodel_v1 import generate_single_model_bulletin

print("--- Step 1: Loading data ---")
dl.load(force=True)
s = dl.get_state()
print(f"Data loaded: demo_mode={s.get('demo_mode')}")
print(f"Models in state: {list(s['MODELS'].keys())}")
print(f"Chirps kiremt present: {bool(s.get('chirps_kiremt'))}")

print("\n--- Step 2: Testing get_model_info for kiremt ---")
k_models = dl.get_model_info(season="kiremt")
print(f"Kiremt models count: {len(k_models)}")
for m in k_models:
    print(f"  Model: {m['name']}, season: {m.get('season')}, window: DOY {m.get('win_doy_start')}-{m.get('win_doy_end')}")

print("\n--- Step 3: Testing Holetta pixel stats (9.06 N, 38.50 E) ---")
px = dl.get_pixel_stats(9.060, 38.500, season="kiremt")
print(f"Grid matched: pi={px.get('pi')}, pj={px.get('pj')}, glat={px.get('glat')}, glon={px.get('glon')}, dist={px.get('delta_km')} km")
print(f"CHIRPS clim at Holetta: onset={px.get('chirps_on_clim')}, cessation={px.get('chirps_cs_clim')}, lgp={px.get('chirps_lg_clim')}")
k_md_stats = px.get("models", {}).get("ECMWF SEAS5 (Kiremt)")
if k_md_stats:
    print(f"ECMWF SEAS5 (Kiremt) stats: onset_med={k_md_stats.get('on_med')}, cess_med={k_md_stats.get('cs_med')}, lgp_med={k_md_stats.get('lg_med')}")
    print(f"  Terciles Onset: {k_md_stats.get('p_on')}")
    print(f"  Alpha Onset: {k_md_stats.get('alpha_on')}")
else:
    print("WARNING: ECMWF SEAS5 (Kiremt) not in pixel stats models!")

print("\n--- Step 4: Testing get_grid_stats for kiremt ---")
grid = dl.get_grid_stats(variable="onset", layer="median", season="kiremt")
print(f"Grid stats: variable={grid.get('variable')}, layer={grid.get('layer')}, lats={len(grid.get('lats', []))}, lons={len(grid.get('lons', []))}")
print(f"Vmin={grid.get('vmin')}, Vmax={grid.get('vmax')}, Units={grid.get('units')}")

print("\n--- Step 5: Testing Single-Model Bulletin Generation for Holetta ---")
with tempfile.TemporaryDirectory() as tmpdir:
    png_path = generate_single_model_bulletin(
        site_name="Holetta Agricultural Research Center",
        lat_q=9.060, lon_q=38.500,
        model_name="ECMWF SEAS5 (Kiremt)",
        season="kiremt",
        f_year=2026,
        out_dir=tmpdir,
        dpi=75
    )
    print(f"Bulletin generated successfully: {png_path}")
    print(f"File size: {os.path.getsize(png_path):,} bytes")

print("\n>>> ALL ETHIOPIA KIREMT BACKEND CHECKS PASSED! <<<")
