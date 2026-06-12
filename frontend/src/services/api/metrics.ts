import api from "../api";
import type { ProjectMetrics } from "../../types/metrics";

/** The project's measured AI effort + cost + human-baseline ROI (E5). Read-only. */
export function getProjectMetricsApi(slug: string): Promise<ProjectMetrics> {
  return api.get<ProjectMetrics>(`/projects/${slug}/metrics`);
}
