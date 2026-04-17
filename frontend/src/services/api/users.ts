/**
 * API client for user management endpoints.
 *
 * Maps to backend routes defined in ``backend.api.routes.users``:
 *
 *   - ``GET   /users``                    -> listUsersApi
 *   - ``POST  /users``                    -> createUserApi
 *   - ``PATCH /users/{id}``               -> updateUserApi
 *   - ``POST  /users/{id}/change-password`` -> changePasswordApi
 */

import api from "../api";
import type {
  PaginatedResponse,
  UserCreate,
  UserRead,
  UserUpdate,
} from "../../types";

/** Query parameters accepted by the list endpoint. */
export interface ListUsersParams {
  skip?: number;
  limit?: number;
  role?: string;
  is_active?: boolean;
}

/**
 * Fetch a paginated list of users.
 *
 * Maps to ``GET /api/v1/users`` with optional query filters.
 */
export function listUsersApi(
  params: ListUsersParams = {},
): Promise<PaginatedResponse<UserRead>> {
  return api.get<PaginatedResponse<UserRead>>("/users", {
    params: {
      skip: params.skip,
      limit: params.limit,
      role: params.role,
      is_active: params.is_active,
    },
  });
}

/**
 * Create a new user.
 *
 * Maps to ``POST /api/v1/users``.  The backend hashes the plaintext
 * password with bcrypt before storage.
 */
export function createUserApi(data: UserCreate): Promise<UserRead> {
  return api.post<UserRead>("/users", data);
}

/**
 * Partially update an existing user.
 *
 * Maps to ``PATCH /api/v1/users/{id}``.  Only the fields present in
 * ``data`` are sent — omitted keys are left unchanged on the server.
 */
export function updateUserApi(
  id: string,
  data: UserUpdate,
): Promise<UserRead> {
  return api.patch<UserRead>(`/users/${id}`, data);
}

/**
 * Change a user's password.
 *
 * Maps to ``POST /api/v1/users/{id}/change-password``.  The backend
 * hashes the new password with bcrypt and bumps ``token_version`` to
 * invalidate all existing JWTs for the target user.
 */
export function changePasswordApi(
  userId: string,
  newPassword: string,
): Promise<UserRead> {
  return api.post<UserRead>(`/users/${userId}/change-password`, {
    new_password: newPassword,
  });
}
