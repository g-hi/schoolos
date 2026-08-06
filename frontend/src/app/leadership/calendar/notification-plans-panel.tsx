"use client";

import { useState } from "react";
import type { CalendarNotificationPlanDetail, CalendarNotificationPlanSummary } from "@/lib/timetable-calendar-api";

interface NotificationPlansPanelProps {
  plans: CalendarNotificationPlanSummary[];
  selectedPlan: CalendarNotificationPlanDetail | null;
  loading: boolean;
  onSelectPlan: (planId: string) => Promise<void>;
  onApprovePlan: (planId: string, reason: string) => Promise<void>;
  onCancelPlan: (planId: string, reason: string) => Promise<void>;
}

export default function NotificationPlansPanel({ plans, selectedPlan, loading, onSelectPlan, onApprovePlan, onCancelPlan }: NotificationPlansPanelProps) {
  const [busy, setBusy] = useState(false);

  async function withBusy(work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-600">Loading notification plans...</p>;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Notification plans</h3>
        {plans.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">No notification plans require approval.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {plans.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => void onSelectPlan(item.id)}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-left text-sm hover:bg-gray-50"
              >
                <p className="font-semibold text-gray-900">{item.trigger_reason}</p>
                <p className="text-xs text-gray-600">event v{item.event_version_number} · affected {item.affected_count}</p>
                <p className="text-xs text-gray-600">approval: {item.approval_status} · outbox: {item.outbox_status}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Plan detail</h3>
        {!selectedPlan ? (
          <p className="mt-2 text-sm text-gray-600">Select a plan to review details.</p>
        ) : (
          <div className="space-y-2 text-sm text-gray-700">
            {selectedPlan.approval_required ? (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-amber-900">This announcement requires authorised human approval before it can be scheduled or delivered.</p>
            ) : null}
            <p><span className="font-medium">Related event:</span> {selectedPlan.event_id}</p>
            <p><span className="font-medium">Event version:</span> {selectedPlan.event_version_number}</p>
            <p><span className="font-medium">Trigger reason:</span> {selectedPlan.trigger_reason}</p>
            <p><span className="font-medium">Affected audience:</span> {selectedPlan.affected_count}</p>
            <p><span className="font-medium">Proposed subject:</span> {selectedPlan.subject}</p>
            <p><span className="font-medium">Proposed message:</span> {selectedPlan.proposed_message}</p>
            <p><span className="font-medium">Proposed channels:</span> {selectedPlan.channels.join(", ") || "none"}</p>
            <p><span className="font-medium">Schedule:</span> {selectedPlan.scheduled_at || "immediate"}</p>
            <p><span className="font-medium">Urgency:</span> {selectedPlan.urgency}</p>
            <p><span className="font-medium">Approval state:</span> {selectedPlan.approval_status}</p>
            <p><span className="font-medium">Outbox state:</span> {selectedPlan.outbox_status}</p>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const reason = window.prompt("Approval reason") || "";
                  if (reason.trim()) {
                    void withBusy(() => onApprovePlan(selectedPlan.id, reason.trim()));
                  }
                }}
                className="rounded border border-emerald-300 px-3 py-1.5 text-xs text-emerald-800 disabled:opacity-60"
              >
                Approve
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const reason = window.prompt("Cancellation reason") || "";
                  if (reason.trim()) {
                    void withBusy(() => onCancelPlan(selectedPlan.id, reason.trim()));
                  }
                }}
                className="rounded border border-rose-300 px-3 py-1.5 text-xs text-rose-800 disabled:opacity-60"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
