/**
 * Sidebar E6 presence toggle (CR-NS-038) — Director-only "🟢 Pri počítači / 🌙 Preč".
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// authStore returns a Director (role "ri") so the toggle renders; selector-applied fake state.
vi.mock("@/store/authStore", () => ({
  useAuthStore: vi.fn((sel: (s: unknown) => unknown) =>
    sel({ user: { username: "zoltan", role: "ri" }, logout: vi.fn(), token: null }),
  ),
}));

import Sidebar from "@/components/layout/Sidebar";
import { usePresenceStore } from "@/store/usePresenceStore";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar — E6 presence toggle (CR-NS-038)", () => {
  beforeEach(() => {
    usePresenceStore.setState({ isAway: false });
  });

  it("renders the Director presence toggle, at-computer by default", () => {
    renderSidebar();
    expect(screen.getByText("Pri počítači")).toBeInTheDocument();
    expect(screen.queryByText("Preč")).not.toBeInTheDocument();
  });

  it("clicking toggles to away and back, driving usePresenceStore", () => {
    renderSidebar();
    fireEvent.click(screen.getByText("Pri počítači"));
    expect(usePresenceStore.getState().isAway).toBe(true);
    expect(screen.getByText("Preč")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Preč"));
    expect(usePresenceStore.getState().isAway).toBe(false);
    expect(screen.getByText("Pri počítači")).toBeInTheDocument();
  });

  it("collapsed sidebar shows the icon only (label hidden)", () => {
    renderSidebar();
    fireEvent.click(screen.getByTitle("Zúžiť")); // collapse
    expect(screen.queryByText("Pri počítači")).not.toBeInTheDocument(); // label hidden when collapsed
    expect(screen.getByText("🟢")).toBeInTheDocument(); // icon still rendered
  });
});
