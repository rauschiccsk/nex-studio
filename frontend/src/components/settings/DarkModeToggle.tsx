/**
 * Dark mode toggle switch — DESIGN.md § 3.3a.
 *
 * A labelled toggle that calls ``useTheme().toggleDark`` on click.
 * Renders as a CSS-only switch (no external UI library).
 */

import { useTheme } from "@/contexts/ThemeContext";

export default function DarkModeToggle() {
  const { isDark, toggleDark } = useTheme();

  return (
    <label
      className="inline-flex cursor-pointer items-center gap-3"
      data-testid="dark-mode-toggle"
    >
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
        {isDark ? "Tmavý režim" : "Svetlý režim"}
      </span>

      {/* Accessible toggle built with a hidden checkbox + styled span. */}
      <div className="relative">
        <input
          type="checkbox"
          checked={isDark}
          onChange={toggleDark}
          className="peer sr-only"
          role="switch"
          aria-checked={isDark}
          aria-label="Prepnúť tmavý režim"
        />
        {/* Track */}
        <div className="h-6 w-11 rounded-full bg-gray-300 peer-checked:bg-indigo-600 peer-focus:ring-2 peer-focus:ring-indigo-400 dark:bg-gray-600" />
        {/* Knob */}
        <div className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5" />
      </div>
    </label>
  );
}
