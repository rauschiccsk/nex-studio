"""Tests for the pipeline WS registry + WS auth (CR-NS-018 Phase 3)."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.routes.pipeline import router as pipeline_router
from backend.services.pipeline_ws import PipelineWsRegistry


class _FakeWS:
    def __init__(self, fail=False):
        self.received = []
        self.fail = fail

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("socket closed")
        self.received.append(data)


# ── registry ──────────────────────────────────────────────────────────────────


async def test_registry_connect_broadcast_disconnect():
    reg = PipelineWsRegistry()
    vid = uuid.uuid4()
    uid = uuid.uuid4()
    ws = _FakeWS()

    await reg.connect(vid, ws, uid)
    assert reg.present_director_ids(vid) == {uid}

    await reg.broadcast(vid, {"type": "state_changed"})
    assert ws.received == [{"type": "state_changed"}]

    await reg.disconnect(vid, ws)
    assert reg.present_director_ids(vid) == set()


async def test_broadcast_prunes_dead_socket():
    reg = PipelineWsRegistry()
    vid = uuid.uuid4()
    good = _FakeWS()
    dead = _FakeWS(fail=True)
    await reg.connect(vid, good, uuid.uuid4())
    await reg.connect(vid, dead, uuid.uuid4())

    await reg.broadcast(vid, {"type": "x"})  # must not raise

    assert good.received == [{"type": "x"}]
    # dead socket pruned
    present = reg.present_director_ids(vid)
    assert len(present) == 1


async def test_present_director_ids_multi_director():
    reg = PipelineWsRegistry()
    vid = uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    await reg.connect(vid, _FakeWS(), a)
    await reg.connect(vid, _FakeWS(), b)
    assert reg.present_director_ids(vid) == {a, b}


# ── WS auth ───────────────────────────────────────────────────────────────────


def test_ws_bad_token_closes_4003():
    app = FastAPI()
    app.include_router(pipeline_router, prefix="/api/v1/pipeline")
    with TestClient(app) as c:
        try:
            with c.websocket_connect(f"/api/v1/pipeline/ws/{uuid.uuid4()}?token=garbage"):
                pass
            raise AssertionError("expected the WS to be rejected before accept")
        except WebSocketDisconnect as exc:
            assert exc.code == 4003
