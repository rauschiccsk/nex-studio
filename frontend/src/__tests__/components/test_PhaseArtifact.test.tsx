/**
 * PhaseArtifact — reads the FULL phase document, not just the gate_report summary (CR-V2-035).
 *
 * Vývoj → Príprava must show the whole `specification.md` so the Manažér can read it before approving
 * (the summary alone was not enough to decide). The gate_report summary stays the fallback when the file
 * is not (yet) readable.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const { getProjectSpecContentMock } = vi.hoisted(() => ({ getProjectSpecContentMock: vi.fn() }));

vi.mock("@/services/api/projectSpecs", () => ({ getProjectSpecContent: getProjectSpecContentMock }));
vi.mock("@/store/activeContextStore", () => ({
  useActiveContextStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      selectedProject: { slug: "nex-agents", name: "NEX Agents" },
      selectedVersion: { versionId: "v1", versionNumber: "0.1.0" },
    }),
}));

import { PhaseArtifact } from "@/components/cockpit/PhaseArtifact";
import type { PipelineMessage } from "@/services/api/pipeline";

function gateReport(report: string): PipelineMessage {
  return {
    id: "m1",
    version_id: "v1",
    stage: "priprava",
    author: "ai_agent",
    recipient: "manazer",
    kind: "gate_report",
    content: "Jednoriadkové zhrnutie.",
    status: "delivered",
    payload: { report },
    created_at: "2026-06-28T00:00:00Z",
    seq: 1,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PhaseArtifact — full spec reading (CR-V2-035)", () => {
  it("renders the full specification.md (not just the gate_report summary)", async () => {
    getProjectSpecContentMock.mockResolvedValue({
      relative_path: "nex-agents/docs/specs/versions/v0.1.0/specification.md",
      content: "# Špecifikácia\n\n## Prehľad\nCelý dokument s detailmi XYZ.",
      is_text: true,
    });

    render(<PhaseArtifact phase="priprava" messages={[gateReport("Krátke zhrnutie.")]} placeholder="—" />);

    expect(await screen.findByText(/Celý dokument s detailmi XYZ/)).toBeInTheDocument();
    expect(getProjectSpecContentMock).toHaveBeenCalledWith(
      "nex-agents",
      "docs/specs/versions/v0.1.0/specification.md",
    );
  });

  it("falls back to the gate_report summary when the file is not readable", async () => {
    getProjectSpecContentMock.mockRejectedValue(new Error("not found"));

    render(<PhaseArtifact phase="priprava" messages={[gateReport("Krátke zhrnutie ABC.")]} placeholder="—" />);

    expect(await screen.findByText(/Krátke zhrnutie ABC/)).toBeInTheDocument();
  });
});
