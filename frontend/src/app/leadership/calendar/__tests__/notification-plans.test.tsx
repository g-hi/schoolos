import { render, screen } from "@testing-library/react";
import NotificationPlansPanel from "@/app/leadership/calendar/notification-plans-panel";

describe("notification plans", () => {
  it("shows high-impact approval banner and plan actions", () => {
    render(
      <NotificationPlansPanel
        plans={[
          {
            id: "plan-1",
            event_id: "evt-1",
            event_version_number: 2,
            trigger_reason: "event_cancelled",
            affected_count: 500,
            approval_required: true,
            approval_status: "pending_approval",
            outbox_status: "pending_approval",
          },
        ]}
        selectedPlan={{
          id: "plan-1",
          event_id: "evt-1",
          event_version_number: 2,
          trigger_reason: "event_cancelled",
          audience_scope: { scope_type: "whole_school" },
          affected_count: 500,
          subject: "Cancellation",
          proposed_message: "Event cancelled",
          channels: ["in_app"],
          scheduled_at: null,
          reminder_settings: {},
          urgency: "critical",
          approval_required: true,
          approval_status: "pending_approval",
          outbox_status: "pending_approval",
          delivery_summary: {},
          audit_reference_json: {},
        }}
        loading={false}
        onSelectPlan={vi.fn(async () => {})}
        onApprovePlan={vi.fn(async () => {})}
        onCancelPlan={vi.fn(async () => {})}
      />,
    );

    expect(screen.getByText(/requires authorised human approval/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByText(/deliver now/i)).not.toBeInTheDocument();
  });
});
