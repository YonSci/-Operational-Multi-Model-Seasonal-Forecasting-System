"""Advisory cards: the draft rule library, option evaluation from the crop outlook, and /explain/advisory.

Uses the demo dataset and the crop outlook published in frontend/public/tracker/data/crop.
"""
import datetime as dt
import os
import string
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import advisory, crop_data, narrate  # noqa: E402

KIBOKO = (-2.21046, 37.7190)
FAO = "ECMWF SEAS5 (Oct+Obs latest) - FAO water balance (agricultural)"
EARLY = dt.date(2026, 9, 1)           # before every modelled sowing: no option is past


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    if not crop_data.load("index.json") or not crop_data.load("scenarios.json"):
        pytest.skip("crop outlook files not available")
    yield


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()


def test_library_is_consistent_and_all_draft():
    lib = advisory.library()
    known = set(lib["decisions"])
    ids = [r["id"] for r in lib["rules"]]
    assert len(ids) == len(set(ids))
    for r in lib["rules"]:
        assert r["decision"] in known, r["id"]
        assert r.get("status") in ("draft", "reviewed"), r["id"]
        if r.get("status") == "reviewed":
            assert r.get("reviewed_by") and r.get("sources"), r["id"]
    for d in lib["decisions"].values():
        for k in d.get("scenario_options") or []:
            assert k in lib["scenarios"], k
    for o in lib["objectives"].values():
        assert o["better"] in ("higher", "lower")


def test_rule_placeholders_are_known_context_fields():
    """A reviewer editing advisory_rules.yaml can only use fields the evidence provides."""
    from assistant import evidence as ev
    lib = advisory.library()
    rec_txt = set()
    loc = ev.location(*KIBOKO, "short_rains", FAO)
    crop = advisory._crop(*KIBOKO, "maize_early", "fao-agricultural")
    for prof in ({"decision": "sowing", "planted": "no"}, {"decision": "establishment", "planted": "yes", "sowing_date": "2026-10-29"}):
        _, txt = advisory.context(loc, advisory.normalise(prof, lib), crop, "maize_early")
        rec_txt |= set(txt)
    # the chance keys exist for every third; the context names them p_<quantity>_<third>_pct
    rec_txt |= {f"p_{q}_{c}_pct" for q, cs in (("onset", ("early", "normal", "late")), ("cessation", ("early", "normal", "late")),
                                               ("lgp", ("short", "normal", "long"))) for c in cs}
    rec_txt |= {"onset_range_days", "onset_rpss", "cessation_most_likely", "onset_most_likely", "lgp_most_likely"}
    for r in lib["rules"]:
        for f in ("assessment", "why", "could_change", "review"):
            names = {n for _, n, _, _ in string.Formatter().parse(r.get(f) or "") if n}
            assert names <= rec_txt, (r["id"], f, names - rec_txt)
        for c in r.get("when") or []:
            assert c["key"] in rec_txt | {"planted"}, (r["id"], c["key"])


def test_sowing_card_ranks_options_and_keeps_the_reference():
    card = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "sowing", "planted": "no", "objective": "maturity"}, today=EARLY)
    assert card["status"] == "draft" and card["crop_outlook"]["available"]
    opts = card["options"]
    assert any(o.get("is_baseline") for o in opts)
    ranked = [o for o in opts if o["rank"]]
    vals = [o["p_mature_pct"] for o in ranked if o["p_mature_pct"] is not None]
    assert vals == sorted(vals, reverse=True)
    assert card["best_for_objective"] == ranked[0]["label"]
    assert any("Draft guidance" in c for c in card["caveats"])
    assert all(r["status"] == "draft" for r in card["rules_used"])


def test_past_sowing_options_are_reference_only():
    late = dt.date(2026, 11, 13)
    card = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "sowing", "planted": "no"}, today=late)
    past = [o for o in card["options"] if o.get("past")]
    assert past and all(o["rank"] is None and o["sowing_median"] < "2026-11-13" for o in past)
    assert all(not o.get("past") for o in card["options"] if o["rank"])
    ref = next(o for o in card["options"] if o.get("is_baseline"))
    if ref["sowing_median"] < "2026-11-13":                       # a past reference is not the best option
        assert ref["rank"] is None and card["best_for_objective"] != ref["label"]
    assert any("before today" in c for c in card["caveats"])


def test_objective_changes_the_order():
    a = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "water", "objective": "yield"}, today=EARLY)
    b = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "water", "objective": "water"}, today=EARLY)
    assert a["options"][0]["yield_median"] == max(o["yield_median"] for o in a["options"])
    assert (b["options"][0]["irrigation_mm"] or 0) == min(o["irrigation_mm"] or 0 for o in b["options"])


def test_crop_choice_and_replanting_options():
    c = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "crop_choice", "crop": "maize_early"}, today=EARLY)
    assert {o["variety"] for o in c["options"]} >= {"maize_early", "sorghum"}
    r = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "replanting", "planted": "yes"}, today=EARLY)
    assert all(o["scenario"] in ("sow_plus14", "sow_plus28") for o in r["options"])


def test_far_from_crop_sites_gives_climate_only_card():
    card = advisory.card(0.5, 35.0, "short_rains", FAO, {"decision": "sowing"})
    assert card["options"] == [] and not card["crop_outlook"]["available"]
    assert "km away" in card["crop_outlook"]["reason"]


def test_advisory_template_passes_the_number_check():
    for dec in ("sowing", "crop_choice", "establishment", "replanting", "water"):
        card = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": dec, "planted": "yes" if dec in ("establishment", "replanting") else "no"}, today=EARLY)
        out = narrate.explain("advisory", card)
        assert out["source"] == "template"
        assert narrate.check_numbers(out["sections"], card) == [], dec


def test_advisory_endpoint():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        r = c.get("/explain/advisory", params={"lat": KIBOKO[0], "lon": KIBOKO[1], "season": "short_rains", "model": FAO,
                                               "decision": "water", "crop": "sorghum", "objective": "downside"})
        assert r.status_code == 200
        j = r.json()
        assert j["evidence"]["kind"] == "advisory" and j["evidence"]["options"]
        assert j["evidence"]["profile"]["crop"] == "sorghum"


def test_scenarios_of_another_configuration_are_not_used(monkeypatch):
    real = crop_data.load
    scen = real("scenarios.json")
    stale = {**scen, "meta": {**scen["meta"], "config_hash": "not-the-current-one"}}
    monkeypatch.setattr(crop_data, "load", lambda n: stale if n == "scenarios.json" else
                        ({"seasonal": {"current_config": "current-hash"}} if n == "skill.json" else real(n)))
    water = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "water"}, today=EARLY)
    assert water["options"] == []
    assert any("being rebuilt" in c for c in water["caveats"])
    choice = advisory.card(*KIBOKO, "short_rains", FAO, {"decision": "crop_choice"}, today=EARLY)
    assert choice["options"]                                   # crops sown by the rule come from the outlook itself


def test_scenarios_check():
    run = {"id": "seasonal_20261001"}
    assert advisory.scenarios_current({"meta": {"id": "seasonal_20261001"}}, run) in (True, False)
    assert advisory.scenarios_current({"meta": {"id": "seasonal_20260901"}}, run) is False
