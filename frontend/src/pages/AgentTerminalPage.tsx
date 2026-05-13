/**
 * AgentTerminalPage — full-page embedded claude CLI session in NEX
 * Studio for one of the three agent roles (Designer / Implementer /
 * Auditor).
 *
 * Layout (approved 2026-05-13):
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │ <role> · <project>     [● status]  [Change] [End]    │
 *   ├──────────────────────────────────────────────────────┤
 *   │                                                      │
 *   │              <xterm.js / AgentTerminal>              │
 *   │                                                      │
 *   └──────────────────────────────────────────────────────┘
 *
 * Flow:
 *
 * 1. Mount → fetch ``GET /agent-terminal/sessions`` to find an active
 *    session for this ``(user, role)``. If found, attach. If not, show
 *    :file:`ProjectPickerModal`.
 * 2. User picks a project → ``POST /agent-terminal/spawn`` → render
 *    :file:`AgentTerminal` with the new ``session_id``.
 * 3. End / Change project → ``DELETE /agent-terminal/sessions/{id}``,
 *    re-show picker.
 *
 * Single component shared by all three roles via the ``role`` prop —
 * routes ``/designer``, ``/implementer``, ``/auditor`` each render
 * ``<AgentTerminalPage role={...} />``.
 *
 * Permissions: ``ri`` only (Director). Non-ri users see a Lock panel;
 * the backend returns 403 + the API client surfaces it as ApiError.
 */

import { useCallback, useEffect, useState } from "react";
import { Lock, Loader2, RefreshCw, X } from "lucide-react";

import { useAuthStore } from "@/store/authStore";
import { ApiError, TOKEN_STORAGE_KEY } from "@/services/api";
import {
  listAgentTerminalSessionsApi,
  spawnAgentTerminalApi,
  endAgentTerminalSessionApi,
  type AgentRole,
  type AgentTerminalSession,
} from "@/services/api/agentTerminal";
import { AgentTerminal } from "@/components/AgentTerminal";
import { ProjectPickerModal } from "@/components/ProjectPickerModal";

const ROLE_LABEL: Record<AgentRole, string> = {
  designer: "Designer",
  implementer: "Implementer",
  auditor: "Auditor",
};

const ROLE_BLURB: Record<AgentRole, string> = {
  designer: "Plánovacia fáza — vyber projekt, na ktorom má Designer pracovať.",
  implementer: "Implementačná fáza — vyber projekt, na ktorom má Implementer pracovať.",
  auditor: "Audit / overenie — vyber projekt, na ktorom má Auditor pracovať.",
};

export interface AgentTerminalPageProps {
  role: AgentRole;
}

export default function AgentTerminalPage({ role }: AgentTerminalPageProps) {
  const user = useAuthStore((s) => s.user);
  const isDirector = user?.role === "ri";

  const [session, setSession] = useState<AgentTerminalSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [spawning, setSpawning] = useState(false);
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState("");

  // Token for WebSocket auth (browser WS API can't set headers, so it
  // travels in the query string). Read once at mount — the WS will
  // re-mount whenever ``session`` changes anyway.
  const token =
    typeof window !== "undefined"
      ? window.localStorage.getItem(TOKEN_STORAGE_KEY)
      : null;

  const refresh = useCallback(async () => {
    if (!isDirector) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const rows = await listAgentTerminalSessionsApi();
      const active = rows.find((r) => r.role === role && r.ended_at === null);
      setSession(active ?? null);
      if (!active) {
        setPicking(true);
      }
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Nepodarilo sa načítať sessions.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [role, isDirector]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handlePickProject(slug: string) {
    setPicking(false);
    setSpawning(true);
    setError("");
    try {
      const row = await spawnAgentTerminalApi({ role, project_slug: slug });
      setSession(row);
    } catch (e) {
      const msg =
        e instanceof ApiError && e.message
          ? `Nepodarilo sa spustiť session: ${e.message}`
          : "Nepodarilo sa spustiť session.";
      setError(msg);
      setPicking(true);
    } finally {
      setSpawning(false);
    }
  }

  async function handleEndSession(reopenPicker: boolean) {
    if (!session) return;
    if (!window.confirm("Naozaj ukončiť session? Aktívna konverzácia zanikne.")) return;
    setEnding(true);
    try {
      await endAgentTerminalSessionApi(session.id);
      setSession(null);
      if (reopenPicker) setPicking(true);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Nepodarilo sa ukončiť session.";
      setError(msg);
    } finally {
      setEnding(false);
    }
  }

  // --- Render ---

  if (!isDirector) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-slate-950 p-6 text-center">
        <Lock className="h-10 w-10 text-slate-700" />
        <h2 className="text-sm font-semibold text-slate-300">
          {ROLE_LABEL[role]} terminál
        </h2>
        <p className="max-w-md text-xs text-slate-500">
          Embedded agent terminál je v1 dostupný iba pre rolu{" "}
          <code className="rounded bg-slate-800 px-1 py-0.5">ri</code>{" "}
          (Director). Per-project membership pre <code>ha</code> a{" "}
          <code>shu</code> príde v ďalšej iterácii.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-slate-950">
      {/* Header chrome */}
      <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-sm font-semibold text-slate-100">
            {ROLE_LABEL[role]}
          </h1>
          {session && (
            <>
              <span className="text-xs text-slate-600">·</span>
              <span className="truncate font-mono text-xs text-slate-400">
                {session.project_slug}
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          {session && (
            <span className="flex items-center gap-1.5 rounded-full bg-green-500/10 px-2 py-0.5 text-[10px] text-green-400">
              <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
              running · pid {session.pid}
            </span>
          )}
          <button
            onClick={() => void refresh()}
            className="text-slate-500 transition-colors hover:text-slate-200"
            title="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          {session && (
            <>
              <button
                onClick={() => void handleEndSession(true)}
                disabled={ending}
                className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 disabled:opacity-40"
                title="Zmeň projekt (ukončí aktuálnu session)"
              >
                Change project
              </button>
              <button
                onClick={() => void handleEndSession(false)}
                disabled={ending}
                className="flex items-center gap-1 rounded border border-red-500/40 px-2 py-0.5 text-xs text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-40"
                title="Ukončí session (SIGTERM)"
              >
                <X className="h-3 w-3" />
                End session
              </button>
            </>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-shrink-0 border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-hidden">
        {loading || spawning ? (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            {spawning ? "Spúšťam claude CLI…" : "Načítavam stav…"}
          </div>
        ) : session && token ? (
          <AgentTerminal
            key={session.id}
            sessionId={session.id}
            token={token}
            onEnded={() => void refresh()}
          />
        ) : !picking ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <p className="text-xs text-slate-500">
              Žiadna aktívna {ROLE_LABEL[role]} session.
            </p>
            <button
              onClick={() => setPicking(true)}
              className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-500"
            >
              Spustiť {ROLE_LABEL[role]}
            </button>
          </div>
        ) : null}
      </div>

      {/* Project picker */}
      {picking && (
        <ProjectPickerModal
          title={`Spustiť ${ROLE_LABEL[role]}`}
          description={ROLE_BLURB[role]}
          onPick={handlePickProject}
          onCancel={() => setPicking(false)}
        />
      )}
    </div>
  );
}
