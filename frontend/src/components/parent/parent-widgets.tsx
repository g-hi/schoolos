import Link from "next/link";
import { ParentDashboardResponse } from "@/lib/parent-api";
import UnavailableModuleCard from "@/components/parent/unavailable-module-card";

interface ParentWidgetsProps {
  dashboard: ParentDashboardResponse;
}

export default function ParentWidgets({ dashboard }: ParentWidgetsProps) {
  const activePickupCount = dashboard.pickup.active_requests.length;
  const timelinePreviewCount = dashboard.timeline_preview.length;

  return (
    <section className="space-y-4" aria-label="Parent dashboard widgets">
      <div className="grid gap-4 md:grid-cols-3">
        <article className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-medium text-gray-600">Linked students</h3>
          <p className="mt-2 text-2xl font-semibold text-gray-900">{dashboard.students.length}</p>
        </article>
        <article className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-medium text-gray-600">Active pickup requests</h3>
          <p className="mt-2 text-2xl font-semibold text-gray-900">{activePickupCount}</p>
        </article>
        <article className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-medium text-gray-600">Recent timeline items</h3>
          <p className="mt-2 text-2xl font-semibold text-gray-900">{timelinePreviewCount}</p>
        </article>
      </div>

      <article className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-base font-semibold text-gray-900">Family timeline preview</h3>
          <Link
            href="/parent/family"
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
          >
            Open timeline
          </Link>
        </div>

        {dashboard.timeline_preview.length === 0 ? (
          <p className="mt-3 text-sm text-gray-600">No timeline events yet.</p>
        ) : (
          <ul className="mt-3 space-y-2" aria-label="Timeline preview list">
            {dashboard.timeline_preview.map((event) => (
              <li key={event.event_id} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                <p className="text-sm font-medium text-gray-900">{event.title}</p>
                <p className="mt-1 text-xs text-gray-600">{new Date(event.occurred_at).toLocaleString()}</p>
              </li>
            ))}
          </ul>
        )}
      </article>

      <section aria-label="Unavailable modules" className="space-y-3">
        <h3 className="text-base font-semibold text-gray-900">Additional modules</h3>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <UnavailableModuleCard label="Academics" state={dashboard.academics} />
          <UnavailableModuleCard label="Attendance" state={dashboard.attendance} />
          <UnavailableModuleCard label="Homework" state={dashboard.homework} />
          <UnavailableModuleCard label="Reports" state={dashboard.reports} />
          <UnavailableModuleCard label="Messages" state={dashboard.messages} />
          <UnavailableModuleCard label="Payments" state={dashboard.payments} />
          <UnavailableModuleCard label="Announcements" state={dashboard.announcements} />
          <UnavailableModuleCard label="Notifications" state={dashboard.notifications} />
        </div>
      </section>
    </section>
  );
}
