/**
 * Modal dialog for editing an existing user.
 *
 * Renders a form with email, role select, and is_active toggle.
 * Username is displayed read-only (immutable after creation).
 *
 * On successful submission the dialog calls ``onUpdated`` so the
 * parent can reload the user list, then closes itself.  Backend
 * errors (e.g. 400 cannot deactivate self) are shown inline.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../../services/api";
import { updateUserApi } from "../../services/api/users";
import { useAuthStore } from "../../store/authStore";
import type { UserRead, UserRole, UserUpdate } from "../../types";

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

export interface EditUserDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** The user being edited. */
  user: UserRead | null;
  /** Callback to close the dialog (cancel or after success). */
  onClose: () => void;
  /** Callback fired after a user is successfully updated. */
  onUpdated: () => void;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

/** Selectable roles — mirrors ``UserRole`` literal union. */
const ROLE_OPTIONS: readonly UserRole[] = ["ri", "ha", "shu"] as const;

/** Human-readable label for each role value. */
const ROLE_LABELS: Record<UserRole, string> = {
  ri: "ri \u2014 Director / Senior",
  ha: "ha \u2014 Medior",
  shu: "shu \u2014 Junior",
};

/** Basic email regex — intentionally permissive. */
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/* ------------------------------------------------------------------ */
/*  Form state                                                         */
/* ------------------------------------------------------------------ */

interface FormState {
  email: string;
  role: UserRole;
  is_active: boolean;
}

interface FormErrors {
  email?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function EditUserDialog({
  open,
  user,
  onClose,
  onUpdated,
}: EditUserDialogProps) {
  const currentUser = useAuthStore((s) => s.user);

  const [form, setForm] = useState<FormState>({
    email: "",
    role: "shu",
    is_active: true,
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  /** Populate form when the dialog opens or the user prop changes. */
  useEffect(() => {
    if (open && user) {
      setForm({
        email: user.email,
        role: user.role,
        is_active: user.is_active,
      });
      setErrors({});
      setServerError(null);
      setSuccessMessage(null);
      setIsSaving(false);
    }
  }, [open, user]);

  const patch = useCallback((fragment: Partial<FormState>) => {
    setForm((prev) => ({ ...prev, ...fragment }));
    for (const key of Object.keys(fragment) as (keyof FormState)[]) {
      setErrors((prev) => {
        if (!prev[key as keyof FormErrors]) return prev;
        const next = { ...prev };
        delete next[key as keyof FormErrors];
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

    if (!form.email.trim()) {
      next.email = "Email is required.";
    } else if (!EMAIL_REGEX.test(form.email.trim())) {
      next.email = "Enter a valid email address.";
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
        const payload: UserUpdate = {
          email: form.email.trim(),
          role: form.role,
          is_active: form.is_active,
        };
        await updateUserApi(user.id, payload);
        setSuccessMessage("User updated successfully.");
        onUpdated();
        onClose();
      } catch (exc) {
        const message =
          exc instanceof ApiError ? exc.message : "Failed to update user.";
        setServerError(message);
      } finally {
        setIsSaving(false);
      }
    },
    [form, validate, user, onUpdated, onClose],
  );

  if (!open || !user) return null;

  const isSelf = currentUser?.id === user.id;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      data-testid="edit-user-dialog"
    >
      <div className="mx-4 w-full max-w-lg rounded-lg border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800">
        <h3 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Edit User
        </h3>

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
            {/* Username (read-only) */}
            <div>
              <label
                htmlFor="edit-username"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Username
              </label>
              <input
                id="edit-username"
                type="text"
                value={user.username}
                disabled
                className="block w-full rounded-md border border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-500 shadow-sm dark:border-gray-600 dark:bg-gray-600 dark:text-gray-400"
                data-testid="edit-username"
              />
            </div>

            {/* Email */}
            <div>
              <label
                htmlFor="edit-email"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Email
              </label>
              <input
                id="edit-email"
                type="email"
                value={form.email}
                onChange={(e) => patch({ email: e.target.value })}
                maxLength={255}
                placeholder="e.g. zoltan@isnex.ai"
                aria-invalid={!!errors.email}
                aria-describedby={
                  errors.email ? "edit-email-error" : undefined
                }
                disabled={isSaving}
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="edit-email"
              />
              {errors.email && (
                <p
                  id="edit-email-error"
                  className="mt-1 text-xs text-red-600 dark:text-red-400"
                  data-testid="email-error"
                >
                  {errors.email}
                </p>
              )}
            </div>

            {/* Role */}
            <div>
              <label
                htmlFor="edit-role"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Role
              </label>
              <select
                id="edit-role"
                value={form.role}
                onChange={(e) => patch({ role: e.target.value as UserRole })}
                disabled={isSaving}
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="edit-role"
              >
                {ROLE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {ROLE_LABELS[option]}
                  </option>
                ))}
              </select>
            </div>

            {/* Active toggle */}
            <div className="flex items-center justify-between">
              <label
                htmlFor="edit-is-active"
                className="text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Active
              </label>
              <button
                id="edit-is-active"
                type="button"
                role="switch"
                aria-checked={form.is_active}
                onClick={() => patch({ is_active: !form.is_active })}
                disabled={isSaving || isSelf}
                title={isSelf ? "Cannot deactivate your own account" : undefined}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                  form.is_active ? "bg-primary-600" : "bg-gray-300 dark:bg-gray-600"
                }`}
                data-testid="edit-is-active"
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform ${
                    form.is_active ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
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
              {isSaving ? "Saving\u2026" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
