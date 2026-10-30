#!/usr/bin/env python3
"""
update_forecast.py
──────────────────
Refresh the Kenya Short Rains forecast as new observations and medium-range forecasts arrive.

  1. Sync CHIRPS: re-download the final 2026 p25 file if CHC updated it; fetch any new preliminary
     daily p05 GeoTIFFs after the final record ends; rebuild the 0.25° preliminary NetCDF
  2. Seasonal (ECMWF SEAS5, latest init) re-run with observed CHIRPS spliced in up to the latest day
     → outputs/ecmwf_<mon>_obs_latest/ (+ run_meta.json); skipped when the observation date is unchanged
  3. Agronomic (planting) onset: CHIRPS + members, terciles, calibration, skill; Agri onset/cessation rules 1–3
     (after ICPAC); FAO water balance (CHIRPS v3 + ERA5-Land, when new CHIRPS v3 days arrive); the seasonal runs,
     rules and FAO definitions repacked for the hosted API
  4. Latest ECMWF ENS (open data) → 1–15 day outlook and composite planting-onset dates
  5. Satellite rainfall, multi-model 10–16 day forecasts, site reports, tracker data and page
  6. Hot-reload the local backend if it is running
  7. With --publish: push the refreshed data to origin/main (publish_daily.py), which redeploys the live platform

Usage:
  python scripts/update_forecast.py                 # everything, skip steps that are already current
  python scripts/update_forecast.py --force         # re-run seasonal + agro even if obs date unchanged
  python scripts/update_forecast.py --no-ens        # skip the ENS download
  python scripts/update_forecast.py --publish       # also publish the new data to the live platform
"""
import argparse
import datetime as dt
import email.utils
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import requests
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent.parent
PY = sys.executable
CHC = "https://data.chc.ucsb.edu/products/CHIRPS-2.0"
FINAL = BASE_DIR / "data" / "chirps_2026" / "chirps-v2.0.2026.days_p25.nc"
PRELIM_DIR = BASE_DIR / "data" / "chirps_prelim_2026"
PRELIM_NC = PRELIM_DIR / "chirps_prelim_2026_p25_kenya.nc"
YEAR = 2026
INIT_MONTH = 10                                    # latest SEAS5 initialization processed for this season
ECMWF_DIR = BASE_DIR / "data" / "seasonal_pr_downloads_ke" / f"ecmwf_{dt.date(2000, INIT_MONTH, 1):%b}".lower()
OUT_DIR = BASE_DIR / "outputs" / f"ecmwf_{dt.date(2000, INIT_MONTH, 1):%b}_obs_latest".lower()
WIN_START, WIN_END = 244, 365                      # Short Rains window (01 Sep – 31 Dec)
API = "http://127.0.0.1:8765"


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def download(url, dest, tries=6):
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i in range(tries):
        try:
            with requests.get(url, stream=True, timeout=180) as r:
                if r.status_code == 404:
                    return False
                if r.status_code == 403:                # access refused: do not keep asking
                    raise RuntimeError(f"access refused (403): {url}")
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(tmp, dest)
            return True
        except requests.RequestException as exc:
            log(f"  retry {i + 1} {url}: {exc}")
    raise RuntimeError(f"download failed: {url}")


def sync_final():
    url = f"{CHC}/global_daily/netcdf/p25/{FINAL.name}"
    try:
        h = requests.head(url, timeout=60)
        h.raise_for_status()
        remote = email.utils.parsedate_to_datetime(h.headers["Last-Modified"]).timestamp()
        if not FINAL.exists() or remote > FINAL.stat().st_mtime + 60:
            log(f"CHIRPS final {YEAR}: updated on server, downloading")
            FINAL.parent.mkdir(parents=True, exist_ok=True)
            download(url, FINAL)
            os.utime(FINAL, (remote, remote))
    except (requests.RequestException, KeyError, RuntimeError) as exc:
        # the CHC server can refuse access for a while (HTTP 403); keep the copy on disk and carry on
        log(f"CHIRPS final {YEAR}: server not reachable ({str(exc)[:120]}); using the copy on disk")
    with xr.open_dataset(FINAL) as ds:
        end = pd.Timestamp(ds.time.values.max()).date()
    log(f"CHIRPS final {YEAR} covers to {end}")
    return end


def sync_prelim(final_end):
    # daily global p05 GeoTIFFs are kept gzipped (~2.4 MB each; ~69 MB unpacked) and read via /vsigzip/
    PRELIM_DIR.mkdir(parents=True, exist_ok=True)
    day, got = final_end + dt.timedelta(days=1), 0
    while day <= dt.date.today():
        name = f"chirps-v2.0.{day:%Y.%m.%d}.tif.gz"
        if not (PRELIM_DIR / name).exists():
            try:
                if not download(f"{CHC}/prelim/global_daily/tifs/p05/{day.year}/{name}", PRELIM_DIR / name):
                    break                               # not published yet
            except RuntimeError as exc:                 # server refusing access: keep the days already on disk
                log(f"CHIRPS preliminary: server not reachable ({str(exc)[:120]}); using the days on disk")
                break
            got += 1
        day += dt.timedelta(days=1)
    # keep only preliminary days after the final record (final data supersedes them)
    for tif in PRELIM_DIR.glob("chirps-v2.0.*.tif.gz"):
        if dt.datetime.strptime(tif.name[12:22], "%Y.%m.%d").date() <= final_end:
            tif.unlink()
    tifs = sorted(PRELIM_DIR.glob("chirps-v2.0.*.tif.gz"))
    if tifs:
        subprocess.run([PY, str(BASE_DIR / "scripts" / "chirps_prelim_to_p25.py"), str(PRELIM_DIR), str(PRELIM_NC)], check=True)
        end = dt.datetime.strptime(tifs[-1].name[12:22], "%Y.%m.%d").date()
    else:
        PRELIM_NC.unlink(missing_ok=True)
        end = final_end
    log(f"CHIRPS preliminary: {got} new day(s); observations now to {end}")
    return end


def run_seasonal(obs_end, force):
    meta_p = OUT_DIR / "run_meta.json"
    if meta_p.exists() and not force and json.loads(meta_p.read_text()).get("obs_end") == str(obs_end):
        log(f"seasonal: already up to date (obs to {obs_end})")
        return False
    obs_end_doy = obs_end.timetuple().tm_yday
    lead0_doy = dt.date(YEAR, INIT_MONTH, 1).timetuple().tm_yday
    extra = [str(FINAL)] + ([str(PRELIM_NC)] if PRELIM_NC.exists() else [])
    cmd = [PY, str(BASE_DIR / "scripts" / "process_ecmwf_september.py"), "--init-month", str(INIT_MONTH),
           "--win-doy-start", str(WIN_START), "--win-doy-end", str(WIN_END),
           "--ecmwf-dir", str(ECMWF_DIR), "--out-dir", str(OUT_DIR), "--chirps-extra", *extra]
    if obs_end_doy >= WIN_START:
        cmd += ["--obs-lead-doy", str(lead0_doy), "--obs-end-doy", str(max(obs_end_doy, lead0_doy - 1))]
    log(f"seasonal: SEAS5 {YEAR}-{INIT_MONTH:02d}-01 init + observations to {obs_end} → {OUT_DIR.name}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "process.log", "w", encoding="utf-8") as f:
        subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    meta_p.write_text(json.dumps({"init": f"{YEAR}-{INIT_MONTH:02d}-01", "obs_end": str(obs_end),
                                  "obs_end_doy": obs_end_doy, "updated": dt.datetime.now().isoformat(timespec="seconds")}, indent=1))
    return True


def update_fao(env):
    """FAO water balance (fao_water_balance.py): fetch new CHIRPS v3 days (Earth Engine, then CHC preliminary) and
    the latest ERA5-Land ET0 (Earth Engine; at most 45 min — days ERA5-Land does not have yet use the ET0
    climatology), then re-run this season's observed water balance and the "+ latest obs" forecast when CHIRPS v3
    has advanced. Returns True when re-run."""
    hist = BASE_DIR / "outputs" / "fao_wb" / "historical" / "fao_wb_seasons.nc"
    if not hist.exists():
        log("FAO water balance: no historical run yet (python scripts/fao_water_balance.py historical); skipped")
        return False
    subprocess.run([PY, str(BASE_DIR / "scripts" / "fao_download_chirps_v3.py"), "--years", str(YEAR)], check=False, env=env)
    try:
        subprocess.run([PY, str(BASE_DIR / "scripts" / "fao_era5land_gee.py"), "--years", str(YEAR)],
                       check=False, env=env, timeout=45 * 60)
    except subprocess.TimeoutExpired:
        log("FAO water balance: ERA5-Land (Earth Engine) took over 45 min; ET0 climatology fills the latest days")
    v3 = BASE_DIR / "data" / "chirps_v3" / f"chirps_v3_p25_kenya_{YEAR}.nc"
    with xr.open_dataset(v3) as ds:
        last = str(pd.Timestamp(ds.time.values[-1]).date())
    meta_p = BASE_DIR / "outputs" / "fao_wb" / "run_meta.json"
    old = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    if old.get("chirps_v3_end") == last and (OUT_DIR / "fao_wb_agricultural" / "method.json").exists():
        log(f"FAO water balance: already up to date (CHIRPS v3 to {last})")
        return False
    fw = str(BASE_DIR / "scripts" / "fao_water_balance.py")
    subprocess.run([PY, fw, "historical", "--years", str(YEAR)], check=True, env=env)
    subprocess.run([PY, fw, "forecast", str(OUT_DIR)], check=True, env=env)
    meta_p.write_text(json.dumps({"chirps_v3_end": last, "updated": dt.datetime.now().isoformat(timespec="seconds")}, indent=1))
    log(f"FAO water balance: CHIRPS v3 to {last}; season so far and the latest-obs forecast updated")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ens", action="store_true")
    ap.add_argument("--publish", action="store_true", help="push the refreshed data to origin/main (live platform)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    obs_end = sync_prelim(sync_final())
    changed = run_seasonal(obs_end, a.force)
    if changed or not (OUT_DIR / "agro_onset" / "rule.json").exists():
        subprocess.run([PY, str(BASE_DIR / "scripts" / "agro_onset.py"), "seasonal", str(OUT_DIR)], check=True, env=env)
    # the hosted API reads the October runs (incl. this one) from backend/demo_short_rains_extra.npz
    if changed or not (BASE_DIR / "backend" / "demo_short_rains_extra.npz").exists():
        subprocess.run([PY, str(BASE_DIR / "scripts" / "pack_short_rains_demo.py")], check=True, env=env)
    # seasonal rainfall statistics (Rainfall Terciles view): total, wet / dry days, intensity, spells
    if changed or not (BASE_DIR / "backend" / "rain_stats.npz").exists():
        subprocess.run([PY, str(BASE_DIR / "scripts" / "rainfall_stats.py")], check=False, env=env)
    # Agri onset / cessation rules 1–3 for the platform's Method selector (PET climatology built once) and the
    # FAO water balance, packed for the backend, then every site's comparison across initializations and methods
    rules_missing = not all((OUT_DIR / f"icpac_rule{k}" / "rule.json").exists() for k in (1, 2, 3))
    try:
        fao_changed = update_fao(env)
    except Exception as exc:                            # the FAO module must not stop the daily update
        log(f"FAO water balance: failed ({str(exc)[:160]}); previous FAO outputs kept")
        fao_changed = False
    if changed or rules_missing or fao_changed:
        if changed or rules_missing:
            if not (BASE_DIR / "data" / "worldclim" / "pet_mhargreaves_clim_kenya.nc").exists():
                subprocess.run([PY, str(BASE_DIR / "scripts" / "pet_hargreaves.py")], check=True, env=env)
            subprocess.run([PY, str(BASE_DIR / "scripts" / "onset_rules.py"), str(OUT_DIR)], check=True, env=env)
        subprocess.run([PY, str(BASE_DIR / "scripts" / "pack_onset_rules.py")], check=True, env=env)
        subprocess.run([PY, str(BASE_DIR / "scripts" / "track_site_inits.py"), "--all-kenya"], check=False,
                       env={**env, "LOAD_BC_DAILY": "0"})

    if not a.no_ens:
        # a failed download (slow or unreachable data.ecmwf.int) keeps the previous run instead of stopping the update
        if subprocess.run([PY, str(BASE_DIR / "scripts" / "fetch_ecmwf_ens.py")], env=env).returncode:
            log("ENS: download failed, using the latest run already on disk")
        ens = sorted((BASE_DIR / "data" / "ecmwf_ens").glob("ens_tp_*_kenya.nc"))[-1]
        subprocess.run([PY, str(BASE_DIR / "scripts" / "agro_onset.py"), "ens", str(ens), str(OUT_DIR)], check=True, env=env)

    # Real-time satellite rainfall (ARC2, TAMSAT, PDIR-Now; IMERG when ~/.netrc has an Earthdata login):
    # fetch missing days since 1 Sep, monitor since 1 Oct, verify against CHIRPS (final Sep + prelim Oct)
    rt = str(BASE_DIR / "scripts" / "realtime_rain.py")
    import netrc
    try:
        has_earthdata = bool(netrc.netrc().authenticators("urs.earthdata.nasa.gov"))
    except (FileNotFoundError, netrc.NetrcParseError):
        has_earthdata = False
    products = ["arc2", "tamsat", "pdirnow"] + (["imerg", "imerg_early"] if has_earthdata else [])
    # IMERG and GSMaP through Google Earth Engine when it is set up (earthengine-api installed, authenticated,
    # project in EE_PROJECT or ~/.config/earthengine/project.txt)
    import importlib.util
    ee_cfg = Path.home() / ".config" / "earthengine"
    if importlib.util.find_spec("ee") and (ee_cfg / "credentials").exists() and (os.environ.get("EE_PROJECT") or (ee_cfg / "project.txt").exists()):
        products += ["imerg_gee", "gsmap_gee"]
    # Multi-model 10–16 day forecasts downloaded directly from ECMWF, NOAA, ECCC, DWD and the Met Office
    # (00 UTC run); any model that cannot be reached is filled from Open-Meteo
    subprocess.run([PY, str(BASE_DIR / "scripts" / "fetch_nwp_direct.py")], check=False, env=env)
    subprocess.run([PY, rt, "sync", "--start", f"{YEAR}-09-01", "--products", *products], check=False, env=env)
    subprocess.run([PY, rt, "monitor", "--since", f"{YEAR}-10-01"], check=False, env=env)
    subprocess.run([PY, rt, "verify", "--ref", "chirps", "--periods", f"{YEAR - 1}-10-01:{YEAR - 1}-12-31",
                    f"{YEAR}-09-01:{obs_end}"], check=False, env=env)

    subprocess.run([PY, str(BASE_DIR / "scripts" / "site_report.py"), "--seasonal-dir", str(OUT_DIR)], check=True, env=env)
    subprocess.run([PY, str(BASE_DIR / "scripts" / "export_dashboard_data.py")], check=False, env=env)
    subprocess.run([PY, str(BASE_DIR / "scripts" / "build_results_report.py")], check=False, env=env)
    subprocess.run([PY, str(BASE_DIR / "scripts" / "build_tracker_page.py")], check=False, env=env)   # platform tab
    try:
        r = requests.post(f"{API}/api/pipeline/reload", timeout=600)
        log(f"backend reload: {r.status_code}")
    except requests.RequestException:
        log("backend not running (no reload needed)")
    if a.publish:
        subprocess.run([PY, str(BASE_DIR / "scripts" / "publish_daily.py"), "--note", f"observations to {obs_end}"],
                       check=False, env=env)
    log("update complete")


if __name__ == "__main__":
    main()
