/**
 * PipelineMessageBubble rendering (CR-NS-053 Pillar A §A.3).
 *
 * The Coordinator's synthesis (payload.is_synthesis) is the PRIMARY Director-facing message
 * (prominent primary rail + "Zhrnutie" badge); a raw worker gate_report is SECONDARY (dimmed +
 * "pôvodný report"); a normal message (question/answer) is neither.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import PipelineMessageBubble from "@/components/cockpit/PipelineMessageBubble";
import type { PipelineMessage } from "@/services/api/pipeline";

function mkMessage(overrides: Partial<PipelineMessage> = {}): PipelineMessage {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    version_id: "22222222-2222-2222-2222-222222222222",
    stage: "gate_a",
    author: "designer",
    recipient: "director",
    kind: "gate_report",
    content: "hotovo",
    status: "delivered",
    payload: null,
    created_at: "2026-06-13T00:00:00Z",
    seq: 1,
    ...overrides,
  };
}

describe("PipelineMessageBubble — synthesis rendering (CR-NS-053 §A.3)", () => {
  it("renders a synthesis (payload.is_synthesis) as primary: 'Zhrnutie' badge + prominent primary rail", () => {
    const { container } = render(
      <PipelineMessageBubble
        message={mkMessage({ author: "coordinator", kind: "answer", payload: { is_synthesis: true } })}
      />,
    );
    expect(screen.getByText("Zhrnutie")).toBeInTheDocument();
    expect(screen.queryByText("pôvodný report")).not.toBeInTheDocument();
    // prominent primary rail (vs the per-author accent / dim of a raw report)
    expect((container.firstChild as HTMLElement).className).toContain("border-primary-500");
  });

  it("renders a raw worker gate_report as secondary: dimmed + 'pôvodný report'", () => {
    const { container } = render(
      <PipelineMessageBubble message={mkMessage({ author: "designer", kind: "gate_report", payload: null })} />,
    );
    expect(screen.getByText("pôvodný report")).toBeInTheDocument();
    expect(screen.queryByText("Zhrnutie")).not.toBeInTheDocument();
    expect((container.firstChild as HTMLElement).className).toContain("opacity-60");
  });

  it("renders a normal message (question) as neither synthesis nor raw-report", () => {
    const { container } = render(
      <PipelineMessageBubble message={mkMessage({ author: "designer", kind: "question", payload: null })} />,
    );
    expect(screen.getByText("question")).toBeInTheDocument();
    expect(screen.queryByText("Zhrnutie")).not.toBeInTheDocument();
    expect(screen.queryByText("pôvodný report")).not.toBeInTheDocument();
    expect((container.firstChild as HTMLElement).className).not.toContain("opacity-60");
  });

  it("does NOT dim a coordinator gate_report (only worker-authored raw reports are secondary)", () => {
    const { container } = render(
      <PipelineMessageBubble message={mkMessage({ author: "coordinator", kind: "gate_report", payload: null })} />,
    );
    expect(screen.queryByText("pôvodný report")).not.toBeInTheDocument();
    expect((container.firstChild as HTMLElement).className).not.toContain("opacity-60");
  });

  // CR-NS-055 Pillar B (§B.3): an autonomous Coordinator decision renders distinctly.
  it("renders an autonomous decision (payload.is_autonomous) with the 'Koordinátor rozhodol' badge + amber rail", () => {
    const { container } = render(
      <PipelineMessageBubble
        message={mkMessage({
          author: "coordinator",
          kind: "notification",
          content: "Koordinátor rozhodol: reset úlohy",
          payload: { is_autonomous: true, action: "coordinator_reset_task" },
        })}
      />,
    );
    expect(screen.getByText("Koordinátor rozhodol")).toBeInTheDocument();
    expect(screen.queryByText("Zhrnutie")).not.toBeInTheDocument();
    expect((container.firstChild as HTMLElement).className).toContain("border-amber-500");
  });
});
