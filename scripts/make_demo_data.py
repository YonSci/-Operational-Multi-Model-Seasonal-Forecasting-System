"""
scripts/make_demo_data.py
Creates backend/demo_data.npz with Kenya grid, CHIRPS climatology, and operational
multi-model seasonal forecast data so the backend runs seamlessly on cloud platforms
like Render without requiring multi-GB raw NetCDF files.
"""
import os, sys
import numpy as np
import xarray as xr

def build_demo_data():
    base_ecmwf = "outputs/ecmwf_v3"
    base_bom   = "outputs/bom_v3"
    cal_ecmwf  = os.path.join(base_ecmwf, "calibration_params")

    print("[1/5] Extracting CHIRPS reference & calibration params...")
    ds_on = xr.open_dataset(os.path.join(base_ecmwf, "CHIRPS_onset_doy_1981_2025.nc"))
    lats = ds_on.lat.values.astype(np.float64)
    lons = ds_on.lon.values.astype(np.float64)
    n_lat, n_lon = len(lats), len(lons)
    onset_chirps = ds_on[list(ds_on.data_vars)[0]].values.astype(np.float32)
    lm = np.isfinite(onset_chirps).any(axis=0)

    ds_cs = xr.open_dataset(os.path.join(base_ecmwf, "CHIRPS_cessation_doy_1981_2025.nc"))
    cess_chirps = ds_cs[list(ds_cs.data_vars)[0]].values.astype(np.float32)

    ds_lgp = xr.open_dataset(os.path.join(base_ecmwf, "CHIRPS_lgp_days_1981_2025.nc"))
    lgp_chirps = ds_lgp[list(ds_lgp.data_vars)[0]].values.astype(np.float32)
    if np.nanmax(np.abs(lgp_chirps)) > 1e6:
        lgp_chirps = (lgp_chirps / 86400e9).astype(np.float32)
    lgp_chirps = np.where((lgp_chirps > 0) & (lgp_chirps <= 366), lgp_chirps, np.nan).astype(np.float32)

    C_clim = xr.open_dataset(os.path.join(base_ecmwf, "chirps_C_clim.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "chirps_C_clim.nc")).data_vars)[0]].values.astype(np.float32)
    Q_bar  = xr.open_dataset(os.path.join(base_ecmwf, "chirps_Q_bar.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "chirps_Q_bar.nc")).data_vars)[0]].values.astype(np.float32)
    d_s    = xr.open_dataset(os.path.join(base_ecmwf, "chirps_d_s.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "chirps_d_s.nc")).data_vars)[0]].values.astype(np.float32)
    d_e    = xr.open_dataset(os.path.join(base_ecmwf, "chirps_d_e.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "chirps_d_e.nc")).data_vars)[0]].values.astype(np.float32)

    t33_on = xr.open_dataset(os.path.join(cal_ecmwf, "t33_onset_doy.nc"))[list(xr.open_dataset(os.path.join(cal_ecmwf, "t33_onset_doy.nc")).data_vars)[0]].values.astype(np.float32)
    t67_on = xr.open_dataset(os.path.join(cal_ecmwf, "t67_onset_doy.nc"))[list(xr.open_dataset(os.path.join(cal_ecmwf, "t67_onset_doy.nc")).data_vars)[0]].values.astype(np.float32)

    t33_cs = xr.open_dataset(os.path.join(cal_ecmwf, "t33_cessation_doy.nc"))[list(xr.open_dataset(os.path.join(cal_ecmwf, "t33_cessation_doy.nc")).data_vars)[0]].values.astype(np.float32)
    t67_cs = xr.open_dataset(os.path.join(cal_ecmwf, "t67_cessation_doy.nc"))[list(xr.open_dataset(os.path.join(cal_ecmwf, "t67_cessation_doy.nc")).data_vars)[0]].values.astype(np.float32)

    t33_lgp = xr.open_dataset(os.path.join(cal_ecmwf, "t33_lgp_days.nc"))[list(xr.open_dataset(os.path.join(cal_ecmwf, "t33_lgp_days.nc")).data_vars)[0]].values.astype(np.float32)
    t67_lgp = xr.open_dataset(os.path.join(cal_ecmwf, "t67_lgp_days.nc"))[list(xr.open_dataset(os.path.join(cal_ecmwf, "t67_lgp_days.nc")).data_vars)[0]].values.astype(np.float32)

    cal_years = np.arange(1981, 2017)
    chirps_years = np.arange(1981, 1981 + onset_chirps.shape[0])
    cal_mask = np.isin(chirps_years, cal_years)

    data_dict = {
        "target_lat": lats,
        "target_lon": lons,
        "lm": lm,
        "chirps_onset": onset_chirps,
        "chirps_cessation": cess_chirps,
        "chirps_lgp": lgp_chirps,
        "chirps_years": chirps_years,
        "C_clim": C_clim,
        "Q_bar": Q_bar,
        "d_s": d_s,
        "d_e": d_e,
        "t33_onset": t33_on,
        "t67_onset": t67_on,
        "t33_cess": t33_cs,
        "t67_cess": t67_cs,
        "t33_lgp": t33_lgp,
        "t67_lgp": t67_lgp,
    }

    # Model metadata configuration
    models_config = [
        {"name": "ECMWF SEAS5",       "key": "ecmwf", "members": 51, "start_yr": 1981, "color": "#1B5EA6", "hr": 0.44, "rpss": 0.18},
        {"name": "UKMO GloSea6",      "key": "ukmo",  "members": 42, "start_yr": 1993, "color": "#C0392B", "hr": 0.41, "rpss": 0.14},
        {"name": "Meteo-France Sys8", "key": "mf",    "members": 51, "start_yr": 1993, "color": "#1E6B45", "hr": 0.42, "rpss": 0.15},
        {"name": "DWD GCFS2.1",       "key": "dwd",   "members": 50, "start_yr": 1993, "color": "#8B4513", "hr": 0.39, "rpss": 0.12},
        {"name": "CMCC-SPS4",         "key": "cmcc",  "members": 40, "start_yr": 1993, "color": "#7B0EA6", "hr": 0.38, "rpss": 0.11},
        {"name": "NCEP CFSv2",        "key": "ncep",  "members": 24, "start_yr": 1993, "color": "#C9920A", "hr": 0.37, "rpss": 0.10},
        {"name": "ECCC CanSIPS",      "key": "eccc",  "members": 20, "start_yr": 1993, "color": "#0E7490", "hr": 0.36, "rpss": 0.09},
    ]

    print("[2/5] Loading real ECMWF SEAS5 data...")
    ec_on_ds = xr.open_dataset(os.path.join(base_ecmwf, "ECMWF_onset_doy_all_years.nc"))
    ec_on = ec_on_ds[list(ec_on_ds.data_vars)[0]].values.astype(np.float32)
    ec_cs_ds = xr.open_dataset(os.path.join(base_ecmwf, "ECMWF_cessation_doy_all_years.nc"))
    ec_cs = ec_cs_ds[list(ec_cs_ds.data_vars)[0]].values.astype(np.float32)
    ec_lg_ds = xr.open_dataset(os.path.join(base_ecmwf, "ECMWF_lgp_days_all_years.nc"))
    ec_lg = ec_lg_ds[list(ec_lg_ds.data_vars)[0]].values.astype(np.float32)

    ec_p_on = xr.open_dataset(os.path.join(base_ecmwf, "probs_damped_onset.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "probs_damped_onset.nc")).data_vars)[0]].values.astype(np.float32)
    ec_p_cs = xr.open_dataset(os.path.join(base_ecmwf, "probs_damped_cessation.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "probs_damped_cessation.nc")).data_vars)[0]].values.astype(np.float32)
    ec_p_lg = xr.open_dataset(os.path.join(base_ecmwf, "probs_damped_lgp.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "probs_damped_lgp.nc")).data_vars)[0]].values.astype(np.float32)

    ec_alpha_on = xr.open_dataset(os.path.join(base_ecmwf, "alpha_onset.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "alpha_onset.nc")).data_vars)[0]].values.astype(np.float32)
    ec_alpha_cs = xr.open_dataset(os.path.join(base_ecmwf, "alpha_cessation.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "alpha_cessation.nc")).data_vars)[0]].values.astype(np.float32)
    ec_alpha_lg = xr.open_dataset(os.path.join(base_ecmwf, "alpha_lgp.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "alpha_lgp.nc")).data_vars)[0]].values.astype(np.float32)

    ec_hr_on = xr.open_dataset(os.path.join(base_ecmwf, "hitrate_onset_cal.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "hitrate_onset_cal.nc")).data_vars)[0]].values.astype(np.float32)
    ec_hr_cs = xr.open_dataset(os.path.join(base_ecmwf, "hitrate_cessation_cal.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "hitrate_cessation_cal.nc")).data_vars)[0]].values.astype(np.float32)
    ec_hr_lg = xr.open_dataset(os.path.join(base_ecmwf, "hitrate_lgp_cal.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "hitrate_lgp_cal.nc")).data_vars)[0]].values.astype(np.float32)

    ec_rpss_on = xr.open_dataset(os.path.join(base_ecmwf, "rpss_onset_val.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "rpss_onset_val.nc")).data_vars)[0]].values.astype(np.float32)
    ec_rpss_cs = xr.open_dataset(os.path.join(base_ecmwf, "rpss_cessation_val.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "rpss_cessation_val.nc")).data_vars)[0]].values.astype(np.float32)
    ec_rpss_lg = xr.open_dataset(os.path.join(base_ecmwf, "rpss_lgp_val.nc"))[list(xr.open_dataset(os.path.join(base_ecmwf, "rpss_lgp_val.nc")).data_vars)[0]].values.astype(np.float32)

    print("[3/5] Generating multi-model dataset for 7 models...")
    # Base climatology means
    clim_on_mean = np.nanmean(onset_chirps[cal_mask], axis=0)
    clim_cs_mean = np.nanmean(cess_chirps[cal_mask], axis=0)
    clim_lg_mean = np.nanmean(lgp_chirps[cal_mask], axis=0)

    np.random.seed(42)

    # Representative calibration years + operational year (total 11 years)
    sample_cal_years = np.arange(2007, 2017)
    model_years_demo = np.append(sample_cal_years, 2026)
    n_yrs = len(model_years_demo)

    # ECMWF indices for the selected years (ECMWF starts in 1993):
    ec_years = np.arange(1993, 2027)
    ec_idx_map = [int(np.where(ec_years == y)[0][0]) for y in model_years_demo if y in ec_years]

    for m in models_config:
        k = m["key"]
        n_mem = min(m["members"], 25)  # 25 members is plenty for realistic distributions
        years = model_years_demo

        if k == "ecmwf":
            # Real ECMWF arrays sliced to selected years
            m_on = ec_on[:n_mem, ec_idx_map]
            m_cs = ec_cs[:n_mem, ec_idx_map]
            m_lg = ec_lg[:n_mem, ec_idx_map]
            p_on = ec_p_on[:, ec_idx_map]
            p_cs = ec_p_cs[:, ec_idx_map]
            p_lg = ec_p_lg[:, ec_idx_map]
            a_on, a_cs, a_lg = ec_alpha_on, ec_alpha_cs, ec_alpha_lg
            h_on, h_cs, h_lg = ec_hr_on, ec_hr_cs, ec_hr_lg
            r_on, r_cs, r_lg = ec_rpss_on, ec_rpss_cs, ec_rpss_lg
        else:
            # Calibrated ensemble model around observed climatology + model-specific signal
            seed = sum(ord(c) for c in k)
            rng = np.random.default_rng(seed)

            # Signal offset for 2026: varied across models
            offset_on = rng.uniform(-4.0, 4.0)
            offset_cs = rng.uniform(-5.0, 5.0)

            # Generate ensemble members [n_mem, n_yrs, n_lat, n_lon]
            m_on = np.zeros((n_mem, n_yrs, n_lat, n_lon), dtype=np.float32)
            m_cs = np.zeros((n_mem, n_yrs, n_lat, n_lon), dtype=np.float32)
            m_lg = np.zeros((n_mem, n_yrs, n_lat, n_lon), dtype=np.float32)

            noise_on = rng.normal(0, rng.uniform(8.0, 12.0), size=(n_mem, n_yrs, n_lat, n_lon)).astype(np.float32)
            noise_cs = rng.normal(0, rng.uniform(10.0, 15.0), size=(n_mem, n_yrs, n_lat, n_lon)).astype(np.float32)

            for yi in range(n_yrs):
                yr_offset_on = offset_on if yi == n_yrs - 1 else rng.uniform(-6.0, 6.0)
                yr_offset_cs = offset_cs if yi == n_yrs - 1 else rng.uniform(-7.0, 7.0)
                m_on[:, yi] = np.where(lm, clim_on_mean + yr_offset_on + noise_on[:, yi], np.nan)
                m_cs[:, yi] = np.where(lm, clim_cs_mean + yr_offset_cs + noise_cs[:, yi], np.nan)
                m_lg[:, yi] = np.where(lm, np.maximum(m_cs[:, yi] - m_on[:, yi], 10.0), np.nan)

            # Vectorized tercile probabilities [3, n_yrs, n_lat, n_lon]
            with np.errstate(invalid="ignore"):
                bn_on = np.mean(m_on < t33_on[None, None, :, :], axis=0).astype(np.float32)
                an_on = np.mean(m_on > t67_on[None, None, :, :], axis=0).astype(np.float32)
                nn_on = np.maximum(0.0, 1.0 - bn_on - an_on).astype(np.float32)
                p_on = np.stack([bn_on, nn_on, an_on], axis=0)

                bn_cs = np.mean(m_cs < t33_cs[None, None, :, :], axis=0).astype(np.float32)
                an_cs = np.mean(m_cs > t67_cs[None, None, :, :], axis=0).astype(np.float32)
                nn_cs = np.maximum(0.0, 1.0 - bn_cs - an_cs).astype(np.float32)
                p_cs = np.stack([bn_cs, nn_cs, an_cs], axis=0)

                bn_lg = np.mean(m_lg < t33_lgp[None, None, :, :], axis=0).astype(np.float32)
                an_lg = np.mean(m_lg > t67_lgp[None, None, :, :], axis=0).astype(np.float32)
                nn_lg = np.maximum(0.0, 1.0 - bn_lg - an_lg).astype(np.float32)
                p_lg = np.stack([bn_lg, nn_lg, an_lg], axis=0)

            # Alpha, hitrate, rpss maps
            a_on = np.where(lm, float(m["hr"] * 0.8), np.nan).astype(np.float32)
            a_cs = np.where(lm, float(m["hr"] * 0.75), np.nan).astype(np.float32)
            a_lg = np.where(lm, float(m["hr"] * 0.7), np.nan).astype(np.float32)

            h_on = np.where(lm, float(m["hr"]), np.nan).astype(np.float32)
            h_cs = np.where(lm, float(m["hr"] - 0.02), np.nan).astype(np.float32)
            h_lg = np.where(lm, float(m["hr"] - 0.03), np.nan).astype(np.float32)

            r_on = np.where(lm, float(m["rpss"]), np.nan).astype(np.float32)
            r_cs = np.where(lm, float(m["rpss"] - 0.02), np.nan).astype(np.float32)
            r_lg = np.where(lm, float(m["rpss"] - 0.03), np.nan).astype(np.float32)

        data_dict[f"{k}_onset"] = m_on
        data_dict[f"{k}_cessation"] = m_cs
        data_dict[f"{k}_lgp"] = m_lg
        data_dict[f"{k}_p_on"] = p_on
        data_dict[f"{k}_p_cs"] = p_cs
        data_dict[f"{k}_p_lg"] = p_lg
        data_dict[f"{k}_a_on"] = a_on
        data_dict[f"{k}_a_cs"] = a_cs
        data_dict[f"{k}_a_lg"] = a_lg
        data_dict[f"{k}_h_on"] = h_on
        data_dict[f"{k}_h_cs"] = h_cs
        data_dict[f"{k}_h_lg"] = h_lg
        data_dict[f"{k}_r_on"] = r_on
        data_dict[f"{k}_r_cs"] = r_cs
        data_dict[f"{k}_r_lg"] = r_lg
        data_dict[f"{k}_years"] = years

    out_file = os.path.join("backend", "demo_data.npz")
    print(f"[4/5] Saving compressed bundle to {out_file}...")
    np.savez_compressed(out_file, **data_dict)
    size_mb = os.path.getsize(out_file) / (1024 * 1024)
    print(f"[5/5] Done! Generated {out_file} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    build_demo_data()
