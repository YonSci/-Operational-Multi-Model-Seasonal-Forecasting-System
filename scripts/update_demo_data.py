"""
scripts/update_demo_data.py
Adds ECMWF SEAS5 Sep (Short Rains OND) and ECMWF SEAS5 May (Ethiopia Kiremt)
into backend/demo_data.npz so that the cloud deployment on Render has full operational
forecasting capabilities for Kenya MAM, Kenya OND, and Ethiopia Kiremt without needing raw multi-GB NetCDF files.
"""
import os
import xarray as xr
import numpy as np

def get_var(p):
    ds = xr.open_dataset(p)
    k = list(ds.data_vars)[0]
    arr = ds[k].values
    ds.close()
    return arr

def update_demo_data():
    sep_dir = 'outputs/ecmwf_sep'
    cal_dir = os.path.join(sep_dir, 'calibration_params')

    print("[1/5] Extracting OND CHIRPS reference & calibration params...")
    data_sep = {}
    if os.path.exists(sep_dir):
        data_sep['sep_chirps_onset'] = get_var(os.path.join(sep_dir, 'CHIRPS_onset_doy_1981_2025.nc')).astype(np.float32)
        data_sep['sep_chirps_cessation'] = get_var(os.path.join(sep_dir, 'CHIRPS_cessation_doy_1981_2025.nc')).astype(np.float32)
        data_sep['sep_chirps_lgp'] = get_var(os.path.join(sep_dir, 'CHIRPS_lgp_days_1981_2025.nc')).astype(np.float32)
        data_sep['sep_C_clim'] = get_var(os.path.join(sep_dir, 'chirps_C_clim.nc')).astype(np.float32)
        data_sep['sep_Q_bar'] = get_var(os.path.join(sep_dir, 'chirps_Q_bar.nc')).astype(np.float32)
        data_sep['sep_d_s'] = get_var(os.path.join(sep_dir, 'chirps_d_s.nc')).astype(np.float32)
        data_sep['sep_d_e'] = get_var(os.path.join(sep_dir, 'chirps_d_e.nc')).astype(np.float32)

        data_sep['sep_t33_on'] = get_var(os.path.join(cal_dir, 't33_onset_doy.nc')).astype(np.float32)
        data_sep['sep_t67_on'] = get_var(os.path.join(cal_dir, 't67_onset_doy.nc')).astype(np.float32)
        data_sep['sep_t33_cs'] = get_var(os.path.join(cal_dir, 't33_cessation_doy.nc')).astype(np.float32)
        data_sep['sep_t67_cs'] = get_var(os.path.join(cal_dir, 't67_cessation_doy.nc')).astype(np.float32)
        data_sep['sep_t33_lg'] = get_var(os.path.join(cal_dir, 't33_lgp_days.nc')).astype(np.float32)
        data_sep['sep_t67_lg'] = get_var(os.path.join(cal_dir, 't67_lgp_days.nc')).astype(np.float32)

        print("[2/5] Extracting OND ECMWF SEAS5 model outputs & skill metrics...")
        data_sep['sep_ecmwf_onset'] = get_var(os.path.join(sep_dir, 'ECMWF_onset_doy_all_years.nc')).astype(np.float32)
        data_sep['sep_ecmwf_cessation'] = get_var(os.path.join(sep_dir, 'ECMWF_cessation_doy_all_years.nc')).astype(np.float32)
        data_sep['sep_ecmwf_lgp'] = get_var(os.path.join(sep_dir, 'ECMWF_lgp_days_all_years.nc')).astype(np.float32)

        data_sep['sep_ecmwf_p_on'] = get_var(os.path.join(sep_dir, 'probs_damped_onset.nc')).astype(np.float32)
        data_sep['sep_ecmwf_p_cs'] = get_var(os.path.join(sep_dir, 'probs_damped_cessation.nc')).astype(np.float32)
        data_sep['sep_ecmwf_p_lg'] = get_var(os.path.join(sep_dir, 'probs_damped_lgp.nc')).astype(np.float32)

        data_sep['sep_ecmwf_a_on'] = get_var(os.path.join(sep_dir, 'alpha_onset.nc')).astype(np.float32)
        data_sep['sep_ecmwf_a_cs'] = get_var(os.path.join(sep_dir, 'alpha_cessation.nc')).astype(np.float32)
        data_sep['sep_ecmwf_a_lg'] = get_var(os.path.join(sep_dir, 'alpha_lgp.nc')).astype(np.float32)

        data_sep['sep_ecmwf_h_on'] = get_var(os.path.join(sep_dir, 'hitrate_onset_val.nc')).astype(np.float32)
        data_sep['sep_ecmwf_h_cs'] = get_var(os.path.join(sep_dir, 'hitrate_cessation_val.nc')).astype(np.float32)
        data_sep['sep_ecmwf_h_lg'] = get_var(os.path.join(sep_dir, 'hitrate_lgp_val.nc')).astype(np.float32)

        data_sep['sep_ecmwf_r_on'] = get_var(os.path.join(sep_dir, 'rpss_onset_val.nc')).astype(np.float32)
        data_sep['sep_ecmwf_r_cs'] = get_var(os.path.join(sep_dir, 'rpss_cessation_val.nc')).astype(np.float32)
        data_sep['sep_ecmwf_r_lg'] = get_var(os.path.join(sep_dir, 'rpss_lgp_val.nc')).astype(np.float32)

        ds_yr = xr.open_dataset(os.path.join(sep_dir, 'model_years.nc'))
        years = ds_yr.year.values.astype(int)
        ds_yr.close()
        data_sep['sep_ecmwf_years'] = years

        print("[3/5] Extracting OND operational daily precipitation arrays (2025 and 2026)...")
        bc_path = os.path.join(sep_dir, 'ECMWF_bc_daily_all_years.nc')
        if os.path.exists(bc_path):
            ds_bc = xr.open_dataset(bc_path)
            vname = list(ds_bc.data_vars)[0]
            if 2025 in years:
                idx_2025 = list(years).index(2025)
                data_sep['sep_ecmwf_bc_daily_2025'] = ds_bc[vname][:, idx_2025].values.astype(np.float16)
            if 2026 in years:
                idx_2026 = list(years).index(2026)
                data_sep['sep_ecmwf_bc_daily_2026'] = ds_bc[vname][:, idx_2026].values.astype(np.float16)
            ds_bc.close()

    # Ethiopia Kiremt extraction
    kiremt_dir = 'outputs/ecmwf_kiremt'
    cal_kiremt = os.path.join(kiremt_dir, 'calibration_params')
    data_kiremt = {}
    if os.path.exists(kiremt_dir):
        print("[4/5] Extracting Ethiopia Kiremt CHIRPS reference, ECMWF SEAS5 and calibration params...")
        data_kiremt['kiremt_chirps_onset'] = get_var(os.path.join(kiremt_dir, 'CHIRPS_onset_doy_1993_2026.nc')).astype(np.float32)
        data_kiremt['kiremt_chirps_cessation'] = get_var(os.path.join(kiremt_dir, 'CHIRPS_cessation_doy_1993_2026.nc')).astype(np.float32)
        data_kiremt['kiremt_chirps_lgp'] = get_var(os.path.join(kiremt_dir, 'CHIRPS_lgp_days_1993_2026.nc')).astype(np.float32)
        data_kiremt['kiremt_C_clim'] = get_var(os.path.join(kiremt_dir, 'chirps_C_clim.nc')).astype(np.float32)
        data_kiremt['kiremt_Q_bar'] = get_var(os.path.join(kiremt_dir, 'chirps_Q_bar.nc')).astype(np.float32)
        data_kiremt['kiremt_d_s'] = get_var(os.path.join(kiremt_dir, 'chirps_d_s.nc')).astype(np.float32)
        data_kiremt['kiremt_d_e'] = get_var(os.path.join(kiremt_dir, 'chirps_d_e.nc')).astype(np.float32)

        data_kiremt['kiremt_t33_on'] = get_var(os.path.join(cal_kiremt, 't33_onset_doy.nc')).astype(np.float32)
        data_kiremt['kiremt_t67_on'] = get_var(os.path.join(cal_kiremt, 't67_onset_doy.nc')).astype(np.float32)
        data_kiremt['kiremt_t33_cs'] = get_var(os.path.join(cal_kiremt, 't33_cessation_doy.nc')).astype(np.float32)
        data_kiremt['kiremt_t67_cs'] = get_var(os.path.join(cal_kiremt, 't67_cessation_doy.nc')).astype(np.float32)
        data_kiremt['kiremt_t33_lg'] = get_var(os.path.join(cal_kiremt, 't33_lgp_days.nc')).astype(np.float32)
        data_kiremt['kiremt_t67_lg'] = get_var(os.path.join(cal_kiremt, 't67_lgp_days.nc')).astype(np.float32)

        ds_ref = xr.open_dataset(os.path.join(kiremt_dir, 'CHIRPS_onset_doy_1993_2026.nc'))
        data_kiremt['kiremt_target_lat'] = ds_ref.lat.values.astype(np.float64)
        data_kiremt['kiremt_target_lon'] = ds_ref.lon.values.astype(np.float64)
        data_kiremt['kiremt_chirps_years'] = ds_ref.year.values.astype(int)
        data_kiremt['kiremt_lm'] = np.isfinite(data_kiremt['kiremt_chirps_onset']).any(axis=0)
        ds_ref.close()

        data_kiremt['kiremt_ecmwf_onset'] = get_var(os.path.join(kiremt_dir, 'ECMWF_onset_doy_all_years.nc')).astype(np.float16)
        data_kiremt['kiremt_ecmwf_cessation'] = get_var(os.path.join(kiremt_dir, 'ECMWF_cessation_doy_all_years.nc')).astype(np.float16)
        data_kiremt['kiremt_ecmwf_lgp'] = get_var(os.path.join(kiremt_dir, 'ECMWF_lgp_days_all_years.nc')).astype(np.float16)

        data_kiremt['kiremt_ecmwf_p_on'] = get_var(os.path.join(kiremt_dir, 'probs_damped_onset.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_p_cs'] = get_var(os.path.join(kiremt_dir, 'probs_damped_cessation.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_p_lg'] = get_var(os.path.join(kiremt_dir, 'probs_damped_lgp.nc')).astype(np.float32)

        data_kiremt['kiremt_ecmwf_a_on'] = get_var(os.path.join(kiremt_dir, 'alpha_onset.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_a_cs'] = get_var(os.path.join(kiremt_dir, 'alpha_cessation.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_a_lg'] = get_var(os.path.join(kiremt_dir, 'alpha_lgp.nc')).astype(np.float32)

        data_kiremt['kiremt_ecmwf_h_on'] = get_var(os.path.join(kiremt_dir, 'hitrate_onset_val.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_h_cs'] = get_var(os.path.join(kiremt_dir, 'hitrate_cessation_val.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_h_lg'] = get_var(os.path.join(kiremt_dir, 'hitrate_lgp_val.nc')).astype(np.float32)

        data_kiremt['kiremt_ecmwf_r_on'] = get_var(os.path.join(kiremt_dir, 'rpss_onset_val.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_r_cs'] = get_var(os.path.join(kiremt_dir, 'rpss_cessation_val.nc')).astype(np.float32)
        data_kiremt['kiremt_ecmwf_r_lg'] = get_var(os.path.join(kiremt_dir, 'rpss_lgp_val.nc')).astype(np.float32)

        ds_yr = xr.open_dataset(os.path.join(kiremt_dir, 'model_years.nc'))
        data_kiremt['kiremt_ecmwf_years'] = ds_yr.year.values.astype(int)
        ds_yr.close()

        bc26_path = os.path.join(kiremt_dir, 'ECMWF_bc_daily_2026.nc')
        if os.path.exists(bc26_path):
            ds_bc26 = xr.open_dataset(bc26_path)
            vbc = list(ds_bc26.data_vars)[0]
            data_kiremt['kiremt_ecmwf_bc_daily_2026'] = ds_bc26[vbc].values.astype(np.float16)
            ds_bc26.close()

    # Ethiopia Belg (FMAM) extraction
    fmam_dir = 'outputs/ecmwf_fmam'
    cal_fmam = os.path.join(fmam_dir, 'calibration_params')
    data_fmam = {}
    if os.path.exists(fmam_dir):
        print("[5/6] Extracting Ethiopia Belg (FMAM) CHIRPS reference, ECMWF SEAS5 and calibration params...")
        data_fmam['fmam_chirps_onset'] = get_var(os.path.join(fmam_dir, 'CHIRPS_onset_doy_1993_2026.nc')).astype(np.float32)
        data_fmam['fmam_chirps_cessation'] = get_var(os.path.join(fmam_dir, 'CHIRPS_cessation_doy_1993_2026.nc')).astype(np.float32)
        data_fmam['fmam_chirps_lgp'] = get_var(os.path.join(fmam_dir, 'CHIRPS_lgp_days_1993_2026.nc')).astype(np.float32)
        data_fmam['fmam_C_clim'] = get_var(os.path.join(fmam_dir, 'chirps_C_clim.nc')).astype(np.float32)
        data_fmam['fmam_Q_bar'] = get_var(os.path.join(fmam_dir, 'chirps_Q_bar.nc')).astype(np.float32)
        data_fmam['fmam_d_s'] = get_var(os.path.join(fmam_dir, 'chirps_d_s.nc')).astype(np.float32)
        data_fmam['fmam_d_e'] = get_var(os.path.join(fmam_dir, 'chirps_d_e.nc')).astype(np.float32)

        data_fmam['fmam_t33_on'] = get_var(os.path.join(cal_fmam, 't33_onset_doy.nc')).astype(np.float32)
        data_fmam['fmam_t67_on'] = get_var(os.path.join(cal_fmam, 't67_onset_doy.nc')).astype(np.float32)
        data_fmam['fmam_t33_cs'] = get_var(os.path.join(cal_fmam, 't33_cessation_doy.nc')).astype(np.float32)
        data_fmam['fmam_t67_cs'] = get_var(os.path.join(cal_fmam, 't67_cessation_doy.nc')).astype(np.float32)
        data_fmam['fmam_t33_lg'] = get_var(os.path.join(cal_fmam, 't33_lgp_days.nc')).astype(np.float32)
        data_fmam['fmam_t67_lg'] = get_var(os.path.join(cal_fmam, 't67_lgp_days.nc')).astype(np.float32)

        ds_ref = xr.open_dataset(os.path.join(fmam_dir, 'CHIRPS_onset_doy_1993_2026.nc'))
        data_fmam['fmam_target_lat'] = ds_ref.lat.values.astype(np.float64)
        data_fmam['fmam_target_lon'] = ds_ref.lon.values.astype(np.float64)
        data_fmam['fmam_chirps_years'] = ds_ref.year.values.astype(int)
        data_fmam['fmam_lm'] = np.isfinite(data_fmam['fmam_chirps_onset']).any(axis=0)
        ds_ref.close()

        data_fmam['fmam_ecmwf_onset'] = get_var(os.path.join(fmam_dir, 'ECMWF_onset_doy_all_years.nc')).astype(np.float16)
        data_fmam['fmam_ecmwf_cessation'] = get_var(os.path.join(fmam_dir, 'ECMWF_cessation_doy_all_years.nc')).astype(np.float16)
        data_fmam['fmam_ecmwf_lgp'] = get_var(os.path.join(fmam_dir, 'ECMWF_lgp_days_all_years.nc')).astype(np.float16)

        data_fmam['fmam_ecmwf_p_on'] = get_var(os.path.join(fmam_dir, 'probs_damped_onset.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_p_cs'] = get_var(os.path.join(fmam_dir, 'probs_damped_cessation.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_p_lg'] = get_var(os.path.join(fmam_dir, 'probs_damped_lgp.nc')).astype(np.float32)

        data_fmam['fmam_ecmwf_a_on'] = get_var(os.path.join(fmam_dir, 'alpha_onset.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_a_cs'] = get_var(os.path.join(fmam_dir, 'alpha_cessation.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_a_lg'] = get_var(os.path.join(fmam_dir, 'alpha_lgp.nc')).astype(np.float32)

        data_fmam['fmam_ecmwf_h_on'] = get_var(os.path.join(fmam_dir, 'hitrate_onset_val.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_h_cs'] = get_var(os.path.join(fmam_dir, 'hitrate_cessation_val.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_h_lg'] = get_var(os.path.join(fmam_dir, 'hitrate_lgp_val.nc')).astype(np.float32)

        data_fmam['fmam_ecmwf_r_on'] = get_var(os.path.join(fmam_dir, 'rpss_onset_val.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_r_cs'] = get_var(os.path.join(fmam_dir, 'rpss_cessation_val.nc')).astype(np.float32)
        data_fmam['fmam_ecmwf_r_lg'] = get_var(os.path.join(fmam_dir, 'rpss_lgp_val.nc')).astype(np.float32)

        ds_yr = xr.open_dataset(os.path.join(fmam_dir, 'model_years.nc'))
        data_fmam['fmam_ecmwf_years'] = ds_yr.year.values.astype(int)
        ds_yr.close()

        bc26_path = os.path.join(fmam_dir, 'ECMWF_bc_daily_2026.nc')
        if os.path.exists(bc26_path):
            ds_bc26 = xr.open_dataset(bc26_path)
            vbc = list(ds_bc26.data_vars)[0]
            data_fmam['fmam_ecmwf_bc_daily_2026'] = ds_bc26[vbc].values.astype(np.float16)
            ds_bc26.close()

    # Ethiopia Bega (ONDJ) extraction
    bega_dir = 'outputs/ecmwf_bega'
    cal_bega = os.path.join(bega_dir, 'calibration_params')
    data_bega = {}
    if os.path.exists(bega_dir):
        print("[6/7] Extracting Ethiopia Bega (ONDJ) CHIRPS reference, ECMWF SEAS5 and calibration params...")
        data_bega['bega_chirps_onset'] = get_var(os.path.join(bega_dir, 'CHIRPS_onset_doy_1993_2026.nc')).astype(np.float32)
        data_bega['bega_chirps_cessation'] = get_var(os.path.join(bega_dir, 'CHIRPS_cessation_doy_1993_2026.nc')).astype(np.float32)
        data_bega['bega_chirps_lgp'] = get_var(os.path.join(bega_dir, 'CHIRPS_lgp_days_1993_2026.nc')).astype(np.float32)
        data_bega['bega_C_clim'] = get_var(os.path.join(bega_dir, 'chirps_C_clim.nc')).astype(np.float32)
        data_bega['bega_Q_bar'] = get_var(os.path.join(bega_dir, 'chirps_Q_bar.nc')).astype(np.float32)
        data_bega['bega_d_s'] = get_var(os.path.join(bega_dir, 'chirps_d_s.nc')).astype(np.float32)
        data_bega['bega_d_e'] = get_var(os.path.join(bega_dir, 'chirps_d_e.nc')).astype(np.float32)

        data_bega['bega_t33_on'] = get_var(os.path.join(cal_bega, 't33_onset_doy.nc')).astype(np.float32)
        data_bega['bega_t67_on'] = get_var(os.path.join(cal_bega, 't67_onset_doy.nc')).astype(np.float32)
        data_bega['bega_t33_cs'] = get_var(os.path.join(cal_bega, 't33_cessation_doy.nc')).astype(np.float32)
        data_bega['bega_t67_cs'] = get_var(os.path.join(cal_bega, 't67_cessation_doy.nc')).astype(np.float32)
        data_bega['bega_t33_lg'] = get_var(os.path.join(cal_bega, 't33_lgp_days.nc')).astype(np.float32)
        data_bega['bega_t67_lg'] = get_var(os.path.join(cal_bega, 't67_lgp_days.nc')).astype(np.float32)

        ds_ref = xr.open_dataset(os.path.join(bega_dir, 'CHIRPS_onset_doy_1993_2026.nc'))
        data_bega['bega_target_lat'] = ds_ref.lat.values.astype(np.float64)
        data_bega['bega_target_lon'] = ds_ref.lon.values.astype(np.float64)
        data_bega['bega_chirps_years'] = ds_ref.year.values.astype(int)
        data_bega['bega_lm'] = np.isfinite(data_bega['bega_chirps_onset']).any(axis=0)
        ds_ref.close()

        data_bega['bega_ecmwf_onset'] = get_var(os.path.join(bega_dir, 'ECMWF_onset_doy_all_years.nc')).astype(np.float16)
        data_bega['bega_ecmwf_cessation'] = get_var(os.path.join(bega_dir, 'ECMWF_cessation_doy_all_years.nc')).astype(np.float16)
        data_bega['bega_ecmwf_lgp'] = get_var(os.path.join(bega_dir, 'ECMWF_lgp_days_all_years.nc')).astype(np.float16)

        data_bega['bega_ecmwf_p_on'] = get_var(os.path.join(bega_dir, 'probs_damped_onset.nc')).astype(np.float32)
        data_bega['bega_ecmwf_p_cs'] = get_var(os.path.join(bega_dir, 'probs_damped_cessation.nc')).astype(np.float32)
        data_bega['bega_ecmwf_p_lg'] = get_var(os.path.join(bega_dir, 'probs_damped_lgp.nc')).astype(np.float32)

        data_bega['bega_ecmwf_a_on'] = get_var(os.path.join(bega_dir, 'alpha_onset.nc')).astype(np.float32)
        data_bega['bega_ecmwf_a_cs'] = get_var(os.path.join(bega_dir, 'alpha_cessation.nc')).astype(np.float32)
        data_bega['bega_ecmwf_a_lg'] = get_var(os.path.join(bega_dir, 'alpha_lgp.nc')).astype(np.float32)

        data_bega['bega_ecmwf_h_on'] = get_var(os.path.join(bega_dir, 'hitrate_onset_val.nc')).astype(np.float32)
        data_bega['bega_ecmwf_h_cs'] = get_var(os.path.join(bega_dir, 'hitrate_cessation_val.nc')).astype(np.float32)
        data_bega['bega_ecmwf_h_lg'] = get_var(os.path.join(bega_dir, 'hitrate_lgp_val.nc')).astype(np.float32)

        data_bega['bega_ecmwf_r_on'] = get_var(os.path.join(bega_dir, 'rpss_onset_val.nc')).astype(np.float32)
        data_bega['bega_ecmwf_r_cs'] = get_var(os.path.join(bega_dir, 'rpss_cessation_val.nc')).astype(np.float32)
        data_bega['bega_ecmwf_r_lg'] = get_var(os.path.join(bega_dir, 'rpss_lgp_val.nc')).astype(np.float32)

        ds_yr = xr.open_dataset(os.path.join(bega_dir, 'model_years.nc'))
        data_bega['bega_ecmwf_years'] = ds_yr.year.values.astype(int)
        ds_yr.close()

        bc26_path = os.path.join(bega_dir, 'ECMWF_bc_daily_2026.nc')
        if os.path.exists(bc26_path):
            ds_bc26 = xr.open_dataset(bc26_path)
            vbc = list(ds_bc26.data_vars)[0]
            data_bega['bega_ecmwf_bc_daily_2026'] = ds_bc26[vbc].values.astype(np.float16)
            ds_bc26.close()

    print("[7/7] Combining with existing MAM, OND, Kiremt, Belg, and Bega data in backend/demo_data.npz...")
    out_file = os.path.join('backend', 'demo_data.npz')
    orig = np.load(out_file)
    combined = {k: orig[k] for k in orig.files}
    combined.update(data_sep)
    combined.update(data_kiremt)
    combined.update(data_fmam)
    combined.update(data_bega)

    # Add seasonal masks and regime map if available
    masks_path = os.path.join('outputs', 'masks', 'seasonal_masks.npz')
    if os.path.exists(masks_path):
        print("Loading seasonal masks and regime map from", masks_path)
        m_data = np.load(masks_path)
        for k in m_data.files:
            if k == 'regime_map':
                combined[k] = m_data[k].astype(np.int8)
            else:
                combined[k] = m_data[k].astype(bool)

    np.savez_compressed(out_file, **combined)
    size_mb = os.path.getsize(out_file) / (1024 * 1024)
    print(f"Successfully updated {out_file} ({size_mb:.2f} MB) with Kenya MAM, Kenya OND, Ethiopia Kiremt, Ethiopia Belg, Ethiopia Bega, and seasonal masks.")

if __name__ == '__main__':
    update_demo_data()
