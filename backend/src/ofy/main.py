"""FastAPI application: JSON API under /api, WebSocket at /api/ws, SPA served from /."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from ofy import __version__
from ofy.api import actions as actions_api
from ofy.api import browse as browse_api
from ofy.api import settings as settings_api
from ofy.api import stream as stream_api
from ofy.api import sync as sync_api
from ofy.config import env
from ofy.db import get_engine, recover_interrupted_jobs
from ofy.events import hub
from ofy.jobs import queue
from ofy.pipeline import register_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ofy")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()
    hub.bind_loop(asyncio.get_running_loop())
    env.tmp_dir.mkdir(parents=True, exist_ok=True)
    env.cover_cache_dir.mkdir(parents=True, exist_ok=True)
    n = recover_interrupted_jobs()
    if n:
        log.info("Recovered %d interrupted jobs", n)
    register_handlers()
    if env.scan_on_startup:
        app.state.scan_task = asyncio.create_task(_startup_scan())
    if env.start_workers:
        queue.start()
    yield
    await queue.stop()


async def _startup_scan() -> None:
    from ofy.library.scanner import scan_library

    try:
        await asyncio.to_thread(scan_library)
    except Exception:
        log.exception("startup library scan failed")


def create_app() -> FastAPI:
    app = FastAPI(title="Ofy", version=__version__, lifespan=lifespan)
    app.include_router(settings_api.router)
    app.include_router(browse_api.router)
    app.include_router(actions_api.router)
    app.include_router(stream_api.router)
    app.include_router(sync_api.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__, "data_dir": str(env.data_dir)}

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
            # Vite puts content hashes in asset names, so they can be cached forever.
            immutable = full_path.startswith("assets/")
            return FileResponse(candidate, headers={
                "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        if index.is_file():
            # Always revalidate the entry point so a rebuilt UI shows up immediately (webviews cache hard).
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)


app = create_app()
