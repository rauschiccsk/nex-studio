/**
 * Versions page — lists all versions for a project with progress tracking.
 *
 * Route: ``/projects/:slug/versions`` (DESIGN.md §3.1).
 *
 * Fetches versions via {@link listVersions} and renders a table with:
 *   - version_number, name, status badge, target_date, EPIC progress bar
 *   - Edit button (``ri`` role only)
 *   - Release button (``ri`` role only, hidden when already released)
 *   - "New Version" button (``ri`` role only) that opens CreateVersionDialog
 *
 * User role is decoded from the JWT stored in localStorage.  When the
 * ``authStore`` is wired in a later feat this will switch to the store.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import VersionProgressBar from "../components/versions/VersionProgressBar";
import VersionStatusBadge from "../components/versions/VersionStatusBadge";
import { ApiError } from "../services/api";
import {
  createVersion,
  listVersions,
  releaseVersion,
} from "../services/api/versions";
import type { Version, VersionCreate } from "../types/version";
import { getUserRole } from "../utils/auth";
import { formatDate } from "../utils/format";

/* ------------------------------------------------------------------ */
/*  Create Version Dialog                                              */
/* ------------------------------------------------------------------ */

interface CreateVersionDialogProps {
  onClose: () => void;
  onCreated: (v: Version) => void;
  projectSlug: string;
}

function CreateVersionDialog({
  onClose,
  onCreated,
  projectSlug,
}: CreateVersionDialogProps) {
  const [form, setForm] = useState<VersionCreate>({
    version_number: "",
    name: "",
    description: "",
    target_date: "",
  });
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setIsSaving(true);
      setError(null);
      try {
        // Strip empty optional fields before sending
        const payload: VersionCreate = {
          version_number: form.version_number,
        };
        if (form.name) payload.name = form.name;
        if (form.description) payload.description = form.description;
        if (form.target_date) payload.target_date = form.target_date;

        const created = await createVersion(projectSlug, payload);
        onCreated(created);
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.message);
        } else {
          setError("Unexpected error");
        }
      } finally {
        setIsSaving(false);
      }
    },
    [form, projectSlug, onCreated],
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl dark:bg-gray-800">
        <h3 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
          New Version
        </h3>

        {error && (
          <div
            role="alert"
            className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Version number *
            </label>
            <input
              type="text"
              required
              value={form.version_number}
              onChange={(e) =>
                setForm((f) => ({ ...f, version_number: e.target.value }))
              }
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              placeholder="e.g. 1.0.0"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Name
            </label>
            <input
              type="text"
              value={form.name ?? ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, name: e.target.value }))
              }
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              placeholder="e.g. Initial release"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Description
            </label>
            <textarea
              value={form.description ?? ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, description: e.target.value }))
              }
              rows={3}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Target date
            </label>
            <input
              type="date"
              value={form.target_date ?? ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, target_date: e.target.value }))
              }
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
              disabled={isSaving}
            >
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={isSaving}>
              {isSaving ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

function VersionsPage() {
  const { slug } = useParams<{ slug: string }>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [releasing, setReleasing] = useState<string | null>(null);

  const role = getUserRole();
  const isRi = role === "ri";

  /* ---- Fetch versions ---- */
  const load = useCallback(async () => {
    if (!slug) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await listVersions(slug);
      setVersions(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to load versions");
      }
    } finally {
      setIsLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  /* ---- Release handler ---- */
  const handleRelease = useCallback(
    async (id: string) => {
      if (!window.confirm("Release this version? This action cannot be undone."))
        return;
      setReleasing(id);
      try {
        const updated = await releaseVersion(id);
        setVersions((prev) =>
          prev.map((v) => (v.id === id ? updated : v)),
        );
      } catch (err) {
        if (err instanceof ApiError) {
          window.alert(err.message);
        } else {
          window.alert("Release failed");
        }
      } finally {
        setReleasing(null);
      }
    },
    [],
  );

  /* ---- Create handler ---- */
  const handleCreated = useCallback((v: Version) => {
    setVersions((prev) => [v, ...prev]);
    setShowCreate(false);
  }, []);

  /* ---- Render ---- */
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Versions — {slug ?? "(unknown)"}
        </h2>
        {isRi && (
          <button
            className="btn-primary"
            onClick={() => setShowCreate(true)}
            data-testid="new-version-btn"
          >
            + New Version
          </button>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
        >
          {error}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading versions…</p>
      ) : versions.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No versions found for this project.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Version
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Target Date
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Progress
                </th>
                {isRi && (
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Actions
                  </th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white dark:divide-gray-700 dark:bg-gray-800">
              {versions.map((v) => (
                <tr key={v.id} className="hover:bg-gray-50 dark:bg-gray-900 dark:hover:bg-gray-800">
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900 dark:text-gray-100">
                    <Link
                      to={`/projects/${slug}/versions/${v.id}`}
                      className="text-primary-600 hover:underline"
                      data-testid={`version-link-${v.id}`}
                    >
                      {v.version_number}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                    {v.name ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <VersionStatusBadge status={v.status} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                    {formatDate(v.target_date)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <VersionProgressBar
                      epicsDone={v.epics_done}
                      epicCount={v.epic_count}
                    />
                  </td>
                  {isRi && (
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <div className="flex gap-2">
                        <button
                          className="btn-secondary text-xs"
                          data-testid={`edit-btn-${v.id}`}
                        >
                          Edit
                        </button>
                        {v.status !== "released" && (
                          <button
                            className="btn-primary text-xs"
                            data-testid={`release-btn-${v.id}`}
                            disabled={releasing === v.id}
                            onClick={() => void handleRelease(v.id)}
                          >
                            {releasing === v.id ? "Releasing…" : "Release"}
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && slug && (
        <CreateVersionDialog
          projectSlug={slug}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </section>
  );
}

export default VersionsPage;
