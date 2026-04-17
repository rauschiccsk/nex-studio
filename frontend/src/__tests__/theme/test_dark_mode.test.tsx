/**
 * Dark mode integration test — verifies that the ``dark`` CSS class
 * is applied to ``<html>`` when ``isDark`` is true, ensuring Tailwind
 * ``dark:`` variants activate correctly (``darkMode: "class"``).
 *
 * This complements the unit-level ThemeContext tests in
 * ``__tests__/contexts/test_ThemeContext.test.tsx`` by testing the
 * DOM-level class manipulation that drives Tailwind's dark mode.
 */

import { describe, it, expect, beforeEach } from "vitest";
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

function wrapper(username: string) {
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

describe("Dark mode class strategy", () => {
  it("adds 'dark' class to <html> when isDark is true", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("testuser"),
    });

    // Initially light mode — no dark class.
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    // Toggle to dark.
    act(() => result.current.toggleDark());

    expect(result.current.isDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("removes 'dark' class from <html> when isDark is toggled back to false", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("testuser"),
    });

    // Enable dark mode.
    act(() => result.current.toggleDark());
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // Disable dark mode.
    act(() => result.current.toggleDark());
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("applies dark class on mount when persisted preference is true", () => {
    // Pre-seed localStorage with dark preference.
    localStorage.setItem(darkModeKey("darkuser"), "true");

    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("darkuser"),
    });

    expect(result.current.isDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("does not apply dark class on mount when persisted preference is false", () => {
    localStorage.setItem(darkModeKey("lightuser"), "false");

    const { result } = renderHook(() => useTheme(), {
      wrapper: wrapper("lightuser"),
    });

    expect(result.current.isDark).toBe(false);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("dark class state is independent per user", () => {
    // User A has dark mode on, User B has default (light).
    localStorage.setItem(darkModeKey("userA"), "true");

    const { result: resultA } = renderHook(() => useTheme(), {
      wrapper: wrapper("userA"),
    });
    expect(resultA.current.isDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // Remove dark class before mounting userB's context to isolate the test.
    document.documentElement.classList.remove("dark");

    const { result: resultB } = renderHook(() => useTheme(), {
      wrapper: wrapper("userB"),
    });
    expect(resultB.current.isDark).toBe(false);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
