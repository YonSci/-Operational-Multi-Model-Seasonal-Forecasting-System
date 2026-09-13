# Skill-Weighted Ensemble Forecast -- Stage 8 notebook cells
# Add these cells to notebook_multimodel_stage8.ipynb


# ============================================================
# SKILL-WEIGHTED ENSEMBLE FORECAST
# Equal Weighting vs HR-Weighted vs RPSS-Weighted
# ============================================================

import numpy as np
import warnings

# ── Available models and their skill scores ──────────────────
state   = dl.get_state()
MODELS  = state["MODELS"]
lm      = state["lm"]
OP_YEAR = state["OP_YEAR"]

def domain_mean_skill(md, var, metric):
    """Return domain-mean skill score for a model, variable, metric."""
    arr = md.get(metric, {}).get(var)
    if arr is None: return np.nan
    vals = arr[lm]
    return float(np.nanmean(vals[~np.isnan(vals)])) if (~np.isnan(vals)).any() else np.nan

print("Model                   | HR Onset | HR Cess | HR LGP | RPSS On | RPSS Cs | RPSS LGP")
print("-" * 90)
hr_weights   = {}
rpss_weights = {}
for name, md in MODELS.items():
    hr_on  = domain_mean_skill(md, "onset",     "hitrate_cal")
    hr_cs  = domain_mean_skill(md, "cessation", "hitrate_cal")
    hr_lgp = domain_mean_skill(md, "lgp",       "hitrate_cal")
    rp_on  = domain_mean_skill(md, "onset",     "rpss_val")
    rp_cs  = domain_mean_skill(md, "cessation", "rpss_val")
    rp_lgp = domain_mean_skill(md, "lgp",       "rpss_val")
    print(f"{name:<25}| {hr_on:7.3f}  | {hr_cs:6.3f}  | {hr_lgp:6.3f} | {rp_on:7.3f} | {rp_cs:6.3f} | {rp_lgp:7.3f}")
    hr_weights[name]   = max(np.nanmean([hr_on, hr_cs, hr_lgp]), 0.01)
    rpss_weights[name] = max(np.nanmean([max(rp_on,0), max(rp_cs,0), max(rp_lgp,0)]), 0.0)

# Normalise
hr_total   = sum(hr_weights.values())
rpss_total = sum(rpss_weights.values())
if rpss_total < 1e-6:
    rpss_total = 1.0
    rpss_weights = {k: 1/len(MODELS) for k in MODELS}

hr_w_norm   = {k: v/hr_total   for k,v in hr_weights.items()}
rpss_w_norm = {k: v/rpss_total for k,v in rpss_weights.items()}

print("\n=== Normalised Weights ===")
print(f"{'Model':<25} | {'Equal':>8} | {'HR-Wt':>8} | {'RPSS-Wt':>8}")
print("-" * 60)
n = len(MODELS)
for name in MODELS:
    print(f"{name:<25} | {1/n:8.3f} | {hr_w_norm.get(name,0):8.3f} | {rpss_w_norm.get(name,0):8.3f}")



# ============================================================
# SKILL-WEIGHTED SPATIAL MAPS
# ============================================================

def skill_weighted_map(var_key, arr_key, weights_dict):
    """Compute skill-weighted MMM P50 map for onset/cessation/lgp."""
    meds, weights = [], []
    for name, md in MODELS.items():
        w = weights_dict.get(name, 0)
        if w <= 0: continue
        med = np.nanmedian(md[arr_key][:, md["op_idx"], :, :], axis=0)
        meds.append(med)
        weights.append(w)
    if not meds:
        return np.full((state["n_lat"], state["n_lon"]), np.nan)
    w_arr   = np.array(weights); w_arr /= w_arr.sum()
    stacked = np.stack(meds, axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        weighted_map = np.nansum(stacked * w_arr[:,None,None], axis=0)
    return np.where(lm, weighted_map, np.nan).astype(np.float32)

# Compute maps for each variable
var_configs = [
    ("onset",     "onset_doy",     "Onset DOY"),
    ("cessation", "cessation_doy", "Cessation DOY"),
    ("lgp",       "lgp_days",      "Season Length (days)"),
]

results = {}
for var, arr_key, label in var_configs:
    results[var] = {
        "equal":    skill_weighted_map(var, arr_key, {k: 1 for k in MODELS}),
        "hr_wt":    skill_weighted_map(var, arr_key, hr_w_norm),
        "rpss_wt":  skill_weighted_map(var, arr_key, rpss_w_norm),
        "chirps":   state["chirps_clim"][var],
        "label":    label,
    }

# Summary stats
print(f"{'Variable':<20} | {'Equal P50':>12} | {'HR-Wt P50':>12} | {'RPSS-Wt P50':>12} | {'CHIRPS CAL':>12}")
print("-" * 80)
for var, d in results.items():
    def dm(arr): return float(np.nanmedian(arr[lm])) if arr is not None else np.nan
    print(f"{d['label']:<20} | {dm(d['equal']):12.1f} | {dm(d['hr_wt']):12.1f} | {dm(d['rpss_wt']):12.1f} | {dm(d['chirps']):12.1f}")
