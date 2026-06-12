/**
 * E5 (CR-NS-044) — the Metriky sidebar link is project-scoped: disabled (not a cross-domain
 * fallback) when no project is selected.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/store/authStore", () => ({
  useAuthStore: (sel: (s: unknown) => unknown) =>
    sel({ user: { username: "ri", role: "ri" }, logout: vi.fn() }),
}));

vi.mock("@/store/activeContextStore", () => ({
  useActiveContextStore: (sel: (s: unknown) => unknown) =>
    sel({ selectedProject: null, selectedVersion: null, setSelectedProject: vi.fn() }),
}));

import Sidebar from "@/components/layout/Sidebar";

describe("Sidebar Metriky link (E5 / CR-NS-044)", () => {
  it("disables the Metriky link when no project is selected", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: /Metriky/i })).toBeDisabled();
  });
});
