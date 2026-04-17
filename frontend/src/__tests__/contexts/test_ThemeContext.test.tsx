/**
 * Tests for ThemeContext — DESIGN.md § 3.3a dark mode.
 *
 * Validates:
 * - toggle persists preference to localStorage
 * - localStorage key is scoped per username
 * - ``dark`` class is applied / removed on ``<html>``
 * - defaults to light mode when no persisted value
 * - reads persisted value on mount
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import {
  ThemeProvider,
  useTheme,
  darkModeKey,
} from "@/contexts/ThemeContext";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function wrapper(username: string | undefined) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <ThemeProvider username={username}>{children}</ThemeProvider>;
  };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ThemeContext", () => {
  it("defaults to light mode (isDark = false)", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("testuser"),
    });

    expect(result.current.isDark).toBe(false);
  });

  it("toggleDark flips isDark to true and back", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("testuser"),
    });

    act(() => result.current.toggleDark());
    expect(result.current.isDark).toBe(true);

    act(() => result.current.toggleDark());
    expect(result.current.isDark).toBe(false);
  });

  it("persists dark mode preference to localStorage", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("alice"),
    });

    act(() => result.current.toggleDark());

    expect(localStorage.getItem(darkModeKey("alice"))).toBe("true");

    act(() => result.current.toggleDark());

    expect(localStorage.getItem(darkModeKey("alice"))).toBe("false");
  });

  it("uses per-user localStorage key (nex_dark_{username})", () => {
    expect(darkModeKey("admin")).toBe("nex_dark_admin");
    expect(darkModeKey("tibor")).toBe("nex_dark_tibor");

    // Set dark for alice, leave bob as default
    localStorage.setItem(darkModeKey("alice"), "true");

    const { result: alice } = renderHook(() => useTheme(), {
      wrapper: wrapper("alice"),
    });
    const { result: bob } = renderHook(() => useTheme(), {
      wrapper: wrapper("bob"),
    });

    expect(alice.current.isDark).toBe(true);
    expect(bob.current.isDark).toBe(false);
  });

  it("reads persisted preference on mount", () => {
    localStorage.setItem(darkModeKey("zoltan"), "true");

    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("zoltan"),
    });

    expect(result.current.isDark).toBe(true);
  });

  it("applies dark class to <html> when isDark is true", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("testuser"),
    });

    expect(document.documentElement.classList.contains("dark")).toBe(false);

    act(() => result.current.toggleDark());

    expect(document.documentElement.classList.contains("dark")).toBe(true);

    act(() => result.current.toggleDark());

    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("defaults to false when username is undefined", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper(undefined),
    });

    expect(result.current.isDark).toBe(false);
  });

  it("does not persist when username is undefined", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper(undefined),
    });

    act(() => result.current.toggleDark());

    // isDark toggled in memory
    expect(result.current.isDark).toBe(true);
    // But nothing written to localStorage
    expect(localStorage.length).toBe(0);
  });

  it("throws when useTheme is called outside ThemeProvider", () => {
    // Suppress React error boundary noise
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => {
      renderHook(() => useTheme());
    }).toThrow("useTheme must be used within a <ThemeProvider>");

    spy.mockRestore();
  });
});
