"""Reviewed method notes the assistant explains from (condensed from the About tab).

These texts are the assistant's documentation: the system prompt quotes them, and the template explanations use the
same wording. Keep them in step with frontend/src/components/AboutTab.jsx when a method changes.
"""

SEASON_LABELS = {
    "short_rains": ("Short Rains (OND)", "Kenya"),
    "long_rains": ("Long Rains (MAM)", "Kenya"),
    "kiremt": ("Kiremt (JJAS)", "Ethiopia"),
    "belg": ("Belg (FMAM)", "Ethiopia"),
    "fmam": ("Belg (FMAM)", "Ethiopia"),
    "bega": ("Bega (ONDJ)", "Ethiopia"),
    "ondj": ("Bega (ONDJ)", "Ethiopia"),
    "deyr": ("Deyr/Hagaya (SON-OND)", "Ethiopia"),
    "gu": ("Gu/Ganna (MAM)", "Ethiopia"),
    "annual": ("Annual wet season", "Ethiopia"),
}

# Onset / cessation methods, keyed by the suffix of the platform's model name (" - Agri rule 1", ...)
METHODS = {
    "dunning": {
        "label": "Dunning",
        "family": "Rainfall pattern",
        "question": "When does the season's rainfall regime change?",
        "onset": "the turning point of the accumulated rainfall anomaly (Dunning et al. 2016)",
        "cessation": "the second turning point of the same curve",
        "data": "CHIRPS v2 rainfall; ECMWF SEAS5 members bias-corrected to CHIRPS",
    },
    "agri rule 1": {
        "label": "Agri rule 1",
        "family": "First planting rains",
        "question": "When is it safe to plant?",
        "onset": "a wet day (1 mm or more) starting more than 20 mm in 3 days, with no dry spell of 7 days or more in the next 21",
        "cessation": "after a 10-day period with rain below half the potential evapotranspiration, the day a 100 mm soil store is empty",
        "data": "CHIRPS v2, ECMWF SEAS5, Hargreaves PET; adapted from ICPAC's operational definitions",
    },
    "agri rule 2": {
        "label": "Agri rule 2",
        "family": "First planting rains",
        "question": "When is it safe to plant?",
        "onset": "20 mm or more in 5 days with at least 3 rainy days, no dry spell longer than 7 days in the next 21",
        "cessation": "as Agri rule 1",
        "data": "CHIRPS v2, ECMWF SEAS5, Hargreaves PET; adapted from ICPAC's operational definitions",
    },
    "agri rule 3": {
        "label": "Agri rule 3",
        "family": "First planting rains",
        "question": "When is it safe to plant?",
        "onset": "more than 20 mm in 3 days, no dry spell longer than 10 days in the next 30",
        "cessation": "the first day of a 10-day period with rain below half the potential evapotranspiration",
        "data": "CHIRPS v2, ECMWF SEAS5, Hargreaves PET; adapted from ICPAC's operational definitions",
    },
    "fao water balance (agricultural)": {
        "label": "FAO water balance (agricultural)",
        "family": "Soil water for the crop",
        "question": "When does the root zone hold enough water for the crop?",
        "onset": "10-day rain at least half the reference evapotranspiration and plant-available water at least 20% of capacity for 5 days, with no 7-day spell below 20% in the next 21",
        "cessation": "7 days with soil water below 20%, crop water use below half its need and a 10-day rain deficit",
        "data": "CHIRPS v3, ERA5-Land reference evapotranspiration (FAO-56), SoilGrids, ECMWF SEAS5",
    },
    "fao water balance (rainfall)": {
        "label": "FAO water balance (rainfall)",
        "family": "Soil water for the crop",
        "question": "When does rain first meet half the evaporation demand?",
        "onset": "the first wet day from which 10-day rain reaches half the reference evapotranspiration",
        "cessation": "10-day rain below half the reference evapotranspiration for two consecutive dekads",
        "data": "CHIRPS v3, ERA5-Land reference evapotranspiration, ECMWF SEAS5",
    },
    "fao water balance (cropwater)": {
        "label": "FAO water balance (crop-water)",
        "family": "Soil water for the crop",
        "question": "When does rain stop covering the crop's water need?",
        "onset": "as the agricultural definition",
        "cessation": "after the rainfall peak, 21-day rain below half the crop's water need with soil water falling below 20%",
        "data": "CHIRPS v3, ERA5-Land, SoilGrids, ECMWF SEAS5",
    },
}

QUANTITIES = {
    "onset": {"label": "Onset", "what": "when the rains start", "unit": "date", "cats": ("early", "normal", "late")},
    "cessation": {"label": "Cessation", "what": "when the rains end", "unit": "date", "cats": ("early", "normal", "late")},
    "lgp": {"label": "Season length (LGP)", "what": "the days between onset and cessation", "unit": "days",
            "cats": ("short", "normal", "long")},
}

# Map layers (the /grid "layer" parameter): what the colour shows, and the usual misreading
LAYERS = {
    "median": ("the median of the forecast members", None),
    "anomaly": ("the forecast median minus the observed normal of the calibration years, in days (negative: earlier or shorter)",
                "An anomaly is a shift in the median, not a certainty: check the chances and the spread."),
    "spread": ("the spread between the members (the width of the forecast range)",
               "A wide spread means the members disagree; it is not a forecast of variability within the season."),
    "prob_bn": ("the chance of the lower third (early onset or cessation, short season)",
                "A 50% chance of the lower third means the event falls in that third one time in two; it is not 50% earlier."),
    "prob_nn": ("the chance of the middle third (near-normal)", None),
    "prob_an": ("the chance of the upper third (late onset or cessation, long season)",
                "A 50% chance of the upper third means the event falls in that third one time in two; it is not 50% later."),
    "tercile": ("the most likely third (lower, middle or upper)",
                "The most likely third can still be less likely than the other two together."),
    "failure": ("the share of members with no onset found in the search window", None),
    "rpss_val": ("the ranked probability skill score on the validation years (above 0 beats climatology)", None),
    "hitrate_val": ("the hit rate on the validation years (above 0.33 beats chance)", None),
    "alpha": ("the skill weight used to damp the chances toward one in three", None),
    "hr_weighted": ("the hit-rate-weighted multi-model value", None),
    "rpss_weighted": ("the RPSS-weighted multi-model value", None),
    "chirps_p50": ("the observed 1993-2025 median (CHIRPS)", None),
    "chirps_spread": ("the observed year-to-year spread (CHIRPS)", None),
    "bias": ("the forecast's bias against the observed record", None),
    "detection_rate": ("how often the forecast found an onset when one was observed", None),
}

GLOSSARY = [
    ("Terciles", "The observed record of the calibration years (1993-2016; 1981-2016 for the Kenya Long Rains) is split "
     "into thirds at each grid cell: early, normal and late (short, normal and long for season length). Climatology "
     "gives each third a one-in-three chance."),
    ("Skill-weighted chances", "The chances shown are alpha x the members' chance + (1 - alpha) x 1/3, where alpha is "
     "the forecast's skill weight at that place, fitted on the hindcasts of the calibration years. Low skill pulls every chance toward one in three, so 25 agreeing "
     "members can still show a chance well below 100%."),
    ("Median and range", "The median is the middle member's date; the 8-in-10 range holds the middle 80% of members. "
     "A median date is not a promise of rain on that day."),
    ("No onset", "A member with no onset in the search window found no qualifying start of the rains."),
    ("Estimated from observations so far", "When most members' onset falls within the observed period, the date comes "
     "from observed rain, not from the forecast; it can still change as later rain arrives under some methods."),
    ("Hit rate", "How often the most likely third was the one observed on the validation years (2017-2024); picking at random "
     "scores 0.33."),
    ("RPSS", "Ranked probability skill score on the independent validation years (2017-2024): above 0 beats climatology, 0 is no "
     "better, below 0 is worse."),
    ("Methods", "The onset methods answer different questions (rainfall pattern, first planting rains, soil water "
     "for the crop), so their dates are not interchangeable."),
]


def method_of(model_name: str) -> dict:
    """The onset method of a platform model name ("... - Agri rule 1" etc.); Dunning when there is no suffix."""
    low = (model_name or "").lower()
    for key in sorted(METHODS, key=len, reverse=True):
        if key != "dunning" and low.endswith(" - " + key):
            return {"id": key, **METHODS[key]}
    return {"id": "dunning", **METHODS["dunning"]}


def reference_text() -> str:
    """The method notes and glossary as plain text, for the system prompt."""
    lines = ["GLOSSARY"]
    lines += [f"- {k}: {v}" for k, v in GLOSSARY]
    lines.append("\nONSET AND CESSATION METHODS")
    for m in METHODS.values():
        lines.append(f"- {m['label']} ({m['family']}; answers: {m['question']}) Onset: {m['onset']}. "
                     f"Cessation: {m['cessation']}. Data: {m['data']}.")
    lines.append("\nMAP LAYERS")
    for k, (what, misread) in LAYERS.items():
        lines.append(f"- {k}: {what}." + (f" Misreading to avoid: {misread}" if misread else ""))
    return "\n".join(lines)
