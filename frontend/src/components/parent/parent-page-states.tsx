import { ReactNode } from "react";

export function ParentPageSkeleton({ title = "Loading" }: { title?: string }) {
  return (
    <section aria-busy="true" aria-live="polite" className="space-y-4">
      <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {[1, 2, 3].map((item) => (
          <div key={item} className="h-28 animate-pulse rounded-2xl bg-gray-200" />
        ))}
      </div>
    </section>
  );
}

interface ParentErrorStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function ParentErrorState({
  title,
  description,
  actionLabel,
  onAction,
}: ParentErrorStateProps) {
  return (
    <section className="rounded-2xl border border-red-200 bg-red-50 p-5" role="alert" aria-live="polite">
      <h2 className="text-lg font-semibold text-red-800">{title}</h2>
      <p className="mt-2 text-sm text-red-700">{description}</p>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="mt-4 inline-flex rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
        >
          {actionLabel}
        </button>
      )}
    </section>
  );
}

interface ParentEmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function ParentEmptyState({ title, description, action }: ParentEmptyStateProps) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-6 text-center">
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      <p className="mt-2 text-sm text-gray-600">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </section>
  );
}
