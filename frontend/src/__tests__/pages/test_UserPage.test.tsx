/**
 * Unit tests for {@link UserPage}.
 *
 * Tests cover:
 *   1. Table renders user rows with username, email, role badge, active badge
 *   2. ri role sees Create button
 *   3. ha role does NOT see Create button (access denied)
 *   4. shu role does NOT see Create button (access denied)
 *   5. Create form has password field (not password_hash)
 *   6. Edit form does NOT show password field
 *   7. Table shows Edit, Change Password, Deactivate actions
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { UserRead } from "@/types/user";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock api module
const apiGetMock: Mock = vi.fn();
const apiPostMock: Mock = vi.fn();
const apiPatchMock: Mock = vi.fn();
const apiDeleteMock: Mock = vi.fn();

vi.mock("@/services/api", () => ({
  api: {
    get: (...args: unknown[]) => apiGetMock(...args),
    post: (...args: unknown[]) => apiPostMock(...args),
    patch: (...args: unknown[]) => apiPatchMock(...args),
    delete: (...args: unknown[]) => apiDeleteMock(...args),
  },
  ApiError: class ApiError extends Error {
    status: number;
    data: unknown;
    constructor(status: number, message: string, data: unknown = null) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.data = data;
    }
  },
  TOKEN_STORAGE_KEY: "nex_studio_token",
}));

// Mock auth utils — controls role guard
const getUserRoleMock: Mock = vi.fn();
vi.mock("@/utils/auth", () => ({
  getUserRole: () => getUserRoleMock(),
}));

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: "u-001",
    username: "zoltan",
    email: "zoltan@isnex.ai",
    role: "ri",
    is_active: true,
    created_at: "2026-01-15T10:00:00Z",
    updated_at: "2026-01-15T10:00:00Z",
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.resetAllMocks();
  // Default: ri role (full access)
  getUserRoleMock.mockReturnValue("ri");
});

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

async function importPage() {
  const mod = await import("@/pages/UserPage");
  return mod.default;
}

function mockUserList(users: UserRead[], total?: number) {
  apiGetMock.mockResolvedValueOnce({
    items: users,
    total: total ?? users.length,
  });
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("UserPage", () => {
  describe("Table rendering", () => {
    it("renders user rows with username, email, role badge, and active badge", async () => {
      const users = [
        makeUser({
          id: "u-1",
          username: "zoltan",
          email: "zoltan@isnex.ai",
          role: "ri",
          is_active: true,
        }),
        makeUser({
          id: "u-2",
          username: "dominik",
          email: "dominik@isnex.ai",
          role: "ha",
          is_active: false,
        }),
      ];
      mockUserList(users);

      const UserPage = await importPage();
      render(<UserPage />);

      await waitFor(() => {
        expect(screen.getByText("zoltan")).toBeInTheDocument();
      });

      // Username column
      expect(screen.getByText("zoltan")).toBeInTheDocument();
      expect(screen.getByText("dominik")).toBeInTheDocument();

      // Email column
      expect(screen.getByText("zoltan@isnex.ai")).toBeInTheDocument();
      expect(screen.getByText("dominik@isnex.ai")).toBeInTheDocument();

      // Role badges — "ri"/"ha"/"shu" also appear in the filter dropdown,
      // so we use getAllByText and check at least one match exists.
      expect(screen.getAllByText("ri").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("ha").length).toBeGreaterThanOrEqual(1);

      // Active badges
      expect(screen.getByText("active")).toBeInTheDocument();
      expect(screen.getByText("inactive")).toBeInTheDocument();
    });

    it("shows Edit, Change Password, and Deactivate actions per row", async () => {
      const users = [makeUser({ id: "u-1" })];
      mockUserList(users);

      const UserPage = await importPage();
      render(<UserPage />);

      await waitFor(() => {
        expect(screen.getByTestId("edit-btn-u-1")).toBeInTheDocument();
      });

      expect(screen.getByTestId("change-password-btn-u-1")).toBeInTheDocument();
      expect(screen.getByTestId("deactivate-btn-u-1")).toBeInTheDocument();
      expect(screen.getByTestId("deactivate-btn-u-1")).toHaveTextContent(
        "Deactivate",
      );
    });

    it("shows Activate button for inactive users", async () => {
      const users = [makeUser({ id: "u-1", is_active: false })];
      mockUserList(users);

      const UserPage = await importPage();
      render(<UserPage />);

      await waitFor(() => {
        expect(screen.getByTestId("deactivate-btn-u-1")).toBeInTheDocument();
      });

      expect(screen.getByTestId("deactivate-btn-u-1")).toHaveTextContent(
        "Activate",
      );
    });
  });

  describe("Role guard", () => {
    it("ri role sees Create button and user table", async () => {
      getUserRoleMock.mockReturnValue("ri");
      mockUserList([makeUser()]);

      const UserPage = await importPage();
      render(<UserPage />);

      await waitFor(() => {
        expect(screen.getByTestId("create-user-btn")).toBeInTheDocument();
      });

      expect(screen.getByTestId("user-page")).toBeInTheDocument();
    });

    it("ha role sees access denied, no Create button", async () => {
      getUserRoleMock.mockReturnValue("ha");

      const UserPage = await importPage();
      render(<UserPage />);

      expect(screen.getByTestId("user-page-denied")).toBeInTheDocument();
      expect(screen.getByText(/Access denied/)).toBeInTheDocument();
      expect(
        screen.queryByTestId("create-user-btn"),
      ).not.toBeInTheDocument();
    });

    it("shu role sees access denied, no Create button", async () => {
      getUserRoleMock.mockReturnValue("shu");

      const UserPage = await importPage();
      render(<UserPage />);

      expect(screen.getByTestId("user-page-denied")).toBeInTheDocument();
      expect(screen.getByText(/Access denied/)).toBeInTheDocument();
      expect(
        screen.queryByTestId("create-user-btn"),
      ).not.toBeInTheDocument();
    });
  });

  describe("Password field", () => {
    it("create form has password field (not password_hash)", async () => {
      mockUserList([]);
      const user = userEvent.setup();

      const UserPage = await importPage();
      render(<UserPage />);

      await waitFor(() => {
        expect(screen.getByTestId("create-user-btn")).toBeInTheDocument();
      });

      await user.click(screen.getByTestId("create-user-btn"));

      await waitFor(() => {
        expect(screen.getByText("Create user")).toBeInTheDocument();
      });

      // Password field should exist with type="password"
      const passwordInput = screen.getByTestId("password-field");
      expect(passwordInput).toBeInTheDocument();
      expect(passwordInput).toHaveAttribute("type", "password");

      // No password_hash label should exist
      expect(screen.queryByText("Password hash")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/password.hash/i)).not.toBeInTheDocument();

      // Password label should be present
      expect(screen.getByText("Password")).toBeInTheDocument();
    });

    it("edit form does NOT show password field", async () => {
      const users = [makeUser({ id: "u-edit" })];
      mockUserList(users);
      const user = userEvent.setup();

      const UserPage = await importPage();
      render(<UserPage />);

      await waitFor(() => {
        expect(screen.getByTestId("edit-btn-u-edit")).toBeInTheDocument();
      });

      // Mock the GET for edit form population
      apiGetMock.mockResolvedValueOnce(
        makeUser({ id: "u-edit", username: "zoltan" }),
      );

      await user.click(screen.getByTestId("edit-btn-u-edit"));

      await waitFor(() => {
        expect(screen.getByText("Edit user")).toBeInTheDocument();
      });

      // Password field should NOT exist in edit mode
      expect(screen.queryByTestId("password-field")).not.toBeInTheDocument();
      expect(screen.queryByText("Password hash")).not.toBeInTheDocument();
    });
  });
});
