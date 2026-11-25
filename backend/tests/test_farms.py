"""Saved farms, the farm diary and the farm crop runs' queue (assistant/farms.py, kenya_api/farms.py)."""
import datetime as dt
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from assistant import farms, store  # noqa: E402
from kenya_api import farms as farms_api  # noqa: E402

D_LAT = 200 / 111195
D_LON = 250 / (111195 * math.cos(math.radians(-2.21)))
SQUARE = {"type": "Polygon", "coordinates": [[[37.70, -2.21], [37.70 + D_LON, -2.21], [37.70 + D_LON, -2.21 + D_LAT],
                                              [37.70, -2.21 + D_LAT]]]}          # 5 ha, ring not closed
SPEC = {"name": "Kiboko test", "geometry": SQUARE, "crop": "maize_early", "consent": True}
TODAY = dt.date.today()
SOWN = (TODAY - dt.timedelta(days=20)).isoformat()


def test_geometry_is_checked_and_measured():
    g = farms.check_geometry(SQUARE)
    assert abs(g["area_ha"] - 5.0) < 0.01
    assert g["geometry"]["coordinates"][0][0] == g["geometry"]["coordinates"][0][-1]          # closed
    assert abs(g["lat"] + 2.2091) < 1e-3 and abs(g["lon"] - 37.7011) < 1e-3
    with pytest.raises(ValueError, match="longitude and latitude"):
        farms.check_geometry({"type": "Polygon", "coordinates": [[[250000, 9750000], [250100, 9750000], [250100, 9750100], [250000, 9750000]]]})
    with pytest.raises(ValueError, match="at most"):
        farms.check_geometry({"type": "Polygon", "coordinates": [[[37, -2], [37.2, -2], [37.2, -1.8], [37, -1.8], [37, -2]]]})
    with pytest.raises(ValueError):
        farms.check_geometry({"type": "Point", "coordinates": [37, -2]})


def test_saving_needs_consent_and_the_key():
    with pytest.raises(ValueError, match="consent"):
        farms.create({**SPEC, "consent": False})
    f = farms.create(SPEC)
    got = farms.get(f["id"], f["key"])
    assert got["farm"]["name"] == "Kiboko test" and "key_hash" not in got["farm"]
    assert got["diary"] == [] and got["simulation"] is None and got["season"] is None
    with pytest.raises(PermissionError):
        farms.get(f["id"], "not-the-key")
    row = store.select(farms.TABLE, eq={"id": f["id"]})[0]
    assert row["key_hash"] != f["key"] and len(row["key_hash"]) == 64


def test_diary_entries_are_validated():
    f = farms.create(SPEC)
    with pytest.raises(ValueError, match="entry_type"):
        farms.add_entry(f["id"], f["key"], {"entry_type": "party", "date": SOWN})
    with pytest.raises(ValueError, match="mm is required"):
        farms.add_entry(f["id"], f["key"], {"entry_type": "irrigation", "date": SOWN, "payload": {}})
    with pytest.raises(ValueError, match="out of range"):
        farms.add_entry(f["id"], f["key"], {"entry_type": "irrigation", "date": SOWN, "payload": {"mm": 900}})
    with pytest.raises(ValueError, match="crop must be one of"):
        farms.add_entry(f["id"], f["key"], {"entry_type": "sowing", "date": SOWN, "payload": {"crop": "coffee"}})
    future = (TODAY + dt.timedelta(days=30)).isoformat()
    with pytest.raises(ValueError, match="once it has happened"):
        farms.add_entry(f["id"], f["key"], {"entry_type": "harvest", "date": future, "payload": {"yield_t_ha": 2}})
    e = farms.add_entry(f["id"], f["key"], {"entry_type": "sowing", "date": future, "payload": {"crop": "sorghum"}})   # planned
    assert e["entry_date"] == future and e["payload"] == {"crop": "sorghum"}


def test_season_inputs_and_queue():
    f = farms.create(SPEC)
    other = farms.create({**SPEC, "name": "not sown"})
    off = farms.create({**SPEC, "name": "no runs", "simulate": False})
    for fid, key in ((f["id"], f["key"]), (off["id"], off["key"])):
        farms.add_entry(fid, key, {"entry_type": "sowing", "date": SOWN, "payload": {"crop": "maize_medium"}})
    farms.add_entry(f["id"], f["key"], {"entry_type": "irrigation", "date": TODAY.isoformat(), "payload": {"mm": 25}})
    farms.add_entry(f["id"], f["key"], {"entry_type": "fertiliser", "date": SOWN, "payload": {"n_kg_ha": 40, "product": "CAN"}})
    farms.add_entry(f["id"], f["key"], {"entry_type": "fertiliser", "date": SOWN, "payload": {"product": "manure"}})   # no N: left out
    s = farms.get(f["id"], f["key"])["season"]
    assert s["sowing_date"] == SOWN and s["crop"] == "maize_medium" and not s["harvested"]
    assert s["irrigation"] == [{"date": TODAY.isoformat(), "mm": 25.0}] and s["nitrogen"] == [{"date": SOWN, "kg_ha": 40.0}]
    q = {x["id"]: x for x in farms.queue()}
    assert f["id"] in q and other["id"] not in q and off["id"] not in q
    assert q[f["id"]]["lat"] == farms.get(f["id"], f["key"])["farm"]["lat"]
    # a harvest ends the season's runs
    farms.add_entry(f["id"], f["key"], {"entry_type": "harvest", "date": TODAY.isoformat(), "payload": {"yield_t_ha": 3.1}})
    assert f["id"] not in {x["id"] for x in farms.queue()}


def test_simulations_keep_the_latest_and_deleting_removes_everything():
    f = farms.create(SPEC)
    farms.add_entry(f["id"], f["key"], {"entry_type": "sowing", "date": SOWN, "payload": {"crop": "bean"}})
    farms.post_simulation(f["id"], {"p_failure": 0.4}, {"sowing_date": SOWN})
    farms.post_simulation(f["id"], {"p_failure": 0.3}, {"sowing_date": SOWN})
    assert len(store.select(farms.SIMS, eq={"farm_id": f["id"]})) == 1
    assert farms.get(f["id"], f["key"])["simulation"]["result"] == {"p_failure": 0.3}
    with pytest.raises(PermissionError):
        farms.post_simulation("no-such-farm", {}, {})
    farms.remove(f["id"], f["key"])
    for t in (farms.TABLE, farms.DIARY, farms.SIMS):
        assert not [r for r in store.select(t, limit=5000) if f["id"] in (r.get("id"), r.get("farm_id"))]


def test_http_routes(monkeypatch):
    monkeypatch.setenv("FARM_BATCH_TOKEN", "batch-secret")
    app = FastAPI()
    app.include_router(farms_api.router, prefix="/farms")
    c = TestClient(app)
    assert "sowing" in c.get("/farms/status").json()["entry_types"]
    assert c.post("/farms", json={**SPEC, "consent": False}).status_code == 400
    f = c.post("/farms", json=SPEC).json()
    h = {"X-Farm-Key": f["key"]}
    assert c.get(f"/farms/{f['id']}", headers={"X-Farm-Key": "wrong"}).status_code == 404
    e = c.post(f"/farms/{f['id']}/diary", headers=h, json={"entry_type": "sowing", "date": SOWN, "payload": {"crop": "maize_early"}}).json()
    assert c.post(f"/farms/{f['id']}/edit", headers=h, json={"patch": {"name": "Renamed"}}).json()["name"] == "Renamed"
    assert c.get("/farms/batch/queue").status_code == 401
    q = c.get("/farms/batch/queue", headers={"X-Batch-Token": "batch-secret"}).json()
    assert [x["id"] for x in q] == [f["id"]]
    r = c.post(f"/farms/batch/{f['id']}/simulation", headers={"X-Batch-Token": "batch-secret"},
               json={"result": {"p_failure": 0.2}, "inputs": q[0]})
    assert r.status_code == 200
    got = c.get(f"/farms/{f['id']}", headers=h).json()
    assert got["simulation"]["result"]["p_failure"] == 0.2 and len(got["diary"]) == 1
    assert c.delete(f"/farms/{f['id']}/diary/{e['id']}", headers=h).status_code == 200
    assert c.delete(f"/farms/{f['id']}", headers=h).status_code == 200
    assert c.get(f"/farms/{f['id']}", headers=h).status_code == 404
