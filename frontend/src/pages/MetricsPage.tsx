import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

import { getProjectMetricsApi } from "@/services/api/metrics";
import { useActiveContextStore } from "@/store/activeContextStore";
import type { ProjectMetrics, ScopeUsage, VersionMetrics } from "@/types/metrics";

type ScopeLevel = "by_epic" | "by_feat" | "by_task";

const SCOPE_LABEL: Record<ScopeLevel, string> = {
  by_epic: "EPIC",
  by_feat: "FEAT",
  by_task: "TASK",
};

// ─── formatting (honest: null → dash, never a fabricated number) ─────────────

function fmtInt(n: number): string {
  return Math.round(n).toLocaleString("sk-SK");
}

function fmtDuration(seconds: number): string {
  if (seconds <= 0) return "0 s";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d} d ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min ${s} s`;
  return `${s} s`;
}

function fmtCost(n: number | null): string {
  return n === null ? "—" : n.toLocaleString("sk-SK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ─── small presentational pieces ─────────────────────────────────────────────

function Card({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "good" | "muted";
}) {
  const valueCls =
    tone === "good" ? "text-green-400" : tone === "muted" ? "text-slate-500" : "text-slate-100";
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 p-4">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`text-xl font-bold mt-1 ${valueCls}`}>{value}</div>
      {hint && <div className="text-[11px] text-slate-600 mt-0.5">{hint}</div>}
    </div>
  );
}

export default function MetricsPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const selectedProject = useActiveContextStore((s) => s.selectedProject);

  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scopeLevel, setScopeLevel] = useState<ScopeLevel>("by_epic");
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setLoading(true);
    getProjectMetricsApi(slug)
      .then((m) => {
        if (cancelled) return;
        setMetrics(m);
        const last = m.by_version[m.by_version.length - 1];
        if (last) setSelectedVersionId(last.version_id);
      })
      .catch(() => {
        if (!cancelled) setError("Nepodarilo sa načítať metriky.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const selectedVersion: VersionMetrics | null = useMemo(
    () => metrics?.by_version.find((v) => v.version_id === selectedVersionId) ?? null,
    [metrics, selectedVersionId],
  );

  const scopeChartData = useMemo(() => {
    if (!selectedVersion) return [];
    return (selectedVersion[scopeLevel] as ScopeUsage[]).map((s) => ({
      name: `#${s.number} ${s.title}`,
      vstup: s.usage.input_tokens,
      výstup: s.usage.output_tokens,
      "čas (min)": Math.round((s.usage.duration_seconds / 60) * 10) / 10,
    }));
  }, [selectedVersion, scopeLevel]);

  const roleChartData = useMemo(() => {
    if (!selectedVersion) return [];
    return selectedVersion.by_role.map((r) => ({
      name: r.role,
      vstup: r.usage.input_tokens,
      výstup: r.usage.output_tokens,
      "čas (min)": Math.round((r.usage.duration_seconds / 60) * 10) / 10,
    }));
  }, [selectedVersion]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-500 text-sm gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Načítavam…
      </div>
    );
  }

  if (error || !metrics) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 p-4 text-sm text-red-400">
          {error || "Metriky nedostupné."}
        </div>
      </div>
    );
  }

  const { roi, usage } = metrics;
  const projectName = selectedProject?.slug === slug ? selectedProject?.name : slug;
  const settingsLink = (
    <button onClick={() => navigate("/settings")} className="text-primary-400 hover:text-primary-300 underline">
      Nastavenia
    </button>
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-base font-bold text-slate-100 mb-1">Metriky &amp; ROI</h1>
      <p className="text-xs text-slate-600 mb-4">
        Nameraná AI práca pre <span className="text-slate-400">{projectName}</span> (tokeny + čas) + odhad
        ľudskej náročnosti z plánu. Čísla, ktoré chýbajú (ceny / odhady), sa nezobrazujú vymyslené.
      </p>

      {/* Headline ROI */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <Card
          label="Rýchlejšie ako človek"
          value={roi.x_faster !== null ? `${roi.x_faster.toLocaleString("sk-SK", { maximumFractionDigits: 1 })}×` : "—"}
          hint={roi.x_faster === null ? "Odhady nenastavené" : "odhad z plánu vs. nameraný AI čas"}
          tone={roi.x_faster !== null ? "good" : "muted"}
        />
        <Card
          label="Lacnejšie ako človek"
          value={roi.y_cheaper_pct !== null ? `${roi.y_cheaper_pct.toLocaleString("sk-SK", { maximumFractionDigits: 1 })} %` : "—"}
          hint={roi.y_cheaper_pct === null ? "Ceny / odhady nenastavené" : "ľudská vs. API cena"}
          tone={roi.y_cheaper_pct !== null ? "good" : "muted"}
        />
        <Card
          label="API náklady (spolu)"
          value={fmtCost(metrics.api_cost)}
          hint={metrics.api_cost === null ? "Ceny nenastavené" : undefined}
          tone={metrics.api_cost === null ? "muted" : "default"}
        />
        <Card
          label="Čas start → PROD"
          value={metrics.total_time_seconds !== null ? fmtDuration(metrics.total_time_seconds) : "—"}
        />
      </div>

      {/* Unset-config banner */}
      {(!metrics.pricing_configured || !metrics.estimates_configured) && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300 mb-4">
          {!metrics.pricing_configured && <>Ceny nenastavené — doplň sadzby v {settingsLink} pre výpočet nákladov a ROI. </>}
          {!metrics.estimates_configured && <>Odhady nenastavené — task-plan zatiaľ neobsahuje odhad ľudskej náročnosti (ROI sa zobrazí po doplnení).</>}
        </div>
      )}

      {/* Director-wait (separate — never mixed into AI time) + cumulative AI + human baseline */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Card
          label="AI výpočtový čas"
          value={fmtDuration(usage.duration_seconds)}
          hint={`${fmtInt(usage.input_tokens)} vstup / ${fmtInt(usage.output_tokens)} výstup tokenov`}
        />
        <Card
          label="Čakanie na Directora (prestoje)"
          value={fmtDuration(metrics.director_wait_seconds)}
          hint="NEzapočítané do AI času"
          tone="muted"
        />
        <Card
          label="Odhad ľudskej práce"
          value={metrics.estimates_configured ? fmtDuration(roi.human_minutes * 60) : "—"}
          hint={metrics.estimates_configured ? "odhad z plánu" : "Odhady nenastavené"}
          tone={metrics.estimates_configured ? "default" : "muted"}
        />
        <Card
          label="Ľudská cena (odhad)"
          value={fmtCost(roi.human_cost)}
          hint={roi.human_cost === null ? "Ceny / odhady nenastavené" : "odhad z plánu × sadzba"}
          tone={roi.human_cost === null ? "muted" : "default"}
        />
      </div>

      {/* Per-version breakdown table */}
      <h2 className="text-sm font-semibold text-slate-300 mb-2">Podľa verzie</h2>
      <div className="rounded-lg border border-slate-700 bg-slate-900 divide-y divide-slate-800 mb-6">
        {metrics.by_version.length === 0 ? (
          <div className="p-4 text-sm text-slate-500">Žiadne pipeline dáta — metriky sa naplnia po prvom builde.</div>
        ) : (
          metrics.by_version.map((v) => (
            <div key={v.version_id} className="p-3 grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
              <div className="font-mono text-slate-300">{v.version_number}</div>
              <div className="text-slate-400">{fmtInt(v.usage.input_tokens + v.usage.output_tokens)} tokenov</div>
              <div className="text-slate-400">{fmtDuration(v.usage.duration_seconds)} AI</div>
              <div className="text-slate-500">prestoje {fmtDuration(v.director_wait_seconds)}</div>
              <div className="text-slate-400">{v.api_cost !== null ? `${fmtCost(v.api_cost)} API` : "cena —"}</div>
            </div>
          ))
        )}
      </div>

      {/* Per-scope + per-role charts (for the selected version) */}
      {metrics.by_version.length > 0 && selectedVersion && (
        <>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-slate-300">Rozpad — {selectedVersion.version_number}</h2>
            <div className="flex items-center gap-2">
              <select
                value={selectedVersionId}
                onChange={(e) => setSelectedVersionId(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100"
              >
                {metrics.by_version.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.version_number}
                  </option>
                ))}
              </select>
              <div className="flex rounded border border-slate-700 overflow-hidden">
                {(["by_epic", "by_feat", "by_task"] as ScopeLevel[]).map((lvl) => (
                  <button
                    key={lvl}
                    onClick={() => setScopeLevel(lvl)}
                    className={`px-2.5 py-1 text-[11px] ${
                      scopeLevel === lvl ? "bg-primary-600 text-white" : "bg-slate-800 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {SCOPE_LABEL[lvl]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-900 p-3 mb-4">
            <div className="text-[11px] text-slate-500 mb-2">Tokeny + čas podľa {SCOPE_LABEL[scopeLevel]}</div>
            {scopeChartData.length === 0 ? (
              <div className="text-xs text-slate-600 py-8 text-center">Žiadne dáta na tejto úrovni.</div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={scopeChartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#94a3b8" }} interval={0} angle={-15} height={50} />
                  <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="vstup" stackId="tok" fill="#38bdf8" />
                  <Bar dataKey="výstup" stackId="tok" fill="#818cf8" />
                  <Bar dataKey="čas (min)" fill="#34d399" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-900 p-3 mb-4">
            <div className="text-[11px] text-slate-500 mb-2">Náklady / práca podľa roly</div>
            {roleChartData.length === 0 ? (
              <div className="text-xs text-slate-600 py-8 text-center">Žiadne dáta.</div>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={roleChartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#94a3b8" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="vstup" stackId="tok" fill="#38bdf8" />
                  <Bar dataKey="výstup" stackId="tok" fill="#818cf8" />
                  <Bar dataKey="čas (min)" fill="#34d399" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </div>
  );
}
