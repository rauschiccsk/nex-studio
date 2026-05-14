/**
 * API client for ``/api/v1/project-specs/*``.
 *
 * Backend: :file:`backend/api/routes/project_specs.py`. Surfaces a
 * filesystem view of every project's ``/opt/projects/<slug>/docs/``
 * tree so the unified KbTree component can render them in a single
 * page (see :file:`src/pages/ProjectSpecsPage.tsx`).
 */

import { api } from "@/services/api";
import type { KnowledgeDoc } from "@/types/knowledge";

interface ListResponse {
  documents: KnowledgeDoc[];
  count: number;
}

export interface ContentResponse {
  relative_path: string;
  content: string;
  /** False for binary files — frontend renders a "cannot display"
   *  placeholder instead of the (empty) ``content``. */
  is_text: boolean;
}

interface UpdateResponse {
  relative_path: string;
  status: string;
}

/** List every file + every empty directory under
 *  ``/opt/projects/{slug}/docs/`` (ri only). Director directive
 *  2026-05-14: the view reflects the real filesystem — all extensions,
 *  empty folders included. */
export async function listProjectSpecs(): Promise<KnowledgeDoc[]> {
  const data = await api.get<ListResponse>("/project-specs/list");
  return data.documents;
}

/** Read a single file. ``slug`` is the project, ``path`` is the part
 *  after the slug (must start with ``docs/``). Returns the full
 *  response so the caller can branch on ``is_text``. */
export async function getProjectSpecContent(
  slug: string,
  path: string,
): Promise<ContentResponse> {
  return await api.get<ContentResponse>("/project-specs/content", {
    params: { slug, path },
  });
}

/** Overwrite an existing ``.md`` file (ri only). */
export async function updateProjectSpecContent(
  slug: string,
  path: string,
  content: string,
): Promise<UpdateResponse> {
  return await api.put<UpdateResponse>(
    "/project-specs/content",
    { content },
    { params: { slug, path } },
  );
}

/**
 * Split a tree-relative-path (``<slug>/docs/...``) into the API params
 * the backend expects (``slug`` + ``path`` within the project).
 */
export function splitProjectPath(
  relativePath: string,
): { slug: string; path: string } | null {
  const idx = relativePath.indexOf("/");
  if (idx < 0) return null;
  return {
    slug: relativePath.slice(0, idx),
    path: relativePath.slice(idx + 1),
  };
}
