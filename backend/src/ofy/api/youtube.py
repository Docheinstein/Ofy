"""Downloading pasted YouTube links (a video or a playlist), matched to MusicBrainz first."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ofy import ytimport
from ofy.db import YTImport, session
from ofy.jobs import PermanentError
from ofy.mb.client import MusicBrainzError, NotFound

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


class ImportBody(BaseModel):
    url: str


@router.post("/import")
async def start(body: ImportBody) -> dict[str, Any]:
    try:
        return await ytimport.start_import(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:  # YouTube Music unreachable
        raise HTTPException(502, str(e)) from e


@router.get("/imports")
def imports() -> list[dict[str, Any]]:
    return ytimport.list_imports()


def _known(import_id: int) -> None:
    if ytimport.get_import(import_id) is None:
        raise HTTPException(404, "Unknown import")


class Choice(BaseModel):
    recording_id: str
    release_id: str | None = None


@router.post("/imports/{import_id}/match")
async def choose(import_id: int, body: Choice) -> dict[str, Any]:
    _known(import_id)
    try:
        imp = await ytimport.choose_recording(import_id, body.recording_id, body.release_id)
    except NotFound as e:
        raise HTTPException(404, "Not found on MusicBrainz") from e
    except (PermanentError, MusicBrainzError) as e:
        raise HTTPException(400 if isinstance(e, PermanentError) else 502, str(e)) from e
    return {"status": imp.status, "track_id": imp.track_id}


@router.post("/imports/{import_id}/retry")
def retry(import_id: int) -> dict[str, Any]:
    _known(import_id)
    ytimport.retry_import(import_id)
    return {"queued": 1}


@router.delete("/imports/{import_id}")
def remove(import_id: int) -> dict[str, Any]:
    with session() as s:
        imp = s.get(YTImport, import_id)
        if imp:
            s.delete(imp)
            s.commit()
    return {"ok": True}


@router.post("/imports/clear")
def clear() -> dict[str, Any]:
    return {"removed": ytimport.clear_finished()}
