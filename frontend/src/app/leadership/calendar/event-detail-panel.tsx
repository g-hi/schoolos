"use client";

import type { EventImpactResponse, EventVersion, ManualEvent } from "@/lib/timetable-calendar-api";
import { lifecycleBadgeTone, publicationLabel, reviewBadgeTone } from "@/app/leadership/calendar/calendar-utils";

interface EventDetailPanelProps {
  selectedEvent: ManualEvent | null;
  versions: EventVersion[];
  impact: EventImpactResponse | null;
  loading: boolean;
}

function pretty(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function EventDetailPanel({ selectedEvent, versions, impact, loading }: EventDetailPanelProps) {
  if (loading) {
    return <p className="text-sm text-gray-600">Loading selected event...</p>;
  }

  if (!selectedEvent) {
    return <p className="rounded-xl border border-dashed border-gray-300 bg-white p-6 text-sm text-gray-600">Select an event to view details, impact, and immutable versions.</p>;
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-lg font-semibold text-gray-900">{selectedEvent.event_name}</h3>
        <p className="mt-1 text-sm text-gray-600">{selectedEvent.start_date} to {selectedEvent.end_date} · {selectedEvent.event_type}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className={`rounded-full px-2 py-1 ${lifecycleBadgeTone(selectedEvent.lifecycle_status)}`}>{selectedEvent.lifecycle_status}</span>
          <span className={`rounded-full px-2 py-1 ${reviewBadgeTone(selectedEvent.review_status)}`}>{selectedEvent.review_status}</span>
          <span className="rounded-full bg-gray-100 px-2 py-1 text-gray-700">{publicationLabel(selectedEvent)}</span>
        </div>

        <dl className="mt-3 grid gap-2 text-sm md:grid-cols-2">
          <div><dt className="font-medium text-gray-700">Source and provenance</dt><dd className="text-gray-600">source_type: {selectedEvent.source_type}</dd></div>
          <div><dt className="font-medium text-gray-700">Notification plan status</dt><dd className="text-gray-600">{selectedEvent.notification_plan_status}</dd></div>
          <div><dt className="font-medium text-gray-700">Current version</dt><dd className="text-gray-600">v{selectedEvent.version_number}</dd></div>
          <div><dt className="font-medium text-gray-700">Change reason</dt><dd className="text-gray-600">{selectedEvent.change_reason || "-"}</dd></div>
        </dl>

        <div className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900">
          <p className="font-semibold">Agent suggestion boundary</p>
          <p className="mt-1 text-xs">Source evidence, agent proposal, deterministic validation, human decision, and operational records are reviewed separately. Suggestions are never final decisions.</p>
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h4 className="text-sm font-semibold text-gray-900">Stakeholder impact preview</h4>
        {!impact ? (
          <p className="mt-2 text-sm text-gray-600">Impact has not been loaded for this view.</p>
        ) : (
          <div className="mt-2 space-y-1 text-sm text-gray-700">
            <p>Total affected: {impact.impact.affected_count}</p>
            <p>Role breakdown: {Object.entries(impact.impact.role_breakdown).map(([key, value]) => `${key}:${value}`).join(", ") || "none"}</p>
            <p>Grade breakdown: {Object.entries(impact.impact.grade_breakdown).map(([key, value]) => `${key}:${value}`).join(", ") || "none"}</p>
            <p>Class breakdown: {Object.entries(impact.impact.class_breakdown).length || 0} classes</p>
            <p>Department breakdown: {Object.entries(impact.impact.department_breakdown).map(([key, value]) => `${key}:${value}`).join(", ") || "none"}</p>
            <p>Unresolved targeting issues: {impact.impact.unresolved_targeting_issues.join("; ") || "none"}</p>
            <p>Privacy notes: {impact.impact.privacy_notes.join("; ") || "none"}</p>
            <p>Recommended communication channels: {impact.impact.recommended_channels.join(", ") || "in_app"}</p>
            <p className="text-xs text-gray-500">Impact is calculated from current canonical SchoolOS data.</p>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h4 className="text-sm font-semibold text-gray-900">Version history (immutable)</h4>
        {versions.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">No change history found.</p>
        ) : (
          <div className="mt-3 space-y-3">
            {versions.map((item) => (
              <article key={item.id} className="rounded-lg border border-gray-100 p-3 text-sm">
                <p className="font-semibold text-gray-900">Version {item.version_number} · {item.change_type}</p>
                <p className="text-xs text-gray-600">Timestamp: {new Date(item.created_at).toLocaleString()}</p>
                <p className="text-xs text-gray-600">Reason: {item.reason || "-"} · Source: {item.source_type}</p>
                <p className="text-xs text-gray-600">Changed fields: {item.changed_fields.join(", ") || "none"}</p>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  {item.changed_fields.map((field) => (
                    <div key={field} className="rounded bg-gray-50 p-2 text-xs text-gray-700">
                      <p className="font-medium text-gray-900">{field}</p>
                      <p>Previous: {pretty(item.previous_values[field])}</p>
                      <p>New: {pretty(item.new_values[field])}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-xs text-gray-600">Affected stakeholder summary: {JSON.stringify(item.affected_stakeholder_summary)}</p>
                <p className="text-xs text-gray-600">Notification plan ref: {item.notification_plan_id || "-"}</p>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
