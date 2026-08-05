import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import OnboardingPage from "@/app/onboarding/page";
import Sidebar from "@/components/sidebar";
import { useAuth } from "@/components/auth/auth-provider";
import {
  acknowledgeOnboardingStep,
  cancelOnboarding,
  completeOnboarding,
  getOnboardingReadiness,
  getOnboardingStatus,
  listOnboardingHistory,
  pauseOnboarding,
  resumeOnboarding,
  skipOnboardingStep,
  startOnboarding,
  updateCurrentStep,
} from "@/lib/onboarding-api";

const mockedUseAuth = vi.fn();
const mockedUsePathname = vi.fn(() => "/onboarding");
const logoutMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => mockedUsePathname(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/lib/announcements-api", () => ({
  getParentUnreadNotificationCount: vi.fn(),
}));

vi.mock("@/lib/onboarding-api", () => ({
  getOnboardingStatus: vi.fn(),
  getOnboardingReadiness: vi.fn(),
  listOnboardingHistory: vi.fn(),
  startOnboarding: vi.fn(),
  updateCurrentStep: vi.fn(),
  acknowledgeOnboardingStep: vi.fn(),
  skipOnboardingStep: vi.fn(),
  pauseOnboarding: vi.fn(),
  resumeOnboarding: vi.fn(),
  completeOnboarding: vi.fn(),
  cancelOnboarding: vi.fn(),
  OnboardingApiError: class OnboardingApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
}));

const scenario = {
  started: false,
  blockers: 2,
  warnings: 1,
  completed: false,
};

const STEP_KEYS = [
  "campus",
  "academic_year",
  "terms",
  "grade_levels",
  "subjects",
  "classes",
  "subject_offerings",
  "people",
  "family_relationships",
  "teacher_assignments",
  "student_enrolments",
  "timetable",
  "data_imports",
  "readiness_review",
];

function makeStatus() {
  if (!scenario.started) {
    return {
      run: null,
      run_status: "not_started",
      current_step: null,
      started_at: null,
      completed_at: null,
      readiness_percentage: 0,
      completed_step_count: 0,
      blocked_step_count: scenario.blockers,
      warning_count: scenario.warnings,
      next_recommended_step: "campus",
      ordered_steps: [],
      grouped_progress: {},
      available_actions: ["start"],
    };
  }

  const runStatus = scenario.completed ? "completed" : scenario.blockers === 0 ? "ready" : "in_progress";
  return {
    run: {
      id: "run-1",
      status: runStatus,
      current_step_key: scenario.completed ? "readiness_review" : "timetable",
      started_by_user_id: "leader-1",
      completed_by_user_id: scenario.completed ? "leader-1" : null,
      started_at: "2026-08-04T10:00:00Z",
      completed_at: scenario.completed ? "2026-08-04T11:00:00Z" : null,
      paused_at: null,
      created_at: "2026-08-04T10:00:00Z",
      updated_at: "2026-08-04T11:00:00Z",
    },
    run_status: runStatus,
    current_step: scenario.completed ? "readiness_review" : "timetable",
    started_at: "2026-08-04T10:00:00Z",
    completed_at: scenario.completed ? "2026-08-04T11:00:00Z" : null,
    readiness_percentage: scenario.completed ? 100 : scenario.blockers === 0 ? 93 : 40,
    completed_step_count: scenario.completed ? STEP_KEYS.length : scenario.blockers === 0 ? 12 : 4,
    blocked_step_count: scenario.blockers,
    warning_count: scenario.warnings,
    next_recommended_step: scenario.blockers === 0 ? "readiness_review" : "timetable",
    ordered_steps: STEP_KEYS.map((step) => ({
      step_key: step,
      status: step === "data_imports" ? "completed" : step === "timetable" && scenario.blockers > 0 ? "blocked" : scenario.completed ? "completed" : "in_progress",
      completion_source: step === "readiness_review" && scenario.completed ? "manual" : null,
      acknowledged_at: null,
      blocked_reason: null,
    })),
    grouped_progress: {},
    available_actions: scenario.completed ? [] : scenario.blockers === 0 ? ["complete", "cancel", "pause", "set_current_step", "acknowledge_step", "skip_optional_step"] : ["pause", "cancel", "set_current_step", "acknowledge_step", "skip_optional_step"],
  };
}

function makeReadiness() {
  return {
    state: !scenario.started ? "not_started" : scenario.completed ? "completed" : scenario.blockers === 0 ? "ready" : "blocked",
    readiness_percentage: scenario.completed ? 100 : scenario.blockers === 0 ? 93 : 40,
    blocker_count: scenario.blockers,
    warning_count: scenario.warnings,
    informational_count: 1,
    grouped_readiness_checks: {
      Foundation: [],
      "Academic Operations": scenario.blockers > 0 ? [{
        check_key: "ops_timetable_required",
        step_key: "timetable",
        title: "Timetable required",
        status: "blocking",
        current_value: 0,
        required_value: 1,
        message: "Timetable coverage is incomplete.",
        recommended_action: "Open /timetable",
        action_route: "/timetable",
        evidence_source: "timetable_entries",
      }] : [],
      Data: [{
        check_key: "data_recent_failed_or_error_imports",
        step_key: "data_imports",
        title: "Recent failed imports",
        status: "warning",
        current_value: 1,
        required_value: 0,
        message: "Failed import remains warning-level.",
        recommended_action: "Open /data",
        action_route: "/data",
        evidence_source: "import_batches",
      }],
      People: [{
        check_key: "family_inactive_history",
        step_key: "family_relationships",
        title: "Historical family relationships",
        status: "informational",
        current_value: 1,
        required_value: 0,
        message: "Historical relationships are preserved.",
        recommended_action: "Open /people",
        action_route: "/people",
        evidence_source: "student_parents",
      }],
    },
    recommended_next_actions: scenario.blockers > 0 ? [{
      step_key: "timetable",
      check_key: "ops_timetable_required",
      message: "Timetable coverage is incomplete.",
      action_route: "/timetable",
    }] : [{
      step_key: "readiness_review",
      check_key: "data_recent_failed_or_error_imports",
      message: "Warnings remain visible but do not block completion.",
      action_route: "/data",
    }],
    safe_routes: ["/academic-structure", "/people", "/data", "/timetable"],
  };
}

function makeHistory() {
  return {
    items: scenario.completed ? [{
      run_id: "run-1",
      status: "completed",
      started_at: "2026-08-04T10:00:00Z",
      completed_at: "2026-08-04T11:00:00Z",
      paused_at: null,
      started_by_user_id: "leader-1",
      completed_by_user_id: "leader-1",
      completion_percentage: 100,
      blocker_count: 0,
      warning_count: scenario.warnings,
    }] : [],
    total: scenario.completed ? 1 : 0,
    page: 1,
    page_size: 5,
  };
}

describe("school setup flow", () => {
  beforeEach(() => {
    scenario.started = false;
    scenario.blockers = 2;
    scenario.warnings = 1;
    scenario.completed = false;
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "prompt").mockReturnValue("");
    mockedUseAuth.mockReturnValue({ user: { role: "principal", is_active: true }, logout: logoutMock, isAuthenticated: true, isHydrating: false });
    (useAuth as ReturnType<typeof vi.fn>).mockImplementation(() => mockedUseAuth());
    (getOnboardingStatus as ReturnType<typeof vi.fn>).mockImplementation(async () => makeStatus());
    (getOnboardingReadiness as ReturnType<typeof vi.fn>).mockImplementation(async () => makeReadiness());
    (listOnboardingHistory as ReturnType<typeof vi.fn>).mockImplementation(async () => makeHistory());
    (startOnboarding as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      scenario.started = true;
      return makeStatus();
    });
    (updateCurrentStep as ReturnType<typeof vi.fn>).mockImplementation(async () => makeStatus());
    (acknowledgeOnboardingStep as ReturnType<typeof vi.fn>).mockImplementation(async () => makeStatus());
    (skipOnboardingStep as ReturnType<typeof vi.fn>).mockImplementation(async () => makeStatus());
    (pauseOnboarding as ReturnType<typeof vi.fn>).mockImplementation(async () => makeStatus());
    (resumeOnboarding as ReturnType<typeof vi.fn>).mockImplementation(async () => makeStatus());
    (completeOnboarding as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      scenario.completed = true;
      return makeStatus();
    });
    (cancelOnboarding as ReturnType<typeof vi.fn>).mockImplementation(async () => ({ run_id: "run-1", status: "cancelled", completed_at: null }));
  });

  it("covers the leadership onboarding workflow across setup pages", async () => {
    const { rerender } = render(<OnboardingPage />);

    expect(await screen.findByRole("button", { name: "Start Onboarding" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start Onboarding" }));
    await waitFor(() => expect(startOnboarding).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole("tab", { name: "Readiness Review" }));
    expect(await screen.findByText("Timetable coverage is incomplete.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open /timetable" })).toHaveAttribute("href", "/timetable");
    expect(screen.getByRole("link", { name: "Open /data" })).toHaveAttribute("href", "/data");
    expect(screen.getByRole("link", { name: "Open /people" })).toHaveAttribute("href", "/people");

    scenario.blockers = 0;
    rerender(<OnboardingPage key="phase2" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Readiness Review" }));
    expect(await screen.findByText("Warnings")).toBeInTheDocument();
    expect(screen.getByText("Failed import remains warning-level.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(await screen.findByRole("button", { name: "Complete" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(completeOnboarding).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole("tab", { name: "History" }));
    expect(await screen.findByText(/Run run-1/i)).toBeInTheDocument();
    expect(screen.getAllByText(/completed/i).length).toBeGreaterThan(0);
  });

  it("shows each leadership navigation entry once in the sidebar", async () => {
    mockedUsePathname.mockReturnValue("/onboarding");
    render(<Sidebar />);
    expect(screen.getByText("School Setup").closest("a")).toHaveAttribute("href", "/onboarding");
    expect(screen.getByText("Academic Structure").closest("a")).toHaveAttribute("href", "/academic-structure");
    expect(screen.getByText("People & Families").closest("a")).toHaveAttribute("href", "/people");
    expect(screen.getByText("Data Imports").closest("a")).toHaveAttribute("href", "/data");
    expect(screen.getByText("Timetable").closest("a")).toHaveAttribute("href", "/timetable");
    expect(screen.getAllByText("School Setup")).toHaveLength(1);
  });
});