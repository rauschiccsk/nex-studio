import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listProjectsApi } from "@/services/api/projects";
import { listProjectModules, listModuleDependencies } from "@/services/api/projectModules";
import type { ProjectRead } from "@/types";
import type { ProjectModuleRead } from "@/types/projectModule";
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
  if (status === "done") return "text-green-400";
  if (status === "in_development") return "text-yellow-400";
  if (status === "in_design") return "text-indigo-400";
  return "text-slate-500";
}

// ─── MMDepMapPage ─────────────────────────────────────────────────────────────

export default function MMDepMapPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectRead | null>(null);
  const [modules, setModules] = useState<ProjectModuleRead[]>([]);
  const [deps, setDeps] = useState<ModuleDependencyRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    listProjectsApi({ limit: 100 })
      .then((res) => {
        if (cancelled) return;
        const found = res.items.find((p) => p.slug === slug);
        if (!found) { setError("Projekt nebol nájdený."); setLoading(false); return; }
        setProject(found);
        return Promise.all([
          listProjectModules({ project_id: found.id, limit: 100 }),
          listModuleDependencies({ limit: 100 }),
        ]).then(([modRes, depRes]) => {
          if (cancelled) return;
          setModules(modRes.items);
          const moduleIds = new Set(modRes.items.map((m) => m.id));
          setDeps(depRes.items.filter(
            (d) => moduleIds.has(d.module_id) && moduleIds.has(d.depends_on_module_id),
          ));
        });
      })
      .catch(() => { if (!cancelled) setError("Nepodarilo sa načítať dáta."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug]);

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

  if (error || !project) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 p-4 text-sm text-red-400">
          {error || "Projekt nebol nájdený."}
        </div>
      </div>
    );
  }

  // Build dependency map: moduleId → [depends on moduleIds]
  const needsMap = new Map<string, string[]>();
  const neededByMap = new Map<string, string[]>();
  for (const mod of modules) {
    needsMap.set(mod.id, []);
    neededByMap.set(mod.id, []);
  }
  for (const dep of deps) {
    needsMap.get(dep.module_id)?.push(dep.depends_on_module_id);
    neededByMap.get(dep.depends_on_module_id)?.push(dep.module_id);
  }

  // Topological sort (Kahn's algorithm) — root modules first
  function topoSort(): ProjectModuleRead[] {
    const inDegree = new Map<string, number>();
    for (const mod of modules) inDegree.set(mod.id, 0);
    for (const dep of deps) {
      inDegree.set(dep.module_id, (inDegree.get(dep.module_id) ?? 0) + 1);
    }
    const queue = modules.filter((m) => (inDegree.get(m.id) ?? 0) === 0);
    const result: ProjectModuleRead[] = [];
    while (queue.length > 0) {
      const mod = queue.shift()!;
      result.push(mod);
      const consumers = neededByMap.get(mod.id) ?? [];
      for (const cId of consumers) {
        const deg = (inDegree.get(cId) ?? 1) - 1;
        inDegree.set(cId, deg);
        if (deg === 0) {
          const m = modules.find((x) => x.id === cId);
          if (m) queue.push(m);
        }
      }
    }
    // Append any remaining (cycle members)
    for (const mod of modules) {
      if (!result.includes(mod)) result.push(mod);
    }
    return result;
  }

  const sorted = topoSort();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 bg-slate-900/50 border-b border-slate-800 px-5 py-2.5 flex items-center gap-3">
        <button
          onClick={() => navigate(`/projects/${slug}/mm`)}
          className="text-slate-500 hover:text-slate-300 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <span className="text-sm font-semibold text-slate-100">{project.name}</span>
        <span className="text-slate-600">·</span>
        <span className="text-sm text-slate-400">Mapa závislostí</span>
        <div className="flex-1" />
        <span className="text-xs text-slate-500">{modules.length} modulov · {deps.length} závislostí</span>
      </div>

      {/* Map content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto">

          {modules.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-800 p-10 text-center">
              <p className="text-sm text-slate-500">Žiadne moduly</p>
            </div>
          ) : deps.length === 0 ? (
            <>
              {/* No deps — just show modules in a flat list */}
              <p className="text-xs text-slate-600 mb-4">Žiadne závislosti medzi modulmi. Moduly sú nezávislé.</p>
              <div className="flex flex-wrap gap-3">
                {sorted.map((mod, i) => (
                  <button
                    key={mod.id}
                    onClick={() => navigate(`/projects/${slug}/mm/${mod.id}`)}
                    className={`px-3 py-2 rounded-lg border font-mono font-bold text-sm ${MODULE_COLORS[i % MODULE_COLORS.length]} hover:opacity-80 transition-opacity`}
                  >
                    {mod.code}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="space-y-2">
              {/* Legend */}
              <div className="flex items-center gap-4 text-[10px] text-slate-600 mb-4">
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-px bg-slate-600 inline-block" />
                  závisí od (→ musí byť hotový skôr)
                </span>
              </div>

              {/* Dependency rows */}
              {sorted.map((mod, i) => {
                const needs = (needsMap.get(mod.id) ?? []).map((id) => modules.find((m) => m.id === id)).filter(Boolean) as ProjectModuleRead[];
                const neededBy = (neededByMap.get(mod.id) ?? []).map((id) => modules.find((m) => m.id === id)).filter(Boolean) as ProjectModuleRead[];

                return (
                  <div
                    key={mod.id}
                    className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 cursor-pointer hover:border-slate-700 transition-colors"
                    onClick={() => navigate(`/projects/${slug}/mm/${mod.id}`)}
                  >
                    {/* Module badge */}
                    <div className={`shrink-0 px-2 py-1 rounded border font-mono font-bold text-xs ${MODULE_COLORS[i % MODULE_COLORS.length]}`}>
                      {mod.code}
                    </div>

                    {/* Name + status */}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-200 font-medium">{mod.name}</div>
                      <div className={`text-xs ${statusCls(mod.status)}`}>{mod.category}</div>
                    </div>

                    {/* Needs */}
                    {needs.length > 0 && (
                      <div className="flex items-center gap-1 text-xs text-slate-500">
                        <span className="text-slate-600">závisí od:</span>
                        {needs.map((n) => (
                          <span
                            key={n.id}
                            className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${MODULE_COLORS[(modules.findIndex((m) => m.id === n.id)) % MODULE_COLORS.length]}`}
                          >
                            {n.code}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* NeededBy */}
                    {neededBy.length > 0 && (
                      <div className="flex items-center gap-1 text-xs text-slate-500">
                        <span className="text-slate-600">vyžadujú:</span>
                        {neededBy.map((n) => (
                          <span
                            key={n.id}
                            className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${MODULE_COLORS[(modules.findIndex((m) => m.id === n.id)) % MODULE_COLORS.length]}`}
                          >
                            {n.code}
                          </span>
                        ))}
                      </div>
                    )}

                    {needs.length === 0 && neededBy.length === 0 && (
                      <span className="text-[10px] text-slate-700">nezávislý</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
