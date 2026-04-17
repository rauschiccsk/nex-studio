/**
 * Unit tests for {@link CreateUserDialog}.
 *
 * Tests cover:
 *   1. Form renders all fields (username, email, password, role)
 *   2. Validation: empty fields show error messages
 *   3. Validation: email format check
 *   4. Validation: password minimum length (8 chars)
 *   5. Successful creation calls API, onCreated, and onClose
 *   6. Duplicate username (409) shows server error toast/banner
 *   7. Dialog not rendered when open=false
 *   8. Cancel button closes dialog
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const createUserApiMock: Mock = vi.fn();

vi.mock("@/services/api/users", () => ({
  createUserApi: (...args: unknown[]) => createUserApiMock(...args),
}));

// Mock the base api module — CreateUserDialog imports ApiError from it
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
}));

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

// Access ApiError from mock for creating error instances
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
  const mod = await import("@/components/users/CreateUserDialog");
  return mod.default;
}

function defaultProps() {
  return {
    open: true,
    onClose: vi.fn(),
    onCreated: vi.fn(),
  };
}

async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  overrides: {
    username?: string;
    email?: string;
    password?: string;
    role?: string;
  } = {},
) {
  const {
    username = "newuser",
    email = "newuser@isnex.ai",
    password = "securepass123",
  } = overrides;

  await user.type(screen.getByTestId("create-username"), username);
  await user.type(screen.getByTestId("create-email"), email);
  await user.type(screen.getByTestId("create-password"), password);

  if (overrides.role) {
    await user.selectOptions(screen.getByTestId("create-role"), overrides.role);
  }
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("CreateUserDialog", () => {
  describe("Rendering", () => {
    it("renders all form fields when open", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      expect(screen.getByTestId("create-user-dialog")).toBeInTheDocument();
      expect(screen.getByTestId("create-username")).toBeInTheDocument();
      expect(screen.getByTestId("create-email")).toBeInTheDocument();
      expect(screen.getByTestId("create-password")).toBeInTheDocument();
      expect(screen.getByTestId("create-role")).toBeInTheDocument();
      expect(screen.getByTestId("submit-btn")).toBeInTheDocument();
      expect(screen.getByTestId("cancel-btn")).toBeInTheDocument();
    });

    it("does not render when open=false", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} open={false} />);

      expect(
        screen.queryByTestId("create-user-dialog"),
      ).not.toBeInTheDocument();
    });

    it("shows role options: ri, ha, shu", async () => {
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      const select = screen.getByTestId("create-role");
      const options = select.querySelectorAll("option");
      expect(options).toHaveLength(3);
      expect(options[0]).toHaveValue("ri");
      expect(options[1]).toHaveValue("ha");
      expect(options[2]).toHaveValue("shu");
    });
  });

  describe("Validation", () => {
    it("shows error when all fields are empty on submit", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("username-error")).toHaveTextContent(
        "Username is required",
      );
      expect(screen.getByTestId("email-error")).toHaveTextContent(
        "Email is required",
      );
      expect(screen.getByTestId("password-error")).toHaveTextContent(
        "Password is required",
      );
      expect(createUserApiMock).not.toHaveBeenCalled();
    });

    it("shows error for invalid email format", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("create-username"), "testuser");
      await user.type(screen.getByTestId("create-email"), "not-an-email");
      await user.type(screen.getByTestId("create-password"), "password123");
      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("email-error")).toHaveTextContent(
        "Enter a valid email address",
      );
      expect(createUserApiMock).not.toHaveBeenCalled();
    });

    it("shows error when password is too short (< 8 chars)", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await user.type(screen.getByTestId("create-username"), "testuser");
      await user.type(screen.getByTestId("create-email"), "test@isnex.ai");
      await user.type(screen.getByTestId("create-password"), "short");
      await user.click(screen.getByTestId("submit-btn"));

      expect(screen.getByTestId("password-error")).toHaveTextContent(
        "Password must be at least 8 characters",
      );
      expect(createUserApiMock).not.toHaveBeenCalled();
    });

    it("clears field error when user starts typing", async () => {
      const user = userEvent.setup();
      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      // Trigger validation
      await user.click(screen.getByTestId("submit-btn"));
      expect(screen.getByTestId("username-error")).toBeInTheDocument();

      // Start typing in username — error should clear
      await user.type(screen.getByTestId("create-username"), "a");

      expect(screen.queryByTestId("username-error")).not.toBeInTheDocument();
    });
  });

  describe("Successful creation", () => {
    it("calls createUserApi with form data and triggers callbacks", async () => {
      const user = userEvent.setup();
      const props = defaultProps();
      createUserApiMock.mockResolvedValueOnce({
        id: "u-new",
        username: "newuser",
        email: "newuser@isnex.ai",
        role: "ha",
        is_active: true,
        created_at: "2026-04-17T10:00:00Z",
        updated_at: "2026-04-17T10:00:00Z",
      });

      const Dialog = await importDialog();
      render(<Dialog {...props} />);

      await fillForm(user, { role: "ha" });
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(createUserApiMock).toHaveBeenCalledOnce();
      });

      expect(createUserApiMock).toHaveBeenCalledWith({
        username: "newuser",
        email: "newuser@isnex.ai",
        password: "securepass123",
        role: "ha",
        is_active: true,
      });

      expect(props.onCreated).toHaveBeenCalledOnce();
      expect(props.onClose).toHaveBeenCalledOnce();
    });
  });

  describe("Server errors", () => {
    it("shows 409 duplicate username error inline", async () => {
      const user = userEvent.setup();
      createUserApiMock.mockRejectedValueOnce(
        new ApiErrorClass(409, "Username already exists"),
      );

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await fillForm(user);
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Username already exists",
      );
    });

    it("shows generic error for non-ApiError failures", async () => {
      const user = userEvent.setup();
      createUserApiMock.mockRejectedValueOnce(new Error("Network failure"));

      const Dialog = await importDialog();
      render(<Dialog {...defaultProps()} />);

      await fillForm(user);
      await user.click(screen.getByTestId("submit-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("server-error")).toBeInTheDocument();
      });

      expect(screen.getByTestId("server-error")).toHaveTextContent(
        "Failed to create user",
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
