import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Package, Layers, Server, Globe, Database, AlertCircle } from "lucide-react";

import { api, ApiError } from "@/services/api";
import type { ProjectRead } from "@/types";

// ── helpers ─────────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, string> = {
  active:   "bg-green-500/15 text-green-400 border border-green-500/30",
  paused:   "bg-yellow-500/15 text-yellow-400 border border-yellow-500/30",
  archived: "bg-gray-500/15 text-gray-400 border border-gray-500/30",
};

const STATUS_LABEL: Record<string, string> = {
  active:   "Aktívny",
  paused:   "Pozastavený",
  archived: "Archivovaný",
};

function CategoryIcon({ category }: { category: string }) {
  return category === "multimodule"
    ? <Layers className="h-4 w-4" />
    : <Package className="h-4 w-4" />;
}

function PortPill({ label, port, icon }: { label: string; port: number | null; icon: React.ReactNode }) {
  if (!port) return null;
  return (
    <span className="flex items-center gap-1 rounded bg-gray-700/60 px-1.5 py-0.5 text-xs text-gray-400">
      {icon}
      <span className="text-gray-300">{port}</span>
      <span className="text-gray-500">{label}</span>
    </span>
  );
}

// ── component ────────────────────────────────────────────────────────────────

function ProjectsPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ items: ProjectRead[]; total: number }>("/projects")
      .then((data) => setProjects(data.items))
      .catch((err) => {
        setError(
          err instanceof ApiError
            ? err.message
            : "Nepodarilo sa načítať projekty.",
        );
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-100">Projekty</h2>
          {!loading && !error && (
            <p className="mt-0.5 text-sm text-gray-500">
              {projects.length === 0
                ? "Žiadne projekty"
                : `${projects.length} ${projects.length === 1 ? "projekt" : "projektov"}`}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => navigate("/projects/new")}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-gray-900"
        >
          <Plus className="h-4 w-4" />
          Nový projekt
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16 text-gray-500">
          <span className="text-sm">Načítavam projekty…</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && projects.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-gray-700 bg-gray-800/50 py-20 text-center">
          <Package className="mb-3 h-10 w-10 text-gray-600" />
          <p className="text-sm font-medium text-gray-400">Žiadne projekty</p>
          <p className="mt-1 text-xs text-gray-600">
            Vytvor prvý projekt kliknutím na "Nový projekt"
          </p>
        </div>
      )}

      {/* Project cards */}
      {!loading && !error && projects.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              onClick={() => navigate(`/projects/${project.slug}`)}
              className="group flex flex-col gap-3 rounded-xl border border-gray-700 bg-gray-800 p-5 text-left transition-colors hover:border-primary/50 hover:bg-gray-750 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-gray-900"
            >
              {/* Card header */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-gray-500">
                    <CategoryIcon category={project.category} />
                  </span>
                  <span className="truncate text-base font-semibold text-gray-100 group-hover:text-white">
                    {project.name}
                  </span>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[project.status] ?? STATUS_BADGE.archived}`}
                >
                  {STATUS_LABEL[project.status] ?? project.status}
                </span>
              </div>

              {/* Slug */}
              <p className="text-xs font-mono text-gray-500">{project.slug}</p>

              {/* Description */}
              {project.description && (
                <p className="line-clamp-2 text-sm text-gray-400">
                  {project.description}
                </p>
              )}

              {/* Ports */}
              {(project.backend_port || project.frontend_port || project.db_port) && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <PortPill label="BE" port={project.backend_port} icon={<Server className="h-3 w-3" />} />
                  <PortPill label="FE" port={project.frontend_port} icon={<Globe className="h-3 w-3" />} />
                  <PortPill label="DB" port={project.db_port} icon={<Database className="h-3 w-3" />} />
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export default ProjectsPage;
