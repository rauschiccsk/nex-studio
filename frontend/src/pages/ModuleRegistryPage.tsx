import { useParams } from "react-router-dom";

/**
 * Module registry + dependency graph page. Implemented in a later feat.
 */
function ModuleRegistryPage() {
  const { slug } = useParams<{ slug: string }>();

  return (
    <section className="space-y-2">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Modules — {slug ?? "(unknown)"}
      </h2>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Module registry and dependency graph will be rendered here.
      </p>
    </section>
  );
}

export default ModuleRegistryPage;
