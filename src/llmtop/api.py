from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from llmtop import __version__
from llmtop.core.models import utc_now
from llmtop.core.runtime import Runtime
from llmtop.core.store import HISTORY_METRICS


def event(kind: str, data: str, cursor: str | None = None) -> str:
    return (f"id: {cursor}\n" if cursor else "") + f"event: {kind}\ndata: {data}\n\n"


def create_app(runtime: Runtime, *, manage_runtime: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if manage_runtime:
            await runtime.start()
        try:
            yield
        finally:
            if manage_runtime:
                await runtime.close()

    app = FastAPI(
        title="LLMTOP read API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.runtime = runtime
    port = runtime.config.web.port
    hosts = {"127.0.0.1", "localhost", "::1"}
    origins = set(runtime.config.web.allowed_origins)
    origins.update({f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"})

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        try:
            host = urlsplit("http://" + request.headers.get("host", "")).hostname
        except ValueError:
            host = None
        if host not in hosts:
            return JSONResponse({"detail": "Host is not allowed"}, status_code=403)
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "Read-only API"}, status_code=405)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    def current():
        if runtime.store.current is None:
            raise HTTPException(503, runtime.last_error or "Collector is initializing")
        return runtime.store.current

    @app.get("/health")
    async def health():
        snapshot = runtime.store.current
        age = (utc_now() - snapshot.collected_at).total_seconds() if snapshot else None
        healthy = (
            snapshot is not None
            and age <= runtime.config.monitor.stale_after_seconds
            and not runtime.last_error
        )
        return JSONResponse(
            {
                "status": "ok" if healthy else "degraded",
                "version": __version__,
                "runtime_id": runtime.runtime_id,
                "snapshot_seq": snapshot.snapshot_seq if snapshot else None,
                "age_seconds": age,
                "reason": runtime.last_error,
            },
            status_code=200 if healthy else 503,
        )

    @app.get("/api/v1/snapshot")
    async def snapshot():
        current()
        return Response(runtime.store.serialized, media_type="application/json")

    @app.get("/api/v1/capabilities")
    async def capabilities():
        snap = current()
        return {
            "schema_version": 1,
            "runtime_id": snap.runtime_id,
            "snapshot_seq": snap.snapshot_seq,
            "services": [
                {
                    "id": s.id,
                    "engine": s.engine,
                    "engine_version": s.engine_version,
                    "version_verified": s.version_verified,
                    "capabilities": [c.model_dump() for c in s.capabilities],
                }
                for s in snap.services
            ],
            "hosts": [
                {"id": h.id, "scope": h.scope, "collector": h.collector, "reason": h.reason}
                for h in snap.hosts
            ],
        }

    @app.get("/api/v1/history")
    async def history(
        id: Annotated[list[str] | None, Query()] = None,
        metric: str = "output_tps",
        window: Annotated[int, Query(ge=1, le=86400)] = 600,
        limit: Annotated[int, Query(ge=1, le=1800)] = 300,
    ):
        snap = current()
        id = id or []
        known = {e.id for e in [*snap.services, *snap.hosts]}
        if len(id) > 32 or any(i not in known for i in id):
            raise HTTPException(400, "Unknown entity or too many IDs")
        if metric not in HISTORY_METRICS:
            raise HTTPException(400, "Metric is not available in history")
        return runtime.store.series(
            id or [s.id for s in snap.services],
            metric,
            min(window, runtime.config.monitor.history_seconds),
            limit,
        )

    @app.get("/api/v1/events")
    async def events(request: Request):
        current()
        try:
            queue = runtime.store.subscribe()
        except ValueError:
            raise HTTPException(503, "Maximum stream clients reached") from None

        async def stream():
            previous = request.headers.get("last-event-id")
            try:
                while not await request.is_disconnected():
                    try:
                        snap = await asyncio.wait_for(queue.get(), timeout=10)
                    except TimeoutError:
                        yield event(
                            "heartbeat",
                            json.dumps(
                                {
                                    "runtime_id": runtime.runtime_id,
                                    "timestamp": utc_now().isoformat(),
                                    "reason": runtime.last_error,
                                }
                            ),
                        )
                        continue
                    cursor = f"{snap.runtime_id}:{snap.snapshot_seq}"
                    if previous and previous != cursor:
                        try:
                            old_runtime, old_seq = previous.rsplit(":", 1)
                            reset = (
                                old_runtime != snap.runtime_id
                                or int(old_seq) != snap.snapshot_seq - 1
                            )
                        except ValueError:
                            reset = True
                        if reset:
                            yield event(
                                "reset",
                                json.dumps(
                                    {
                                        "runtime_id": snap.runtime_id,
                                        "reason": "Snapshot cursor changed; use latest snapshot",
                                    }
                                ),
                            )
                    if previous != cursor:
                        yield event("snapshot", snap.model_dump_json(), cursor)
                    previous = cursor
            finally:
                runtime.store.unsubscribe(queue)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    static = Path(__file__).parent / "web_static"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        if not (static / "index.html").is_file():
            return JSONResponse(
                {
                    "detail": "Web assets are not built. Run npm ci and npm run build in frontend before packaging."
                },
                status_code=503,
            )
        return FileResponse(static / "index.html")

    return app
