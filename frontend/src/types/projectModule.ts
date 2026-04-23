/**
 * TypeScript type definitions for the ``ProjectModule`` domain object.
 *
 * Mirrors ``backend.schemas.project_module`` — a project module is the
 * per-module record for a multi-module project (e.g. NEX Horizont).
 */

/**
 * Mirrors ``status IN ('planned', 'in_design', 'in_development', 'done')``
 * on the ``project_modules`` table.
 */
export type ProjectModuleStatus =
  | "planned"
  | "in_design"
  | "in_development"
  | "done";

/**
 * Allowed SK-localized category labels for a project module.
 * Mirrors ``ck_project_modules_category`` (migration 031) and the
 * Pydantic ``ProjectModuleCategory`` literal on the backend.
 */
export type ProjectModuleCategory =
  | "Systém"
  | "Katalógy"
  | "Sklad"
  | "Predaj"
  | "Nákup"
  | "Účtovníctvo"
  | "Pokladňa";

/** Ordered list of category labels — used to populate the new-module dropdown. */
export const PROJECT_MODULE_CATEGORIES: ProjectModuleCategory[] = [
  "Systém",
  "Katalógy",
  "Sklad",
  "Predaj",
  "Nákup",
  "Účtovníctvo",
  "Pokladňa",
];

/** Payload for creating a new project module. */
export interface ProjectModuleCreate {
  project_id: string;
  /**
   * Kebab-case module code, unique within the project
   * (e.g. ``partner-catalog``). Must match
   * ``^[a-z][a-z0-9-]*[a-z0-9]$`` — enforced by backend regex +
   * ``ck_project_modules_code_format`` (migration 032).
   */
  code: string;
  /** Full human-readable module name. */
  name: string;
  /** Module grouping (e.g. ``Katalógy``). */
  category: string;
  /** Lifecycle status; server default ``planned``. */
  status?: ProjectModuleStatus;
  /** Absolute filesystem path to the module DESIGN.md in the KB. */
  design_doc_path?: string | null;
}

/**
 * Partial update for an existing project module.
 *
 * ``project_id`` is immutable — a module belongs to one project for
 * its lifetime.
 */
export interface ProjectModuleUpdate {
  code?: string;
  name?: string;
  category?: string;
  status?: ProjectModuleStatus;
  design_doc_path?: string | null;
}

/** Serialised representation of a project module row. */
export interface ProjectModuleRead {
  id: string;
  project_id: string;
  code: string;
  name: string;
  category: string;
  status: ProjectModuleStatus;
  design_doc_path: string | null;
  /** ISO-8601 timestamp. */
  created_at: string;
  /** ISO-8601 timestamp. */
  updated_at: string;
}
