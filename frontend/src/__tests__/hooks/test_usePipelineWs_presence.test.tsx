/**
 * usePipelineWs E6 presence send (CR-NS-038) — sends {"type":"presence","away"} on WS open and on
 * every isAway toggle over the EXISTING socket (no reconnect).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

vi.mock("@/store/authStore", () => ({
  useAuthStore: vi.fn((sel: (s: unknown) => unknown) => sel({ token: "jwt.token", user: null })),
}));
vi.mock("@/services/api/pipeline", () => ({
  getPipelineBoardApi: vi.fn(() => Promise.resolve({ state: null, recent_messages: [] })),
  buildPipelineWsUrl: vi.fn(() => "ws://test/ws"),
}));

import { usePipelineWs } from "@/hooks/usePipelineWs";
import { usePresenceStore } from "@/store/usePresenceStore";

class FakeWS {
  static instances: FakeWS[] = [];
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  _open() {
    this.readyState = FakeWS.OPEN;
    this.onopen?.();
  }
}

const PRESENCE = (away: boolean) => JSON.stringify({ type: "presence", away });

describe("usePipelineWs — E6 presence send (CR-NS-038)", () => {
  beforeEach(() => {
    FakeWS.instances = [];
    usePresenceStore.setState({ isAway: false });
    vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
  });

  it("sends the current away state on WS open", async () => {
    renderHook(() => usePipelineWs("v1"));
    await waitFor(() => expect(FakeWS.instances.length).toBe(1));
    const ws = FakeWS.instances[0]!;
    act(() => ws._open());
    expect(ws.sent).toContain(PRESENCE(false));
  });

  it("pushes a presence frame when isAway toggles — over the same socket (no reconnect)", async () => {
    renderHook(() => usePipelineWs("v1"));
    await waitFor(() => expect(FakeWS.instances.length).toBe(1));
    const ws = FakeWS.instances[0]!;
    act(() => ws._open());
    ws.sent = []; // drop the on-open send; isolate the toggle

    act(() => usePresenceStore.getState().setIsAway(true));

    expect(ws.sent).toContain(PRESENCE(true));
    expect(FakeWS.instances.length).toBe(1); // same connection — no reconnect
  });
});
