import { useParams } from "react-router-dom";

/**
 * Project overview with tabs. Implemented in a later feat.
 */
function ProjectPage() {
  const { slug } = useParams<{ slug: string }>();

  return (
    <section className="space-y-2">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Project: {slug ?? "(unknown)"}
      </h2>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Project overview and tabs will be rendered here.
      </p>
    </section>
  );
}

export default ProjectPage;
