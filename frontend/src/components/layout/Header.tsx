/**
 * Application header — displays app title, username/role badge, and dark
 * mode toggle.
 *
 * Dark mode toggle calls ThemeContext.toggleDark() which adds/removes the
 * `dark` class on <html>.  The per-user preference is persisted in
 * localStorage under `nex_dark_${username}` (see ThemeContext.tsx).
 *
 * Username is read directly from the JWT stored in localStorage — no extra
 * API call needed for a display-only badge.
 */
import { Moon, Sun } from "lucide-react";

import { useTheme } from "../../contexts/ThemeContext";
import { getCurrentUser } from "../../services/api";

function Header() {
  const { isDark, toggleDark } = useTheme();
  const user = getCurrentUser();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6 dark:border-gray-700 dark:bg-gray-900">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          NEX Studio
        </h1>
      </div>

      <div className="flex items-center gap-3">
        {/* Dark mode toggle */}
        <button
          type="button"
          onClick={toggleDark}
          className="rounded-full p-1.5 text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          aria-label={isDark ? "Prepnúť na svetlý režim" : "Prepnúť na tmavý režim"}
          title={isDark ? "Svetlý režim" : "Tmavý režim"}
        >
          {isDark ? (
            <Sun className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4" aria-hidden="true" />
          )}
        </button>

        {/* User badge */}
        {user && (
          <span className="rounded-full bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            {user.username}
            <span className="ml-1 rounded bg-primary-100 px-1 py-0.5 text-[10px] font-semibold uppercase text-primary-700 dark:bg-primary-900 dark:text-primary-300">
              {user.role}
            </span>
          </span>
        )}
      </div>
    </header>
  );
}

export default Header;
