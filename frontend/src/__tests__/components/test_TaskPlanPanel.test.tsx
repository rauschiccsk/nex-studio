/**
 * Component tests for TaskPlanPanel (CR-NS-020 CR-5).
 *
 * Renders the EPIC→FEAT→TASK tree (with per-node status) from getTaskPlan, and on a task
 * click shows the per-task audit verdict matched from the live message stream by
 * payload.task_id (the Auditor turn's tag).
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import TaskPlanPanel from "@/components/cockpit/TaskPlanPanel";
import type { PipelineMessage } from "@/services/api/pipeline";
import type { TaskPlanResponse, TaskNodeStatus } from "@/types/task-plan";
import { getTaskPlan } from "@/services/api/versions";

vi.mock("@/services/api/versions", () => ({ getTaskPlan: vi.fn() }));

const PLAN: TaskPlanResponse = {
  plan: [
    {
      id: "e1",
      number: 1,
      title: "Foundation",
      status: "in_progress",
      feats: [
        {
          id: "f1",
          number: 1,
          title: "Schema",
          status: "in_progress",
          tasks: [
            { id: "t1", number: 1, title: "GL tables", task_type: "migration", status: "in_progress", priority: "normal", checklist_type: null, description: "" },
            { id: "t2", number: 2, title: "AP tables", task_type: "migration", status: "todo", priority: "normal", checklist_type: null, description: "" },
          ],
        },
      ],
    },
  ],
  epic_count: 1,
  feat_count: 1,
  task_count: 2,
};

function mkMsg(over: Partial<PipelineMessage>): PipelineMessage {
  return {
    id: `m${Math.random()}`,
    version_id: "v1",
    stage: "build",
    author: "auditor",
    recipient: "director",
    kind: "gate_report",
    content: "",
    status: "delivered",
    payload: {},
    created_at: "2026-06-08T00:00:00Z",
    seq: 1,
    ...over,
  };
}

describe("TaskPlanPanel (CR-NS-020 CR-5)", () => {
  beforeEach(() => {
    vi.mocked(getTaskPlan).mockResolvedValue(PLAN);
  });

  it("renders the EPIC→FEAT→TASK tree with status labels", async () => {
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText(/Foundation/)).toBeInTheDocument();
    expect(screen.getByText(/Schema/)).toBeInTheDocument();
    expect(screen.getByText(/GL tables/)).toBeInTheDocument();
    expect(screen.getByText(/AP tables/)).toBeInTheDocument();
    expect(screen.getAllByText("Prebieha").length).toBeGreaterThan(0); // in_progress
    expect(screen.getByText("Čaká")).toBeInTheDocument(); // todo
  });

  it("shows the per-task audit verdict matched by payload.task_id on task click", async () => {
    const messages = [
      mkMsg({ author: "auditor", stage: "build", payload: { task_id: "t1", task_pass: false, findings: ["chýba podvojnosť"] } }),
    ];
    render(<TaskPlanPanel versionId="v1" messages={messages} />);
    const task = await screen.findByText(/GL tables/);
    task.closest("button")!.click();
    expect(await screen.findByText("Audit FAIL")).toBeInTheDocument();
    expect(screen.getByText("chýba podvojnosť")).toBeInTheDocument();
  });
});

function planWith(statuses: TaskNodeStatus[]): TaskPlanResponse {
  return {
    plan: [
      {
        id: "e1",
        number: 1,
        title: "Epic",
        status: "in_progress",
        feats: [
          {
            id: "f1",
            number: 1,
            title: "Feat",
            status: "in_progress",
            tasks: statuses.map((status, i) => ({
              id: `t${i + 1}`,
              number: i + 1,
              title: `Task ${i + 1}`,
              task_type: "backend",
              status,
              priority: "normal",
              checklist_type: null,
              description: "",
            })),
          },
        ],
      },
    ],
    epic_count: 1,
    feat_count: 1,
    task_count: statuses.length,
  };
}

const EMPTY_PLAN: TaskPlanResponse = { plan: [], epic_count: 0, feat_count: 0, task_count: 0 };

describe("TaskPlanPanel — build progress indicator (CR-NS-025 Part 2 / CR-NS-026 'Stav' polish)", () => {
  it("renders the 'Stav' heading + % of tasks done for a mixed plan (3/8 → 38 %)", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(
      planWith(["done", "done", "done", "in_progress", "todo", "todo", "todo", "todo"]),
    );
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText(/Stav:/)).toBeInTheDocument(); // renamed from "Postup" (CR-NS-026)
    expect(screen.getByText(/3\/8 úloh/)).toBeInTheDocument();
    expect(screen.getByText(/38 %/)).toBeInTheDocument();
    expect(screen.getByTestId("taskplan-progress-fill")).toHaveClass("from-amber-500"); // <100 → amber
  });

  it("shows 100 % and a green bar when all tasks are done", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith(["done", "done", "done"]));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText(/3\/3 úloh/)).toBeInTheDocument();
    expect(screen.getByText(/100 %/)).toBeInTheDocument();
    expect(screen.getByTestId("taskplan-progress-fill")).toHaveClass("from-emerald-500"); // 100 → green
  });

  it("surfaces the failed count in red when any task failed", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith(["done", "failed", "todo", "failed"]));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText(/1\/4 úloh/)).toBeInTheDocument();
    expect(screen.getByText(/25 %/)).toBeInTheDocument();
    expect(screen.getByText(/· 2 zlyhané/)).toBeInTheDocument();
  });

  it("hides the indicator when there is no plan", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(EMPTY_PLAN);
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText("Plán úloh ešte nebol vytvorený.")).toBeInTheDocument();
    expect(screen.queryByText(/Stav:/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("taskplan-progress-fill")).not.toBeInTheDocument();
  });

  it("hides the indicator when a plan has epics but zero tasks (no '0/0' state)", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith([])); // one epic/feat, no tasks → totalCount 0
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText(/Epic/)).toBeInTheDocument(); // the tree still renders the epic
    expect(screen.queryByText(/Stav:/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("taskplan-progress-fill")).not.toBeInTheDocument();
  });

  it("hides the indicator on a fetch error (consistent with the tree's error state)", async () => {
    vi.mocked(getTaskPlan).mockRejectedValue(new Error("Načítanie plánu zlyhalo"));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText("Načítanie plánu zlyhalo")).toBeInTheDocument();
    expect(screen.queryByText(/Stav:/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("taskplan-progress-fill")).not.toBeInTheDocument();
  });
});

describe("TaskPlanPanel — parent-status rollup from descendant tasks (CR-NS-026)", () => {
  // planWith builds 1 epic / 1 feat / N tasks, so the epic and feat both roll up from the same set.
  it("rolls FEAT + EPIC up to in_progress when any task is in_progress", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith(["done", "in_progress", "todo"]));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    // epic + feat + the in_progress task → "Prebieha" ≥3× (parents derived, not the lagging DB status)
    expect((await screen.findAllByText("Prebieha")).length).toBeGreaterThanOrEqual(3);
  });

  it("rolls up to done when all tasks are done", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith(["done", "done"]));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect((await screen.findAllByText("Hotovo")).length).toBeGreaterThanOrEqual(4); // epic + feat + 2 tasks
    expect(screen.queryByText("Prebieha")).not.toBeInTheDocument();
  });

  it("rolls up to failed when a task failed and none is in_progress (failed beats done/todo)", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith(["done", "failed", "todo"]));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect((await screen.findAllByText("Zlyhalo")).length).toBeGreaterThanOrEqual(3); // epic + feat + failed task
    expect(screen.queryByText("Prebieha")).not.toBeInTheDocument();
  });

  it("rests at todo (feat) / planned (epic) when all tasks are todo", async () => {
    vi.mocked(getTaskPlan).mockResolvedValue(planWith(["todo", "todo"]));
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect(await screen.findByText("Naplánované")).toBeInTheDocument(); // epic resting label (unique)
    expect(screen.getAllByText("Čaká").length).toBeGreaterThanOrEqual(1); // feat + tasks at todo
  });

  it("falls back to the DB node status when a feat/epic has no tasks (no false 'todo')", async () => {
    // Review-found edge: with zero tasks the children tell us nothing, so trust the authoritative DB
    // status — a done feat/epic with an empty tasks array must read "Hotovo", never "Čaká"/"Naplánované".
    vi.mocked(getTaskPlan).mockResolvedValue({
      plan: [
        {
          id: "e1",
          number: 1,
          title: "Epic",
          status: "done",
          feats: [{ id: "f1", number: 1, title: "Feat", status: "done", tasks: [] }],
        },
      ],
      epic_count: 1,
      feat_count: 1,
      task_count: 0,
    });
    render(<TaskPlanPanel versionId="v1" messages={[]} />);
    expect((await screen.findAllByText("Hotovo")).length).toBeGreaterThanOrEqual(2); // epic + feat via DB fallback
    expect(screen.queryByText("Čaká")).not.toBeInTheDocument();
    expect(screen.queryByText("Naplánované")).not.toBeInTheDocument();
  });
});
