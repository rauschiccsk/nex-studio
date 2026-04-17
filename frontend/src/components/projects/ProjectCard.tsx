import { Link } from "react-router-dom";
import { Tag } from "lucide-react";

import type { ProjectRead } from "../../types/project";

/**
 * Compact project summary card — renders a {@link ProjectRead} as a
 * clickable card with status badges.
 *
 * Per DESIGN.md § 3.2 the card shows:
 *   - Project name and description
 *   - Status badge (active / paused / archived)
 *   - Category badge (singlemodule / multimodule)
 *   - Active version badge when ``activeVersion`` is provided
 *
 * The ``activeVersion`` prop is optional because the project list API
 * may not always include version information.  When present, a small
 * ``v{version_number}`` badge is rendered in the card header.
 */

interface ProjectCardProps {
  project: ProjectRead;
  /** Currently active version number string, e.g. ``"1.0.0"``. */
  activeVersion?: string | null;
}

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  paused: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  archived: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400",
};

const CATEGORY_LABELS: Record<string, string> = {
  singlemodule: "Single",
  multimodule: "Multi",
};

function ProjectCard({ project, activeVersion }: ProjectCardProps) {
  const statusStyle = STATUS_STYLES[project.status] ?? "bg-gray-100 text-gray-600";

  return (
    <Link
      to={`/projects/${project.slug}`}
      className="block rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md dark:border-gray-700 dark:bg-gray-800 dark:hover:shadow-gray-900/40"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900 truncate dark:text-gray-100">
          {project.name}
        </h3>
        <div className="flex shrink-0 items-center gap-1.5">
          {activeVersion && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary-100 px-2 py-0.5 text-xs font-medium text-primary-800 dark:bg-primary-900 dark:text-primary-200">
              <Tag className="h-3 w-3" aria-hidden="true" />
              v{activeVersion}
            </span>
          )}
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusStyle}`}
          >
            {project.status}
          </span>
        </div>
      </div>

      {project.description && (
        <p className="mt-1 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">
          {project.description}
        </p>
      )}

      <div className="mt-3 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
        <span className="rounded bg-gray-50 px-1.5 py-0.5 font-medium dark:bg-gray-700">
          {CATEGORY_LABELS[project.category] ?? project.category}
        </span>
      </div>
    </Link>
  );
}

export default ProjectCard;
