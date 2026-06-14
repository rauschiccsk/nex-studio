/**
 * PipelineRail agent chips — unified status colours (CR-NS-028).
 * working = blue (sky), awaiting = amber, blocked = red, idle = neutral — never emerald-for-working.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import PipelineRail from "@/components/cockpit/PipelineRail";
import type { PipelineState, PipelineStatus } from "@/services/api/pipeline";

function mkState(status: PipelineStatus): PipelineState {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    version_id: "22222222-2222-2222-2222-222222222222",
    flow_type: "new_version",
    current_stage: "build",
    current_actor: "implementer",
    status,
    next_action: "",
    is_regate: false,
    iteration: 0,
    created_at: "2026-06-09T00:00:00Z",
    updated_at: "2026-06-09T00:00:00Z",
  };
}

describe("PipelineRail — unified chip colours (CR-NS-028)", () => {
  it("the active agent's working chip = blue (not emerald)", () => {
    render(<PipelineRail state={mkState("agent_working")} activeAgent="implementer" />);
    const chip = screen.getByText("working");
    // CR-NS-067c: TONE_TEXT is now theme-aware (text-X-600 dark:text-X-400) — assert the light base.
    expect(chip).toHaveClass("text-sky-600");
    expect(chip).not.toHaveClass("text-emerald-600"); // no emerald-for-working
  });

  it("awaiting chip = amber, blocked chip = red", () => {
    const { rerender } = render(<PipelineRail state={mkState("awaiting_director")} activeAgent="implementer" />);
    expect(screen.getByText("awaiting")).toHaveClass("text-amber-600");
    rerender(<PipelineRail state={mkState("blocked")} activeAgent="implementer" />);
    expect(screen.getByText("blocked")).toHaveClass("text-red-600");
  });
});
