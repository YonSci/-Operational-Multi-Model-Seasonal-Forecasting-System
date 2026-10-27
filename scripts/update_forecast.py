#!/usr/bin/env python3
"""
update_forecast.py
──────────────────
Refresh the Kenya Short Rains forecast as new observations and medium-range forecasts arrive.

  1. Sync CHIRPS: re-download the final 2026 p25 file if CHC updated it; fetch any new preliminary
     daily p05 GeoTIFFs after the final record ends; rebuild the 0.25° preliminary NetCDF
  2. Seasonal (ECMWF SEAS5, latest init) re-run with observed CHIRPS spliced in up to the latest day
     → outputs/ecmwf_<mon>_obs_latest/ (+ run_meta.json); skipped when the observation date is unchanged
  3. Agronomic (planting) onset: CHIRPS + members, terciles, calibration, skill; ICPAC onset/cessation rules 1–3
  4. Latest ECMWF ENS (open data) → 1–15 day outlook and composite planting-onset dates
  5. Site reports for the Kenya monitored sites (outputs/site_reports/<today>/)
  6. Hot-reload the local backend if it is running

Usage:
  python scripts/update_forecast.py                 # everything, skip steps that are already current
  python scripts/update_forecast.py --force         # re-run seasonal + agro even if obs date unchanged
  python scripts/update_forecast.py --no-ens        # skip the ENS download
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
    h = requests.head(url, timeout=60)
    remote = email.utils.parsedate_to_datetime(h.headers["Last-Modified"]).timestamp()
    if not FINAL.exists() or remote > FINAL.stat().st_mtime + 60:
        log(f"CHIRPS final {YEAR}: updated on server, downloading")
        FINAL.parent.mkdir(parents=True, exist_ok=True)
        download(url, FINAL)
        os.utime(FINAL, (remote, remote))
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
            if not download(f"{CHC}/prelim/global_daily/tifs/p05/{day.year}/{name}", PRELIM_DIR / name):
                break                                   # not published yet
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ens", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    obs_end = sync_prelim(sync_final())
    changed = run_seasonal(obs_end, a.force)
    if changed or not (OUT_DIR / "agro_onset" / "rule.json").exists():
        subprocess.run([PY, str(BASE_DIR / "scripts" / "agro_onset.py"), "seasonal", str(OUT_DIR)], check=True, env=env)
    # ICPAC onset / cessation rules 1–3 for the platform's Method selector (PET climatology built once),
    # packed for the backend, then every site's comparison across initializations and methods
    if changed or not all((OUT_DIR / f"icpac_rule{k}" / "rule.json").exists() for k in (1, 2, 3)):
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
    log("update complete")


if __name__ == "__main__":
    main()
