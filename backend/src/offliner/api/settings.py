from __future__ import annotations

from fastapi import APIRouter, HTTPException

from offliner.config import Settings
from offliner.db import load_settings, save_settings
from offliner.download.paths import TemplateError, validate_template

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings() -> Settings:
    return load_settings()


@router.put("")
def put_settings(new: Settings) -> Settings:
    try:
        validate_template(new.path_template)
    except TemplateError as e:
        raise HTTPException(400, f"Invalid path template: {e}") from e
    saved = save_settings(new)
    from offliner.jobs import queue

    queue.wake()
    return saved
