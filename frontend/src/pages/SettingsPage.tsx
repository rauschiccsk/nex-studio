/**
 * Settings page — per-user preferences.
 *
 * Dark mode toggle: stores preference in localStorage under
 * `nex_dark_${username}` (see ThemeContext.tsx).  Each team member
 * gets their own setting on a shared machine.
 */
import { Moon, Sun } from "lucide-react";

import { useTheme } from "../contexts/ThemeContext";
import { getCurrentUser } from "../services/api";

function SettingsPage() {
  const { isDark, toggleDark } = useTheme();
  const user = getCurrentUser();

  return (
    <section className="space-y-6">
      <header>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Nastavenia
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Osobné nastavenia pre{" "}
          <span className="font-medium">{user?.username ?? "používateľa"}</span>
          . Každý člen tímu má vlastné preferencie.
        </p>
      </header>

      {/* Appearance */}
      <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Vzhľad
        </h3>

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              Tmavý režim
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Nastavenie je uložené pre tohto používateľa na tomto zariadení.
            </p>
          </div>

          <button
            type="button"
            onClick={toggleDark}
            className={[
              "relative inline-flex h-9 w-16 items-center justify-between rounded-full px-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:focus:ring-offset-gray-900",
              isDark
                ? "bg-primary-600"
                : "bg-gray-200 dark:bg-gray-700",
            ].join(" ")}
            aria-label={isDark ? "Vypnúť tmavý režim" : "Zapnúť tmavý režim"}
            aria-pressed={isDark}
          >
            <Sun
              className={`h-4 w-4 transition-opacity ${isDark ? "text-white opacity-100" : "text-gray-400 opacity-40"}`}
              aria-hidden="true"
            />
            <Moon
              className={`h-4 w-4 transition-opacity ${isDark ? "text-white opacity-40" : "text-gray-500 opacity-100"}`}
              aria-hidden="true"
            />
          </button>
        </div>
      </div>
    </section>
  );
}

export default SettingsPage;
