/**
 * Unit tests for {@link VersionsPage}.
 *
 * Tests cover:
 *   1. Rendering the version table with data
 *   2. Progress calculation (epics_done / epic_count)
 *   3. ``ri``-only buttons (New Version, Edit, Release)
 *
 * Dependencies are mocked at the module boundary:
 *   - ``react-router-dom`` — stub ``useParams``
 *   - ``../services/api/versions`` — stub ``listVersions``
 *   - ``localStorage`` — control JWT role claim
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { Version } from "@/types/version";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock react-router-dom — include Link as a simple anchor stub
vi.mock("react-router-dom", () => ({
  useParams: vi.fn(() => ({ slug: "test-project" })),
  Link: ({ to, children, ...rest }: { to: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={to} {...rest}>{children}</a>
  ),
}));

// Mock API module
const listVersionsMock: Mock = vi.fn();
vi.mock("@/services/api/versions", () => ({
  listVersions: (...args: unknown[]) => listVersionsMock(...args),
  createVersion: vi.fn(),
  releaseVersion: vi.fn(),
}));

// Mock api error import + token key — constructor signature matches real ApiError
vi.mock("@/services/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    data: unknown;
    constructor(status: number, message: string, data: unknown = null) {
      super(message);
      this.status = status;
      this.data = data;
    }
  },
  TOKEN_STORAGE_KEY: "nex_studio_token",
}));

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

function makeVersion(overrides: Partial<Version> = {}): Version {
  return {
    id: "v-001",
    project_id: "p-001",
    version_number: "1.0.0",
    name: "Alpha",
    status: "planned",
    description: null,
    target_date: "2026-06-01",
    release_date: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    epic_count: 10,
    epics_done: 3,
    bug_count: 2,
    ...overrides,
  };
}

/**
 * Build a minimal JWT with the given role claim.
 * The token is not cryptographically valid — only the payload matters
 * because the page decodes it with ``atob`` for UI-only role checks.
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
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

// Lazy import so mocks are registered first
async function importPage() {
  const mod = await import("@/pages/VersionsPage");
  return mod.default;
}

describe("VersionsPage", () => {
  it("renders version rows with correct data", async () => {
    const versions = [
      makeVersion({ id: "v-1", version_number: "1.0.0", name: "Alpha" }),
      makeVersion({
        id: "v-2",
        version_number: "2.0.0",
        name: "Beta",
        status: "active",
      }),
    ];
    listVersionsMock.mockResolvedValueOnce(versions);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(screen.getByText("1.0.0")).toBeInTheDocument();
    });
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("2.0.0")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("displays correct progress label (epics_done/epic_count EPICs)", async () => {
    const versions = [
      makeVersion({ epic_count: 8, epics_done: 5 }),
    ];
    listVersionsMock.mockResolvedValueOnce(versions);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(screen.getByText("5/8 EPICs")).toBeInTheDocument();
    });
  });

  it("shows 0% progress when epic_count is 0", async () => {
    const versions = [
      makeVersion({ epic_count: 0, epics_done: 0 }),
    ];
    listVersionsMock.mockResolvedValueOnce(versions);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(screen.getByText("0/0 EPICs")).toBeInTheDocument();
    });

    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).toBe("0");
  });

  it("shows New Version, Edit and Release buttons for ri role", async () => {
    const versions = [makeVersion({ status: "active" })];
    listVersionsMock.mockResolvedValueOnce(versions);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("new-version-btn")).toBeInTheDocument();
    });
    expect(screen.getByTestId("edit-btn-v-001")).toBeInTheDocument();
    expect(screen.getByTestId("release-btn-v-001")).toBeInTheDocument();
  });

  it("hides action buttons for non-ri role", async () => {
    // Override localStorage to return non-ri JWT
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) =>
        key === "nex_studio_token" ? fakeJwt("ha") : null,
      ),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    const versions = [makeVersion({ status: "active" })];
    listVersionsMock.mockResolvedValueOnce(versions);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(screen.getByText("1.0.0")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("new-version-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("edit-btn-v-001")).not.toBeInTheDocument();
    expect(screen.queryByTestId("release-btn-v-001")).not.toBeInTheDocument();
  });

  it("hides Release button when version is already released", async () => {
    const versions = [makeVersion({ status: "released" })];
    listVersionsMock.mockResolvedValueOnce(versions);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("edit-btn-v-001")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("release-btn-v-001")).not.toBeInTheDocument();
  });

  it("shows loading state initially", async () => {
    // Never-resolving promise to keep loading state
    listVersionsMock.mockReturnValueOnce(new Promise(() => {}));

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    expect(screen.getByText("Loading versions…")).toBeInTheDocument();
  });

  it("shows empty state when no versions exist", async () => {
    listVersionsMock.mockResolvedValueOnce([]);

    const VersionsPage = await importPage();
    render(<VersionsPage />);

    await waitFor(() => {
      expect(
        screen.getByText("No versions found for this project."),
      ).toBeInTheDocument();
    });
  });
});
