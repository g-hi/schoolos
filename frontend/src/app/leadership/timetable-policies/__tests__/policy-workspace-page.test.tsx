import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadershipTimetablePoliciesPage from "@/app/leadership/timetable-policies/page";

const replaceMock = vi.fn();
const useAuthMock = vi.fn();

const listPolicySetsMock = vi.fn();
const listPolicyExceptionsMock = vi.fn();
const listConstraintTypesMock = vi.fn();
const getPolicyDiagnosticsMock = vi.fn();
const getPolicyReadinessMock = vi.fn();
const getEffectivePolicyMock = vi.fn();
const getEffectiveConstraintsMock = vi.fn();
const getSchedulingAuthorizationMock = vi.fn();
const getPolicyResolutionGuidanceMock = vi.fn();
const listPolicyConstraintsMock = vi.fn();
const listPolicySetVersionsMock = vi.fn();
const listPolicyConstraintVersionsMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams("tab=overview"),
  usePathname: () => "/leadership/timetable-policies",
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/lib/timetable-policies-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/timetable-policies-api")>("@/lib/timetable-policies-api");
  return {
    ...actual,
    listPolicySets: () => listPolicySetsMock(),
    listPolicyExceptions: () => listPolicyExceptionsMock(),
    listConstraintTypes: () => listConstraintTypesMock(),
    getPolicyDiagnostics: () => getPolicyDiagnosticsMock(),
    getPolicyReadiness: () => getPolicyReadinessMock(),
    getEffectivePolicy: () => getEffectivePolicyMock(),
    getEffectiveConstraints: () => getEffectiveConstraintsMock(),
    getSchedulingAuthorization: () => getSchedulingAuthorizationMock(),
    getPolicyResolutionGuidance: () => getPolicyResolutionGuidanceMock(),
    listPolicyConstraints: () => listPolicyConstraintsMock(),
    listPolicySetVersions: () => listPolicySetVersionsMock(),
    listPolicyConstraintVersions: () => listPolicyConstraintVersionsMock(),
    submitPolicySet: vi.fn(),
    approvePolicySet: vi.fn(),
    activatePolicySet: vi.fn(),
    suspendPolicySet: vi.fn(),
    retirePolicySet: vi.fn(),
    createPolicySetDraft: vi.fn(),
    patchPolicySet: vi.fn(),
    createPolicyConstraint: vi.fn(),
    submitPolicyConstraint: vi.fn(),
    approvePolicyConstraint: vi.fn(),
    activatePolicyConstraint: vi.fn(),
    suspendPolicyConstraint: vi.fn(),
    retirePolicyConstraint: vi.fn(),
    createPolicyException: vi.fn(),
    submitPolicyException: vi.fn(),
    approvePolicyException: vi.fn(),
    rejectPolicyException: vi.fn(),
    revokePolicyException: vi.fn(),
  };
});

describe("leadership timetable policies page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "principal", is_active: true } });

    listPolicySetsMock.mockResolvedValue([
      {
        id: "set-1",
        tenant_id: "tenant-1",
        academic_year_id: "year-1",
        term_id: "term-1",
        campus_id: null,
        name: "Main Policy",
        description: "Primary scope",
        lifecycle_status: "active",
        version_number: 3,
        is_active: true,
        effective_start_date: null,
        effective_end_date: null,
        source_type: "manual",
        created_by_user_id: null,
        approved_by_user_id: null,
        approved_at: null,
        created_at: "2026-08-01T10:00:00Z",
        updated_at: "2026-08-01T10:00:00Z",
      },
    ]);
    listPolicyExceptionsMock.mockResolvedValue([]);
    listConstraintTypesMock.mockResolvedValue([]);
    listPolicyConstraintsMock.mockResolvedValue([]);
    listPolicySetVersionsMock.mockResolvedValue([]);
    listPolicyConstraintVersionsMock.mockResolvedValue([]);
    getPolicyDiagnosticsMock.mockResolvedValue({
      generated_at: "2026-08-07T10:00:00Z",
      summary: { blocker_count: 0, warning_count: 1, information_count: 2, impossible_count: 0 },
      generation: { generation_allowed: true },
      policy_counts: {},
      conflicts: [],
      feasibility: [],
      impact: [],
      resolution_guidance: [],
    });
    getPolicyReadinessMock.mockResolvedValue({
      generated_at: "2026-08-07T10:00:00Z",
      calculation_id: "calc-1",
      readiness_status: "ready",
      generation_allowed: true,
      policy_set_id: "set-1",
      policy_set_status: "active",
      policy_set_version: 3,
      policy_explanation: {},
      source_and_provenance_summary: {},
      policy_blocker_count: 0,
      policy_warning_count: 0,
      policy_pending_approval_count: 0,
      policy_readiness_status: "ready",
      overall_policy_score: 100,
      calculation_breakdown: { approval_queue: [] },
    });
    getEffectivePolicyMock.mockResolvedValue({
      generated_at: "2026-08-07T10:00:00Z",
      calculation_id: "calc-1",
      readiness_status: "ready",
      generation_allowed: true,
      policy_set_id: "set-1",
      policy_set_status: "active",
      policy_set_version: 3,
      policy_explanation: {},
      source_and_provenance_summary: {},
      policy_blocker_count: 0,
      policy_warning_count: 0,
      policy_pending_approval_count: 0,
      policy_readiness_status: "ready",
      overall_policy_score: 100,
      calculation_breakdown: { approval_queue: [] },
    });
    getEffectiveConstraintsMock.mockResolvedValue({
      generated_at: "2026-08-07T10:00:00Z",
      policy_set_id: "set-1",
      policy_set_status: "active",
      effective_constraint_count: 0,
      coverage: { coverage_percentage: 100 },
      effective_constraints: [],
      exception_readiness: { ready: true },
      policy_score: { applicable_weight: 1, completed_weight: 1, excluded_not_applicable_weight: 0 },
    });
    getSchedulingAuthorizationMock.mockResolvedValue({
      generated_at: "2026-08-07T10:00:00Z",
      calculation_id: "calc-1",
      readiness_status: "ready",
      generation_allowed: true,
      policy_readiness_status: "ready",
      policy_blocker_count: 0,
      policy_warning_count: 0,
      policy_pending_approval_count: 0,
      overall_policy_score: 100,
      required_actions: [],
      readiness_blockers: [],
      readiness_warnings: [],
    });
    getPolicyResolutionGuidanceMock.mockResolvedValue({
      generated_at: "2026-08-07T10:00:00Z",
      summary: {},
      resolution_guidance: [],
      generation: { generation_allowed: true },
    });
  });

  it("renders workspace tabs and overview for principal", async () => {
    render(<LeadershipTimetablePoliciesPage />);

    expect(await screen.findByRole("heading", { name: "Timetable Policies" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Policy Sets" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Readiness" })).toBeInTheDocument();
    expect(screen.getByText(/Score does not override blockers/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Diagnostics" }));
    await waitFor(() => expect(replaceMock).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Run Policy Diagnostics" })).toBeInTheDocument();
  });

  it("blocks unauthorized direct access for teacher", async () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "teacher", is_active: true } });
    render(<LeadershipTimetablePoliciesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/leadership access is required/i);
  });

  it("blocks unauthorized direct access for parent", async () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "parent", is_active: true } });
    render(<LeadershipTimetablePoliciesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/leadership access is required/i);
  });
});
