import { version } from "../../../package.json";

/**
 * Sidebar footer displaying the application version.
 *
 * Reads the version string from ``package.json`` and renders it as
 * "NEX Studio v{version}" in a muted gray style, positioned at the
 * bottom of the sidebar.
 */
function SidebarFooter() {
  return (
    <p
      className="px-3 text-xs text-gray-400 dark:text-gray-500"
      data-testid="version-text"
    >
      NEX Studio v{version}
    </p>
  );
}

export default SidebarFooter;
