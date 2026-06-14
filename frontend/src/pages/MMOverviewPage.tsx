import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listProjectsApi } from "@/services/api/projects";
import {
  listProjectModules,
  createProjectModule,
  listModuleDependencies,
} from "@/services/api/projectModules";
import type { ProjectRead } from "@/types";
import type { ProjectModuleRead } from "@/types/projectModule";
import { PROJECT_MODULE_CATEGORIES } from "@/types/projectModule";
import type { ModuleDependencyRead } from "@/types/moduleDependency";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const MODULE_COLORS = [
  "bg-indigo-500/20 border-indigo-500/30 text-indigo-700 dark:text-indigo-400",
  "bg-green-500/20 border-green-500/25 text-green-700 dark:text-green-400",
  "bg-amber-500/20 border-amber-500/30 text-amber-700 dark:text-amber-400",
  "bg-rose-500/20 border-rose-500/30 text-rose-700 dark:text-rose-400",
  "bg-cyan-500/20 border-cyan-500/30 text-cyan-700 dark:text-cyan-400",
  "bg-purple-500/20 border-purple-500/30 text-purple-700 dark:text-purple-400",
];

function moduleColor(index: number) {
  return MODULE_COLORS[index % MODULE_COLORS.length];
}

function statusCls(status: string) {
  if (status === "done") return "bg-[var(--color-state-success-bg)] border border-[var(--color-state-success-bg)] text-[var(--color-state-success-fg)]";
  if (status === "in_development") return "bg-[var(--color-state-warning-bg)] border border-[var(--color-state-warning-bg)] text-[var(--color-state-warning-fg)]";
  if (status === "in_design") return "bg-indigo-500/20 border border-indigo-500/30 text-indigo-700 dark:text-indigo-400";
  return "bg-[var(--color-surface-active)] border border-[var(--color-border-strong)] text-[var(--color-text-muted)]";
}

function statusLabel(status: string) {
  if (status === "done") return "Hotovo";
  if (status === "in_development") return "Vo vývoji";
  if (status === "in_design") return "V návrhu";
  return "Plánované";
}

// ─── Module Card ──────────────────────────────────────────────────────────────

function ModuleCard({
  mod,
  index,
  deps,
  allModules,
  onOpen,
}: {
  mod: ProjectModuleRead;
  index: number;
  deps: ModuleDependencyRead[];
  allModules: ProjectModuleRead[];
  onOpen: () => void;
}) {
  const color = moduleColor(index);
  // Modules this one depends on
  const needsIds = deps.filter((d) => d.module_id === mod.id).map((d) => d.depends_on_module_id);
  const needs = allModules.filter((m) => needsIds.includes(m.id));
  // Modules that depend on this one
  const neededByIds = deps.filter((d) => d.depends_on_module_id === mod.id).map((d) => d.module_id);
  const neededBy = allModules.filter((m) => neededByIds.includes(m.id));

  return (
    <div
      className="rounded-xl border border-[var(--color-border-default)] bg-[var(--color-canvas)] p-4 cursor-pointer hover:border-[var(--color-border-default)] transition-colors"
      onClick={onOpen}
    >
      <div className="flex items-start gap-3">
        {/* Code badge */}
        <div className={`shrink-0 px-2 py-1 rounded-lg border font-mono font-bold text-xs ${color}`}>
          {mod.code}
        </div>
        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-[var(--color-text-primary)]">{mod.name}</span>
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${statusCls(mod.status)}`}>
              {statusLabel(mod.status)}
            </span>
          </div>
          <div className="text-xs text-[var(--color-text-muted)]">{mod.category}</div>
          {/* Dependency chips */}
          {(needs.length > 0 || neededBy.length > 0) && (
            <div className="flex flex-wrap gap-1 mt-2">
              {needs.map((n) => (
                <span key={n.id} className="text-[10px] bg-[var(--color-surface)] border border-[var(--color-border-default)] text-[var(--color-text-secondary)] px-1.5 py-0.5 rounded font-mono">
                  ← {n.code}
                </span>
              ))}
              {neededBy.map((n) => (
                <span key={n.id} className="text-[10px] bg-[var(--color-surface)] border border-[var(--color-border-default)] text-[var(--color-text-secondary)] px-1.5 py-0.5 rounded font-mono">
                  → {n.code}
                </span>
              ))}
            </div>
          )}
        </div>
        <svg className="w-4 h-4 text-[var(--color-text-muted)] shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </div>
  );
}

// ─── New Module Modal ─────────────────────────────────────────────────────────

interface NewModuleModalProps {
  projectId: string;
  existingModules: ProjectModuleRead[];
  onClose: () => void;
  onCreated: (mod: ProjectModuleRead) => void;
}

function NewModuleModal({ projectId, existingModules, onClose, onCreated }: NewModuleModalProps) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState("");
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => { codeRef.current?.focus(); }, []);

  function validate() {
    const next: Record<string, string> = {};
    if (!code.trim()) next.code = "Kód modulu je povinný.";
    else if (!/^[a-z][a-z0-9-]*[a-z0-9]$/.test(code.trim()))
      next.code =
        "Kód: kebab-case, malé písmená/číslice/spojovníky (napr. partner-catalog), max 50 znakov.";
    if (!name.trim()) next.name = "Názov modulu je povinný.";
    if (!category.trim()) next.category = "Kategória je povinná.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setFormError("");
    setLoading(true);
    try {
      const mod = await createProjectModule({
        project_id: projectId,
        code: code.trim().toLowerCase(),
        name: name.trim(),
        category: category.trim(),
      });
      onCreated(mod);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Chyba pri vytváraní modulu.");
    } finally {
      setLoading(false);
    }
  }

  const inputCls = "w-full rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)] focus:outline-none focus:border-primary-500 transition-colors";

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-[var(--color-canvas)] border border-[var(--color-border-default)] rounded-2xl shadow-2xl">
        <div className="px-6 py-4 border-b border-[var(--color-border-default)] flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">Nový modul</h2>
          <button onClick={onClose} className="text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} noValidate className="p-6 space-y-4">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Kód modulu *</label>
            <input
              ref={codeRef}
              type="text"
              placeholder="napr. partner-catalog"
              maxLength={50}
              value={code}
              onChange={(e) => { setCode(e.target.value.toLowerCase()); if (errors.code) setErrors((er) => ({ ...er, code: "" })); }}
              className={`${inputCls} font-mono lowercase ${errors.code ? "border-[var(--color-state-error-bg)]" : ""}`}
            />
            {errors.code && <p className="mt-1 text-xs text-[var(--color-status-error)]">{errors.code}</p>}
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Názov modulu *</label>
            <input
              type="text"
              placeholder="napr. Účtovníctvo"
              value={name}
              onChange={(e) => { setName(e.target.value); if (errors.name) setErrors((er) => ({ ...er, name: "" })); }}
              className={`${inputCls} ${errors.name ? "border-[var(--color-state-error-bg)]" : ""}`}
            />
            {errors.name && <p className="mt-1 text-xs text-[var(--color-status-error)]">{errors.name}</p>}
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Kategória *</label>
            <select
              value={category}
              onChange={(e) => { setCategory(e.target.value); if (errors.category) setErrors((er) => ({ ...er, category: "" })); }}
              className={`${inputCls} ${errors.category ? "border-[var(--color-state-error-bg)]" : ""}`}
            >
              <option value="" disabled>— vyber kategóriu —</option>
              {PROJECT_MODULE_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
            {errors.category && <p className="mt-1 text-xs text-[var(--color-status-error)]">{errors.category}</p>}
          </div>

          {existingModules.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Závisí od modulov</label>
              <div className="flex flex-wrap gap-1.5 p-2 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-surface)] min-h-[36px] text-[10px] text-[var(--color-text-muted)]">
                <span>Závislosti pridáš po vytvorení modulu v detail zobrazení.</span>
              </div>
            </div>
          )}

          {formError && (
            <div className="rounded-lg bg-[var(--color-state-error-bg)] border border-[var(--color-state-error-bg)] p-3 text-sm text-[var(--color-state-error-fg)]">
              {formError}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-xs text-[var(--color-text-secondary)] border border-[var(--color-border-default)] rounded-lg hover:bg-[var(--color-surface-hover)] transition-colors"
            >
              Zrušiť
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 text-xs font-medium text-white bg-primary-600 hover:bg-primary-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
            >
              {loading ? "Pridávam…" : "Pridať modul"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── MMOverviewPage ───────────────────────────────────────────────────────────

export default function MMOverviewPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectRead | null>(null);
  const [modules, setModules] = useState<ProjectModuleRead[]>([]);
  const [deps, setDeps] = useState<ModuleDependencyRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    listProjectsApi({ limit: 100 })
      .then((res) => {
        if (cancelled) return;
        const found = res.items.find((p) => p.slug === slug);
        if (!found) { setError("Projekt nebol nájdený."); setLoading(false); return; }
        setProject(found);
        // Load modules + all dependencies in parallel
        return Promise.all([
          listProjectModules({ project_id: found.id, limit: 100 }),
          listModuleDependencies({ limit: 100 }),
        ]).then(([modRes, depRes]) => {
          if (cancelled) return;
          setModules(modRes.items);
          setDeps(depRes.items);
        });
      })
      .catch(() => { if (!cancelled) setError("Nepodarilo sa načítať projekt."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug]);

  function handleModuleCreated(mod: ProjectModuleRead) {
    setModules((prev) => [...prev, mod]);
    setShowModal(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-[var(--color-text-muted)] text-sm gap-2">
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Načítavam…
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="rounded-lg bg-[var(--color-state-error-bg)] border border-[var(--color-state-error-bg)] p-4 text-sm text-[var(--color-state-error-fg)]">
          {error || "Projekt nebol nájdený."}
        </div>
      </div>
    );
  }

  const doneCount = modules.filter((m) => m.status === "done").length;
  const pct = modules.length > 0 ? Math.round((doneCount / modules.length) * 100) : 0;

  // Filter deps to only those between modules in this project
  const moduleIds = new Set(modules.map((m) => m.id));
  const projectDeps = deps.filter(
    (d) => moduleIds.has(d.module_id) && moduleIds.has(d.depends_on_module_id),
  );

  return (
    <div className="flex flex-col h-full">
      {/* Topbar */}
      <div className="flex-shrink-0 bg-[var(--color-surface-hover)] border-b border-[var(--color-border-default)] px-5 py-2.5 flex items-center gap-3">
        <button
          onClick={() => navigate(`/projects/${slug}`)}
          className="text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--color-text-primary)]">{project.name}</span>
          <span className="text-[10px] bg-indigo-500/20 border border-indigo-500/30 text-indigo-700 dark:text-indigo-400 px-2 py-0.5 rounded-full font-medium">
            Multi-Module
          </span>
        </div>
        <div className="flex-1" />
        {/* Stats */}
        <div className="flex items-center gap-4 text-xs text-[var(--color-text-secondary)]">
          <span>
            <span className="text-[var(--color-text-secondary)] font-semibold">{modules.length}</span> modulov
          </span>
          <div className="flex items-center gap-1.5">
            <div className="w-20 h-1.5 bg-[var(--color-surface-active)] rounded-full overflow-hidden">
              <div
                className="h-full bg-primary-500 rounded-full transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-primary-700 dark:text-primary-400 font-medium">{pct}%</span>
          </div>
        </div>
      </div>

      {/* Action bar */}
      <div className="flex-shrink-0 px-5 py-2.5 border-b border-[var(--color-border-default)] flex items-center gap-2">
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 bg-primary-600 hover:bg-primary-500 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Pridať modul
        </button>
        <button
          onClick={() => navigate(`/projects/${slug}/mm/depmap`)}
          className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] border border-[var(--color-border-default)] hover:border-[var(--color-border-strong)] px-3 py-1.5 rounded-lg transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          Mapa závislostí
        </button>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-5">
        <div className="max-w-5xl mx-auto space-y-5">

          {/* Module grid */}
          {modules.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--color-border-default)] p-10 text-center">
              <div className="w-10 h-10 rounded-xl bg-[var(--color-surface)] flex items-center justify-center mx-auto mb-3">
                <svg className="w-5 h-5 text-[var(--color-text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              </div>
              <p className="text-sm text-[var(--color-text-muted)] mb-1">Žiadne moduly</p>
              <p className="text-xs text-[var(--color-text-muted)]">Pridaj prvý modul a začni vývoj multi-module projektu.</p>
              <button
                onClick={() => setShowModal(true)}
                className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 hover:bg-primary-500 rounded-lg transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Pridať modul
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {modules.map((mod, i) => (
                <ModuleCard
                  key={mod.id}
                  mod={mod}
                  index={i}
                  deps={projectDeps}
                  allModules={modules}
                  onOpen={() => navigate(`/projects/${slug}/mm/${mod.id}`)}
                />
              ))}
            </div>
          )}

          {/* Bottom row: dep summary + placeholder activity */}
          {modules.length > 0 && (
            <div className="grid grid-cols-2 gap-4">
              {/* Dependency summary */}
              <div className="rounded-xl border border-[var(--color-border-default)] bg-[var(--color-canvas)] p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">Závislosti</span>
                  <button
                    onClick={() => navigate(`/projects/${slug}/mm/depmap`)}
                    className="text-[10px] text-primary-700 dark:text-primary-400 hover:text-primary-300 transition-colors"
                  >
                    Mapa závislostí →
                  </button>
                </div>
                {projectDeps.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-muted)]">Žiadne závislosti medzi modulmi.</p>
                ) : (
                  <div className="space-y-2">
                    {projectDeps.slice(0, 5).map((d) => {
                      const from = modules.find((m) => m.id === d.module_id);
                      const to = modules.find((m) => m.id === d.depends_on_module_id);
                      return (
                        <div key={d.id} className="flex items-center gap-2 text-xs">
                          <span className="font-mono text-[var(--color-text-secondary)]">{from?.code}</span>
                          <span className="text-[var(--color-text-muted)]">→</span>
                          <span className="font-mono text-[var(--color-text-secondary)]">{to?.code}</span>
                        </div>
                      );
                    })}
                    {projectDeps.length > 5 && (
                      <div className="pt-1 border-t border-[var(--color-border-default)] text-[10px] text-[var(--color-text-muted)]">
                        + {projectDeps.length - 5} ďalších závislostí
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Status summary */}
              <div className="rounded-xl border border-[var(--color-border-default)] bg-[var(--color-canvas)] p-4">
                <div className="text-xs font-semibold text-[var(--color-text-secondary)] mb-3">Stav modulov</div>
                <div className="space-y-2">
                  {(["planned", "in_design", "in_development", "done"] as const).map((s) => {
                    const count = modules.filter((m) => m.status === s).length;
                    if (count === 0) return null;
                    return (
                      <div key={s} className="flex items-center justify-between text-xs">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${statusCls(s)}`}>
                          {statusLabel(s)}
                        </span>
                        <span className="text-[var(--color-text-secondary)] font-semibold">{count}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* New Module Modal */}
      {showModal && (
        <NewModuleModal
          projectId={project.id}
          existingModules={modules}
          onClose={() => setShowModal(false)}
          onCreated={handleModuleCreated}
        />
      )}
    </div>
  );
}
