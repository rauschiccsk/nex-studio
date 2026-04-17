/**
 * Tests for Header component — dark mode toggle button.
 *
 * Validates:
 * - Moon icon shown in light mode, Sun icon in dark mode
 * - Clicking toggle switches the icon
 * - Toggle persists preference to localStorage across sessions
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeProvider, darkModeKey } from "@/contexts/ThemeContext";
import Header from "@/components/layout/Header";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER = "testuser";

function renderHeader(username: string = TEST_USER) {
  return render(
    <ThemeProvider username={username}>
      <Header />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Header dark mode toggle", () => {
  it("shows Moon icon (switch to dark) in light mode by default", () => {
    renderHeader();
    const btn = screen.getByRole("button", { name: /switch to dark mode/i });
    expect(btn).toBeInTheDocument();
    // Moon icon should be present — lucide renders SVG
    expect(btn.querySelector("svg")).toBeInTheDocument();
  });

  it("shows Sun icon after toggling to dark mode", () => {
    renderHeader();
    const btn = screen.getByRole("button", { name: /switch to dark mode/i });
    fireEvent.click(btn);

    // After toggle, label changes to "Switch to light mode"
    const lightBtn = screen.getByRole("button", {
      name: /switch to light mode/i,
    });
    expect(lightBtn).toBeInTheDocument();
  });

  it("toggles back to Moon icon on second click", () => {
    renderHeader();
    const btn = screen.getByRole("button", { name: /switch to dark mode/i });

    // Toggle to dark
    fireEvent.click(btn);
    expect(
      screen.getByRole("button", { name: /switch to light mode/i }),
    ).toBeInTheDocument();

    // Toggle back to light
    fireEvent.click(
      screen.getByRole("button", { name: /switch to light mode/i }),
    );
    expect(
      screen.getByRole("button", { name: /switch to dark mode/i }),
    ).toBeInTheDocument();
  });

  it("persists dark mode preference to localStorage", () => {
    renderHeader();
    const btn = screen.getByRole("button", { name: /switch to dark mode/i });
    fireEvent.click(btn);

    expect(localStorage.getItem(darkModeKey(TEST_USER))).toBe("true");
  });

  it("reads persisted dark mode on mount (simulates new session)", () => {
    // Pre-set dark mode preference
    localStorage.setItem(darkModeKey(TEST_USER), "true");

    renderHeader();

    // Should mount with Sun icon (dark mode active)
    expect(
      screen.getByRole("button", { name: /switch to light mode/i }),
    ).toBeInTheDocument();
  });

  it("persists across unmount/remount (session persistence)", () => {
    // First session: toggle to dark
    const { unmount } = renderHeader();
    fireEvent.click(
      screen.getByRole("button", { name: /switch to dark mode/i }),
    );
    expect(localStorage.getItem(darkModeKey(TEST_USER))).toBe("true");
    unmount();

    // Second session: should start in dark mode
    renderHeader();
    expect(
      screen.getByRole("button", { name: /switch to light mode/i }),
    ).toBeInTheDocument();
  });
});
