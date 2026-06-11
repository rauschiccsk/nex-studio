/**
 * Tests for ``usePresenceStore`` — E6 Telegram presence toggle (CR-NS-038).
 */

import { describe, it, expect, beforeEach } from "vitest";

import { usePresenceStore } from "@/store/usePresenceStore";

describe("usePresenceStore", () => {
  beforeEach(() => {
    usePresenceStore.setState({ isAway: false });
    window.localStorage.clear();
  });

  it("defaults to at-computer (isAway=false)", () => {
    expect(usePresenceStore.getState().isAway).toBe(false);
  });

  it("setIsAway toggles the away flag", () => {
    usePresenceStore.getState().setIsAway(true);
    expect(usePresenceStore.getState().isAway).toBe(true);
    usePresenceStore.getState().setIsAway(false);
    expect(usePresenceStore.getState().isAway).toBe(false);
  });

  it("persists isAway under the nex-presence localStorage key", () => {
    usePresenceStore.getState().setIsAway(true);
    const raw = window.localStorage.getItem("nex-presence");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw as string).state.isAway).toBe(true);
  });
});
