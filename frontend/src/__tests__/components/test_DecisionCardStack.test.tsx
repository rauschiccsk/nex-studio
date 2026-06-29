/**
 * DecisionCardStack — the interactive consultation surface (CR-V2-041). Renders the AI Agent's decision
 * queue ONE card at a time so a non-expert Manažér resolves a blocked build by clicking. Acceptance:
 * a clear "⛔ build stojí" banner, the plain-language question, options with a recommended default, and it
 * reads the ACTUAL consultation message (not a stale gate_report).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import { DecisionCardStack } from "@/components/cockpit/DecisionCardStack";
import type { PipelineMessage } from "@/services/api/pipeline";

function msg(over: Partial<PipelineMessage>): PipelineMessage {
  return {
    id: "m",
    version_id: "v",
    stage: "navrh",
    author: "ai_agent",
    recipient: "manazer",
    kind: "consultation",
    content: "",
    status: "delivered",
    payload: null,
    created_at: "2026-06-29T00:00:00Z",
    seq: 1,
    ...over,
  } as PipelineMessage;
}

const CONSULT = {
  id: "c1",
  source: "auditor_upfront",
  intro: "Treba vyjasniť 2 veci.",
  decisions: [
    {
      key: "d1",
      question: "Otázka jedna?",
      explanation: "Prečo jedna.",
      options: [
        { id: "a", label: "Voľba A", recommended: true },
        { id: "b", label: "Voľba B" },
      ],
      rationale: "Odporúčam A.",
    },
    {
      key: "d2",
      question: "Otázka dva?",
      options: [
        { id: "a", label: "A2", recommended: true },
        { id: "b", label: "B2" },
      ],
    },
  ],
};

const consultMsg = () => msg({ seq: 1, payload: { consultation: CONSULT } });

describe("DecisionCardStack (CR-V2-041)", () => {
  it("shows the ⛔ blocker banner + the first decision card with the recommended badge", () => {
    render(<DecisionCardStack messages={[consultMsg()]} onDecide={vi.fn()} />);
    expect(screen.getByText(/Build stojí — treba tvoje rozhodnutie \(1\/2\)/)).toBeInTheDocument();
    expect(screen.getByText("Otázka jedna?")).toBeInTheDocument();
    expect(screen.getByText("Rozhodnutie 1 z 2")).toBeInTheDocument();
    expect(screen.getByText("Odporúčané")).toBeInTheDocument();
  });

  it("calls onDecide with the picked option", () => {
    const onDecide = vi.fn();
    render(<DecisionCardStack messages={[consultMsg()]} onDecide={onDecide} />);
    fireEvent.click(screen.getByText("Voľba B"));
    fireEvent.click(screen.getByText(/Rozhodnúť/));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ decision_key: "d1", option_id: "b" }));
  });

  it("advances to the next undecided decision once one is answered", () => {
    const answer = msg({
      seq: 2,
      kind: "answer",
      author: "manazer",
      recipient: "ai_agent",
      payload: { consultation_decision: { consultation_id: "c1", key: "d1", label: "Voľba A" } },
    });
    render(<DecisionCardStack messages={[consultMsg(), answer]} onDecide={vi.fn()} />);
    expect(screen.getByText("Otázka dva?")).toBeInTheDocument();
    expect(screen.getByText(/\(2\/2\)/)).toBeInTheDocument();
    expect(screen.getByText(/Voľba A/)).toBeInTheDocument(); // the answered trail
  });

  it("renders nothing without a consultation message", () => {
    const { container } = render(
      <DecisionCardStack messages={[msg({ kind: "gate_report", payload: { report: "x" } })]} onDecide={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
