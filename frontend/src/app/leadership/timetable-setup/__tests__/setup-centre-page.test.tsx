import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TimetableSetupCentrePage from "@/app/leadership/timetable-setup/page";

const replaceMock = vi.fn();
const refreshMock = vi.fn();
const confirmMock = vi.fn();
const useAuthMock = vi.fn();
const summaryMock = vi.fn();
const stepsMock = vi.fn();
const issuesMock = vi.fn();
const approvalsMock = vi.fn();
const activityMock = vi.fn();
const recommendationsMock = vi.fn();
const revalidateMock = vi.fn();
const stepDetailMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: refreshMock }),
  usePathname: () => "/leadership/timetable-setup",
  useSearchParams: () => new URLSearchParams("tab=overview"),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/lib/timetable-setup-centre-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/timetable-setup-centre-api")>("@/lib/timetable-setup-centre-api");
  return {
    ...actual,
    getSetupCentreSummary: () => summaryMock(),
    getSetupCentreSteps: () => stepsMock(),
    getSetupCentreIssues: () => issuesMock(),
    getSetupCentreApprovals: () => approvalsMock(),
    getSetupCentreActivity: () => activityMock(),
    getSetupCentreRecommendations: () => recommendationsMock(),
    getSetupCentreStep: () => stepDetailMock(),
    revalidateSetupCentre: () => revalidateMock(),
  };
});

describe("TimetableSetupCentrePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("confirm", confirmMock);
    confirmMock.mockReturnValue(true);
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "principal", is_active: true } });

    summaryMock.mockResolvedValue({
      generated_at: "2026-08-06T10:30:00Z",
      progress: { completed_steps: 7, total_steps: 10, completed_weight: 72, total_weight: 100, excluded_weight: 8, progress_percentage: 72, explanation: "7 steps complete; one step not applicable." },
      generation: { generation_allowed: false, readiness_status: "blocked", blocker_count: 2, warning_count: 1, information_count: 1, pending_approval_count: 3, required_actions: [{ issue_key: "readiness:calendar", title: "Calendar setup incomplete", recommended_action: "Review calendar", setup_route: "/leadership/calendar", requires_human_authorization: true, authorized_roles: ["principal"] }] },
      provenance: { source_breakdown: { manual: 3, excel_import: 2, pdf_extraction: 1 }, review_breakdown: { approved: 4, pending_review: 2, rejected: 1 }, lifecycle_counts: { approved: 4, pending_review: 2, inactive: 1 }, manual_count: 3, excel_import_count: 2, pdf_extraction_count: 1, agent_recommendation_count: 0, system_generated_count: 1, inactive_count: 1 },
      source_breakdown: { manual: 3, excel_import: 2, pdf_extraction: 1 },
      review_breakdown: { approved: 4, pending_review: 2, rejected: 1 },
      import_summaries: {
        workbook: { direct_route: "/leadership/timetable-setup/imports/workbooks", latest_import: { original_filename: "workbook.xlsx", status: "validated" }, status_counts: { validated: 1, committed: 0 }, pending_count: 1, unresolved_mapping_count: 1, blocker_count: 0, review_count: 2, committed_count: 0, failed_count: 0, latest_status: "validated" },
        pdf: { direct_route: "/leadership/timetable-setup/calendar/pdf-intake/imports", latest_import: { original_filename: "calendar.pdf", extraction_status: "review_ready" }, status_counts: { review_ready: 1 }, pending_count: 1, unresolved_mapping_count: 0, blocker_count: 0, review_count: 1, committed_count: 0, failed_count: 0, pdf_state_counts: { preflighting: 0, extracting: 0, extraction_failed: 0, ocr_required: 1, review_ready: 1, partially_reviewed: 0, ready_to_commit: 0, committed: 0, cancelled: 0 }, candidate_review_counts: { pending_review: 1, approved: 0, rejected: 0, committed: 0 } },
        total_pending: 2,
        total_failed: 0,
        total_committed: 0,
        latest_imports: { workbook: { original_filename: "workbook.xlsx", status: "validated" }, pdf: { original_filename: "calendar.pdf", extraction_status: "review_ready" } },
      },
      approval_queue: { items: [], pending_total: 0, direct_route: "/leadership/timetable-setup/centre/approvals" },
      policy: { authorized_roles: ["principal", "school_admin"], agent_allowed_actions: ["inspect_setup_state"], agent_prohibited_actions: ["commit_imports"], human_approval_required_for: ["import_commit"] },
      counts: { calendar_approved: 2, imports_total: 3 },
      progress_explanation: "7 steps complete; one step not applicable.",
    });
    stepsMock.mockResolvedValue({
      generated_at: "2026-08-06T10:30:00Z",
      progress: { completed_steps: 7, total_steps: 10, completed_weight: 72, total_weight: 100, excluded_weight: 8, progress_percentage: 72, explanation: "7 steps complete; one step not applicable." },
      steps: [
        { step_key: "operational_calendar", title: "Academic Calendar", status: "complete", weight: 10, applicable: true, approved_count: 2, pending_count: 0, required_minimum: 1, prerequisites: [], route: "/leadership/calendar", policy_rule: "Approved events required.", authorized_roles: ["principal", "school_admin"], source_summary: { manual: 2 }, review_summary: { approved: 2 }, lifecycle_summary: { approved: 2 } },
        { step_key: "approvals_and_readiness", title: "Timetable Readiness", status: "blocked", weight: 10, applicable: true, approved_count: 0, pending_count: 3, required_minimum: 0, prerequisites: ["operational_calendar"], route: "/leadership/timetable-setup/readiness", policy_rule: "Generation can proceed only when blockers are clear.", authorized_roles: ["principal", "school_admin"], source_summary: {}, review_summary: {}, lifecycle_summary: {} },
      ],
      progress_explanation: "7 steps complete; one step not applicable.",
    });
    issuesMock.mockResolvedValue({ generated_at: "2026-08-06T10:30:00Z", total: 1, page: 1, page_size: 12, items: [{ issue_key: "readiness:blocker", source: "readiness_check", step_key: "approvals_and_readiness", severity: "blocker", status: "blocking", title: "Missing approval", summary: "Need review.", policy_rule: "Policy", explanation: "Need review.", affected_count: 1, recommended_action: "Review calendar", setup_route: "/leadership/calendar", authorized_roles: ["principal"], requires_human_authorization: true, resolved: false, created_at: "2026-08-06T10:00:00Z", blocker_relationship: "blocks generation", tenant_safe_references: {} }], direct_route: "/leadership/timetable-setup/centre/issues" });
    approvalsMock.mockResolvedValue({ generated_at: "2026-08-06T10:30:00Z", pending_total: 3, total: 1, page: 1, page_size: 12, items: [{ type: "calendar_candidate_pending_review", title: "Candidate", summary: "Needs review", urgency: "high", setup_step: "operational_calendar", source: "calendar_candidate", created_at: "2026-08-06T10:00:00Z", required_approver_roles: ["principal"], recommended_action: "Review", route: "/leadership/calendar", blocker_relationship: "blocks commit", requires_human_authorization: true }], direct_route: "/leadership/timetable-setup/centre/approvals" });
    activityMock.mockResolvedValue({ items: [{ id: "act-1", action: "timetable_setup.calendar.created", entity_type: "OperationalCalendarEvent", entity_id: null, actor_id: null, created_at: "2026-08-06T09:00:00Z", detail_summary: { source_type: "manual", note: "Created" } }], total: 1, page: 1, page_size: 12, direct_route: "/leadership/timetable-setup/centre/activity" });
    recommendationsMock.mockResolvedValue({ generated_at: "2026-08-06T10:30:00Z", generation: { generation_allowed: false, readiness_status: "blocked", blocker_count: 2, warning_count: 1, information_count: 1, pending_approval_count: 3, required_actions: [] }, recommendations: [{ recommendation_key: "recommend:one", priority_score: 100, title: "Fix blockers", why: "Deterministic evidence", recommended_action: "Open blocker route", setup_route: "/leadership/calendar", authorized_roles: ["principal"], requires_human_authorization: true, agent_can_execute: false }], policy: { authorized_roles: ["principal", "school_admin"], agent_allowed_actions: ["inspect_setup_state"], agent_prohibited_actions: ["commit_imports"], human_approval_required_for: ["import_commit"] } });
    revalidateMock.mockResolvedValue({ revalidated: true, generated_at: "2026-08-06T10:31:00Z", generation: { generation_allowed: false, readiness_status: "blocked", blocker_count: 2, warning_count: 1, information_count: 1, pending_approval_count: 3, required_actions: [] }, progress: { completed_steps: 7, total_steps: 10, completed_weight: 72, total_weight: 100, excluded_weight: 8, progress_percentage: 72, explanation: "7 steps complete; one step not applicable." } });
    stepDetailMock.mockResolvedValue({ step: { step_key: "operational_calendar", title: "Academic Calendar", status: "complete", weight: 10, applicable: true, approved_count: 2, pending_count: 0, required_minimum: 1, prerequisites: [], route: "/leadership/calendar", policy_rule: "Approved events required.", authorized_roles: ["principal", "school_admin"], source_summary: { manual: 2 }, review_summary: { approved: 2 }, lifecycle_summary: { approved: 2 } }, related_issues: [] });
  });

  it("renders summary, steps, issues, approvals, imports, activity, and revalidation behavior", async () => {
    render(<TimetableSetupCentrePage />);

    expect(await screen.findByRole("heading", { name: "Timetable Setup Centre" })).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText(/generation_allowed: false/i)).toBeInTheDocument();
    expect(screen.getByText(/Timetable generation is currently blocked/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Setup Steps" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Issues" })).toBeInTheDocument();
    expect(screen.getByText("Fix blockers")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Setup Steps" }));
    expect(await screen.findByText("Timetable Readiness")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Academic Calendar" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Issues" }));
    expect(await screen.findByText("Missing approval")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Approvals" }));
    expect(await screen.findByText("Candidate")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Imports" }));
    expect(await screen.findByText("workbook.xlsx")).toBeInTheDocument();
    expect(screen.getByText("calendar.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Activity" }));
    expect(await screen.findByText("timetable_setup.calendar.created")).toBeInTheDocument();

    await waitFor(() => expect(revalidateMock).not.toHaveBeenCalled());
    confirmMock.mockReturnValue(true);
    screen.getByRole("button", { name: /revalidate setup/i }).click();
    await waitFor(() => expect(revalidateMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/canonical records were unchanged/i)).toBeInTheDocument();
  });

  it("blocks unauthorized access for teachers", () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "teacher", is_active: true } });
    render(<TimetableSetupCentrePage />);
    expect(screen.getByRole("alert")).toHaveTextContent(/leadership access is required/i);
  });
});