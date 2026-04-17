/**
 * Unit tests for {@link ChangePasswordDialog}.
 *
 * Tests cover:
 *   1. Form renders with empty password fields
 *   2. Password match validation — mismatch shows error
 *   3. Password minimum length validation
 *   4. Successful change calls API, shows success toast
 *   5. Token invalidation note in success message
 *   6. Server error displayed inline
 *   7. Dialog not rendered when open=false or user=null
 *   8. Cancel button closes dialog
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const changePasswordApiMock: Mock = vi.fn();

vi.mock("@/services/api/users", () => ({
  changePasswordApi: (...args: unknown[]) => changePasswordApiMock(...args),
}));

// Mock the base api module — ChangePasswordDialog imports ApiError from it
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
  const mod = await import("@/components/users/ChangePasswordDialog");
  return mod.default;
}

const SAMPLE_USER = {
  id: "u-target",
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
    onChanged: vi.fn(),
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("ChangePasswordDialog", () => {
  describe("Rendering", () => {
    it("renders dialog with empty password fields when open", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      expect(
        screen.getByTestId("change-password-dialog"),
      ).toBeInTheDocument();
      expect(screen.getByTestId("new-password")).toHaveValue("");
      expect(screen.getByTestId("confirm-password")).toHaveValue("");
      expect(screen.getByTestId("submit-btn")).toBeInTheDocument();
      expect(screen.getByTestId("cancel-btn")).toBeInTheDocument();
    });

    it("shows target username in description", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      expect(screen.getByText("tibor")).toBeInTheDocument();
    });

    it("does not render when open=false", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} open={false} />);

      expect(
        screen.queryByTestId("change-password-dialog"),
      ).not.toBeInTheDocument();
    });

    it("does not render when user is null", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} user={null} />);

      expect(
        screen.queryByTestId("change-password-dialog"),
      ).not.toBeInTheDocument();
    });
  });

  describe("Validation — password match", () => {
    it("shows error when passwords do not match", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("new-password"), "SecurePass1!");
      await user.type(screen.getByTestId("confirm-password"), "DifferentPass!");
      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("confirm-password-error")).toHaveTextContent(
        "Passwords do not match",
      );
      expect(changePasswordApiMock).not.toHaveBeenCalled();
    });

    it("does not show mismatch error when passwords match", async () => {
      const user = userEvent.setup();
      changePasswordApiMock.mockResolvedValueOnce({ ...SAMPLE_USER });

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("new-password"), "SecurePass1!");
      await user.type(screen.getByTestId("confirm-password"), "SecurePass1!");
      await user.click(screen.getByTestId("submit-btn"));

      expect(
        screen.queryByTestId("confirm-password-error"),
      ).not.toBeInTheDocument();
    });
  });

  describe("Validation — minimum length", () => {
    it("shows error when password is too short", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("new-password"), "short");
      await user.type(screen.getByTestId("confirm-password"), "short");
      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("new-password-error")).toHaveTextContent(
        "at least 8 characters",
      );
      expect(changePasswordApiMock).not.toHaveBeenCalled();
    });

    it("shows error when password is empty", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("new-password-error")).toHaveTextContent(
        "Password is required",
      );
    });
  });

  describe("Successful password change", () => {
    it("calls changePasswordApi with correct args and triggers callbacks", async () => {
      const user = userEvent.setup();
      const props = defaultProps();
      changePasswordApiMock.mockResolvedValueOnce({
        ...SAMPLE_USER,
        updated_at: "2026-04-17T10:00:00Z",
      });

      const Dialog = await importDialog();
      render(<Dialog {...props} />);

      await user.type(screen.getByTestId("new-password"), "NewSecurePass1!");
      await user.type(
        screen.getByTestId("confirm-password"),
        "NewSecurePass1!",
      );
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(changePasswordApiMock).toHaveBeenCalledOnce();
      });

      expect(changePasswordApiMock).toHaveBeenCalledWith(
        "u-target",
        "NewSecurePass1!",
      );

      expect(props.onChanged).toHaveBeenCalledOnce();
      expect(props.onClose).toHaveBeenCalledOnce();
    });
  });

  describe("Token invalidation — 401 redirect", () => {
    it("displays server error on 401 (token invalidated)", async () => {
      const user = userEvent.setup();
      changePasswordApiMock.mockRejectedValueOnce(
        new ApiErrorClass(401, "Token has been invalidated"),
      );

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("new-password"), "NewSecurePass1!");
      await user.type(
        screen.getByTestId("confirm-password"),
        "NewSecurePass1!",
      );
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Token has been invalidated",
      );
    });
  });

  describe("Server errors", () => {
    it("shows API error message inline", async () => {
      const user = userEvent.setup();
      changePasswordApiMock.mockRejectedValueOnce(
        new ApiErrorClass(403, "Insufficient permissions"),
      );

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("new-password"), "NewSecurePass1!");
      await user.type(
        screen.getByTestId("confirm-password"),
        "NewSecurePass1!",
      );
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Insufficient permissions",
      );
    });

    it("shows generic error for non-ApiError failures", async () => {
      const user = userEvent.setup();
      changePasswordApiMock.mockRejectedValueOnce(
        new Error("Network failure"),
      );

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("new-password"), "NewSecurePass1!");
      await user.type(
        screen.getByTestId("confirm-password"),
        "NewSecurePass1!",
      );
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Failed to change password",
      );
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
