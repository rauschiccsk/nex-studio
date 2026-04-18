/**
 * Sidebar footer displaying the application version.
 *
 * Version is injected at build time via the VITE_APP_VERSION environment
 * variable, which CI sets to "0.1.<github.run_number>" before every Docker
 * build.  Falls back to "dev" for local development where the variable is
 * not set.
 */
function SidebarFooter() {
  const version = import.meta.env.VITE_APP_VERSION || "dev";
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
