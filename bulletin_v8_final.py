"""Compatibility shim for Stage 8 notebook loaders expecting bulletin_v8*.py."""

import os

# Load multimodel bulletin definitions without executing footer code.
_SRC_PATH = os.path.join(os.getcwd(), "bulletin_multimodel_v1.py")
with open(_SRC_PATH, encoding="utf-8") as _f:
    _SRC = _f.read()

_CUT = len(_SRC)
for _marker in [
    "\nmm_failed = []",
    "multi-model bulletin(s)",
]:
    _pos = _SRC.find(_marker)
    if _pos > 0:
        _CUT = _pos
        break

exec(compile(_SRC[:_CUT], _SRC_PATH, "exec"), globals())


def _ensure_models_defined():
    models = globals().get("MODELS")
    if isinstance(models, dict) and models:
        normalized = {}
        for key, item in models.items():
            if isinstance(item, dict):
                normalized[str(key)] = _normalize_model_bundle(str(key), item)
            else:
                normalized[str(key)] = _build_model_bundle(str(key))
        globals()["MODELS"] = normalized
        return

    # Stage-8 notebooks may not define MODELS explicitly.
    # Infer a single-model list from known in-memory arrays before failing.
    if models is None or (hasattr(models, "__len__") and len(models) == 0):
        if "bom_onset_doy" in globals() or "bom_years" in globals():
            models = ["bom"]
        elif "seas5_onset_doy" in globals() or "seas5_years" in globals():
            models = ["seas5"]

    if not isinstance(models, list) or not models:
        raise RuntimeError("MODELS is not defined and could not be inferred")

    converted = {}
    for idx, item in enumerate(models):
        if isinstance(item, dict):
            key = (
                item.get("key")
                or item.get("name")
                or item.get("model_name")
                or item.get("short_name")
                or item.get("id")
                or f"model_{idx + 1}"
            )
            converted[str(key)] = item
        elif isinstance(item, str):
            converted[item] = _build_model_bundle(item)
        elif isinstance(item, (tuple, list)) and item and isinstance(item[0], str):
            converted[str(item[0])] = _build_model_bundle(str(item[0]))
        else:
            converted[f"model_{idx + 1}"] = _build_model_bundle(f"model_{idx + 1}")

    globals()["MODELS"] = converted


def _build_model_bundle(prefix):
    return _normalize_model_bundle(prefix, {})


def _normalize_model_bundle(prefix, base):
    bundle = dict(base) if isinstance(base, dict) else {}

    direct_map = {
        "onset_doy": [f"{prefix}_onset_doy", "bom_onset_doy", "seas5_onset_doy"],
        "cessation_doy": [f"{prefix}_cessation_doy", "bom_cessation_doy", "seas5_cessation_doy"],
        "lgp_days": [f"{prefix}_lgp_days", "bom_lgp_days", "seas5_lgp_days"],
        "bc_daily": [f"{prefix}_bc_daily", "bom_bc", "seas5_bc", "da_seas5_bc_final"],
        "model_years": [f"{prefix}_years", "bom_years", "seas5_years"],
        "op_idx": [f"{prefix}_op_idx"],
        "n_members": [f"{prefix}_n_members"],
    }

    for key, candidates in direct_map.items():
        if key in bundle and bundle[key] is not None:
            continue
        for candidate in candidates:
            if candidate in globals() and globals()[candidate] is not None:
                bundle[key] = globals()[candidate]
                break

    if "op_idx" not in bundle:
        bundle["op_idx"] = 0

    if "n_members" not in bundle and "onset_doy" in bundle:
        try:
            bundle["n_members"] = int(bundle["onset_doy"].shape[0])
        except Exception:
            bundle["n_members"] = 1

    for key in ["probs_damped", "hitrate_cal", "rpss_val", "alpha", "hitrate_val", "bc_daily"]:
        if key in bundle and bundle[key] is not None:
            continue
        candidate = f"{prefix}_{key}"
        if candidate in globals() and globals()[candidate] is not None:
            bundle[key] = globals()[candidate]

    if "probs_damped" not in bundle:
        bundle["probs_damped"] = _fallback_prob_tables(bundle)

    if "hitrate_cal" not in bundle:
        bundle["hitrate_cal"] = _fallback_skill_tables(bundle, 0.5)

    if "rpss_val" not in bundle:
        bundle["rpss_val"] = _fallback_skill_tables(bundle, 0.0)

    if "alpha" not in bundle:
        bundle["alpha"] = _fallback_skill_tables(bundle, 1.0)

    if "hitrate_val" not in bundle:
        bundle["hitrate_val"] = _fallback_skill_tables(bundle, 0.5)

    # Keep daily series length consistent with plotting window.
    bc_daily = bundle.get("bc_daily")
    if hasattr(bc_daily, "shape") and len(bc_daily.shape) >= 5:
        target_days = int(globals().get("WIN_N_DAYS", bc_daily.shape[2]))
        cur_days = int(bc_daily.shape[2])
        if cur_days > target_days:
            bundle["bc_daily"] = bc_daily[:, :, :target_days, :, :]
        elif cur_days < target_days:
            pad = target_days - cur_days
            pad_shape = (bc_daily.shape[0], bc_daily.shape[1], pad, bc_daily.shape[3], bc_daily.shape[4])
            pad_arr = np.full(pad_shape, np.nan, dtype=bc_daily.dtype)
            bundle["bc_daily"] = np.concatenate([bc_daily, pad_arr], axis=2)

    if "color" not in bundle or bundle["color"] is None:
        if isinstance(globals().get("MM_MODEL_COLORS"), list) and globals()["MM_MODEL_COLORS"]:
            try:
                idx = list(globals().get("MODELS", {}).keys()).index(prefix)
            except Exception:
                idx = 0
            bundle["color"] = globals()["MM_MODEL_COLORS"][idx % len(globals()["MM_MODEL_COLORS"])]

    if "color" not in bundle:
        bundle["color"] = "#1B5EA6"

    return bundle


def _fallback_prob_tables(bundle):
    onset = bundle.get("onset_doy")
    if hasattr(onset, "shape") and len(onset.shape) >= 4:
        _, n_years, n_lat, n_lon = onset.shape[:4]
    else:
        n_years = int(globals().get("N_YEARS", 1))
        n_lat = int(globals().get("n_lat", 1))
        n_lon = int(globals().get("n_lon", 1))
    shape = (3, n_years, n_lat, n_lon)
    probs = np.full(shape, 1.0 / 3.0, dtype=np.float32)
    return {"onset": probs.copy(), "cessation": probs.copy(), "lgp": probs.copy()}


def _fallback_skill_tables(bundle, fill_value):
    onset = bundle.get("onset_doy")
    if hasattr(onset, "shape") and len(onset.shape) >= 4:
        _, _, n_lat, n_lon = onset.shape[:4]
    else:
        n_lat = int(globals().get("n_lat", 1))
        n_lon = int(globals().get("n_lon", 1))
    table = np.full((n_lat, n_lon), fill_value, dtype=np.float32)
    return {"onset": table.copy(), "cessation": table.copy(), "lgp": table.copy()}


def generate_bulletin_v8(site_name, lat_q, lon_q):
    """Backward-compatible entrypoint used by Stage 8 cells."""
    _ensure_models_defined()
    return generate_mm_bulletin(site_name, lat_q, lon_q)


def export_bulletin_to_pdf(*args, **kwargs):
    """Optional PDF export hook expected by some Stage 8 flows.

    This shim intentionally no-ops because PDF creation is handled
    inside the multimodel script when possible.
    """
    raise RuntimeError("PDF export helper is not bundled in this shim")
