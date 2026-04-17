/**
 * Confirmation dialog for releasing a version.
 *
 * If blocking EPICs exist (``epics_done < epic_count``) the dialog shows a
 * warning and disables the Confirm button.  On confirmation it calls
 * {@link releaseVersion} and reports success/failure via inline banners.
 */

import { useCallback, useState } from "react";

import { ApiError } from "../../services/api";
import { releaseVersion } from "../../services/api/versions";
import type { Version } from "../../types/version";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ReleaseVersionDialogProps {
  version: Version;
  /** Called after a successful release — parent should refresh data. */
  onReleased: (updated: Version) => void;
  onClose: () => void;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ReleaseVersionDialog({
  version,
  onReleased,
  onClose,
}: ReleaseVersionDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blockingCount = version.epic_count - version.epics_done;
  const hasBlocking = blockingCount > 0;

  const handleConfirm = useCallback(async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      const updated = await releaseVersion(version.id);
      onReleased(updated);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Unexpected error while releasing version");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [version.id, onReleased]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      data-testid="release-dialog"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h3 className="mb-4 text-lg font-semibold text-gray-900">
          Release Version {version.version_number}
        </h3>

        {error && (
          <div
            role="alert"
            className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        {hasBlocking ? (
          <div
            className="mb-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
            data-testid="blocking-warning"
          >
            <p className="font-medium">
              {blockingCount} EPIC{blockingCount !== 1 ? "s" : ""} not completed
            </p>
            <p className="mt-1 text-xs">
              All EPICs must be done before releasing.{" "}
              {version.epics_done}/{version.epic_count} completed.
            </p>
          </div>
        ) : (
          <p className="mb-4 text-sm text-gray-600">
            All {version.epic_count} EPIC{version.epic_count !== 1 ? "s" : ""}{" "}
            are completed. This version is ready for release.
          </p>
        )}

        <p className="mb-4 text-sm text-gray-500">
          Releasing sets the status to <strong>released</strong> and records
          today as the release date. This action cannot be undone.
        </p>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary"
            disabled={isSubmitting}
            data-testid="release-cancel-btn"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleConfirm()}
            className="btn-primary"
            disabled={hasBlocking || isSubmitting}
            data-testid="release-confirm-btn"
          >
            {isSubmitting ? "Releasing…" : "Confirm Release"}
          </button>
        </div>
      </div>
    </div>
  );
}
