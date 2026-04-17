/**
 * Unit tests for {@link SettingsPage}.
 *
 * Tests cover:
 *   1. Tab bar renders correctly for each role
 *   2. Správa používateľov + User Sessions tabs visible only for ri
 *   3. Tab switching displays correct panel
 *   4. Dark mode toggle integration
 *   5. Vzhľad tab always visible
 *
 * @vitest-environment jsdom
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock UserPage — we don't want to pull in its full dependency tree.
vi.mock("@/pages/UserPage", () => ({
  default: () => <div data-testid="user-page-embed">UserPage</div>,
}));

// Mock UserSessionPage
vi.mock("@/pages/UserSessionPage", () => ({
  default: () => (
    <div data-testid="user-session-page-embed">UserSessionPage</div>
  ),
}));

// Mock api (UserPage dependency, but also needed to avoid import errors)
vi.mock("@/services/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  TOKEN_STORAGE_KEY: "nex_studio_token",
}));

vi.mock("@/utils/auth", () => ({
  getUserRole: vi.fn().mockReturnValue("ri"),
}));

// ThemeContext — provide a controllable mock
const toggleDarkMock = vi.fn();
let mockIsDark = false;

vi.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: mockIsDark, toggleDark: toggleDarkMock }),
  ThemeProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  darkModeKey: (u: string) => `nex_dark_${u}`,
}));

// Auth store — control role per test
let mockRole: string | null = "ri";
let mockUsername: string | null = "zoltan";

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      token: "fake-jwt",
      user: mockRole
        ? {
            id: "u-001",
            username: mockUsername,
            email: "test@isnex.ai",
            role: mockRole,
            is_active: true,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          }
        : null,
    }),
}));

/* ------------------------------------------------------------------ */
/*  Import under test (AFTER mocks)                                    */
/* ------------------------------------------------------------------ */

import SettingsPage from "@/pages/SettingsPage";

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks();
  mockRole = "ri";
  mockUsername = "zoltan";
  mockIsDark = false;
});

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getTablist() {
  return screen.getByRole("tablist", { name: "Settings tabs" });
}

function getTabs() {
  const tablist = getTablist();
  return within(tablist).getAllByRole("tab");
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("SettingsPage", () => {
  it("renders page heading", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Nastavenia")).toBeInTheDocument();
  });

  // ---- Tab bar rendering ----

  describe("tab bar", () => {
    it("shows all three tabs for ri role", () => {
      mockRole = "ri";
      render(<SettingsPage />);

      const tabs = getTabs();
      expect(tabs).toHaveLength(3);
      expect(tabs[0]).toHaveTextContent("Vzhľad");
      expect(tabs[1]).toHaveTextContent("Správa používateľov");
      expect(tabs[2]).toHaveTextContent("User Sessions");
    });

    it("shows only Vzhľad tab for ha role", () => {
      mockRole = "ha";
      render(<SettingsPage />);

      const tabs = getTabs();
      expect(tabs).toHaveLength(1);
      expect(tabs[0]).toHaveTextContent("Vzhľad");
    });

    it("shows only Vzhľad tab for shu role", () => {
      mockRole = "shu";
      render(<SettingsPage />);

      const tabs = getTabs();
      expect(tabs).toHaveLength(1);
      expect(tabs[0]).toHaveTextContent("Vzhľad");
    });

    it("marks Vzhľad tab as selected by default", () => {
      render(<SettingsPage />);

      const tabs = getTabs();
      expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    });
  });

  // ---- Tab switching ----

  describe("tab switching", () => {
    it("switches to Správa používateľov panel on tab click", async () => {
      mockRole = "ri";
      const user = userEvent.setup();
      render(<SettingsPage />);

      // Initially appearance panel is shown
      expect(screen.getByTestId("section-appearance")).toBeInTheDocument();
      expect(screen.queryByTestId("section-users")).not.toBeInTheDocument();

      // Click users tab
      await user.click(screen.getByRole("tab", { name: "Správa používateľov" }));

      expect(screen.getByTestId("section-users")).toBeInTheDocument();
      expect(screen.getByTestId("user-page-embed")).toBeInTheDocument();
      expect(screen.queryByTestId("section-appearance")).not.toBeInTheDocument();
    });

    it("switches to User Sessions panel on tab click", async () => {
      mockRole = "ri";
      const user = userEvent.setup();
      render(<SettingsPage />);

      await user.click(screen.getByRole("tab", { name: "User Sessions" }));

      expect(screen.getByTestId("section-sessions")).toBeInTheDocument();
      expect(
        screen.getByTestId("user-session-page-embed"),
      ).toBeInTheDocument();
      expect(screen.queryByTestId("section-appearance")).not.toBeInTheDocument();
    });

    it("updates aria-selected on tab change", async () => {
      mockRole = "ri";
      const user = userEvent.setup();
      render(<SettingsPage />);

      const usersTab = screen.getByRole("tab", { name: "Správa používateľov" });
      await user.click(usersTab);

      expect(usersTab).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tab", { name: "Vzhľad" })).toHaveAttribute(
        "aria-selected",
        "false",
      );
    });
  });

  // ---- Vzhľad section ----

  describe("Vzhľad (appearance)", () => {
    it("always shows Vzhľad section by default", () => {
      render(<SettingsPage />);
      expect(screen.getByTestId("section-appearance")).toBeInTheDocument();
      expect(screen.getByText("Vzhľad")).toBeInTheDocument();
    });

    it("renders dark mode toggle", () => {
      render(<SettingsPage />);
      expect(screen.getByTestId("dark-mode-toggle")).toBeInTheDocument();
    });

    it("calls toggleDark when the switch is clicked", async () => {
      const user = userEvent.setup();
      render(<SettingsPage />);

      const toggle = screen.getByRole("switch");
      await user.click(toggle);

      expect(toggleDarkMock).toHaveBeenCalledTimes(1);
    });

    it("reflects isDark state on the toggle", () => {
      mockIsDark = true;
      render(<SettingsPage />);

      const toggle = screen.getByRole("switch") as HTMLInputElement;
      expect(toggle.checked).toBe(true);
      expect(screen.getByText("Tmavý režim")).toBeInTheDocument();
    });

    it("shows Svetlý režim label when light mode", () => {
      mockIsDark = false;
      render(<SettingsPage />);
      expect(screen.getByText("Svetlý režim")).toBeInTheDocument();
    });
  });

  // ---- ri-only tabs visibility ----

  describe("ri-only tab visibility", () => {
    it("hides Správa používateľov tab for ha role", () => {
      mockRole = "ha";
      render(<SettingsPage />);
      expect(
        screen.queryByRole("tab", { name: "Správa používateľov" }),
      ).not.toBeInTheDocument();
    });

    it("hides Správa používateľov tab for shu role", () => {
      mockRole = "shu";
      render(<SettingsPage />);
      expect(
        screen.queryByRole("tab", { name: "Správa používateľov" }),
      ).not.toBeInTheDocument();
    });

    it("hides User Sessions tab for ha role", () => {
      mockRole = "ha";
      render(<SettingsPage />);
      expect(
        screen.queryByRole("tab", { name: "User Sessions" }),
      ).not.toBeInTheDocument();
    });

    it("hides User Sessions tab for shu role", () => {
      mockRole = "shu";
      render(<SettingsPage />);
      expect(
        screen.queryByRole("tab", { name: "User Sessions" }),
      ).not.toBeInTheDocument();
    });

    it("hides ri-only tabs when user is null", () => {
      mockRole = null;
      render(<SettingsPage />);

      expect(
        screen.queryByRole("tab", { name: "Správa používateľov" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("tab", { name: "User Sessions" }),
      ).not.toBeInTheDocument();
    });
  });
});
