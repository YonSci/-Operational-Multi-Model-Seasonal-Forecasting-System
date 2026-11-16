"""
A site's measured growing conditions for the outlook itself (crop_engine/data/site_conditions.yaml): soil fertility,
weeds, salinity and the water table, each only where the site's managers or a soil test have reported it. The
outlook is water-limited on a free-draining, weed-free, non-saline soil until then; a site's entry makes its outlook,
its benchmark (the same crop in past seasons' weather) and its scenarios carry the reported condition, so each
forecast is still read against a normal grown the same way. AquaCrop only (adapters/aquacrop_adapter.with_conditions;
WOFOST and DSSAT do not read them).

The table, per site id (crop_engine.data.sites), any of:
  fertility    {"stress_pct": %} or {"stress_pct_by_crop": {AquaCrop crop: %}}: AquaCrop 7's soil fertility stress
               (adapters/aquacrop_stress.py), e.g. from a fertiliser trial's unfertilised yield
               (calibration/aquacrop_fertility.py)
  weeds        {"rc_pct": %, "weeding_das": [days after sowing], "efficacy_pct": %, "regrowth_days": d}: the weeds'
               relative cover at canopy closure and the farmers' weeding
  salinity     {"ece_initial": dS/m, "ecgw": dS/m}: the soil's ECe at the season's start (a soil test), a saline
               water table's ECgw
  groundwater  {"depth_m": m} or {"monthly_m": {month: m}}: a measured water table
and, for the record, "source" (who reported it, when) and "note". Nothing is filled in by default.

The engines' configuration hash includes only the conditions in effect (run_outlook.config_hash): an empty table
rebuilds nothing.
"""
from pathlib import Path

import yaml

TABLE_FILE = Path(__file__).with_name("site_conditions.yaml")
KEYS = ("fertility", "weeds", "salinity", "groundwater")


def _table(path=TABLE_FILE):
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("sites") or {}


def conditions(site_id, path=TABLE_FILE):
    """The site's conditions as AquaCrop task keys ({} without any)."""
    e = _table(path).get(site_id) or {}
    return {k: e[k] for k in KEYS if e.get(k)}


def in_effect(path=TABLE_FILE):
    """Every site's conditions in effect, for the configuration hash (empty: unchanged)."""
    return sorted((sid, sorted((k, repr(v)) for k, v in conditions(sid, path).items()))
                  for sid in _table(path) if conditions(sid, path))
