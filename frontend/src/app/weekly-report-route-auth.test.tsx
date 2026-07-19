import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import ReportsReviewRoute from "@/app/reports/review/page";
import ReportReviewDetailRoute from "@/app/reports/[reportId]/review/page";
import TeacherReportsRoute from "@/app/teacher/reports/page";
import TeacherReportDetailRoute from "@/app/teacher/reports/[reportId]/page";

const guardCalls: Array<string> = [];

vi.mock("@/components/auth/role-guard", () => ({
  default: ({ allowedRoles, children }: { allowedRoles: string[]; children: ReactNode }) => {
    guardCalls.push(allowedRoles.join(","));
    return <div data-testid={`guard-${allowedRoles.join("-")}`}>{children}</div>;
  },
}));

vi.mock("@/components/reports/teacher-reports-page", () => ({
  default: () => <div>Teacher list page</div>,
}));

vi.mock("@/components/reports/teacher-report-detail-page", () => ({
  default: ({ reportId }: { reportId: string }) => <div>Teacher detail {reportId}</div>,
}));

vi.mock("@/components/reports/review-queue-page", () => ({
  default: () => <div>Review queue page</div>,
}));

vi.mock("@/components/reports/review-detail-page", () => ({
  default: ({ reportId }: { reportId: string }) => <div>Review detail {reportId}</div>,
}));

describe("weekly report route auth guards", () => {
  beforeEach(() => {
    guardCalls.length = 0;
  });

  it("wraps teacher list route with teacher mode", () => {
    render(<TeacherReportsRoute />);
    expect(screen.getByTestId("guard-teacher")).toBeInTheDocument();
    expect(screen.getByText("Teacher list page")).toBeInTheDocument();
    expect(guardCalls).toContain("teacher");
  });

  it("wraps teacher detail route with teacher mode", async () => {
    const node = await TeacherReportDetailRoute({ params: Promise.resolve({ reportId: "report-1" }) });
    render(node);
    expect(screen.getByTestId("guard-teacher")).toBeInTheDocument();
    expect(screen.getByText("Teacher detail report-1")).toBeInTheDocument();
    expect(guardCalls).toContain("teacher");
  });

  it("wraps review queue route with leadership mode", () => {
    render(<ReportsReviewRoute />);
    expect(screen.getByTestId("guard-principal-school_admin")).toBeInTheDocument();
    expect(screen.getByText("Review queue page")).toBeInTheDocument();
    expect(guardCalls).toContain("principal,school_admin");
  });

  it("wraps review detail route with leadership mode", async () => {
    const node = await ReportReviewDetailRoute({ params: Promise.resolve({ reportId: "report-9" }) });
    render(node);
    expect(screen.getByTestId("guard-principal-school_admin")).toBeInTheDocument();
    expect(screen.getByText("Review detail report-9")).toBeInTheDocument();
    expect(guardCalls).toContain("principal,school_admin");
  });
});
