import { useEffect } from "react";

export interface SuggestionMenuState {
  word: string;
  suggestions: string[];
  /** Absolute document coordinates where the menu anchors. */
  x: number;
  y: number;
  /** Start/end offsets of the misspelled word in the textarea value. */
  start: number;
  end: number;
}

interface Props {
  menu: SuggestionMenuState;
  onReplace: (replacement: string) => void;
  onIgnore: () => void;
  onClose: () => void;
}

/**
 * Right-click context menu for a misspelled word — lists the
 * spellchecker's top suggestions plus an "Ignore" option that adds
 * the word to the user's personal dictionary.
 */
export default function SpellSuggestionMenu({ menu, onReplace, onIgnore, onClose }: Props) {
  // Close on Escape or on click outside.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const onClick = () => onClose();
    window.addEventListener("keydown", onKey);
    // Deferred so the contextmenu event that opened us isn't captured.
    const t = setTimeout(() => window.addEventListener("mousedown", onClick), 0);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
      clearTimeout(t);
    };
  }, [onClose]);

  return (
    <div
      style={{ position: "fixed", top: menu.y, left: menu.x, zIndex: 100 }}
      className="min-w-[180px] rounded-lg border border-[var(--color-border-default)] bg-[var(--color-canvas)] shadow-xl py-1 text-sm"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="px-3 py-1 text-[10px] uppercase tracking-widest text-[var(--color-text-muted)] border-b border-[var(--color-border-default)]">
        <span className="text-[var(--color-text-secondary)] font-semibold">{menu.word}</span>
      </div>
      {menu.suggestions.length === 0 && (
        <div className="px-3 py-2 text-xs text-[var(--color-text-muted)] italic">Žiadne návrhy</div>
      )}
      {menu.suggestions.map((s) => (
        <button
          key={s}
          onClick={() => onReplace(s)}
          className="w-full text-left px-3 py-1.5 text-[var(--color-text-primary)] hover:bg-[var(--color-surface-hover)] transition-colors"
        >
          {s}
        </button>
      ))}
      <div className="border-t border-[var(--color-border-default)] mt-1 pt-1">
        <button
          onClick={onIgnore}
          className="w-full text-left px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text-primary)] transition-colors"
        >
          Pridať do slovníka
        </button>
      </div>
    </div>
  );
}
