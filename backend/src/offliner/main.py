"""FastAPI application: JSON API under /api, WebSocket at /api/ws, SPA served from /."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from offliner import __version__
from offliner.api import settings as settings_api
from offliner.config import env
from offliner.db import get_engine, recover_interrupted_jobs
from offliner.events import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("offliner")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()
    hub.bind_loop(asyncio.get_running_loop())
    env.tmp_dir.mkdir(parents=True, exist_ok=True)
    env.cover_cache_dir.mkdir(parents=True, exist_ok=True)
    n = recover_interrupted_jobs()
    if n:
        log.info("Recovered %d interrupted jobs", n)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Offliner", version=__version__, lifespan=lifespan)
    app.include_router(settings_api.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = hub.subscribe()
        try:
            while True:
                msg = await q.get()
                await websocket.send_text(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.unsubscribe(q)

    _mount_spa(app, env.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)


app = create_app()
