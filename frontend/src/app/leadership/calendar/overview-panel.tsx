"use client";

import type { CalendarEventCandidate, CalendarNotificationPlanSummary, CalendarPdfImportItem, ManualEvent } from "@/lib/timetable-calendar-api";

interface OverviewPanelProps {
  events: ManualEvent[];
  imports: CalendarPdfImportItem[];
  plans: CalendarNotificationPlanSummary[];
  candidates: CalendarEventCandidate[];
}

function countBy(events: ManualEvent[], predicate: (item: ManualEvent) => boolean): number {
  return events.filter(predicate).length;
}

export default function OverviewPanel({ events, imports, plans, candidates }: OverviewPanelProps) {
  const today = new Date().toISOString().slice(0, 10);

  const eventsToday = countBy(events, (item) => item.start_date <= today && item.end_date >= today);
  const eventsThisWeek = countBy(events, (item) => {
    const start = new Date(item.start_date).getTime();
    const now = Date.now();
    return start >= now - 86400000 && start <= now + 7 * 86400000;
  });
  const pendingApprovals = countBy(events, (item) => item.lifecycle_status === "pending_review");
  const changedEvents = countBy(events, (item) => ["rescheduled", "cancelled"].includes(item.lifecycle_status));
  const cancelledEvents = countBy(events, (item) => item.lifecycle_status === "cancelled");
  const pendingPlanApprovals = plans.filter((item) => item.approval_status === "pending_approval").length;
  const pendingCandidateReviews = candidates.filter((item) => ["proposed", "edited"].includes(item.candidate_status)).length;
  const unresolvedCandidateBlockers = candidates.reduce((total, item) => total + (item.validation_issues_json?.blockers?.length || 0), 0);

  const cards = [
    { label: "Events today", value: eventsToday },
    { label: "Events this week", value: eventsThisWeek },
    { label: "Pending event approvals", value: pendingApprovals },
    { label: "Pending candidate reviews", value: pendingCandidateReviews },
    { label: "Unresolved validation blockers", value: unresolvedCandidateBlockers },
    { label: "Changed or rescheduled events", value: changedEvents },
    { label: "Cancelled events", value: cancelledEvents },
    { label: "Pending notification approvals", value: pendingPlanApprovals },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <article key={card.label} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <p className="text-xs uppercase tracking-wide text-gray-500">{card.label}</p>
            <p className="mt-2 text-2xl font-semibold text-gray-900">{card.value}</p>
          </article>
        ))}
      </div>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Lifecycle legend</h3>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-700">
          <span className="rounded-full bg-slate-100 px-2 py-1">draft</span>
          <span className="rounded-full bg-amber-100 px-2 py-1">pending review</span>
          <span className="rounded-full bg-emerald-100 px-2 py-1">approved</span>
          <span className="rounded-full bg-blue-100 px-2 py-1">published</span>
          <span className="rounded-full bg-cyan-100 px-2 py-1">rescheduled</span>
          <span className="rounded-full bg-rose-100 px-2 py-1">cancelled</span>
          <span className="rounded-full bg-zinc-200 px-2 py-1">archived</span>
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Agenda snapshot</h3>
        {events.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">No upcoming events.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {events.slice(0, 6).map((item) => (
              <li key={item.id} className="rounded-lg border border-gray-100 p-3">
                <p className="text-sm font-medium text-gray-900">{item.event_name}</p>
                <p className="text-xs text-gray-600">{item.start_date} to {item.end_date} · {item.lifecycle_status}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-gray-500">{imports.length} imports tracked. Agent proposals are queued for human review before commit.</p>
      </section>
    </div>
  );
}
