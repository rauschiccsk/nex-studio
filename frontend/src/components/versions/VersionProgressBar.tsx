/**
 * Horizontal progress bar showing EPIC completion for a version.
 *
 * Displays a percentage-filled bar with a label ``{epics_done}/{epic_count} EPICs``.
 * When ``epic_count`` is zero the bar renders at 0 % to avoid division by zero.
 */

interface VersionProgressBarProps {
  epicsDone: number;
  epicCount: number;
}

export default function VersionProgressBar({
  epicsDone,
  epicCount,
}: VersionProgressBarProps) {
  const pct = epicCount > 0 ? Math.round((epicsDone / epicCount) * 100) : 0;

  return (
    <div className="flex items-center gap-2" data-testid="version-progress">
      {/* Track */}
      <div className="h-2 w-24 rounded-full bg-gray-200 dark:bg-gray-700">
        {/* Fill */}
        <div
          className="h-2 rounded-full bg-primary-600 transition-all"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {/* Label */}
      <span className="whitespace-nowrap text-xs text-gray-600 dark:text-gray-400">
        {epicsDone}/{epicCount} EPICs
      </span>
    </div>
  );
}
