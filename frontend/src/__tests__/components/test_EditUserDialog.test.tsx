/**
 * Unit tests for {@link EditUserDialog}.
 *
 * Tests cover:
 *   1. Form renders with pre-populated fields (email, role, active toggle)
 *   2. Username is displayed read-only
 *   3. Successful update calls API with correct payload, triggers callbacks
 *   4. Cannot deactivate self — backend returns 400, toast shown
 *   5. Dialog not rendered when open=false
 *   6. Cancel button closes dialog
 *   7. Email validation
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const updateUserApiMock: Mock = vi.fn();

vi.mock("@/services/api/users", () => ({
  updateUserApi: (...args: unknown[]) => updateUserApiMock(...args),
}));

// Mock the base api module — EditUserDialog imports ApiError from it
vi.mock("@/services/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
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
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  TOKEN_STORAGE_KEY: "nex_studio_token",
  registerAuthCallback: vi.fn(),
}));

// Mock authStore — provide current user for self-deactivation check
const mockAuthUser = {
  id: "u-current",
  username: "admin",
  email: "admin@isnex.ai",
  role: "ri" as const,
  is_active: true,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

vi.mock("@/store/authStore", () => {
  const store = (
    selector: (s: { user: typeof mockAuthUser }) => unknown,
  ) => selector({ user: mockAuthUser });
  store.getState = () => ({ user: mockAuthUser });
  store.setState = vi.fn();
  store.subscribe = vi.fn();
  return { useAuthStore: store };
});

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

let ApiErrorClass: new (
  status: number,
  message: string,
  data?: unknown,
) => Error;

beforeEach(async () => {
  vi.resetAllMocks();
  const mod = await import("@/services/api");
  ApiErrorClass = mod.ApiError as unknown as typeof ApiErrorClass;
});

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

async function importDialog() {
  const mod = await import("@/components/users/EditUserDialog");
  return mod.default;
}

const SAMPLE_USER = {
  id: "u-other",
  username: "tibor",
  email: "tibor@isnex.ai",
  role: "ha" as const,
  is_active: true,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

function defaultProps() {
  return {
    open: true,
    user: { ...SAMPLE_USER },
    onClose: vi.fn(),
    onUpdated: vi.fn(),
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("EditUserDialog", () => {
  describe("Rendering", () => {
    it("renders all form fields when open with pre-populated values", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      expect(screen.getByTestId("edit-user-dialog")).toBeInTheDocument();
      expect(screen.getByTestId("edit-username")).toHaveValue("tibor");
      expect(screen.getByTestId("edit-username")).toBeDisabled();
      expect(screen.getByTestId("edit-email")).toHaveValue("tibor@isnex.ai");
      expect(screen.getByTestId("edit-role")).toHaveValue("ha");
      expect(screen.getByTestId("edit-is-active")).toHaveAttribute(
        "aria-checked",
        "true",
      );
      expect(screen.getByTestId("submit-btn")).toBeInTheDocument();
      expect(screen.getByTestId("cancel-btn")).toBeInTheDocument();
    });

    it("does not render when open=false", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} open={false} />);

      expect(
        screen.queryByTestId("edit-user-dialog"),
      ).not.toBeInTheDocument();
    });

    it("does not render when user is null", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} user={null} />);

      expect(
        screen.queryByTestId("edit-user-dialog"),
      ).not.toBeInTheDocument();
    });

    it("shows role options: ri, ha, shu", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      const select = screen.getByTestId("edit-role");
      const options = select.querySelectorAll("option");
      expect(options).toHaveLength(3);
      expect(options[0]).toHaveValue("ri");
      expect(options[1]).toHaveValue("ha");
      expect(options[2]).toHaveValue("shu");
    });
  });

  describe("Validation", () => {
    it("shows error when email is cleared and submitted", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      const emailInput = screen.getByTestId("edit-email");
      await user.clear(emailInput);
      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("email-error")).toHaveTextContent(
        "Email is required",
      );
      expect(updateUserApiMock).not.toHaveBeenCalled();
    });

    it("shows error for invalid email format", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      const emailInput = screen.getByTestId("edit-email");
      await user.clear(emailInput);
      await user.type(emailInput, "not-an-email");
      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("email-error")).toHaveTextContent(
        "Enter a valid email address",
      );
      expect(updateUserApiMock).not.toHaveBeenCalled();
    });
  });

  describe("Successful update", () => {
    it("calls updateUserApi with form data and triggers callbacks", async () => {
      const user = userEvent.setup();
      const props = defaultProps();
      updateUserApiMock.mockResolvedValueOnce({
        ...SAMPLE_USER,
        email: "tibor-new@isnex.ai",
        role: "ri",
        updated_at: "2026-04-17T10:00:00Z",
      });

      const Dialog = await importDialog();
      render(<Dialog {...props} />);

      // Change email
      const emailInput = screen.getByTestId("edit-email");
      await user.clear(emailInput);
      await user.type(emailInput, "tibor-new@isnex.ai");

      // Change role
      await user.selectOptions(screen.getByTestId("edit-role"), "ri");

      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(updateUserApiMock).toHaveBeenCalledOnce();
      });

      expect(updateUserApiMock).toHaveBeenCalledWith("u-other", {
        email: "tibor-new@isnex.ai",
        role: "ri",
        is_active: true,
      });

      expect(props.onUpdated).toHaveBeenCalledOnce();
      expect(props.onClose).toHaveBeenCalledOnce();
    });
  });

  describe("Server errors", () => {
    it("shows 400 cannot deactivate self error inline", async () => {
      const user = userEvent.setup();
      updateUserApiMock.mockRejectedValueOnce(
        new ApiErrorClass(400, "Cannot deactivate your own account"),
      );

      // Edit current user (self)
      const props = defaultProps();
      props.user = {
        ...SAMPLE_USER,
        id: "u-current",
        username: "admin",
      };

      const Dialog = await importDialog();
      render(<Dialog {...props} />);

      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Cannot deactivate your own account",
      );
    });

    it("shows generic error for non-ApiError failures", async () => {
      const user = userEvent.setup();
      updateUserApiMock.mockRejectedValueOnce(new Error("Network failure"));

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Failed to update user",
      );
    });
  });

  describe("Active toggle", () => {
    it("toggle is disabled when editing self", async () => {
      const props = defaultProps();
      props.user = {
        ...SAMPLE_USER,
        id: "u-current",
        username: "admin",
      };

      const Dialog = await importDialog();
      render(<Dialog {...props} />);

      const toggle = screen.getByTestId("edit-is-active");
      expect(toggle).toBeDisabled();
    });

    it("toggle is enabled when editing another user", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      const toggle = screen.getByTestId("edit-is-active");
      expect(toggle).not.toBeDisabled();
    });

    it("toggles is_active state on click", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      const toggle = screen.getByTestId("edit-is-active");
      expect(toggle).toHaveAttribute("aria-checked", "true");

      await user.click(toggle);
      expect(toggle).toHaveAttribute("aria-checked", "false");

      await user.click(toggle);
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });
  });

  describe("Cancel", () => {
    it("calls onClose when cancel button is clicked", async () => {
      const user = userEvent.setup();
      const props = defaultProps();

      const Dialog = await importDialog();
      render(<Dialog {...props} />);

      await user.click(screen.getByTestId("cancel-btn"));

      expect(props.onClose).toHaveBeenCalledOnce();
    });
  });
});
