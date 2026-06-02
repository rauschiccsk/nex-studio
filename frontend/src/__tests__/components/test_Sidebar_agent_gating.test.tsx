/**
 * CR-NS-014 — Sidebar gates AG nav tabs by per-project charter availability.
 *
 * The AG Koordinátor tab renders disabled when the selected project has no
 * coordinator charter, and enabled when it does. Other AG tabs are unaffected
 * when their charters exist.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { mockGetRoles } = vi.hoisted(() => ({ mockGetRoles: vi.fn() }));

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

vi.mock("@/services/api/agentTerminal", () => ({
  getAvailableRolesApi: mockGetRoles,
}));

import Sidebar from "@/components/layout/Sidebar";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar AG tab gating (CR-NS-014)", () => {
  beforeEach(() => {
    mockGetRoles.mockReset();
  });

  it("disables AG Koordinátor when the project has no coordinator charter", async () => {
    mockGetRoles.mockResolvedValue({
      designer: true,
      implementer: true,
      auditor: true,
      coordinator: false,
    });

    renderSidebar();

    const coordinator = screen.getByRole("button", { name: /AG Koordinátor/i });
    await waitFor(() => expect(coordinator).toBeDisabled());

    // Other AG tabs with present charters stay enabled.
    expect(screen.getByRole("button", { name: /AG Designer/i })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /AG Auditor/i })).not.toBeDisabled();
  });

  it("enables AG Koordinátor when the project has a coordinator charter", async () => {
    mockGetRoles.mockResolvedValue({
      designer: true,
      implementer: true,
      auditor: true,
      coordinator: true,
    });

    renderSidebar();

    await waitFor(() => expect(mockGetRoles).toHaveBeenCalledWith("nex-inbox"));
    expect(screen.getByRole("button", { name: /AG Koordinátor/i })).not.toBeDisabled();
  });
});
