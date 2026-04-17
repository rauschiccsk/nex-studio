/**
 * Settings page — DESIGN.md § 3.1 ``/settings``.
 *
 * Two sections:
 *   - **Vzhľad** — dark mode toggle (all roles).
 *   - **Správa používateľov** — embedded UserPage, visible only to ``ri``
 *     role users.  ``ha`` and ``shu`` never see this section.
 */

import { useAuthStore } from "@/store/authStore";
import DarkModeToggle from "@/components/settings/DarkModeToggle";
import UserPage from "./UserPage";

function SettingsPage() {
  const role = useAuthStore((s) => s.user?.role);

  return (
    <section className="space-y-8">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Nastavenia
      </h2>

      {/* ------- Vzhľad ------- */}
      <div data-testid="section-appearance">
        <h3 className="mb-3 text-lg font-medium text-gray-800 dark:text-gray-200">
          Vzhľad
        </h3>
        <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <DarkModeToggle />
        </div>
      </div>

      {/* ------- Správa používateľov (ri only) ------- */}
      {role === "ri" && (
        <div data-testid="section-users">
          <h3 className="mb-3 text-lg font-medium text-gray-800 dark:text-gray-200">
            Správa používateľov
          </h3>
          <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
            <UserPage />
          </div>
        </div>
      )}
    </section>
  );
}

export default SettingsPage;
