/**
 * Modal dialog for creating a new user.
 *
 * Renders a form with username, email, password, and role fields.
 * Client-side validation:
 *   - All fields required
 *   - Email must match a basic email pattern
 *   - Password must be at least 8 characters
 *
 * On successful submission the dialog calls ``onCreated`` so the
 * parent can reload the user list, then closes itself.  Backend
 * errors (e.g. 409 duplicate username) are shown inline.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../../services/api";
import { createUserApi } from "../../services/api/users";
import type { UserCreate, UserRole } from "../../types";

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

export interface CreateUserDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Callback to close the dialog (cancel or after success). */
  onClose: () => void;
  /** Callback fired after a user is successfully created. */
  onCreated: () => void;
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

/** Minimum password length (mirrors backend schema). */
const MIN_PASSWORD_LENGTH = 8;

/* ------------------------------------------------------------------ */
/*  Form state                                                         */
/* ------------------------------------------------------------------ */

interface FormState {
  username: string;
  email: string;
  password: string;
  role: UserRole;
}

const EMPTY_FORM: FormState = {
  username: "",
  email: "",
  password: "",
  role: "shu",
};

interface FormErrors {
  username?: string;
  email?: string;
  password?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function CreateUserDialog({
  open,
  onClose,
  onCreated,
}: CreateUserDialogProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const patch = useCallback(
    (fragment: Partial<FormState>) => {
      setForm((prev) => ({ ...prev, ...fragment }));
      // Clear field-level error on change
      for (const key of Object.keys(fragment) as (keyof FormState)[]) {
        setErrors((prev) => {
          if (!prev[key as keyof FormErrors]) return prev;
          const next = { ...prev };
          delete next[key as keyof FormErrors];
          return next;
        });
      }
    },
    [],
  );

  /** Reset form to empty state. */
  const resetForm = useCallback(() => {
    setForm(EMPTY_FORM);
    setErrors({});
    setServerError(null);
    setIsSaving(false);
  }, []);

  /** Close dialog and reset form. */
  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [onClose, resetForm]);

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

    if (!form.username.trim()) {
      next.username = "Username is required.";
    }

    if (!form.email.trim()) {
      next.email = "Email is required.";
    } else if (!EMAIL_REGEX.test(form.email.trim())) {
      next.email = "Enter a valid email address.";
    }

    if (!form.password) {
      next.password = "Password is required.";
    } else if (form.password.length < MIN_PASSWORD_LENGTH) {
      next.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  }, [form]);

  /** Submit the form to the backend. */
  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setServerError(null);

      if (!validate()) return;

      setIsSaving(true);
      try {
        const payload: UserCreate = {
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          role: form.role,
          is_active: true,
        };
        await createUserApi(payload);
        resetForm();
        onCreated();
        onClose();
      } catch (exc) {
        const message =
          exc instanceof ApiError ? exc.message : "Failed to create user.";
        setServerError(message);
      } finally {
        setIsSaving(false);
      }
    },
    [form, validate, resetForm, onCreated, onClose],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      data-testid="create-user-dialog"
    >
      <div className="mx-4 w-full max-w-lg rounded-lg border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800">
        <h3 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Create User
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

        <form onSubmit={handleSubmit} noValidate>
          <div className="space-y-4">
            {/* Username */}
            <div>
              <label
                htmlFor="create-username"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Username
              </label>
              <input
                id="create-username"
                type="text"
                value={form.username}
                onChange={(e) => patch({ username: e.target.value })}
                maxLength={50}
                placeholder="e.g. zoltan"
                aria-invalid={!!errors.username}
                aria-describedby={
                  errors.username ? "create-username-error" : undefined
                }
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="create-username"
              />
              {errors.username && (
                <p
                  id="create-username-error"
                  className="mt-1 text-xs text-red-600 dark:text-red-400"
                  data-testid="username-error"
                >
                  {errors.username}
                </p>
              )}
            </div>

            {/* Email */}
            <div>
              <label
                htmlFor="create-email"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Email
              </label>
              <input
                id="create-email"
                type="email"
                value={form.email}
                onChange={(e) => patch({ email: e.target.value })}
                maxLength={255}
                placeholder="e.g. zoltan@isnex.ai"
                aria-invalid={!!errors.email}
                aria-describedby={
                  errors.email ? "create-email-error" : undefined
                }
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="create-email"
              />
              {errors.email && (
                <p
                  id="create-email-error"
                  className="mt-1 text-xs text-red-600 dark:text-red-400"
                  data-testid="email-error"
                >
                  {errors.email}
                </p>
              )}
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="create-password"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Password
                <span className="ml-1 text-xs font-normal text-gray-500 dark:text-gray-400">
                  (min {MIN_PASSWORD_LENGTH} characters)
                </span>
              </label>
              <input
                id="create-password"
                type="password"
                value={form.password}
                onChange={(e) => patch({ password: e.target.value })}
                maxLength={128}
                placeholder="Enter password"
                aria-invalid={!!errors.password}
                aria-describedby={
                  errors.password ? "create-password-error" : undefined
                }
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="create-password"
              />
              {errors.password && (
                <p
                  id="create-password-error"
                  className="mt-1 text-xs text-red-600 dark:text-red-400"
                  data-testid="password-error"
                >
                  {errors.password}
                </p>
              )}
            </div>

            {/* Role */}
            <div>
              <label
                htmlFor="create-role"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Role
              </label>
              <select
                id="create-role"
                value={form.role}
                onChange={(e) => patch({ role: e.target.value as UserRole })}
                className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400"
                data-testid="create-role"
              >
                {ROLE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {ROLE_LABELS[option]}
                  </option>
                ))}
              </select>
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
              {isSaving ? "Creating\u2026" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
