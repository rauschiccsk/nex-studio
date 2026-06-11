// Per-user per-role agent model/effort config (CR-NS-040, E3(b/c)).
// Mirrors backend/schemas/user_agent_setting.py.

// The PIPELINE agent role (NOT the user's ri/ha/shu access role).
export type PipelineAgentRole =
  | "coordinator"
  | "designer"
  | "customer"
  | "implementer"
  | "auditor";

export type AgentModel =
  | "claude-opus-4-8"
  | "claude-sonnet-4-6"
  | "claude-haiku-4-5-20251001";

// The 5 effort levels `claude --effort` accepts (NO ultracode — the CLI ignores it).
export type AgentEffort = "low" | "medium" | "high" | "xhigh" | "max";

export interface UserAgentSettingRead {
  agent_role: PipelineAgentRole;
  model: AgentModel | null;
  effort: AgentEffort | null;
}

export interface UserAgentSettingUpsert {
  model: AgentModel | null;
  effort: AgentEffort | null;
}
