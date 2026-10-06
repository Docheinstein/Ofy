"""Sync selection (artists / albums / tracks to keep on the remote) and sync runs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from ofy import sync
from ofy.db import SyncSelection, load_settings, session

router = APIRouter(prefix="/api/sync", tags=["sync"])

Kind = Literal["artist", "album", "track"]


@router.get("/selection")
def get_selection() -> list[SyncSelection]:
    with session() as s:
        return list(s.exec(select(SyncSelection).order_by(col(SyncSelection.kind), col(SyncSelection.title))).all())


class Toggle(BaseModel):
    kind: Kind
    id: str
    selected: bool
    title: str = ""
    subtitle: str = ""


@router.put("/selection")
def set_selection(body: Toggle) -> dict[str, Any]:
    with session() as s:
        row = s.get(SyncSelection, (body.kind, body.id))
        if body.selected and row is None:
            s.add(SyncSelection(kind=body.kind, ref_id=body.id, title=body.title, subtitle=body.subtitle))
        elif not body.selected and row is not None:
            s.delete(row)
        s.commit()
    return {"ok": True}


@router.get("/summary")
async def summary() -> dict[str, Any]:
    plan = await asyncio.to_thread(sync.build_plan, Path(load_settings().library_path))
    return {"tracks": plan.tracks, "files": len(plan.files), "bytes": plan.bytes,
            "pending": plan.pending, "outside": plan.outside}


@router.get("/status")
def status() -> dict[str, Any]:
    return sync.state.to_dict()


class RunRequest(BaseModel):
    dry_run: bool = False


@router.post("/run")
async def run(body: RunRequest) -> dict[str, Any]:
    try:
        sync.start(load_settings(), body.dry_run)
    except sync.SyncError as e:
        raise HTTPException(400, str(e)) from e
    return sync.state.to_dict()


@router.post("/cancel")
async def cancel() -> dict[str, Any]:
    return {"cancelled": sync.cancel()}


@router.post("/test")
async def test() -> dict[str, Any]:
    try:
        return await sync.test_connection(load_settings())
    except sync.SyncError as e:
        return {"ok": False, "message": str(e)}
