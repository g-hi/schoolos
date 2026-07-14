import Link from "next/link";

interface TeacherPlaceholderPageProps {
  title: string;
  description: string;
  badge?: string;
  actionLabel?: string;
  actionHref?: string;
}

export default function TeacherPlaceholderPage({
  title,
  description,
  badge = "Coming soon",
  actionLabel = "Back to Teacher Dashboard",
  actionHref = "/teacher",
}: TeacherPlaceholderPageProps) {
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">{badge}</p>
            <h1 className="mt-2 text-2xl font-semibold text-gray-900">{title}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-gray-600">{description}</p>
          </div>
          <Link
            href={actionHref}
            className="inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700"
          >
            {actionLabel}
          </Link>
        </div>

        <div className="mt-8 rounded-xl border border-dashed border-gray-300 bg-gray-50 p-8 text-center">
          <p className="text-lg font-medium text-gray-800">This workspace is reserved for the next Teacher Portal capability.</p>
          <p className="mt-2 text-sm text-gray-600">
            The current release keeps the route structure in place and leaves the dashboard fully functional while the remaining modules remain placeholders.
          </p>
        </div>
      </div>
    </div>
  );
}
