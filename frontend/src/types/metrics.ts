// Project metrics / ROI (E5, CR-NS-044). Mirrors backend/schemas/metrics.py (ProjectMetricsRead).
// Honest by construction: any figure depending on an unset price/estimate is null, never fabricated.

export interface UsageTotals {
  input_tokens: number;
  output_tokens: number;
  duration_seconds: number;
  messages: number;
}

export interface ScopeUsage {
  id: string;
  number: number;
  title: string;
  usage: UsageTotals;
}

export interface RoleUsage {
  role: string;
  usage: UsageTotals;
}

export interface VersionMetrics {
  version_id: string;
  version_number: string;
  status: string;
  usage: UsageTotals;
  by_epic: ScopeUsage[];
  by_feat: ScopeUsage[];
  by_task: ScopeUsage[];
  by_role: RoleUsage[];
  director_wait_seconds: number;
  total_time_seconds: number | null;
  api_cost: number | null;
}

export interface Roi {
  human_minutes: number;
  ai_compute_minutes: number;
  human_cost: number | null;
  api_cost: number | null;
  x_faster: number | null;
  y_cheaper_pct: number | null;
  configured: boolean;
}

export interface ProjectMetrics {
  project_id: string;
  slug: string;
  usage: UsageTotals;
  api_cost: number | null;
  director_wait_seconds: number;
  total_time_seconds: number | null;
  by_version: VersionMetrics[];
  roi: Roi;
  pricing_configured: boolean;
  estimates_configured: boolean;
}
