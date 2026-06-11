import api from "../api";
import type { PaginatedResponse } from "../../types";
import type {
  BacklogItemCreate,
  BacklogItemRead,
  BacklogItemUpdate,
} from "../../types/backlog";

export interface ListBacklogParams {
  project_id?: string;
  status?: string;
  skip?: number;
  limit?: number;
  [key: string]: string | number | boolean | null | undefined;
}

export function listBacklogApi(
  params: ListBacklogParams = {},
): Promise<PaginatedResponse<BacklogItemRead>> {
  return api.get<PaginatedResponse<BacklogItemRead>>("/backlog", { params });
}

export function createBacklogApi(data: BacklogItemCreate): Promise<BacklogItemRead> {
  return api.post<BacklogItemRead>("/backlog", data);
}

/** Edit (title/desc/priority) | reject (status) | assign-to-version (version_id → included). */
export function updateBacklogApi(
  id: string,
  data: BacklogItemUpdate,
): Promise<BacklogItemRead> {
  return api.patch<BacklogItemRead>(`/backlog/${id}`, data);
}

export function deleteBacklogApi(id: string): Promise<void> {
  return api.delete<void>(`/backlog/${id}`);
}
