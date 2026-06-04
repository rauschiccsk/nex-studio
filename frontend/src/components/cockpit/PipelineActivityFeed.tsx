// Live agent activity feed (F-007, CR-NS-018). Shown only while the agent is
// working — a streaming view of what the headless agent is doing (reads, writes,
// tool calls, partial reasoning), auto-scrolling. Ephemeral; not persisted.

import { useEffect, useRef } from "react";
import { FileText, Loader2, Terminal, Wrench } from "lucide-react";

import type { ActivityLine } from "../../services/api/pipeline";

function KindIcon({ kind, line }: { kind: ActivityLine["kind"]; line: string }) {
  if (kind === "text") return <FileText className="h-3 w-3 shrink-0 text-slate-500" />;
  if (line.startsWith("spúšťa:")) return <Terminal className="h-3 w-3 shrink-0 text-sky-500" />;
  return <Wrench className="h-3 w-3 shrink-0 text-emerald-500" />;
}

interface Props {
  activity: ActivityLine[];
}

export function PipelineActivityFeed({ activity }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [activity.length]);

  return (
    <div className="flex max-h-32 flex-col overflow-y-auto border-b border-slate-800 bg-slate-950/60 px-4 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        Živá aktivita agenta
      </div>
      {activity.length === 0 ? (
        <div className="text-[11px] text-slate-600">Agent štartuje…</div>
      ) : (
        <ul className="space-y-0.5">
          {activity.map((a, i) => (
            <li key={i} className="flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
              <KindIcon kind={a.kind} line={a.line} />
              <span className="truncate">{a.line}</span>
            </li>
          ))}
        </ul>
      )}
      <div ref={endRef} />
    </div>
  );
}

export default PipelineActivityFeed;
