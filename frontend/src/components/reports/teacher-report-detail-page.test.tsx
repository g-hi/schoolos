import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import TeacherReportDetailPage from "@/components/reports/teacher-report-detail-page";
import {
  editWeeklyReportDraft,
  generateWeeklyReportDraft,
  getWeeklyReport,
  getWeeklyReportReviewEvents,
  getWeeklyReportVersions,
  submitWeeklyReportForReview,
  StaffApiError,
} from "@/lib/weekly-reports-api";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

vi.mock("@/lib/weekly-reports-api", () => ({
  getWeeklyReport: vi.fn(),
  getWeeklyReportVersions: vi.fn(),
  getWeeklyReportReviewEvents: vi.fn(),
  editWeeklyReportDraft: vi.fn(),
  generateWeeklyReportDraft: vi.fn(),
  submitWeeklyReportForReview: vi.fn(),
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

function mockLoad(overrides?: Partial<Awaited<ReturnType<typeof getWeeklyReport>>>) {
  (getWeeklyReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    report_id: "report-1",
    student_id: "student-1",
    student_display_name: "Ahmed Hassan",
    class_name: "Grade 5-A",
    week_start: "2026-07-13",
    week_end: "2026-07-19",
    timezone_used: "UTC",
    status: "draft",
    row_version: 4,
    current_version_number: 2,
    approved_version_number: null,
    published_version_number: null,
    current_content: {
      title: "Weekly Report",
      sections: [
        { section_type: "teacher_comment", content: "Current text", used_evidence_ids: ["staff_input_1"] },
        { section_type: "data_availability_note", content: "No attendance data", used_evidence_ids: ["attendance_1"] },
      ],
      warnings: [],
    },
    current_evidence_snapshot: {
      evidence_items: [
        { evidence_id: "attendance_1", source_type: "attendance", available: false, unavailable_reason: "No attendance data" },
      ],
    },
    current_validation_status: "passed",
    current_validation_errors: [],
    versions: [],
    ...overrides,
  });
  (getWeeklyReportVersions as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
    { version_id: "v1", version_number: 1, source_type: "manual", validation_status: "passed", created_by_user_id: "u1", created_at: "2026-07-18T00:00:00Z" },
    { version_id: "v2", version_number: 2, source_type: "ai_generated", validation_status: "passed", created_by_user_id: "u1", created_at: "2026-07-18T00:10:00Z" },
  ]);
  (getWeeklyReportReviewEvents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
    { event_id: "e1", report_id: "report-1", report_version_id: "v1", actor_user_id: "u1", event_type: "report_initialized", previous_status: null, new_status: "draft", comment: null, created_at: "2026-07-18T00:00:00Z" },
  ]);
}

describe("teacher-report-detail-page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLoad();
    (editWeeklyReportDraft as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ report_id: "report-1", status: "draft", row_version: 5, current_version_number: 3 });
    (generateWeeklyReportDraft as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ report_id: "report-1", status: "pending_review", row_version: 5, current_version_number: 3 });
    (submitWeeklyReportForReview as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ report_id: "report-1", status: "pending_review", row_version: 5, current_version_number: 3 });
  });

  it("requests AI draft generation", async () => {
    render(<TeacherReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Generate AI-assisted draft/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Generate AI-assisted draft/i }));

    await waitFor(() => {
      expect(generateWeeklyReportDraft).toHaveBeenCalledWith("report-1", { expected_row_version: 4, use_ai: true });
    });
  });

  it("supports manual workflow without AI", async () => {
    render(<TeacherReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Refresh deterministic draft/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Refresh deterministic draft/i }));

    await waitFor(() => {
      expect(generateWeeklyReportDraft).toHaveBeenCalledWith("report-1", { expected_row_version: 4, use_ai: false });
    });
  });

  it("edits structured sections and submits for review", async () => {
    render(<TeacherReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByLabelText("Title")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Updated report" } });
    fireEvent.change(screen.getByLabelText(/teacher comment/i), { target: { value: "Updated plain text" } });
    fireEvent.click(screen.getByRole("button", { name: /Save draft/i }));

    await waitFor(() => {
      expect(editWeeklyReportDraft).toHaveBeenCalled();
    });

    fireEvent.change(screen.getByLabelText("Review note"), { target: { value: "Ready for review" } });
    fireEvent.click(screen.getByRole("button", { name: /Submit for review/i }));

    await waitFor(() => {
      expect(submitWeeklyReportForReview).toHaveBeenCalledWith("report-1", {
        expected_row_version: 4,
        comment: "Ready for review",
      });
    });
  });

  it("prevents duplicate submission while an action is active", async () => {
    let resolveRequest: (value: unknown) => void = () => {};
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    (generateWeeklyReportDraft as unknown as ReturnType<typeof vi.fn>).mockReturnValue(pending);

    render(<TeacherReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Generate AI-assisted draft/i })).toBeInTheDocument();
    });

    const button = screen.getByRole("button", { name: /Generate AI-assisted draft/i });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(generateWeeklyReportDraft).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRequest({ report_id: "report-1", status: "pending_review", row_version: 5, current_version_number: 3 });
    });
  });

  it("renders stale version conflicts and validation warnings", async () => {
    mockLoad({ current_validation_errors: [{ code: "unknown_evidence_id", message: "Unknown evidence id" }] });
    (editWeeklyReportDraft as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new StaffApiError(409, "The report was updated by another user.", null),
    );

    render(<TeacherReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByText("Unknown evidence id")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Save draft/i }));

    await waitFor(() => {
      expect(screen.getByText(/updated by another user/i)).toBeInTheDocument();
    });
  });

  it("renders version history and hides approval or publish actions", async () => {
    render(<TeacherReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByText(/Version 1/i)).toBeInTheDocument();
      expect(screen.getByText(/Version 2/i)).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /^Approve$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Publish$/i })).not.toBeInTheDocument();
  });
});
