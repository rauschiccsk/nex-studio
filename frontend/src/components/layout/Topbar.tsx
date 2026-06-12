import { useLocation } from "react-router-dom";
import { Header } from "nex-shared";

const breadcrumbMap: Record<string, string> = {
  "/": "Prehľad",
  "/projects": "Projekty",
  "/kb": "Dokumentácia",
  "/settings": "Nastavenia",
};

export default function Topbar() {
  const location = useLocation();

  const label = breadcrumbMap[location.pathname] ?? "NEX Studio";

  // The header chrome (height, dark bg, border) comes from the shared <Header>;
  // the connection dot + breadcrumb stay NEX Studio content.
  return (
    <Header>
      {/* Connected indicator */}
      <div className="flex items-center gap-1.5 shrink-0">
        <div className="w-2 h-2 rounded-full bg-green-400" />
        <span className="text-xs text-slate-300 font-medium">Pripojené</span>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 flex-1 min-w-0 overflow-hidden text-xs text-slate-500">
        <span className="text-slate-600">/</span>
        <span className="text-slate-300">{label}</span>
      </div>
    </Header>
  );
}
