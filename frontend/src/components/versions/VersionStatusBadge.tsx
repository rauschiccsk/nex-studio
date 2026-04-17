/**
 * Badge component that maps a {@link VersionStatus} to a coloured pill.
 *
 * Colour mapping follows the DESIGN.md §3.2 convention:
 *   - ``planned``  → gray
 *   - ``active``   → blue
 *   - ``released`` → green
 */

import type { VersionStatus } from "../../types/version";

interface VersionStatusBadgeProps {
  status: VersionStatus;
}

function badgeClass(status: VersionStatus): string {
  switch (status) {
    case "planned":
      return "bg-gray-100 text-gray-800";
    case "active":
      return "bg-blue-100 text-blue-800";
    case "released":
      return "bg-emerald-100 text-emerald-800";
  }
}

export default function VersionStatusBadge({
  status,
}: VersionStatusBadgeProps) {
  return (
    <span
      data-testid="version-status-badge"
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badgeClass(status)}`}
    >
      {status}
    </span>
  );
}
