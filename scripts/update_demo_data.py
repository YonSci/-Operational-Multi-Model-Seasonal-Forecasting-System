"""
scripts/update_demo_data.py
Adds ECMWF SEAS5 Sep (Short Rains OND) and CHIRPS Sep data into backend/demo_data.npz
so that the cloud deployment on Render has full operational forecasting capabilities
for both Long Rains (MAM) and Short Rains (OND) without needing raw multi-GB NetCDF files.
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

    print("[1/4] Extracting OND CHIRPS reference & calibration params...")
    data_sep = {}
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

    print("[2/4] Extracting OND ECMWF SEAS5 model outputs & skill metrics...")
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

    print("[3/4] Extracting operational daily precipitation arrays (2025 and 2026)...")
    ds_bc = xr.open_dataset(os.path.join(sep_dir, 'ECMWF_bc_daily_all_years.nc'))
    vname = list(ds_bc.data_vars)[0]
    if 2025 in years:
        idx_2025 = list(years).index(2025)
        data_sep['sep_ecmwf_bc_daily_2025'] = ds_bc[vname][:, idx_2025].values.astype(np.float16)
    if 2026 in years:
        idx_2026 = list(years).index(2026)
        data_sep['sep_ecmwf_bc_daily_2026'] = ds_bc[vname][:, idx_2026].values.astype(np.float16)
    ds_bc.close()

    print("[4/4] Combining with existing MAM data in backend/demo_data.npz...")
    out_file = os.path.join('backend', 'demo_data.npz')
    orig = np.load(out_file)
    combined = {k: orig[k] for k in orig.files}
    combined.update(data_sep)
    np.savez_compressed(out_file, **combined)
    size_mb = os.path.getsize(out_file) / (1024 * 1024)
    print(f"Successfully updated {out_file} ({size_mb:.2f} MB)")

if __name__ == '__main__':
    update_demo_data()
