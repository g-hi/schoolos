import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ParentReportDetailPage from "@/components/parent/parent-report-detail-page";
import ParentReportsPage from "@/components/parent/parent-reports-page";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import {
  getParentPublishedReport,
  getParentPublishedReportList,
  getParentStudents,
  ParentApiError,
} from "@/lib/parent-api";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

vi.mock("@/components/parent/parent-auth-provider", () => ({
  useParentAuth: vi.fn(),
}));

vi.mock("@/components/parent/parent-login-panel", () => ({
  default: () => <div>Login required</div>,
}));

vi.mock("@/lib/parent-api", () => ({
  getParentStudents: vi.fn(),
  getParentPublishedReportList: vi.fn(),
  getParentPublishedReport: vi.fn(),
  ParentApiError: class ParentApiError extends Error {
    status: number;
    body: unknown;

    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
}));

describe("parent weekly report pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useParentAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      token: "parent-token",
      login: vi.fn(),
      logout: vi.fn(),
      status: "authenticated",
    });
    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      students: [
        {
          student_id: "student-1",
          name: "Ahmed Hassan",
          student_code: "S001",
          grade: "5",
          section: "A",
          class_name: "Grade 5-A",
          homeroom_teacher: "Ms. Ali",
          is_primary_guardian: true,
          can_pickup: true,
          can_view_academics: true,
          can_view_behaviour: true,
        },
      ],
    });
    (getParentPublishedReportList as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        report_id: "report-1",
        student_id: "student-1",
        student_display_name: "Ahmed Hassan",
        class_name: "Grade 5-A",
        week_start: "2026-07-13",
        week_end: "2026-07-19",
        title: "Weekly Report",
        published_at: "2026-07-18T00:00:00Z",
      },
    ]);
    (getParentPublishedReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      report_id: "report-1",
      student_id: "student-1",
      student_display_name: "Ahmed Hassan",
      class_name: "Grade 5-A",
      week_start: "2026-07-13",
      week_end: "2026-07-19",
      title: "Weekly Report",
      sections: [
        { section_type: "teacher_comment", content: "<script>alert('x')</script> rendered safely" },
        { section_type: "data_availability_note", content: "Attendance data was unavailable this week." },
      ],
      published_at: "2026-07-18T00:00:00Z",
    });
  });

  it("shows only published reports and supports child filtering", async () => {
    render(<ParentReportsPage />);

    await waitFor(() => {
      expect(screen.getByText("Weekly Report")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Child"), { target: { value: "student-1" } });

    await waitFor(() => {
      expect(getParentPublishedReportList).toHaveBeenLastCalledWith("parent-token", { studentId: "student-1" });
    });
  });

  it("renders the parent report detail as plain text without raw html execution", async () => {
    const { container } = render(<ParentReportDetailPage reportId="report-1" />);

    await waitFor(() => {
      expect(screen.getByText("<script>alert('x')</script> rendered safely")).toBeInTheDocument();
    });

    expect(container.querySelector("script")).toBeNull();
  });

  it("renders a 403 permission state", async () => {
    (getParentPublishedReportList as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new ParentApiError(403, "denied", null));

    render(<ParentReportsPage />);

    await waitFor(() => {
      expect(screen.getByText(/cannot access weekly student reports/i)).toBeInTheDocument();
    });
  });
});
