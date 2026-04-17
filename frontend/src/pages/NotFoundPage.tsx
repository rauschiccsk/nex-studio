import { Link } from "react-router-dom";

/**
 * 404 fallback rendered for unknown routes.
 */
function NotFoundPage() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="text-center">
        <h1 className="mb-2 text-3xl font-semibold text-gray-900 dark:text-gray-100">404</h1>
        <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">
          The page you requested does not exist.
        </p>
        <Link to="/" className="btn-primary">
          Go to Dashboard
        </Link>
      </div>
    </div>
  );
}

export default NotFoundPage;
