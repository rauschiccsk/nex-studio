import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listProjectsApi } from "@/services/api/projects";
import {
  getProjectModule,
  updateProjectModule,
  listModuleDependencies,
  createModuleDependency,
  deleteModuleDependency,
} from "@/services/api/projectModules";
import { listProjectModules } from "@/services/api/projectModules";
import type { ProjectRead } from "@/types";
import type { ProjectModuleRead, ProjectModuleStatus } from "@/types/projectModule";
import type { ModuleDependencyRead } from "@/types/moduleDependency";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const MODULE_COLORS = [
  "bg-indigo-500/20 border-indigo-500/30 text-indigo-400",
  "bg-green-500/20 border-green-500/25 text-green-400",
  "bg-amber-500/20 border-amber-500/30 text-amber-400",
  "bg-rose-500/20 border-rose-500/30 text-rose-400",
  "bg-cyan-500/20 border-cyan-500/30 text-cyan-400",
  "bg-purple-500/20 border-purple-500/30 text-purple-400",
];

function statusCls(status: string) {
  if (status === "done") return "bg-green-500/10 border border-green-500/25 text-green-400";
  if (status === "in_development") return "bg-yellow-500/15 border border-yellow-500/30 text-yellow-400";
  if (status === "in_design") return "bg-indigo-500/20 border border-indigo-500/30 text-indigo-400";
  return "bg-slate-700/60 border border-slate-600 text-slate-400";
}

function statusLabel(status: string) {
  if (status === "done") return "Hotovo";
  if (status === "in_development") return "Vo vývoji";
  if (status === "in_design") return "V návrhu";
  return "Plánované";
}

const STATUS_ORDER: ProjectModuleStatus[] = ["planned", "in_design", "in_development", "done"];

// ─── Tab type ─────────────────────────────────────────────────────────────────

type Tab = "workflow" | "deps";

// ─── MMModulePage ─────────────────────────────────────────────────────────────

export default function MMModulePage() {
  const { slug, moduleId } = useParams<{ slug: string; moduleId: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectRead | null>(null);
  const [mod, setMod] = useState<ProjectModuleRead | null>(null);
  const [allModules, setAllModules] = useState<ProjectModuleRead[]>([]);
  const [deps, setDeps] = useState<ModuleDependencyRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("workflow");

  // Status update state
  const [savingStatus, setSavingStatus] = useState(false);

  // New dependency
  const [addingDep, setAddingDep] = useState(false);
  const [selectedDepId, setSelectedDepId] = useState("");

  useEffect(() => {
    if (!slug || !moduleId) return;
    let cancelled = false;
    Promise.all([
      listProjectsApi({ limit: 100 }).then((res) => res.items.find((p) => p.slug === slug) ?? null),
      getProjectModule(moduleId),
    ])
      .then(([proj, m]) => {
        if (cancelled || !proj || !m) { setError("Dáta neboli nájdené."); return; }
        setProject(proj);
        setMod(m);
        return Promise.all([
          listProjectModules({ project_id: proj.id, limit: 100 }),
          // Load both outgoing (this module depends on) and incoming (depends on this)
          listModuleDependencies({ module_id: moduleId, limit: 100 }),
          listModuleDependencies({ depends_on_module_id: moduleId, limit: 100 }),
        ]).then(([modRes, outgoing, incoming]) => {
          if (cancelled) return;
          setAllModules(modRes.items);
          // Merge deps deduplicated by id
          const all = [...outgoing.items, ...incoming.items];
          const unique = Array.from(new Map(all.map((d) => [d.id, d])).values());
          setDeps(unique);
        });
      })
      .catch(() => { if (!cancelled) setError("Nepodarilo sa načítať dáta."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug, moduleId]);

  async function handleStatusChange(newStatus: ProjectModuleStatus) {
    if (!mod || savingStatus) return;
    setSavingStatus(true);
    try {
      const updated = await updateProjectModule(mod.id, { status: newStatus });
      setMod(updated);
    } finally {
      setSavingStatus(false);
    }
  }

  async function handleAddDep() {
    if (!mod || !selectedDepId || selectedDepId === mod.id) return;
    setAddingDep(true);
    try {
      const dep = await createModuleDependency({
        module_id: mod.id,
        depends_on_module_id: selectedDepId,
      });
      setDeps((prev) => [...prev, dep]);
      setSelectedDepId("");
    } catch {
      // conflict — dep already exists, ignore
    } finally {
      setAddingDep(false);
    }
  }

  async function handleRemoveDep(depId: string) {
    await deleteModuleDependency(depId);
    setDeps((prev) => prev.filter((d) => d.id !== depId));
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-500 text-sm gap-2">
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Načítavam…
      </div>
    );
  }

  if (error || !project || !mod) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 p-4 text-sm text-red-400">
          {error || "Modul nebol nájdený."}
        </div>
      </div>
    );
  }

  const modIndex = allModules.findIndex((m) => m.id === mod.id);
  const badgeColor = MODULE_COLORS[modIndex % MODULE_COLORS.length] ?? MODULE_COLORS[0];

  // Outgoing deps (this module depends on)
  const outgoing = deps.filter((d) => d.module_id === mod.id);
  const outgoingModules = outgoing.map((d) =>
    ({ dep: d, mod: allModules.find((m) => m.id === d.depends_on_module_id) })
  ).filter((x) => x.mod !== undefined) as { dep: ModuleDependencyRead; mod: ProjectModuleRead }[];

  // Incoming deps (other modules depend on this)
  const incoming = deps.filter((d) => d.depends_on_module_id === mod.id);
  const incomingModules = incoming.map((d) =>
    ({ dep: d, mod: allModules.find((m) => m.id === d.module_id) })
  ).filter((x) => x.mod !== undefined) as { dep: ModuleDependencyRead; mod: ProjectModuleRead }[];

  // Modules available to add as dependencies (not already a dep, not self)
  const existingDepIds = new Set(outgoing.map((d) => d.depends_on_module_id));
  const availableForDep = allModules.filter(
    (m) => m.id !== mod.id && !existingDepIds.has(m.id),
  );

  return (
    <div className="flex flex-col h-full">
      {/* Topbar */}
      <div className="flex-shrink-0 bg-slate-900/50 border-b border-slate-800 px-5 py-2.5 flex items-center gap-3">
        <button
          onClick={() => navigate(`/projects/${slug}/mm`)}
          className="text-slate-500 hover:text-slate-300 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <span className={`text-[11px] font-bold px-2 py-0.5 rounded border font-mono ${badgeColor}`}>
          {mod.code}
        </span>
        <span className="text-sm font-semibold text-slate-100">{mod.name}</span>
        <span className={`text-[10px] px-2.5 py-0.5 rounded-full border font-medium ${statusCls(mod.status)}`}>
          {statusLabel(mod.status)}
        </span>
        <div className="flex-1" />
        {/* Status changer */}
        <div className="flex items-center gap-1">
          {STATUS_ORDER.map((s) => (
            <button
              key={s}
              onClick={() => handleStatusChange(s)}
              disabled={savingStatus || mod.status === s}
              className={`text-[10px] px-2 py-1 rounded transition-colors ${
                mod.status === s
                  ? "bg-primary-600 text-white"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
              }`}
            >
              {statusLabel(s)}
            </button>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex-shrink-0 border-b border-slate-800 px-5 flex items-center gap-0">
        {(["workflow", "deps"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
              tab === t
                ? "border-primary-500 text-primary-400"
                : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {t === "workflow" ? "Postup" : "Závislosti"}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5">
        <div className="max-w-3xl mx-auto">

          {/* Workflow tab */}
          {tab === "workflow" && (
            <div className="space-y-3">
              {/* Info card */}
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-slate-500 text-xs">Kategória</span>
                    <div className="text-slate-200 mt-0.5">{mod.category}</div>
                  </div>
                  <div>
                    <span className="text-slate-500 text-xs">Kód</span>
                    <div className="font-mono text-slate-200 mt-0.5">{mod.code}</div>
                  </div>
                  {mod.design_doc_path && (
                    <div className="col-span-2">
                      <span className="text-slate-500 text-xs">DESIGN.md</span>
                      <div className="font-mono text-slate-400 text-xs mt-0.5 truncate">{mod.design_doc_path}</div>
                    </div>
                  )}
                </div>
              </div>

              {/* Pipeline placeholder — linked to version pipeline in future */}
              <div className="rounded-xl border border-dashed border-slate-800 p-6 text-center">
                <p className="text-sm text-slate-500">Postup</p>
                <p className="text-xs text-slate-700 mt-1">
                  Pipeline sa zobrazí po priradení modulu k verzii projektu.
                </p>
              </div>
            </div>
          )}

          {/* Dependencies tab */}
          {tab === "deps" && (
            <div className="space-y-4">
              {/* This module depends on */}
              <div>
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">
                  {mod.code} závisí od
                </h3>
                {outgoingModules.length === 0 ? (
                  <p className="text-xs text-slate-600 py-2">Žiadne závislosti.</p>
                ) : (
                  <div className="space-y-2">
                    {outgoingModules.map(({ dep, mod: m }) => (
                      <div key={dep.id} className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
                        <span className="font-mono font-bold text-xs text-slate-300">{m.code}</span>
                        <span className="text-sm text-slate-300 flex-1">{m.name}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full ${statusCls(m.status)}`}>
                          {statusLabel(m.status)}
                        </span>
                        <button
                          onClick={() => handleRemoveDep(dep.id)}
                          className="text-slate-600 hover:text-red-400 transition-colors"
                          title="Odstrániť závislosť"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {/* Add dependency */}
                {availableForDep.length > 0 && (
                  <div className="flex items-center gap-2 mt-3">
                    <select
                      value={selectedDepId}
                      onChange={(e) => setSelectedDepId(e.target.value)}
                      className="flex-1 text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-300 focus:outline-none focus:border-primary-500"
                    >
                      <option value="">Vybrať modul…</option>
                      {availableForDep.map((m) => (
                        <option key={m.id} value={m.id}>{m.code} — {m.name}</option>
                      ))}
                    </select>
                    <button
                      onClick={handleAddDep}
                      disabled={!selectedDepId || addingDep}
                      className="flex items-center gap-1.5 text-xs bg-primary-600 hover:bg-primary-500 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg transition-colors"
                    >
                      {addingDep ? "Pridávam…" : "+ Pridať"}
                    </button>
                  </div>
                )}
              </div>

              {/* Modules that depend on this */}
              {incomingModules.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">
                    Závisí od {mod.code}
                  </h3>
                  <div className="space-y-2">
                    {incomingModules.map(({ dep, mod: m }) => (
                      <div key={dep.id} className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
                        <span className="font-mono font-bold text-xs text-slate-300">{m.code}</span>
                        <span className="text-sm text-slate-300 flex-1">{m.name}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full ${statusCls(m.status)}`}>
                          {statusLabel(m.status)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
