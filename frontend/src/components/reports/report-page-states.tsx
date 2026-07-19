import type { ReactNode } from "react";

export function ReportPageSkeleton({ title = "Loading" }: { title?: string }) {
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

export function ReportErrorState({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <section className="rounded-2xl border border-red-200 bg-red-50 p-5" role="alert" aria-live="polite">
      <h2 className="text-lg font-semibold text-red-800">{title}</h2>
      <p className="mt-2 text-sm text-red-700">{description}</p>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="mt-4 inline-flex rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100"
        >
          {actionLabel}
        </button>
      ) : null}
    </section>
  );
}

export function ReportEmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-6 text-center">
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      <p className="mt-2 text-sm text-gray-600">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </section>
  );
}

export function ReportStatusBadge({ status }: { status: string }) {
  const tone =
    status === "published"
      ? "bg-green-100 text-green-700"
      : status === "approved"
        ? "bg-blue-100 text-blue-700"
        : status === "pending_review"
          ? "bg-amber-100 text-amber-700"
          : status === "changes_requested"
            ? "bg-orange-100 text-orange-700"
            : status.includes("failed")
              ? "bg-red-100 text-red-700"
              : "bg-gray-100 text-gray-700";

  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}>{status.replaceAll("_", " ")}</span>;
}
