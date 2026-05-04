/**
 * TypeScript type definitions for the ``KbDocument`` domain object.
 *
 * Mirrors ``backend.schemas.kb_document`` — knowledge-base documents
 * with optional Qdrant indexing metadata.
 */

/**
 * KB document category code.
 *
 * The backend (``backend/constants/kb_categories.py``) is the single
 * source of truth for the allowed category set; the frontend treats it
 * as an open string to avoid drift (Clean Code §2 DRY). Components
 * fetch the live list via ``GET /api/v1/kb-documents/categories`` and
 * render whatever the backend currently allows.
 */
export type KbDocumentCategory = string;

/** Single category entry returned by ``GET /kb-documents/categories``. */
export interface KbDocumentCategoryWithCount {
  code: KbDocumentCategory;
  count: number;
}

/** Payload for creating a new knowledge-base document. */
export interface KbDocumentCreate {
  /** ``null`` denotes an ICC-wide document. */
  project_id?: string | null;
  /** ``null`` denotes a project-level or ICC-wide document. */
  module_id?: string | null;
  title: string;
  /** Absolute path to the document on the ANDROS filesystem. */
  file_path: string;
  /** Document category discriminator. */
  doc_category: KbDocumentCategory;
  /** Qdrant collection holding the vectorised content. */
  qdrant_collection?: string | null;
  /** Qdrant point identifier; ``null`` until indexed. */
  qdrant_point_id?: string | null;
  /** ISO-8601 timestamp of the most recent Qdrant indexing run. */
  indexed_at?: string | null;
}

/**
 * Partial update for an existing knowledge-base document.
 *
 * ``project_id`` and ``doc_category`` are immutable; ``module_id``
 * remains mutable because project-level / ICC-wide scope is expressed
 * through the same column.
 */
export interface KbDocumentUpdate {
  module_id?: string | null;
  title?: string;
  file_path?: string;
  qdrant_collection?: string | null;
  qdrant_point_id?: string | null;
  indexed_at?: string | null;
}

/** Serialised representation of a KB document row. */
export interface KbDocumentRead {
  id: string;
  project_id: string | null;
  module_id: string | null;
  title: string;
  file_path: string;
  doc_category: KbDocumentCategory;
  qdrant_collection: string | null;
  qdrant_point_id: string | null;
  indexed_at: string | null;
  /** ISO-8601 timestamp. */
  created_at: string;
  /** ISO-8601 timestamp. */
  updated_at: string;
}
