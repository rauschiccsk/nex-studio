/**
 * Shared formatting utilities used across multiple pages.
 */

/** Format an ISO date string to a user-friendly ``sk-SK`` representation. */
export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("sk-SK", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}
