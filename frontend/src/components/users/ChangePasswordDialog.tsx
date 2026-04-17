/**
 * Modal dialog for changing a user's password.
 *
 * Renders a form with new_password and confirm_password fields.
 * Validates that both passwords match and meet the minimum length
 * requirement (8 characters) before calling the backend.
 *
 * On success, shows a toast informing the admin that the target user's
 * existing tokens have been invalidated (server bumps ``token_version``).
 * If the admin changed their own password, the next API call will
 * return 401 and the auto-logout handler redirects to ``/login``.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../../services/api";
import { changePasswordApi } from "../../services/api/users";
import type { UserRead } from "../../types";

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

export interface ChangePasswordDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** The user whose password is being changed. */
  user: UserRead | null;
  /** Callback to close the dialog (cancel or after success). */
  onClose: () => void;
  /** Callback fired after a password is successfully changed. */
  onChanged: () => void;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const MIN_PASSWORD_LENGTH = 8;

/* ------------------------------------------------------------------ */
/*  Form state                                                         */
/* ------------------------------------------------------------------ */

interface FormState {
  new_password: string;
  confirm_password: string;
}

interface FormErrors {
  new_password?: string;
  confirm_password?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ChangePasswordDialog({
  open,
  user,
  onClose,
  onChanged,
}: ChangePasswordDialogProps) {
  const [form, setForm] = useState<FormState>({
    new_password: "",
    confirm_password: "",
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  /** Reset form when the dialog opens. */
  useEffect(() => {
    if (open && user) {
      setForm({ new_password: "", confirm_password: "" });
      setErrors({});
      setServerError(null);
      setSuccessMessage(null);
      setIsSaving(false);
    }
  }, [open, user]);

  const patch = useCallback((fragment: Partial<FormState>) => {
    setForm((prev) => ({ ...prev, ...fragment }));
    for (const key of Object.keys(fragment) as (keyof FormErrors)[]) {
      setErrors((prev) => {
        if (!prev[key]) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  }, []);

  /** Close dialog. */
  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  /** Close dialog on Escape key press. */
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, handleClose]);

  /** Validate all fields, returning true if valid. */
  const validate = useCallback((): boolean => {
    const next: FormErrors = {};

    if (!form.new_password) {
      next.new_password = "Password is required.";
    } else if (form.new_password.length < MIN_PASSWORD_LENGTH) {
      next.new_password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    }

    if (!form.confirm_password) {
      next.confirm_password = "Please confirm the password.";
    } else if (form.new_password !== form.confirm_password) {
      next.confirm_password = "Passwords do not match.";
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  }, [form]);

  /** Submit the form to the backend. */
  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setServerError(null);
      setSuccessMessage(null);

      if (!validate() || !user) return;

      setIsSaving(true);
      try {
        await changePasswordApi(user.id, form.new_password);
        setSuccessMessage(
          "Password changed successfully. User's existing sessions have been invalidated.",
        );
        onChanged();
        onClose();
      } catch (exc) {
        const message =
          exc instanceof ApiError
            ? exc.message
            : "Failed to change password.";
        setServerError(message);
      } finally {
        setIsSaving(false);
      }
    },
    [form, validate, user, onChanged, onClose],
  );

  if (!open || !user) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      data-testid="change-password-dialog"
    >
      <div className="mx-4 w-full max-w-lg rounded-lg border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800">
        <h3 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Change Password
        </h3>

        <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
          Changing password for{" "}
          <span className="font-medium text-gray-900 dark:text-gray-100">
            {user.username}
          </span>
          . This will invalidate all existing sessions for this user.
        </p>

        {serverError && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-900/30 dark:text-red-300"
            data-testid="server-error"
          >
            {serverError}
          </div>
        )}

        {successMessage && (
          <div
            role="status"
            className="mb-4 rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800 dark:border-green-800 dark:bg-green-900/30 dark:text-green-300"
            data-testid="success-message"
          >
            {successMessage}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="space-y-4">
            {/* New Password */}
            <div>
              <label
                htmlFor="change-new-password"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                New Password
              </label>
              <input
                id="change-new-password"
                type="password"
                value={form.new_password}
                onChange={(e) => patch({ new_password: e.target.value })}
                maxLength={128}
                placeholder="Min. 8 characters"
                aria-invalid={!!errors.new_password}
                aria-describedby={
                  errors.new_password
                    ? "change-new-password-error"
                    : undefined
                }
                disabled={isSaving}
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="new-password"
              />
              {errors.new_password && (
                <p
                  id="change-new-password-error"
                  className="mt-1 text-xs text-red-600 dark:text-red-400"
                  data-testid="new-password-error"
                >
                  {errors.new_password}
                </p>
              )}
            </div>

            {/* Confirm Password */}
            <div>
              <label
                htmlFor="change-confirm-password"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Confirm Password
              </label>
              <input
                id="change-confirm-password"
                type="password"
                value={form.confirm_password}
                onChange={(e) => patch({ confirm_password: e.target.value })}
                maxLength={128}
                placeholder="Re-enter password"
                aria-invalid={!!errors.confirm_password}
                aria-describedby={
                  errors.confirm_password
                    ? "change-confirm-password-error"
                    : undefined
                }
                disabled={isSaving}
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="confirm-password"
              />
              {errors.confirm_password && (
                <p
                  id="change-confirm-password-error"
                  className="mt-1 text-xs text-red-600 dark:text-red-400"
                  data-testid="confirm-password-error"
                >
                  {errors.confirm_password}
                </p>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="mt-6 flex justify-end gap-2">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleClose}
              disabled={isSaving}
              data-testid="cancel-btn"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSaving}
              data-testid="submit-btn"
            >
              {isSaving ? "Changing\u2026" : "Change Password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
