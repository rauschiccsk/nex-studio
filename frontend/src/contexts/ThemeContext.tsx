/**
 * Per-user dark mode preference.
 *
 * Preference is stored in localStorage under a key that includes the
 * username, so each team member (Zoltán, Tibor, Nazar, Dominik) gets
 * their own setting on a shared machine.  Falls back to a generic key
 * when no user is authenticated.
 *
 * Toggling calls `document.documentElement.classList.add/remove("dark")`
 * which is the signal Tailwind `darkMode: "class"` watches.
 */
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { getCurrentUser } from "../services/api";

function darkStorageKey(username: string | null): string {
  return username ? `nex_dark_${username}` : "nex_dark";
}

function readStoredPreference(username: string | null): boolean {
  try {
    return window.localStorage.getItem(darkStorageKey(username)) === "true";
  } catch {
    return false;
  }
}

interface ThemeContextValue {
  isDark: boolean;
  toggleDark: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  isDark: false,
  toggleDark: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const user = getCurrentUser();
  const username = user?.username ?? null;

  const [isDark, setIsDark] = useState<boolean>(() =>
    readStoredPreference(username),
  );

  useEffect(() => {
    const root = document.documentElement;
    if (isDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    try {
      window.localStorage.setItem(darkStorageKey(username), String(isDark));
    } catch {
      // ignore — localStorage may be unavailable in some environments
    }
  }, [isDark, username]);

  const toggleDark = () => setIsDark((prev) => !prev);

  return (
    <ThemeContext.Provider value={{ isDark, toggleDark }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
