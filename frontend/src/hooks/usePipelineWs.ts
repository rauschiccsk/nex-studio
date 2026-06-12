// Live pipeline board subscription (F-007 §7, CR-NS-018 Phase 4).
//
// Fetches the board once over REST, then keeps it live via the cockpit WS.
// The open WS connection doubles as the §9 Director-presence signal — a live
// connection anywhere in NEX Studio means "Director is in-app".

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthStore } from "../store/authStore";
import { usePresenceStore } from "../store/usePresenceStore";
import {
  buildPipelineWsUrl,
  getPipelineBoardApi,
  type ActivityLine,
  type PipelineBoard,
  type PipelineWsFrame,
} from "../services/api/pipeline";

const _MAX_ACTIVITY = 50;

export interface UsePipelineWs {
  board: PipelineBoard | null;
  connected: boolean;
  error: string | null;
  /** Live agent activity for the current run; reset on every state change. */
  activity: ActivityLine[];
  /** The socket dropped AFTER being established and is auto-reconnecting — drives a "stale" banner
   *  (false during the initial connect, so it never flashes on load). */
  reconnecting: boolean;
  /** Replace the board (e.g. with the fresh board returned by a POST action). */
  setBoard: (board: PipelineBoard) => void;
}

export function usePipelineWs(versionId: string | null): UsePipelineWs {
  const token = useAuthStore((s) => s.token);
  const isAway = usePresenceStore((s) => s.isAway);
  const [board, setBoard] = useState<PipelineBoard | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityLine[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const everConnectedRef = useRef(false);

  useEffect(() => {
    if (!versionId || !token) {
      setBoard(null);
      setConnected(false);
      setReconnecting(false);
      setActivity([]);
      return;
    }

    let cancelled = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    everConnectedRef.current = false;
    setReconnecting(false);

    // Fresh REST snapshot — on first mount AND on every WS reconnect, so a board that went stale
    // while the socket was down resyncs at once (incident 2026-06-12: a backend redeploy killed the
    // socket → with no reconnect the board froze → the Director's action buttons vanished until a
    // manual hard-refresh). WS also pushes one on connect, but REST fills the board before it opens.
    const fetchSnapshot = () => {
      getPipelineBoardApi(versionId)
        .then((b) => {
          if (!cancelled) setBoard(b);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : "Načítanie boardu zlyhalo");
        });
    };

    const connect = () => {
      if (cancelled) return;
      fetchSnapshot();

      const ws = new WebSocket(buildPipelineWsUrl(versionId, token));
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        attempt = 0; // reset backoff after a successful connect
        everConnectedRef.current = true;
        setConnected(true);
        setReconnecting(false);
        setError(null);
        // E6 (CR-NS-038): a fresh connection inherits the current away state. Read the LIVE value
        // (getState) — this effect is keyed on [versionId, token], not isAway, so the closure value
        // could be stale; the separate effect below pushes subsequent toggles.
        try {
          ws.send(JSON.stringify({ type: "presence", away: usePresenceStore.getState().isAway }));
        } catch {
          /* socket race — the toggle effect will resend on the next change */
        }
      };

      ws.onmessage = (ev) => {
        if (cancelled) return;
        let frame: PipelineWsFrame;
        try {
          frame = JSON.parse(ev.data) as PipelineWsFrame;
        } catch {
          return; // malformed frame ignored
        }
        if (frame.type === "state_changed" && "board" in frame) {
          setBoard(frame.board);
          setActivity([]); // activity belongs to one run; a state change ends/starts it
        } else if (frame.type === "state_changed" && "state" in frame) {
          setBoard((prev) =>
            prev ? { ...prev, state: frame.state } : { state: frame.state, recent_messages: [] },
          );
          setActivity([]);
        } else if (frame.type === "message_added") {
          setBoard((prev) => {
            if (!prev) return { state: null, recent_messages: [frame.message] };
            if (prev.recent_messages.some((m) => m.id === frame.message.id)) return prev; // id-dedupe
            // Insert by authoritative seq (not arrival order) — robust even if frames race.
            const next = [...prev.recent_messages, frame.message].sort((a, b) => a.seq - b.seq);
            return { ...prev, recent_messages: next };
          });
        } else if (frame.type === "agent_activity") {
          const { stage, actor, kind, line } = frame;
          setActivity((prev) => [...prev, { stage, actor, kind, line }].slice(-_MAX_ACTIVITY));
        }
      };

      // Auto-reconnect with capped exponential backoff (CR 2026-06-12). Without this a dropped
      // socket (idle timeout, network blip, or a backend redeploy) froze the board permanently
      // until a manual refresh. onclose + onerror both route here; we detach the DEAD socket's
      // handlers (so it can't re-fire) and keep retryTimer non-null through connect() — together
      // those guarantee one drop schedules exactly one retry, with no double-socket.
      const scheduleReconnect = () => {
        if (cancelled) return;
        ws.onclose = null;
        ws.onerror = null; // this socket is dead — ignore any further events from it
        setConnected(false);
        setError(null); // the amber "reconnecting" banner now owns the connection messaging
        if (everConnectedRef.current) setReconnecting(true);
        if (retryTimer) return; // a retry is already pending
        const delay = Math.min(1000 * 2 ** attempt, 15000); // 1s,2s,4s,8s,…,15s cap
        attempt += 1;
        retryTimer = setTimeout(() => {
          connect(); // retryTimer stays non-null through connect() → blocks any re-entrant schedule
          retryTimer = null;
        }, delay);
      };

      ws.onclose = scheduleReconnect;
      ws.onerror = scheduleReconnect;
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      try {
        wsRef.current?.close();
      } catch {
        /* already closing */
      }
      wsRef.current = null;
    };
  }, [versionId, token]);

  // E6 (CR-NS-038): push the away state live whenever it toggles, over the EXISTING socket — no
  // reconnect. On first mount / before open this no-ops (the onopen handler sends the initial state).
  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "presence", away: isAway }));
      } catch {
        /* socket race — ignored */
      }
    }
  }, [isAway]);

  const replaceBoard = useCallback((b: PipelineBoard) => setBoard(b), []);

  return { board, connected, error, activity, reconnecting, setBoard: replaceBoard };
}
