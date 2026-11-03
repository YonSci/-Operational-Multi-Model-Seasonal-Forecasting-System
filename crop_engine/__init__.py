"""
Crop Model Engine: crop growth, yield and risk from the platform's forecast rainfall ensembles.

Layers (see CROP_ENGINE.md):
  data/       standardized inputs: daily weather ensembles with per-day provenance, soil profiles, sites
  scenarios/  planting dates from the platform's onset methods
  adapters/   crop models (AquaCrop-OSPy first); each turns one member's inputs into crop outcomes
  run_outlook.py  the daily run: forecast runs × sites × varieties × planting rules, and the climatology benchmark

The engine reads the climate pipeline's outputs and never changes them; a failure here does not affect the forecasts.
"""
