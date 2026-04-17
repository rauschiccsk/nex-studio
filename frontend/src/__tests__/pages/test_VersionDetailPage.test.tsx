/**
 * Unit tests for {@link VersionDetailPage}.
 *
 * Tests cover:
 *   1. Release button disabled when blocking EPICs exist
 *   2. Blocking warning in ReleaseVersionDialog
 *   3. Successful release flow
 *
 * Dependencies are mocked at the module boundary:
 *   - ``react-router-dom`` — stub ``useParams``
 *   - ``../services/api/versions`` — stub ``getVersion``, ``releaseVersion``
 *   - ``localStorage`` — control JWT role claim
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import type { Version } from "@/types/version";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock react-router-dom
vi.mock("react-router-dom", () => ({
  useParams: vi.fn(() => ({ slug: "test-project", vid: "v-001" })),
}));

// Mock API module
const getVersionMock: Mock = vi.fn();
const releaseVersionMock: Mock = vi.fn();
vi.mock("@/services/api/versions", () => ({
  getVersion: (...args: unknown[]) => getVersionMock(...args),
  releaseVersion: (...args: unknown[]) => releaseVersionMock(...args),
  listVersions: vi.fn(),
  createVersion: vi.fn(),
  updateVersion: vi.fn(),
}));

// Mock api error import + token key — constructor signature matches real ApiError
vi.mock("@/services/api", () => {
  class ApiError extends Error {
    status: number;
    data: unknown;
    constructor(status: number, message: string, data: unknown = null) {
      super(message);
      this.status = status;
      this.data = data;
    }
  }
  return { ApiError, TOKEN_STORAGE_KEY: "nex_studio_token" };
});

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

function makeVersion(overrides: Partial<Version> = {}): Version {
  return {
    id: "v-001",
    project_id: "p-001",
    version_number: "1.0.0",
    name: "Alpha",
    status: "active",
    description: "First release",
    target_date: "2026-06-01",
    release_date: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    epic_count: 10,
    epics_done: 7,
    bug_count: 2,
    ...overrides,
  };
}

/**
 * Build a minimal JWT with the given role claim.
 */
function fakeJwt(role: string): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = btoa(JSON.stringify({ sub: "user-1", role }));
  return `${header}.${payload}.fakesig`;
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.resetAllMocks();
  // Default: ri role
  vi.stubGlobal("localStorage", {
    getItem: vi.fn((key: string) =>
      key === "nex_studio_token" ? fakeJwt("ri") : null,
    ),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
});

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

async function importPage() {
  const mod = await import("@/pages/VersionDetailPage");
  return mod.default;
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("VersionDetailPage", () => {
  it("disables release button when blocking EPICs exist", async () => {
    const version = makeVersion({ epic_count: 10, epics_done: 7 });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    const releaseBtn = screen.getByTestId("release-version-btn");
    expect(releaseBtn).toBeDisabled();
  });

  it("enables release button when all EPICs are done", async () => {
    const version = makeVersion({ epic_count: 5, epics_done: 5 });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    const releaseBtn = screen.getByTestId("release-version-btn");
    expect(releaseBtn).not.toBeDisabled();
  });

  it("shows blocking warning in ReleaseVersionDialog", async () => {
    const version = makeVersion({ epic_count: 10, epics_done: 6 });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    // Release button is disabled — but we can still open the dialog
    // by making a version where button is enabled and then checking dialog
    // Re-render with all done to open dialog
    getVersionMock.mockResolvedValueOnce(
      makeVersion({ epic_count: 10, epics_done: 6 }),
    );

    // For blocking warning test, we test the dialog component directly
    const dialogMod = await import(
      "@/components/versions/ReleaseVersionDialog"
    );
    const ReleaseVersionDialog = dialogMod.default;

    const onReleased = vi.fn();
    const onClose = vi.fn();

    const { unmount } = render(
      <ReleaseVersionDialog
        version={version}
        onReleased={onReleased}
        onClose={onClose}
      />,
    );

    expect(screen.getByTestId("blocking-warning")).toBeInTheDocument();
    expect(screen.getByTestId("blocking-warning")).toHaveTextContent(
      "4 EPICs not completed",
    );
    expect(screen.getByTestId("release-confirm-btn")).toBeDisabled();

    unmount();
  });

  it("completes release successfully", async () => {
    const version = makeVersion({ epic_count: 5, epics_done: 5 });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    // Click the release button to open dialog
    const releaseBtn = screen.getByTestId("release-version-btn");
    expect(releaseBtn).not.toBeDisabled();
    fireEvent.click(releaseBtn);

    // Dialog should appear
    await waitFor(() => {
      expect(screen.getByTestId("release-dialog")).toBeInTheDocument();
    });

    // Confirm button should be enabled (all epics done)
    const confirmBtn = screen.getByTestId("release-confirm-btn");
    expect(confirmBtn).not.toBeDisabled();

    // Mock release API
    const releasedVersion = makeVersion({
      epic_count: 5,
      epics_done: 5,
      status: "released",
      release_date: "2026-04-16",
    });
    releaseVersionMock.mockResolvedValueOnce(releasedVersion);

    // Click confirm
    fireEvent.click(confirmBtn);

    // Dialog should close and version should update
    await waitFor(() => {
      expect(
        screen.queryByTestId("release-dialog"),
      ).not.toBeInTheDocument();
    });

    expect(releaseVersionMock).toHaveBeenCalledWith("v-001");
  });

  it("shows error on 422 release failure", async () => {
    const version = makeVersion({ epic_count: 5, epics_done: 5 });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    // Open dialog
    fireEvent.click(screen.getByTestId("release-version-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("release-dialog")).toBeInTheDocument();
    });

    // Mock 422 error
    const { ApiError } = await import(
      "@/services/api"
    );
    releaseVersionMock.mockRejectedValueOnce(
      new ApiError(422, "Blocking EPICs remain"),
    );

    // Click confirm
    fireEvent.click(screen.getByTestId("release-confirm-btn"));

    // Error should appear in dialog
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Blocking EPICs remain",
      );
    });

    // Dialog should still be open
    expect(screen.getByTestId("release-dialog")).toBeInTheDocument();
  });

  it("hides release button for non-ri role", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) =>
        key === "nex_studio_token" ? fakeJwt("ha") : null,
      ),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    const version = makeVersion({ epic_count: 5, epics_done: 5 });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    expect(
      screen.queryByTestId("release-version-btn"),
    ).not.toBeInTheDocument();
  });

  it("hides release button for released version", async () => {
    const version = makeVersion({ status: "released" });
    getVersionMock.mockResolvedValueOnce(version);

    const Page = await importPage();
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByTestId("version-title")).toHaveTextContent("1.0.0");
    });

    expect(
      screen.queryByTestId("release-version-btn"),
    ).not.toBeInTheDocument();
  });
});
