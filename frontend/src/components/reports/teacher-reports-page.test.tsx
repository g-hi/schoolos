import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TeacherReportsPage from "@/components/reports/teacher-reports-page";
import {
  initializeWeeklyReport,
  listWeeklyReportStudents,
  listWeeklyReports,
  StaffApiError,
} from "@/lib/weekly-reports-api";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

vi.mock("@/lib/weekly-reports-api", () => ({
  listWeeklyReportStudents: vi.fn(),
  listWeeklyReports: vi.fn(),
  initializeWeeklyReport: vi.fn(),
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

describe("teacher-reports-page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pushMock.mockReset();
    (listWeeklyReportStudents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { student_id: "student-1", student_display_name: "Ahmed Hassan", class_name: "Grade 5-A" },
    ]);
    (listWeeklyReports as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        report_id: "report-1",
        student_id: "student-1",
        student_display_name: "Ahmed Hassan",
        class_name: "Grade 5-A",
        week_start: "2026-07-13",
        week_end: "2026-07-19",
        status: "draft",
        current_version_number: 1,
        approved_version_number: null,
        published_version_number: null,
        row_version: 1,
        updated_at: "2026-07-18T00:00:00Z",
      },
    ]);
    (initializeWeeklyReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      report_id: "report-1",
      status: "draft",
      row_version: 1,
      current_version_number: 1,
    });
  });

  it("loads the teacher report list", async () => {
    render(<TeacherReportsPage />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Ahmed Hassan" })).toBeInTheDocument();
    });

    expect(listWeeklyReportStudents).toHaveBeenCalled();
    expect(listWeeklyReports).toHaveBeenCalled();
  });

  it("initializes a report and navigates to detail", async () => {
    render(<TeacherReportsPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Student")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Student"), { target: { value: "student-1" } });
    fireEvent.change(screen.getByLabelText("Reporting week"), { target: { value: "2026-07-13" } });
    fireEvent.change(screen.getByLabelText("Weekly teacher summary"), { target: { value: "Solid week." } });
    fireEvent.click(screen.getByRole("button", { name: /Initialize report/i }));

    await waitFor(() => {
      expect(initializeWeeklyReport).toHaveBeenCalledWith(expect.objectContaining({
        student_id: "student-1",
        week_start: "2026-07-13",
      }));
    });
    expect(pushMock).toHaveBeenCalledWith("/teacher/reports/report-1");
  });

  it("renders a 403 permission state", async () => {
    (listWeeklyReportStudents as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new StaffApiError(403, "denied", null),
    );
    (listWeeklyReports as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new StaffApiError(403, "denied", null),
    );

    render(<TeacherReportsPage />);

    await waitFor(() => {
      expect(screen.getByText(/cannot access the weekly reports workspace/i)).toBeInTheDocument();
    });
  });
});
