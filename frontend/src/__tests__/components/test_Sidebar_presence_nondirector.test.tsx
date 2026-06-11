/**
 * Sidebar E6 presence toggle (CR-NS-038) — Director-only gating: a non-Director (role !== "ri") must
 * NOT see the presence toggle.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// authStore returns a NON-Director user (role "ha").
vi.mock("@/store/authStore", () => ({
  useAuthStore: vi.fn((sel: (s: unknown) => unknown) =>
    sel({ user: { username: "ha-user", role: "ha" }, logout: vi.fn(), token: null }),
  ),
}));

import Sidebar from "@/components/layout/Sidebar";

describe("Sidebar — E6 presence toggle gating (CR-NS-038)", () => {
  it("does NOT render the presence toggle for a non-Director", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Pri počítači")).not.toBeInTheDocument();
    expect(screen.queryByText("Preč")).not.toBeInTheDocument();
  });
});
