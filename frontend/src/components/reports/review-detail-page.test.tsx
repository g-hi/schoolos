import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReviewDetailPage from "@/components/reports/review-detail-page";
import {
  approveWeeklyReport,
  getWeeklyReport,
  getWeeklyReportReviewEvents,
  publishWeeklyReport,
  requestWeeklyReportChanges,
  StaffApiError,
} from "@/lib/weekly-reports-api";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

vi.mock("@/lib/weekly-reports-api", () => ({
  getWeeklyReport: vi.fn(),
  getWeeklyReportReviewEvents: vi.fn(),
  requestWeeklyReportChanges: vi.fn(),
  approveWeeklyReport: vi.fn(),
  publishWeeklyReport: vi.fn(),
  StaffApiError: class StaffApiError extends Error {
    status: number;
    body: unknown;

    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
}));

describe("review-detail-page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (getWeeklyReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      report_id: "report-1",
      student_id: "student-1",
      student_display_name: "Ahmed Hassan",
      class_name: "Grade 5-A",
      week_start: "2026-07-13",
      week_end: "2026-07-19",
      timezone_used: "UTC",
      status: "pending_review",
      row_version: 6,
      current_version_number: 2,
      approved_version_number: null,
      published_version_number: null,
      current_content: {
        title: "Weekly Report",
        sections: [{ section_type: "teacher_comment", content: "Plain text comment" }],
      },
      current_evidence_snapshot: {
        evidence_items: [{ evidence_id: "attendance_1", source_type: "attendance", available: false, unavailable_reason: "No attendance data" }],
      },
      current_validation_status: "passed",
      current_validation_errors: [],
      versions: [],
    });
    (getWeeklyReportReviewEvents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { event_id: "e1", report_id: "report-1", report_version_id: null, actor_user_id: "u1", event_type: "submitted_for_review", previous_status: "draft", new_status: "pending_review", comment: null, created_at: "2026-07-18T00:00:00Z" },
    ]);
    (requestWeeklyReportChanges as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (approveWeeklyReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (publishWeeklyReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests changes with a comment", async () => {
    render(<ReviewDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByLabelText("Review comment")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Review comment"), { target: { value: "Please revise section two." } });
    fireEvent.click(screen.getByRole("button", { name: /Request changes/i }));

    await waitFor(() => {
      expect(requestWeeklyReportChanges).toHaveBeenCalledWith("report-1", {
        expected_row_version: 6,
        comment: "Please revise section two.",
      });
    });
  });

  it("approves the report", async () => {
    render(<ReviewDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Approve$/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Approve$/i }));

    await waitFor(() => {
      expect(approveWeeklyReport).toHaveBeenCalledWith("report-1", {
        expected_row_version: 6,
        comment: "",
      });
    });
  });

  it("confirms before publication and publishes once confirmed", async () => {
    render(<ReviewDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Publish$/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Publish$/i }));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(publishWeeklyReport).toHaveBeenCalledWith("report-1", {
        expected_row_version: 6,
        comment: "",
      });
    });
  });

  it("renders a safe permission-denied state", async () => {
    (getWeeklyReport as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new StaffApiError(403, "denied", null));

    render(<ReviewDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByText(/cannot be reviewed by the current account/i)).toBeInTheDocument();
    });
  });
});
