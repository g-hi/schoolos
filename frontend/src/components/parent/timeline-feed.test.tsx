import { render, screen } from "@testing-library/react";
import TimelineFeed, { isSafeParentActionUrl } from "@/components/parent/timeline-feed";
import { FamilyTimelineEvent } from "@/lib/parent-api";

describe("timeline-feed url safety", () => {
  it("accepts only safe parent paths", () => {
    expect(isSafeParentActionUrl("/parent/student/abc")).toBe(true);
    expect(isSafeParentActionUrl("/teacher/abc")).toBe(false);
    expect(isSafeParentActionUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeParentActionUrl("//evil.example.com")).toBe(false);
    expect(isSafeParentActionUrl("https://evil.example.com")).toBe(false);
  });

  it("renders empty state for empty timeline", () => {
    render(<TimelineFeed events={[]} hasMore={false} loadingMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText(/No family timeline events yet/i)).toBeInTheDocument();
  });

  it("renders load more button when pagination exists", () => {
    const events: FamilyTimelineEvent[] = [
      {
        event_id: "1",
        event_type: "pickup.released",
        event_category: "pickup",
        title: "Pickup released",
        description: null,
        occurred_at: new Date().toISOString(),
        student_id: null,
        source_module: "pickup",
        priority: null,
        action_url: "/parent/student/1",
        visibility: "family",
      },
    ];

    render(<TimelineFeed events={events} hasMore={true} loadingMore={false} onLoadMore={() => {}} />);
    expect(screen.getByRole("button", { name: /Load more/i })).toBeInTheDocument();
  });
});
