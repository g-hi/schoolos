import { render, screen } from "@testing-library/react";
import EventDetailPanel from "@/app/leadership/calendar/event-detail-panel";

const selectedEvent = {
  id: "evt-1",
  event_name: "Exam window",
  description: null,
  start_date: "2026-11-01",
  end_date: "2026-11-07",
  event_type: "examination_period",
  teaching_day_effect: "special_schedule",
  source_type: "manual",
  review_status: "approved",
  lifecycle_status: "published",
  version_number: 3,
  change_reason: null,
  impact_scope_json: { scope_type: "whole_school" },
  notification_plan_status: "planned",
  notification_plan_json: {},
  published_at: null,
  is_active: true,
} as const;

describe("event impact panel", () => {
  it("renders counts, breakdowns, unresolved and privacy notes", () => {
    render(
      <EventDetailPanel
        selectedEvent={selectedEvent}
        versions={[]}
        loading={false}
        impact={{
          event_id: "evt-1",
          impact: {
            scope_type: "whole_school",
            audience_categories: ["teacher", "parent"],
            affected_count: 120,
            role_breakdown: { teacher: 20, parent: 100 },
            grade_breakdown: { "Grade 7": 3 },
            class_breakdown: { "class-1": 1 },
            department_breakdown: { Academics: 0 },
            tenant_safe_references: { class_ids: ["class-1"], selected_user_ids: [] },
            unresolved_targeting_issues: ["No recipients matched the selected scope."],
            privacy_notes: ["Confidential staffing information cannot target parents or students."],
            recommended_channels: ["in_app", "email"],
          },
        }}
      />,
    );

    expect(screen.getByText(/total affected: 120/i)).toBeInTheDocument();
    expect(screen.getByText(/privacy notes:/i)).toHaveTextContent(/confidential staffing/i);
    expect(screen.getByText(/unresolved targeting issues:/i)).toHaveTextContent(/No recipients matched/i);
  });
});
