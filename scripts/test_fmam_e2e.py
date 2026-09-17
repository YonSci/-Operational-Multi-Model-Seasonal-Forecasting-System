"""
Comprehensive End-to-End Test for Ethiopia FMAM (Belg) SEAS5 Pipeline
and Multi-Season Regression Verification.
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))

from mam_loader import load, get_model_info, get_pixel_stats, get_grid_stats, SITES

print("Loading dataset via mam_loader.load()...")
load()
print("mam_loader.load() completed successfully.")

print("=" * 70)
print("1. VERIFY RESEARCH STATIONS")
print("=" * 70)
eth_stations = [s for s in SITES if s.get("country") == "ethiopia"]
print(f"Total Ethiopia Research Stations: {len(eth_stations)}")
for s in eth_stations:
    print(f" - {s['site_name']} ({s['lat']}, {s['lon']})")
assert any("Yabello" in s["site_name"] for s in eth_stations), "Yabello missing!"
assert any("Kobo" in s["site_name"] for s in eth_stations), "Kobo missing!"

print("\n" + "=" * 70)
print("2. VERIFY MODEL INFO FOR ALL 4 SEASONS")
print("=" * 70)
for season in ["fmam", "kiremt", "long_rains", "short_rains"]:
    models_list = get_model_info(season)
    names = [m["raw_name"] for m in models_list]
    print(f"Season '{season}': {len(models_list)} models loaded -> {names}")
    if season == "fmam":
        assert any("FMAM" in m["raw_name"] for m in models_list), "ECMWF SEAS5 (FMAM) missing in fmam!"
        ecmwf = next(m for m in models_list if "FMAM" in m["raw_name"])
        assert ecmwf["n_members"] == 25, f"Expected 25 members, got {ecmwf['n_members']}"
        assert ecmwf["season"] == "fmam", f"Expected season 'fmam', got {ecmwf['season']}"
        assert ecmwf["win_doy_start"] == 32 and ecmwf["win_doy_end"] == 166, f"Incorrect window: {ecmwf['win_doy_start']}-{ecmwf['win_doy_end']}"
        print(f"  [PASS] FMAM Metadata: raw_name={ecmwf['raw_name']}, members={ecmwf['n_members']}, window={ecmwf['win_doy_start']}-{ecmwf['win_doy_end']}, HR={ecmwf['hr_onset']}")

print("\n" + "=" * 70)
print("3. VERIFY PIXEL STATS FOR HOLETTA (ETHIOPIA FMAM)")
print("=" * 70)
holetta_fmam = get_pixel_stats(9.06, 38.50, season="fmam", model="ECMWF SEAS5 (FMAM)")
assert "error" not in holetta_fmam, f"Error in Holetta FMAM: {holetta_fmam.get('error')}"
ecmwf_m = holetta_fmam["models"]["ECMWF SEAS5"]
print("Holetta FMAM Pixel Response:")
print(f" - Grid Pixel: ({holetta_fmam['glat']}, {holetta_fmam['glon']}) [dist: {holetta_fmam['delta_km']} km]")
print(f" - Season: {holetta_fmam['season']}")
print(f" - Onset Median: {ecmwf_m['on_med']:.1f} (anom: {ecmwf_m['on_anom']:+.1f})")
print(f" - Cessation Median: {ecmwf_m['cs_med']:.1f} (anom: {ecmwf_m['cs_anom']:+.1f})")
print(f" - LGP Median: {ecmwf_m['lg_med']:.1f} days (anom: {ecmwf_m['lg_anom']:+.1f})")
print(f" - Climatology Onset: {holetta_fmam['chirps_clim']['onset']:.1f}")
print(f" - Tercile Probs: Onset={ecmwf_m['p_on']}, Agreement={ecmwf_m['agree_on']*100:.1f}%")
bc = ecmwf_m["bc_pixel"]
print(f" - Daily BC Plume: Members={len(bc)}, DOY Days={len(bc[0])}")
assert len(bc) == 25, f"Expected 25 plume members, got {len(bc)}"
assert len(bc[0]) == 135, f"Expected 135 daily points per member, got {len(bc[0])}"
assert len(holetta_fmam["C_clim_vec"]) == 135, f"Expected 135 C_clim points, got {len(holetta_fmam['C_clim_vec'])}"

print("\n" + "=" * 70)
print("4. VERIFY GRID STATS FOR ETHIOPIA FMAM")
print("=" * 70)
grid_onset = get_grid_stats("onset", "median", season="fmam", model="ECMWF SEAS5 (FMAM)")
assert "error" not in grid_onset, f"Error in FMAM Grid: {grid_onset.get('error')}"
n_lat, n_lon = len(grid_onset['lats']), len(grid_onset['lons'])
print(f" - Grid Dimensions: {n_lat} x {n_lon}")
print(f" - Lat Range: [{min(grid_onset['lats'])}, {max(grid_onset['lats'])}]")
print(f" - Lon Range: [{min(grid_onset['lons'])}, {max(grid_onset['lons'])}]")
print(f" - Min Value: {grid_onset['vmin']:.1f}, Max Value: {grid_onset['vmax']:.1f}")
assert n_lat == 48 and n_lon == 60, f"Expected 48x60 grid shape, got {n_lat}x{n_lon}"
assert len(grid_onset['values']) == 48 and len(grid_onset['values'][0]) == 60, "Values shape mismatch"

print("\n" + "=" * 70)
print("5. VERIFY REGRESSION ON OTHER 3 SEASONS")
print("=" * 70)
# Kiremt (Ethiopia)
kiremt_stat = get_pixel_stats(9.06, 38.50, season="kiremt", model="ECMWF SEAS5 (Kiremt)")
assert "error" not in kiremt_stat, f"Kiremt error: {kiremt_stat.get('error')}"
print(f" [PASS] Kiremt (Holetta): Onset Median = {kiremt_stat['models']['ECMWF SEAS5']['on_med']:.1f}")

# Long Rains MAM (Kenya)
mam_stat = get_pixel_stats(-2.21, 37.72, season="long_rains", model="ECMWF SEAS5")
assert "error" not in mam_stat, f"Kenya MAM error: {mam_stat.get('error')}"
print(f" [PASS] Kenya MAM (Kiboko): Onset Median = {mam_stat['models']['ECMWF SEAS5']['on_med']:.1f}")

# Short Rains OND (Kenya)
ond_stat = get_pixel_stats(-2.21, 37.72, season="short_rains", model="ECMWF SEAS5 (Sep)")
assert "error" not in ond_stat, f"Kenya OND error: {ond_stat.get('error')}"
print(f" [PASS] Kenya OND (Kiboko): Onset Median = {ond_stat['models']['ECMWF SEAS5']['on_med']:.1f}")

print("\n" + "=" * 70)
print("ALL E2E CHECKS PASSED SUCCESSFULLY!")
print("=" * 70)
