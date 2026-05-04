/**
 * Cosmetic Tailwind class mapping for KB document categories.
 *
 * Per ICC Clean Code §3 — central config: colour mapping lives in one
 * place, not spread across switch statements in components. The set of
 * category codes themselves is the backend's responsibility (single
 * source of truth: ``backend/constants/kb_categories.py`` exposed via
 * ``GET /api/v1/kb-documents/categories``); this file only decides
 * what each one looks like.
 *
 * If a category code is not in the map (e.g. a freshly added
 * filesystem category that didn't get a colour assigned yet), the
 * helper falls back to a neutral slate styling — never throws.
 */

export const KB_CATEGORY_DEFAULT_COLOR =
  "bg-slate-700/60 border-slate-600 text-slate-400";

export const KB_CATEGORY_COLORS: Record<string, string> = {
  // Original 7 — NEX Studio pipeline / ICC-wide reference docs
  standards: "bg-indigo-500/20 border-indigo-500/30 text-indigo-400",
  decisions: "bg-purple-500/20 border-purple-500/30 text-purple-400",
  lessons: "bg-amber-500/20 border-amber-500/30 text-amber-400",
  patterns: "bg-cyan-500/20 border-cyan-500/30 text-cyan-400",
  design: "bg-green-500/20 border-green-500/25 text-green-400",
  behavior: "bg-rose-500/20 border-rose-500/30 text-rose-400",
  session: "bg-slate-700/60 border-slate-600 text-slate-400",
  // Filesystem-derived (migration 037)
  icc: "bg-blue-500/20 border-blue-500/30 text-blue-400",
  infrastructure: "bg-teal-500/20 border-teal-500/30 text-teal-400",
  customers: "bg-fuchsia-500/20 border-fuchsia-500/30 text-fuchsia-400",
  shuhari: "bg-violet-500/20 border-violet-500/30 text-violet-400",
  templates: "bg-sky-500/20 border-sky-500/30 text-sky-400",
  "service-manuals": "bg-emerald-500/20 border-emerald-500/30 text-emerald-400",
  deployment: "bg-orange-500/20 border-orange-500/30 text-orange-400",
  quarantine: "bg-red-500/20 border-red-500/30 text-red-400",
  "project-status": "bg-lime-500/20 border-lime-500/30 text-lime-400",
  "project-history": "bg-yellow-500/20 border-yellow-500/30 text-yellow-400",
  "project-architect": "bg-cyan-600/20 border-cyan-600/30 text-cyan-300",
  "project-other": "bg-slate-600/40 border-slate-500/40 text-slate-300",
};

export function kbCategoryColor(category: string): string {
  return KB_CATEGORY_COLORS[category] ?? KB_CATEGORY_DEFAULT_COLOR;
}
