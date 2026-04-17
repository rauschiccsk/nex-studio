/**
 * Unit tests for {@link SettingsPage}.
 *
 * Tests cover:
 *   1. Dark mode toggle updates ThemeContext (toggleDark called)
 *   2. "Správa používateľov" section visible for ri role
 *   3. "Správa používateľov" section hidden for ha role
 *   4. "Správa používateľov" section hidden for shu role
 *   5. "Vzhľad" section always visible
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock UserPage — we don't want to pull in its full dependency tree.
vi.mock("@/pages/UserPage", () => ({
  default: () => <div data-testid="user-page-embed">UserPage</div>,
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
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("SettingsPage", () => {
  it("renders page heading", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Nastavenia")).toBeInTheDocument();
  });

  it("always shows Vzhľad section", () => {
    render(<SettingsPage />);
    expect(screen.getByTestId("section-appearance")).toBeInTheDocument();
    expect(screen.getByText("Vzhľad")).toBeInTheDocument();
  });

  // ---- Dark mode toggle ----

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

  // ---- Users section — role-based visibility ----

  it("shows Správa používateľov section for ri role", () => {
    mockRole = "ri";
    render(<SettingsPage />);

    expect(screen.getByTestId("section-users")).toBeInTheDocument();
    expect(screen.getByText("Správa používateľov")).toBeInTheDocument();
    expect(screen.getByTestId("user-page-embed")).toBeInTheDocument();
  });

  it("hides Správa používateľov section for ha role", () => {
    mockRole = "ha";
    render(<SettingsPage />);

    expect(screen.queryByTestId("section-users")).not.toBeInTheDocument();
    expect(screen.queryByText("Správa používateľov")).not.toBeInTheDocument();
  });

  it("hides Správa používateľov section for shu role", () => {
    mockRole = "shu";
    render(<SettingsPage />);

    expect(screen.queryByTestId("section-users")).not.toBeInTheDocument();
    expect(screen.queryByText("Správa používateľov")).not.toBeInTheDocument();
  });

  it("hides Správa používateľov section when user is null", () => {
    mockRole = null;
    render(<SettingsPage />);

    expect(screen.queryByTestId("section-users")).not.toBeInTheDocument();
  });
});
