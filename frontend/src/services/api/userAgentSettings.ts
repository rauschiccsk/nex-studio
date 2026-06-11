import api from "../api";
import type {
  PipelineAgentRole,
  UserAgentSettingRead,
  UserAgentSettingUpsert,
} from "../../types/user_agent_setting";

/** The authenticated user's per-role model/effort config rows (only roles they have set). */
export function listUserAgentSettingsApi(): Promise<UserAgentSettingRead[]> {
  return api.get<UserAgentSettingRead[]>("/user-agent-settings");
}

/** Upsert the caller's model + effort for one pipeline role. */
export function upsertUserAgentSettingApi(
  agentRole: PipelineAgentRole,
  body: UserAgentSettingUpsert,
): Promise<UserAgentSettingRead> {
  return api.put<UserAgentSettingRead>(`/user-agent-settings/${agentRole}`, body);
}
