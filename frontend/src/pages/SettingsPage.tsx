/**
 * Settings page — DESIGN.md § 3.1 ``/settings``.
 *
 * Three tabs:
 *   - **Vzhľad** — dark mode toggle (all roles).
 *   - **Správa používateľov** — embedded UserPage, visible only to ``ri``
 *     role users.  ``ha`` and ``shu`` never see this tab.
 *   - **User Sessions** — embedded UserSessionPage, visible only to ``ri``
 *     role users.
 */

import { useMemo, useState } from "react";

import { useAuthStore } from "@/store/authStore";
import DarkModeToggle from "@/components/settings/DarkModeToggle";
import SettingsTabs from "@/components/settings/SettingsTabs";
import type { TabDefinition } from "@/components/settings/SettingsTabs";
import UserPage from "./UserPage";
import UserSessionPage from "./UserSessionPage";

type TabId = "appearance" | "users" | "sessions";

interface SettingsTab extends TabDefinition<TabId> {
  riOnly: boolean;
}

const ALL_TABS: SettingsTab[] = [
  { id: "appearance", label: "Vzhľad", riOnly: false },
  { id: "users", label: "Správa používateľov", riOnly: true },
  { id: "sessions", label: "User Sessions", riOnly: true },
];

function SettingsPage() {
  const role = useAuthStore((s) => s.user?.role);
  const [activeTab, setActiveTab] = useState<TabId>("appearance");

  const isRi = role === "ri";

  const visibleTabs = useMemo(
    () => ALL_TABS.filter((tab) => !tab.riOnly || isRi),
    [isRi],
  );

  // If the active tab became invisible (e.g. role changed), reset to first.
  const resolvedTab = visibleTabs.some((t) => t.id === activeTab)
    ? activeTab
    : visibleTabs[0]?.id ?? "appearance";

  return (
    <section className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Nastavenia
      </h2>

      {/* Tab bar */}
      <SettingsTabs
        tabs={visibleTabs}
        activeTab={resolvedTab}
        onTabChange={setActiveTab}
      />

      {/* Tab panels */}
      {resolvedTab === "appearance" && (
        <div
          id="tabpanel-appearance"
          role="tabpanel"
          data-testid="section-appearance"
        >
          <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
            <DarkModeToggle />
          </div>
        </div>
      )}

      {resolvedTab === "users" && isRi && (
        <div
          id="tabpanel-users"
          role="tabpanel"
          data-testid="section-users"
        >
          <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
            <UserPage />
          </div>
        </div>
      )}

      {resolvedTab === "sessions" && isRi && (
        <div
          id="tabpanel-sessions"
          role="tabpanel"
          data-testid="section-sessions"
        >
          <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
            <UserSessionPage />
          </div>
        </div>
      )}
    </section>
  );
}

export default SettingsPage;
