import api from "../api";

/** A text file read from under ``/opt/projects/<slug>/`` (backend ``GET /project-specs/content``). */
export interface ProjectSpecContent {
  relative_path: string;
  content: string;
  is_text: boolean;
}

/**
 * Read a project file by its repo-relative path (CR-V2-035). The Vývoj phase tabs use this to render the
 * FULL durable artifact — the Špecifikácia (``specification.md``) / návrhový dokument (``design.md``) —
 * so the Manažér can read the whole document before approving, not just the gate_report summary.
 */
export function getProjectSpecContent(slug: string, path: string): Promise<ProjectSpecContent> {
  return api.get<ProjectSpecContent>("/project-specs/content", { params: { slug, path } });
}
