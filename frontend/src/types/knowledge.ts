/**
 * Knowledge Base document types — extracted from KnowledgeBasePage for
 * reuse across components (KbTree, viewer, search results).
 *
 * Backend source: ``backend/api/routes/knowledge.py`` —
 * ``KnowledgeDoc`` response schema for ``GET /knowledge/documents``.
 */

export interface KnowledgeDoc {
  relative_path: string;
  filename: string;
  category: string;
  size_bytes: number;
  /** Synthetic entry for an empty directory — Project Specs uses this
   *  so users see folders they've created (e.g. an empty ``import/``)
   *  even before any file is added. KB list never sets this field, so
   *  the default ``false`` keeps existing KB behaviour. */
  is_directory?: boolean;
}

/**
 * One node in the KB tree.
 *
 * - ``folder``: hierarchical container (icc/, projects/nex-inbox/, ...)
 * - ``file``: a single ``.md`` document — carries the underlying
 *   ``KnowledgeDoc`` so the page can load its content on click.
 *
 * ``depth`` is 0-indexed (root level = 0, ``icc/X.md`` → ``icc`` is
 * depth 0 and ``X.md`` is depth 1). Used for indentation in the UI.
 */
export type TreeNode =
  | {
      type: "folder";
      path: string;
      name: string;
      depth: number;
      children: TreeNode[];
    }
  | {
      type: "file";
      path: string;
      name: string;
      depth: number;
      doc: KnowledgeDoc;
    };
