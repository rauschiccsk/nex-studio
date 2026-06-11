/**
 * E3(a) (CR-NS-039) — Sidebar AG terminal is Coordinator-only (hub-and-spoke).
 *
 * Supersedes the CR-NS-014 per-charter gating test: the Designer / Customer /
 * Implementer / Auditor sidebar terminals were removed, so only the single
 * AG Koordinátor NavItem remains and it is no longer charter-gated (the Sidebar
 * no longer calls ``getAvailableRolesApi``). The pipeline still dispatches all
 * roles internally — this only asserts the trimmed sidebar surface.
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
    sel({
      selectedProject: { slug: "nex-inbox", name: "NEX Inbox" },
      selectedVersion: null,
      setSelectedProject: vi.fn(),
    }),
}));

import Sidebar from "@/components/layout/Sidebar";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar AG terminal (E3(a) / CR-NS-039)", () => {
  it("shows the single AG Koordinátor terminal, always enabled", () => {
    renderSidebar();

    const coordinator = screen.getByRole("button", { name: /AG Koordinátor/i });
    expect(coordinator).not.toBeDisabled();
  });

  it("no longer renders the Designer / Customer / Implementer / Auditor terminals", () => {
    renderSidebar();

    expect(screen.queryByRole("button", { name: /AG Designer/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /AG Customer/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /AG Implementator/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /AG Auditor/i })).toBeNull();
  });
});
