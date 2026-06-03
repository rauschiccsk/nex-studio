"""Pipeline WebSocket connection registry + presence (F-007 §6/§9, CR-NS-018 Phase 3).

A process-global, in-memory registry of live board connections per version. The
``POST /pipeline/{version_id}/action`` handler broadcasts ``state_changed`` /
``message_added`` to all sockets of that version; the same registry is the §9
**presence signal** — Phase 5 reads ``present_director_ids`` to decide whether a
Director needs a Telegram nudge (only when they have no live board socket).

Single backend process is assumed (NEX Studio runs one); a multi-worker
deployment would need an external pub/sub — explicitly out of scope.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class PipelineWsRegistry:
    """Tracks ``(websocket, user_id)`` connections per ``version_id``."""

    def __init__(self) -> None:
        self._conns: dict[UUID, set[tuple[WebSocket, UUID]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, version_id: UUID, ws: WebSocket, user_id: UUID) -> None:
        async with self._lock:
            self._conns[version_id].add((ws, user_id))

    async def disconnect(self, version_id: UUID, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._conns.get(version_id)
            if not conns:
                return
            for item in [c for c in conns if c[0] is ws]:
                conns.discard(item)
            if not conns:
                self._conns.pop(version_id, None)

    async def broadcast(self, version_id: UUID, event: dict[str, Any]) -> None:
        """Send ``event`` (JSON) to every socket of ``version_id``.

        Never raises — a failing socket is pruned, not propagated.
        """
        async with self._lock:
            targets = list(self._conns.get(version_id, set()))
        dead: list[WebSocket] = []
        for ws, _uid in targets:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 — socket may be closed mid-broadcast
                dead.append(ws)
        for ws in dead:
            await self.disconnect(version_id, ws)

    def present_director_ids(self, version_id: UUID) -> set[UUID]:
        """User ids with a live board socket for ``version_id`` (§9 presence read)."""
        return {uid for (_ws, uid) in self._conns.get(version_id, set())}


#: Process-global registry shared by the route handlers + the WS endpoint.
registry = PipelineWsRegistry()
