import asyncio

import httpx
import pytest

from llmtop.api import create_app
from llmtop.client import decode_snapshot
from llmtop.core.runtime import Runtime


async def test_multi_client_reads_share_collector_and_history(config, raw_vllm):
    calls = []

    def source(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=raw_vllm if request.url.path == "/metrics" else "ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as engine:
        runtime = Runtime(config, client=engine)
        try:
            await runtime.poll()
            app = create_app(runtime, manage_runtime=False)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
            ) as client:
                replies = await asyncio.gather(*(client.get("/api/v1/snapshot") for _ in range(20)))
                assert len(calls) == 2
                assert {r.json()["snapshot_seq"] for r in replies} == {1}
                assert decode_snapshot(replies[0].content).runtime_id == runtime.runtime_id
                history = (
                    await client.get("/api/v1/history?id=service&metric=output_tps&limit=2")
                ).json()
                assert history["series"][0]["points"][0]["value"] is None
                assert (await client.get("/api/v1/capabilities")).status_code == 200
                assert (await client.get("/health")).json()["status"] == "ok"
        finally:
            await runtime.close()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/history?id=unregistered",
        "/api/v1/history?metric=secret",
        "/api/v1/history?limit=9999",
        "/api/v1/history?window=0",
    ],
)
async def test_history_rejects_unbounded_or_unknown_queries(config, path):
    runtime = Runtime(config, demo=True)
    try:
        await runtime.poll()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_runtime=False)),
            base_url="http://127.0.0.1:8787",
        ) as client:
            assert (await client.get(path)).status_code in {400, 422}
    finally:
        await runtime.close()


@pytest.mark.parametrize("headers", [{"Host": "evil.example"}, {"Origin": "https://evil.example"}])
async def test_local_host_and_origin_boundary(config, headers):
    runtime = Runtime(config, demo=True)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_runtime=False)),
            base_url="http://127.0.0.1:8787",
        ) as client:
            assert (await client.get("/api/v1/snapshot", headers=headers)).status_code == 403
            assert (await client.post("/api/v1/snapshot")).status_code == 405
            assert (await client.get("/api/v1/snapshot")).status_code == 503
    finally:
        await runtime.close()


async def test_stream_reset_cursor_and_cleanup(config):
    from starlette.requests import Request

    runtime = Runtime(config, demo=True)
    try:
        await runtime.poll()
        app = create_app(runtime, manage_runtime=False)
        route = next(r for r in app.routes if getattr(r, "path", "") == "/api/v1/events")

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {
                "type": "http",
                "headers": [(b"last-event-id", b"old-runtime:100")],
                "method": "GET",
                "path": "/api/v1/events",
            },
            receive=receive,
        )
        response = await route.endpoint(request)
        reset = await anext(response.body_iterator)
        snapshot = await anext(response.body_iterator)
        assert "event: reset" in reset
        assert f"id: {runtime.runtime_id}:1" in snapshot
        await response.body_iterator.aclose()
        assert not runtime.store.subscribers
    finally:
        await runtime.close()
