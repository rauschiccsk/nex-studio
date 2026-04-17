/**
 * Shared authentication utilities.
 *
 * Centralizes JWT-parsing helpers that were previously duplicated across
 * VersionDetailPage and VersionsPage.  When the Zustand ``authStore``
 * (DESIGN.md §3.3) is wired, callers should migrate to the store and
 * this module can be retired.
 */

import { TOKEN_STORAGE_KEY } from "../services/api";
import type { UserRole } from "../types/user";

/** Decode the ``role`` claim from the JWT stored in localStorage. */
export function getUserRole(): UserRole | null {
  const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]!));
    return (payload.role as UserRole) ?? null;
  } catch {
    return null;
  }
}
