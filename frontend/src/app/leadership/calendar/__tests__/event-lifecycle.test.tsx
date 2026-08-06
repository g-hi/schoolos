import { render, screen } from "@testing-library/react";
import EventListPanel from "@/app/leadership/calendar/event-list-panel";
import type { ManualEvent } from "@/lib/timetable-calendar-api";

function makeEvent(overrides: Partial<ManualEvent>): ManualEvent {
  return {
    id: "evt-1",
    event_name: "Calendar Event",
    description: null,
    start_date: "2026-09-01",
    end_date: "2026-09-01",
    event_type: "school_event",
    teaching_day_effect: "no_change",
    source_type: "manual",
    review_status: "pending_review",
    lifecycle_status: "draft",
    version_number: 1,
    change_reason: null,
    impact_scope_json: { scope_type: "public_information" },
    notification_plan_status: "not_planned",
    notification_plan_json: {},
    published_at: null,
    is_active: true,
    ...overrides,
  };
}

describe("event lifecycle action availability", () => {
  it("shows submit for draft and hides publish", () => {
    const item = makeEvent({ lifecycle_status: "draft", review_status: "pending_review" });
    render(<EventListPanel events={[item]} loading={false} onSelect={vi.fn()} onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: "submit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "publish" })).not.toBeInTheDocument();
  });

  it("shows approve for pending review", () => {
    const item = makeEvent({ lifecycle_status: "pending_review", review_status: "pending_review" });
    render(<EventListPanel events={[item]} loading={false} onSelect={vi.fn()} onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: "approve" })).toBeInTheDocument();
  });

  it("shows publish only after approval and keeps reason-required actions available", () => {
    const item = makeEvent({ lifecycle_status: "approved", review_status: "approved" });
    render(<EventListPanel events={[item]} loading={false} onSelect={vi.fn()} onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: "publish" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "reschedule" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "cancel" })).toBeInTheDocument();
  });
});
