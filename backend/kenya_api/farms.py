"""/farms/*  --  saved farms and the farm diary (assistant/farms.py), and the daily farm crop runs' queue.

A farm is anonymous: saving one returns its id and a private key; the dashboard keeps both in the browser and sends
the key (header X-Farm-Key) to read, change or delete the farm and its diary. The daily update's farm crop runs read
the queue and post results with the batch token (header X-Batch-Token = FARM_BATCH_TOKEN).
"""
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from assistant import farms

router = APIRouter()


def _call(fn, *a):
    try:
        return fn(*a)
    except PermissionError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:                              # storage errors (e.g. the farm tables not created yet)
        raise HTTPException(503, f"farm storage unavailable: {str(e)[:200]}")


def _batch(token):
    want = os.environ.get("FARM_BATCH_TOKEN", "")
    if not want or not token or not hmac.compare_digest(str(token), want):
        raise HTTPException(401, "Batch token required")


@router.get("/status")
def status():
    """Diary entry types and their fields, the crops, and whether farms are stored permanently."""
    return farms.schema()


class FarmIn(BaseModel):
    name: str = ""
    geometry: dict
    crop: str | None = None
    simulate: bool = True
    country: str = "kenya"
    consent: bool = False


@router.post("")
def create(body: FarmIn):
    return _call(farms.create, body.model_dump())


@router.get("/batch/queue")
def queue(x_batch_token: str = Header(None)):
    """Farms to simulate in the daily farm crop runs (batch token)."""
    _batch(x_batch_token)
    return _call(farms.queue)


class SimIn(BaseModel):
    result: dict
    inputs: dict


@router.post("/batch/{fid}/simulation")
def simulation(fid: str, body: SimIn, x_batch_token: str = Header(None)):
    """A farm crop run's result (batch token); replaces the previous one."""
    _batch(x_batch_token)
    return _call(farms.post_simulation, fid, body.result, body.inputs)


@router.get("/{fid}")
def get(fid: str, x_farm_key: str = Header(...)):
    """The farm, its diary, this season's crop-run inputs and the latest crop run."""
    return Response(content=json.dumps(_call(farms.get, fid, x_farm_key), default=str), media_type="application/json")


class EditIn(BaseModel):
    patch: dict


@router.post("/{fid}/edit")
def edit(fid: str, body: EditIn, x_farm_key: str = Header(...)):
    return _call(farms.edit, fid, x_farm_key, body.patch)


@router.delete("/{fid}")
def delete(fid: str, x_farm_key: str = Header(...)):
    _call(farms.remove, fid, x_farm_key)
    return {"id": fid, "status": "deleted"}


class EntryIn(BaseModel):
    entry_type: str
    date: str
    payload: dict = {}


@router.post("/{fid}/diary")
def add_entry(fid: str, body: EntryIn, x_farm_key: str = Header(...)):
    return _call(farms.add_entry, fid, x_farm_key, body.model_dump())


@router.delete("/{fid}/diary/{eid}")
def remove_entry(fid: str, eid: str, x_farm_key: str = Header(...)):
    _call(farms.remove_entry, fid, x_farm_key, eid)
    return {"id": eid, "status": "deleted"}
