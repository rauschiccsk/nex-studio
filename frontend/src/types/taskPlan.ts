/**
 * TypeScript types for the Task Plan pipeline.
 *
 * Mirrors the SSE event schema emitted by
 * ``POST /api/v1/versions/{id}/generate-task-plan``
 * and the REST response from
 * ``GET /api/v1/versions/{id}/task-plan``.
 */

export type TaskPriority = "normal" | "high" | "urgent";
export type TaskStatus = "todo" | "in_progress" | "done" | "failed";
export type FeatStatus = "todo" | "in_progress" | "done" | "failed";
export type EpicStatus = "planned" | "in_progress" | "done";

/** A single task within a feat. */
export interface TaskPlanTask {
  id: string;
  number: number;
  title: string;
  description: string;
  task_type: "backend" | "frontend" | "migration" | "test" | "docs";
  checklist_type: string | null;
  status: TaskStatus;
  priority: TaskPriority;
}

/** A feat grouping tasks within an epic. */
export interface TaskPlanFeat {
  id: string;
  number: number;
  title: string;
  status: FeatStatus;
  tasks: TaskPlanTask[];
}

/** An epic grouping feats within a version. */
export interface TaskPlanEpic {
  id: string;
  number: number;
  title: string;
  status: EpicStatus;
  feats: TaskPlanFeat[];
}

/** SSE event emitted during task plan generation / append-epic. */
export type TaskPlanEvent =
  | { type: "progress"; message: string; percent: number }
  | {
      type: "done";
      plan: TaskPlanEpic[];
      epic_count: number;
      feat_count: number;
      task_count: number;
    }
  | { type: "error"; content: string }
  | { type: "validation_error"; content: string };
