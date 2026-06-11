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


# ── E6 presence: away flag + active_director_ids (CR-NS-038) ──────────────────


async def test_registry_set_away_and_active_director_ids():
    reg = PipelineWsRegistry()
    vid, uid = uuid.uuid4(), uuid.uuid4()
    ws = _FakeWS()
    await reg.connect(vid, ws, uid)
    assert reg.present_director_ids(vid) == {uid} and reg.active_director_ids(vid) == {uid}

    await reg.set_away(vid, ws, True)
    assert reg.present_director_ids(vid) == {uid}  # raw presence UNCHANGED (still on the board)
    assert reg.active_director_ids(vid) == set()  # but away → not active (the ping will fire)

    await reg.set_away(vid, ws, False)
    assert reg.active_director_ids(vid) == {uid}  # toggled back → active again


async def test_registry_active_excludes_only_the_away_connection():
    reg = PipelineWsRegistry()
    vid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    wa, wb = _FakeWS(), _FakeWS()
    await reg.connect(vid, wa, a)
    await reg.connect(vid, wb, b)
    await reg.set_away(vid, wa, True)
    assert reg.present_director_ids(vid) == {a, b}
    assert reg.active_director_ids(vid) == {b}  # only the non-away connection is active


async def test_registry_set_away_noop_on_unknown_socket():
    reg = PipelineWsRegistry()
    vid = uuid.uuid4()
    await reg.set_away(vid, _FakeWS(), True)  # never connected → no-op, no raise
    assert reg.active_director_ids(vid) == set()


async def test_apply_ws_presence_frame_sets_and_clears_away(monkeypatch):
    from backend.api.routes import pipeline as pipeline_routes

    reg = PipelineWsRegistry()
    monkeypatch.setattr(pipeline_routes, "registry", reg)
    vid, uid = uuid.uuid4(), uuid.uuid4()
    ws = _FakeWS()
    await reg.connect(vid, ws, uid)

    await pipeline_routes._apply_ws_presence_frame(vid, ws, '{"type":"presence","away":true}')
    assert reg.active_director_ids(vid) == set()  # away applied from the inbound frame
    await pipeline_routes._apply_ws_presence_frame(vid, ws, '{"type":"presence","away":false}')
    assert reg.active_director_ids(vid) == {uid}  # cleared from the inbound frame


async def test_apply_ws_presence_frame_ignores_malformed_silently(monkeypatch):
    from backend.api.routes import pipeline as pipeline_routes

    reg = PipelineWsRegistry()
    monkeypatch.setattr(pipeline_routes, "registry", reg)
    vid, uid = uuid.uuid4(), uuid.uuid4()
    ws = _FakeWS()
    await reg.connect(vid, ws, uid)
    bad_frames = [
        "not json at all",
        "[]",
        '{"type":"other"}',
        '"just a string"',
        "42",
        "{}",
        '{"type":"presence"}',  # presence WITHOUT away → malformed (must NOT coerce None→False)
        '{"type":"presence","away":"nope"}',  # non-bool away → malformed
        '{"type":"presence","away":1}',  # int, not bool → malformed
    ]
    for bad in bad_frames:
        await pipeline_routes._apply_ws_presence_frame(vid, ws, bad)  # must not raise, must not set away
    assert reg.active_director_ids(vid) == {uid}  # unchanged — only a well-formed presence frame sets away
