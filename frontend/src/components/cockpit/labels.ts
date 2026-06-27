// Slovak human-facing display labels for the cockpit (CR-NS-018).
//
// Display layer only — the machine values (current_stage, current_actor, author,
// recipient enums) are unchanged. A single shared map per dimension keeps the
// rail, the agent chips, and the message bubbles consistent (no duplicated
// literals). Director feedback: internal codes + English roles aren't
// understandable, especially for Directors who don't know the ICC methodology.

import type { BlockReason, PipelineParticipant, PipelineStage } from "../../services/api/pipeline";

// ── v2.0.0 vocabulary (CR-V2-019) ─────────────────────────────────────────────
// The v2 build pipeline is visible as FOUR phases (design §2.1) — the display now
// shows *which stage the AI Agent is in*, not *which agent is active*. This is the
// canonical v2 vocabulary; the Vývoj 4-phase board (CR-V2-021) and the AI Agent
// tab strip (CR-V2-022) read it. Owned end-to-end by ONE doer (the AI Agent) and
// checked by the independent Auditor — three participants only (design §1/§4.1):
// AI Agent (does the work), Auditor (independent verifier), Manažér (approves).
//
// NOTE (deliberate, flagged): the legacy v1 STAGE_*/ROLE_LABELS + the coordinator/
// triage/regate maps below are NOT yet removed. They are typed `Record<PipelineStage|
// PipelineParticipant,…>` over the still-v1 generated enums (the FE openapi-typescript
// regen for the v2 backend is CR-V2-021's dependency) and are still consumed by the v1
// cockpit components (PipelineRail / ExchangePanel / PipelineActionBar / WhosTurnBoard /
// PipelineMessageBubble) + SettingsPage role list — all of which CR-V2-021/022/010 re-
// author. Dropping them here would break the type-check gate and reach into those CRs'
// scope. They retire WITH their consumers; this CR establishes the v2 vocabulary they
// migrate ONTO. The tone palette (TONE_*/StatusTone/DECISION_BANNER) is intact (salvaged).

// The v2 build phase machine value (mirrors design §2.1; `done` is the terminal phase).
export type BuildPhase = "priprava" | "navrh" | "programovanie" | "verifikacia" | "done";

// Slovak human-facing label per v2 build phase — the 4-phase Vývoj board chips + the
// AI Agent tab strip. Collapses the v1 11-stage STAGE_LABELS to the four real phases.
export const PHASE_LABELS: Record<BuildPhase, string> = {
  priprava: "Príprava",
  navrh: "Návrh",
  programovanie: "Programovanie",
  verifikacia: "Verifikácia",
  done: "Hotovo",
};

// Canonical v2 phase order — the horizontal phase bar (Príprava › Návrh › Programovanie
// › Verifikácia › Hotovo). Replaces the v1 STAGE_ORDER for v2 surfaces.
export const PHASE_ORDER: BuildPhase[] = ["priprava", "navrh", "programovanie", "verifikacia", "done"];

// Raw machine code per phase — usable as a hover tooltip alongside the label.
export const PHASE_CODES: Record<BuildPhase, string> = {
  priprava: "priprava",
  navrh: "navrh",
  programovanie: "programovanie",
  verifikacia: "verifikacia",
  done: "done",
};

// The v2 pipeline participant machine value — exactly three (design §1/§4.1): the AI
// Agent does the whole build, the Auditor independently verifies, the Manažér approves.
// (No Coordinator / Designer / Customer / Implementer — those v1 roles collapse into
// the single AI Agent; `system` stays for system-authored notices.)
export type V2Participant = "ai_agent" | "auditor" | "manazer" | "system";

// Slovak label per v2 participant — the 3-role vocabulary. Replaces the v1 7-role
// ROLE_LABELS for v2 surfaces (who's-up status, the AI Agent header, message bubbles).
export const V2_ROLE_LABELS: Record<V2Participant, string> = {
  ai_agent: "AI Agent",
  auditor: "Audítor",
  manazer: "Manažér",
  system: "Systém",
};

// Human label of the phase that follows `phase` (clamped at the terminal `done`). Drives
// the "Schváliť → spustí sa ďalšia fáza (…)" consequence line on the v2 board.
export function nextPhaseLabel(phase: BuildPhase): string {
  const idx = PHASE_ORDER.indexOf(phase);
  const next = idx >= 0 ? PHASE_ORDER[Math.min(idx + 1, PHASE_ORDER.length - 1)] : undefined;
  return next ? PHASE_LABELS[next] : PHASE_LABELS[phase];
}

// ── v1 (legacy) vocabulary — retires WITH its consumers (CR-V2-021/022/010) ────────────
export const STAGE_LABELS: Record<PipelineStage, string> = {
  kickoff: "Príprava",
  gate_a: "Rozsah",
  gate_b: "Rozhranie (API)",
  gate_c: "Backend návrh",
  gate_d: "Frontend návrh",
  gate_e: "Kontrola zákazníkom",
  task_plan: "Plán úloh",
  build: "Programovanie",
  gate_g: "Audit",
  release: "Vydanie",
  done: "Hotovo",
};

// Raw machine code per stage — usable as a hover tooltip alongside the label.
export const STAGE_CODES: Record<PipelineStage, string> = {
  kickoff: "kickoff",
  gate_a: "Gate A",
  gate_b: "Gate B",
  gate_c: "Gate C",
  gate_d: "Gate D",
  gate_e: "Gate E",
  task_plan: "task_plan",
  build: "build",
  gate_g: "Gate G",
  release: "release",
  done: "done",
};

export const ROLE_LABELS: Record<PipelineParticipant, string> = {
  coordinator: "Koordinátor",
  designer: "Návrhár",
  customer: "Zákazník",
  implementer: "Programátor",
  auditor: "Audítor",
  manazer: "Manažér",
  system: "Systém",
};

// CR-NS-053 Pillar A: the Coordinator's Director-facing synthesis (payload.is_synthesis) is the PRIMARY
// message at each decision point — its badge label. The raw worker report it summarizes stays in the
// thread as a secondary, dimmed "pôvodný report" (drill-down audit trail; never removed).
export const SYNTHESIS_LABEL = "Zhrnutie";
export const RAW_REPORT_LABEL = "pôvodný report";

// CR-NS-055 Pillar B: an AUTONOMOUS Coordinator decision (payload.is_autonomous) auto-executed a bounded
// recovery without a Director click — the Director SEES it (never silent), badged distinctly.
export const AUTONOMOUS_LABEL = "Koordinátor rozhodol";

// CR-2 (v0.7.3): a Director-facing brief (payload.is_director_brief) — the Coordinator's relay / verify turn
// addressed to the Director. Shares the synthesis's prominent rail, badged "Na rade" (it's the Director's turn).
export const DIRECTOR_BRIEF_LABEL = "Na rade";

// R4 (D1/D2): Slovak phrase per block_reason — the precise reason a pipeline is `blocked`, so the Director
// distinguishes an agent QUESTION from an agent ERROR from a SYSTEM error from a parse failure at a glance.
export const BLOCK_REASON_LABELS: Record<BlockReason, string> = {
  agent_question: "Agent sa pýta",
  agent_error: "Agent zlyhal",
  system_error: "Systémová chyba",
  parse_exhaustion: "Chyba spracovania výstupu",
};

// Slovak labels for EPIC/FEAT/TASK node statuses in the TaskPlanPanel tree (CR-NS-020 CR-5).
// Union of epic (planned/in_progress/done) + feat/task (todo/in_progress/done/failed).
export const TASK_STATUS_LABELS: Record<string, string> = {
  planned: "Naplánované",
  todo: "Čaká",
  in_progress: "Prebieha",
  done: "Hotovo",
  failed: "Zlyhalo",
};

// ── Unified cockpit status palette (CR-NS-028) ────────────────────────────────
// ONE colour means exactly one thing across the whole cockpit, so it can't drift:
//   green (emerald) = done / ok / pass
//   blue  (sky)     = in_progress / working / currently active
//   amber (yellow)  = waiting / todo / planned / awaiting_manazer
//   red             = error / fail / blocked
//   neutral (slate) = idle / inactive
// Components map a status → a tone here (single source of truth), then a tone → their
// own class shape (dot / text / banner) via the TONE_* maps below.
export type StatusTone = "green" | "blue" | "amber" | "red" | "neutral";

// Task/node lifecycle status (tasks.status, and derived feat/epic) → tone.
export const TASK_STATUS_TONE: Record<string, StatusTone> = {
  done: "green",
  in_progress: "blue",
  planned: "amber",
  todo: "amber",
  failed: "red",
};

// Pipeline state status (pipeline_state.status) → tone.
export const PIPELINE_STATUS_TONE: Record<string, StatusTone> = {
  agent_working: "blue",
  awaiting_manazer: "amber",
  blocked: "red",
  paused: "amber", // waiting on the Manažér to resume/end (CR-NS-035)
  done: "green",
};

// Tone → class shape. Centralising the colour VALUES too (not just the semantic
// assignment) keeps "blue" the same blue everywhere.
export const TONE_DOT: Record<StatusTone, string> = {
  green: "bg-emerald-500",
  blue: "bg-sky-500",
  amber: "bg-amber-400",
  red: "bg-red-500",
  neutral: "bg-slate-500",
};

// CR-NS-067c: light-readable + dark-identical (`text-X-600 dark:text-X-400`); the -400
// status colors were too faint on a white surface in light mode.
export const TONE_TEXT: Record<StatusTone, string> = {
  green: "text-emerald-600 dark:text-emerald-400",
  blue: "text-sky-600 dark:text-sky-400",
  amber: "text-amber-600 dark:text-amber-400",
  red: "text-red-600 dark:text-red-400",
  neutral: "text-[var(--color-text-muted)]",
};

// Coordinator executable-action → Slovak effect phrase (E7, F-008 §5/§9). The build approve button is
// labelled "Schváliť Koordinátorov návrh (<effect>)" so it names the concrete effect (WS-C class-D),
// never a generic "Schváliť".
export const COORDINATOR_ACTION_LABELS: Record<string, string> = {
  coordinator_reset_task: "reštartovať úlohu",
  coordinator_move_baseline: "posunúť baseline",
  coordinator_clear_session: "vyčistiť session",
  coordinator_escalate_dedo: "eskalovať Dedovi",
  coordinator_route_to_designer: "opraviť spec cez Návrhára",
  capture_backlog_item: "Zaevidovať do backlogu",
};

// R4 (D3): Coordinator triage_class → Slovak phrase, so the board's "Koordinátor klasifikoval: X" line reads
// legibly for a non-Dedo Director. Mirrors the BE CoordinatorDirective.triage_class Literal.
export const TRIAGE_CLASS_LABELS: Record<string, string> = {
  spec_problem: "problém v špecifikácii",
  programmer_guidance: "vedenie programátora",
  nex_studio_bug: "chyba NEX Studio",
  director_decision: "rozhodnutie Directora",
  programmer_routine_question: "rutinná otázka programátora",
};

// CR-NS-067c: light-readable + dark-identical (`text-X-700 dark:text-X-200`); the -200
// banner text was near-white and unreadable on the pale tint in light mode.
export const TONE_BANNER: Record<StatusTone, string> = {
  green: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
  blue: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-200",
  amber: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-200",
  red: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-200",
  neutral: "border-[var(--color-border-default)] bg-[var(--color-surface-hover)] text-[var(--color-text-secondary)]",
};

// CR-2 (v0.7.3): the HIGH-CONTRAST sticky decision CTA banner — used (instead of the low-key TONE_BANNER) only
// when status is awaiting_manazer / blocked, so a "your turn" board never reads as "stuck". Solid state-token
// bg + fg + a left accent in the same fg (token-disciplined: the shared --color-state-* pairs carry light+dark,
// no raw pastels). Tone-aware so it stays inside the unified palette (CR-NS-028): amber = awaiting, red = blocked.
export const DECISION_BANNER: Partial<Record<StatusTone, string>> = {
  amber:
    "bg-[var(--color-state-warning-bg)] text-[var(--color-state-warning-fg)] border-[var(--color-state-warning-fg)]",
  red: "bg-[var(--color-state-error-bg)] text-[var(--color-state-error-fg)] border-[var(--color-state-error-fg)]",
};

// Canonical stage order — mirrors backend orchestrator.STAGE_ORDER. Shared so the
// rail and the action bar don't each keep a copy (DRY).
export const STAGE_ORDER: PipelineStage[] = [
  "kickoff",
  "gate_a",
  "gate_b",
  "gate_c",
  "gate_d",
  "gate_e",
  "task_plan",
  "build",
  "gate_g",
  "release",
  "done",
];

// Fast-Fix Lane stage path (F-009, CR-NS-094/095) — mirrors backend orchestrator.FAST_FIX_STAGE_ORDER.
// The lightweight lane skips the full waterfall (gate_a-e / task_plan / gate_g): kickoff advances straight
// to build, a settled build to release. A subset of STAGE_ORDER, so STAGE_LABELS / STAGE_CODES already
// cover every member.
export const FAST_FIX_STAGE_ORDER: PipelineStage[] = ["kickoff", "build", "release", "done"];

// The stage order for a given pipeline flow_type. fast_fix runs the short lane; every other flow
// (new_version / cr / bug) traverses the full STAGE_ORDER (F-009 §3). Default new_version.
export function stageOrderForFlow(flowType?: string): PipelineStage[] {
  return flowType === "fast_fix" ? FAST_FIX_STAGE_ORDER : STAGE_ORDER;
}

// Slovak display label per pipeline flow_type (F-009). The fast-fix lane is badged on the board so it
// reads distinctly from a full-waterfall version; the map covers all flows for reuse/consistency.
export const FLOW_LABELS: Record<string, string> = {
  new_version: "Nová verzia",
  cr: "Zmena (CR)",
  bug: "Oprava chyby",
  fast_fix: "Rýchla oprava",
};

// CR-NS-057 §F2.4: the stages a gate_g FAIL can re-gate to (override chips). Excludes kickoff / release /
// done / gate_g — only the design + build stages (gate_a..build) are valid re-gate targets.
export const REGATE_TARGETS: PipelineStage[] = STAGE_ORDER.filter(
  (s) => s !== "kickoff" && s !== "release" && s !== "done" && s !== "gate_g",
);

// Human label of the stage that follows `stage` in the given flow (clamped at the last). Drives the
// "Schváliť → spustí sa ďalšia fáza (…)" consequence line. Flow-aware so a fast_fix kickoff correctly
// reads "Programovanie" (build), not "Rozsah" (gate_a) — that gate is skipped in the short lane.
export function nextStageLabel(stage: PipelineStage, flowType?: string): string {
  const order = stageOrderForFlow(flowType);
  const idx = order.indexOf(stage);
  const next = idx >= 0 ? order[Math.min(idx + 1, order.length - 1)] : undefined;
  return next ? STAGE_LABELS[next] : STAGE_LABELS[stage];
}
