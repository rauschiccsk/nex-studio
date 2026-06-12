import { Outlet } from "react-router-dom";
import { AppShell } from "nex-shared";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import { PersistentTerminalsLayer } from "@/components/PersistentTerminalsLayer";

export default function AppLayout() {
  return (
    <AppShell sidebar={<Sidebar />} header={<Topbar />}>
      <Outlet />
      {/* Overlay anchored in AppShell's relative <main> region. */}
      <PersistentTerminalsLayer />
    </AppShell>
  );
}
