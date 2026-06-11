// Backlog — deferred future customer requirements (E2, CR-NS-041).
// Mirrors backend/schemas/backlog.py.

export type BacklogPriority = "low" | "medium" | "high" | "critical";
export type BacklogStatus = "open" | "included" | "realized" | "rejected";

export interface BacklogItemRead {
  id: string;
  project_id: string;
  number: number; // display id: REQ-{number}
  title: string;
  description: string | null;
  priority: BacklogPriority;
  status: BacklogStatus;
  version_id: string | null;
  realized_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BacklogItemCreate {
  project_id: string;
  title: string;
  description?: string | null;
  priority?: BacklogPriority;
}

export interface BacklogItemUpdate {
  title?: string;
  description?: string | null;
  priority?: BacklogPriority;
  status?: BacklogStatus;
  version_id?: string;
}
