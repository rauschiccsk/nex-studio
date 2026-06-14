/**
 * E5 (CR-NS-044) — MetricsPage renders the ROI shape and is HONEST: unset pricing/estimates show
 * "nenastavené" with a Settings link, never a fabricated number.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { ProjectMetrics } from "@/types/metrics";

const { mockGetMetrics } = vi.hoisted(() => ({ mockGetMetrics: vi.fn() }));

vi.mock("@/services/api/metrics", () => ({ getProjectMetricsApi: mockGetMetrics }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useParams: () => ({ slug: "p1" }), useNavigate: () => vi.fn() };
});

vi.mock("@/store/activeContextStore", () => ({
  useActiveContextStore: (sel: (s: unknown) => unknown) =>
    sel({ selectedProject: { slug: "p1", name: "Projekt 1" } }),
}));

// Recharts needs real layout dimensions (jsdom has none) — stub to plain wrappers.
vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Empty = () => null;
  return {
    ResponsiveContainer: Passthrough,
    BarChart: Passthrough,
    Bar: Empty,
    XAxis: Empty,
    YAxis: Empty,
    Tooltip: Empty,
    Legend: Empty,
    CartesianGrid: Empty,
  };
});

import MetricsPage from "@/pages/MetricsPage";
// MetricsPage now reads useTheme() for theme-aware chart colors (CR-NS-067b) → needs ThemeProvider.
import { ThemeProvider } from "@/contexts/ThemeContext";

const usage = { input_tokens: 1000, output_tokens: 500, duration_seconds: 600, messages: 3 };
const version = {
  version_id: "v1",
  version_number: "1.0.0",
  status: "active",
  usage,
  by_epic: [],
  by_feat: [],
  by_task: [],
  by_role: [{ role: "implementer", usage }],
  director_wait_seconds: 120,
  total_time_seconds: null,
  api_cost: null,
};

const UNSET: ProjectMetrics = {
  project_id: "pid",
  slug: "p1",
  usage,
  api_cost: null,
  director_wait_seconds: 120,
  total_time_seconds: null,
  by_version: [version],
  roi: {
    human_minutes: 0,
    ai_compute_minutes: 10,
    human_cost: null,
    api_cost: null,
    x_faster: null,
    y_cheaper_pct: null,
    configured: false,
  },
  pricing_configured: false,
  estimates_configured: false,
};

const CONFIGURED: ProjectMetrics = {
  ...UNSET,
  api_cost: 0.0285,
  by_version: [{ ...version, api_cost: 0.0285 }],
  roi: {
    human_minutes: 120,
    ai_compute_minutes: 10,
    human_cost: 120,
    api_cost: 0.0285,
    x_faster: 240,
    y_cheaper_pct: 99.97,
    configured: true,
  },
  pricing_configured: true,
  estimates_configured: true,
};

describe("MetricsPage (E5 / CR-NS-044)", () => {
  beforeEach(() => mockGetMetrics.mockReset());

  it("renders the headline ROI when configured", async () => {
    mockGetMetrics.mockResolvedValue(CONFIGURED);
    render(
      <ThemeProvider username="test">
        <MetricsPage />
      </ThemeProvider>,
    );
    await waitFor(() => expect(screen.getByText(/Metriky/i)).toBeInTheDocument());
    expect(screen.getByText(/240×/)).toBeInTheDocument();
    expect(screen.queryByText(/Ceny nenastavené/i)).toBeNull();
  });

  it("shows 'nenastavené' (never a fake number) when pricing + estimates are unset", async () => {
    mockGetMetrics.mockResolvedValue(UNSET);
    render(
      <ThemeProvider username="test">
        <MetricsPage />
      </ThemeProvider>,
    );
    await waitFor(() => expect(screen.getByText(/Metriky/i)).toBeInTheDocument());
    // the unset banner + a Settings link, not a fabricated cost
    expect(screen.getAllByText(/nenastavené/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Nastavenia/i })).toBeInTheDocument();
    // Director-wait is still shown (it's measured, not priced)
    expect(screen.getByText(/Čakanie na Directora/i)).toBeInTheDocument();
  });
});
