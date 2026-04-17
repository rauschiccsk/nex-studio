/**
 * Reusable tabs component for the Settings page.
 *
 * Renders a horizontal tab bar with ARIA attributes and manages
 * active tab state.  Tabs can be filtered by visibility predicates
 * (e.g. role-based guards).
 *
 * @see DESIGN.md § 3.1 — ``/settings`` page tabs.
 */

export interface TabDefinition<T extends string = string> {
  /** Unique identifier for the tab. */
  id: T;
  /** Display label (Slovak UI text). */
  label: string;
}

interface SettingsTabsProps<T extends string> {
  /** All tabs to display. */
  tabs: TabDefinition<T>[];
  /** Currently active tab id. */
  activeTab: T;
  /** Callback when a tab is clicked. */
  onTabChange: (tabId: T) => void;
}

export default function SettingsTabs<T extends string>({
  tabs,
  activeTab,
  onTabChange,
}: SettingsTabsProps<T>) {
  return (
    <div
      className="flex gap-1 border-b border-gray-200 dark:border-gray-700"
      role="tablist"
      aria-label="Settings tabs"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          aria-controls={`tabpanel-${tab.id}`}
          className={[
            "px-4 py-2 text-sm font-medium transition-colors",
            activeTab === tab.id
              ? "border-b-2 border-primary-600 text-primary-700 dark:border-primary-400 dark:text-primary-300"
              : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200",
          ].join(" ")}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
