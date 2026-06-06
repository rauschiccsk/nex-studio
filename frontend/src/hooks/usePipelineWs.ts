// Live pipeline board subscription (F-007 §7, CR-NS-018 Phase 4).
//
// Fetches the board once over REST, then keeps it live via the cockpit WS.
// The open WS connection doubles as the §9 Director-presence signal — a live
// connection anywhere in NEX Studio means "Director is in-app".

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthStore } from "../store/authStore";
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
  /** Replace the board (e.g. with the fresh board returned by a POST action). */
  setBoard: (board: PipelineBoard) => void;
}

export function usePipelineWs(versionId: string | null): UsePipelineWs {
  const token = useAuthStore((s) => s.token);
  const [board, setBoard] = useState<PipelineBoard | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityLine[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!versionId || !token) {
      setBoard(null);
      setConnected(false);
      setActivity([]);
      return;
    }

    let cancelled = false;

    // Immediate REST snapshot (WS also sends one on connect, but REST fills the
    // board before the socket opens).
    getPipelineBoardApi(versionId)
      .then((b) => {
        if (!cancelled) setBoard(b);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Načítanie boardu zlyhalo");
      });

    const ws = new WebSocket(buildPipelineWsUrl(versionId, token));
    wsRef.current = ws;

    ws.onopen = () => {
      if (!cancelled) {
        setConnected(true);
        setError(null);
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

    ws.onclose = () => {
      if (!cancelled) setConnected(false);
    };

    ws.onerror = () => {
      if (!cancelled) setConnected(false);
    };

    return () => {
      cancelled = true;
      try {
        ws.close();
      } catch {
        /* already closing */
      }
      wsRef.current = null;
    };
  }, [versionId, token]);

  const replaceBoard = useCallback((b: PipelineBoard) => setBoard(b), []);

  return { board, connected, error, activity, setBoard: replaceBoard };
}
