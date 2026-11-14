"""The assistant on the crop outlook page: evidence from the published crop outlook, the standard explanations
(number check), the chat's routing and the endpoints. The outlook changes daily, so the tests check structure and
consistency, not values."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOAD_BC_DAILY", "0")

import mam_loader as dl  # noqa: E402
from assistant import chat, crop, narrate  # noqa: E402

IX = crop._index()
SITES = list(IX["sites"])
RUNS = [r["id"] for r in IX["runs"]]


@pytest.fixture(scope="module", autouse=True)
def loaded():
    if not dl.is_loaded():
        dl.configure()
        dl.load()
    yield


@pytest.fixture(autouse=True)
def no_claude(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    narrate._cache.clear()


def test_site_matching():
    sid, s = crop.find_site(IX, "Kiboko")
    assert sid == "kalro_kiboko_makueni_farm"
    assert crop.find_site(IX, sid)[0] == sid
    assert crop.find_site(IX, None, s["lat"] + 0.05, s["lon"])[0] == sid
    with pytest.raises(ValueError, match="covers these sites only"):
        crop.find_site(IX, "Gondar", 12.6, 37.5)


@pytest.mark.parametrize("sid", SITES)
def test_every_outlook_is_consistent_and_checked(sid):
    n = 0
    for v in IX["varieties"]:
        for rule in IX["planting_rules"]:
            for run in RUNS:
                try:
                    rec = crop.outlook(sid, v, rule, run)
                except ValueError:
                    continue
                n += 1
                o = rec["outlook"]
                assert rec["kind"] == "crop" and rec["scope"]["site_id"] == sid and rec["crop"]["id"] == v
                assert 97 <= sum(o["outcomes_pct"].values()) <= 103
                ys = o["yield_if_sown_t_ha"]
                if ys and ys["median"] is not None:
                    assert ys["p10"] <= ys["median"] <= ys["p90"]
                for x in rec["other_crop_models"].values():
                    ag = x.get("agreement_with_aquacrop")
                    assert ag is None or 0 <= ag["same_verdict_pct"] <= 100
                assert "Experimental" in rec["caveats"][0]
                sec = narrate.TEMPLATES["crop"](rec)
                assert narrate.check_numbers(sec, rec) == [], (v, rule, run)
    assert n > 0


def test_disagreement_and_configuration_cautions():
    rec = crop.outlook("Kiboko", "maize_early")
    if rec["other_crop_models"]:
        name = next(iter(rec["other_crop_models"]))
        low = {**rec, "other_crop_models": {name: {**rec["other_crop_models"][name], "agreement_with_aquacrop": {"members_compared": 25, "same_verdict_pct": 60}}}}
        assert any("disagree" in c for c in crop._caveats(low, IX))
    if rec["since_previous_update"]:
        same = {**rec, "since_previous_update": {**rec["since_previous_update"], "same_crop_configuration": True}}
        assert not any("configuration changed" in c for c in crop._caveats(same, IX))


@pytest.mark.parametrize("sid", SITES)
def test_compare(sid):
    rec = crop.compare(sid)
    assert rec["rows"] and rec["kind"] == "crop_compare"
    assert rec["highest_maturity"]["matured_pct"] == max(r["matured_pct"] for r in rec["rows"] if r["matured_pct"] is not None)
    assert rec["lowest_failure"]["chance_of_failure_pct"] == min(r["chance_of_failure_pct"] for r in rec["rows"] if r["chance_of_failure_pct"] is not None)
    assert narrate.check_numbers(narrate.TEMPLATES["crop_compare"](rec), rec) == []


def test_chat_routes_to_the_crop_outlook():
    page = {"page": "crop", "crop_site": "kalro_kiboko_makueni_farm", "crop_variety": "sorghum", "crop_rule": None, "crop_run": None,
            "lat": -2.21046, "lon": 37.719}
    assert chat.route("What yield can I expect?", page="crop") == "crop"
    assert chat.route("Which crop is best here?", page="crop") == "crop_compare"
    assert chat.route("What maize yield is expected?") == "crop"
    assert chat.route("Which crop fits this season here?") == "advisory"           # the forecast tabs keep the card
    out = chat.reply([{"role": "user", "content": "What yield can I expect?"}], page)
    assert out["evidence"][0]["kind"] == "crop" and out["reply"].startswith("Sorghum")
    out = chat.reply([{"role": "user", "content": "And for beans?"}], page)
    assert out["reply"].startswith("Dry bean")


def test_endpoints():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        j = c.get("/explain/crop", params={"site": "Kiboko", "crop": "sorghum"}).json()
        assert j["kind"] == "crop" and j["evidence"]["crop"]["id"] == "sorghum" and j["explanation"]["sections"]["summary"]
        assert c.get("/explain/crop/compare", params={"site": "Kiboko"}).json()["kind"] == "crop_compare"
        assert c.get("/explain/crop", params={"site": "Nowhere"}).status_code == 404
        assert c.get("/explain/crop", params={"site": "Kiboko", "crop": "teff"}).status_code == 404
