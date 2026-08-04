import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";

// ─── Mock dependencies ─────────────────────────────────────────────────────────

vi.mock("@/lib/auth", () => ({
  readAccessToken: vi.fn(() => "test-token"),
  isLeadershipRole: vi.fn((role: string) => role === "principal" || role === "school_admin"),
}));

const mockedUseAuth = vi.fn(() => ({
  user: { role: "principal", id: "u1", email: "principal@school.test" },
  isHydrating: false,
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => mockedUseAuth(),
}));

const mockedUsePathname = vi.fn(() => "/");
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockedUsePathname(),
  useRouter: () => ({
    push: vi.fn(),
    replace: replaceMock,
    refresh: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
  }),
}));

const mockGetMasterDataSetupSummary = vi.fn();
const mockGetAcademicStructureSummary = vi.fn();
const mockGetTeacherAssignmentSummary = vi.fn();
const mockGetEnrolmentSummary = vi.fn();
const mockListCampuses = vi.fn();
const mockListAcademicYears = vi.fn();
const mockListGradeLevels = vi.fn();
const mockListTerms = vi.fn();
const mockCreateTerm = vi.fn();
const mockUpdateTerm = vi.fn();
const mockListClasses = vi.fn();
const mockListSubjectOfferings = vi.fn();
const mockListTeacherAssignments = vi.fn();
const mockListEnrolments = vi.fn();
const mockGetReconciliationDiagnostics = vi.fn();
const mockCreateCampus = vi.fn();
const mockUpdateCampus = vi.fn();

vi.mock("@/lib/master-data-api", () => ({
  getMasterDataSetupSummary: (...args: unknown[]) => mockGetMasterDataSetupSummary(...args),
  listCampuses: (...args: unknown[]) => mockListCampuses(...args),
  listAcademicYears: (...args: unknown[]) => mockListAcademicYears(...args),
  listGradeLevels: (...args: unknown[]) => mockListGradeLevels(...args),
  listTerms: (...args: unknown[]) => mockListTerms(...args),
  createCampus: (...args: unknown[]) => mockCreateCampus(...args),
  updateCampus: (...args: unknown[]) => mockUpdateCampus(...args),
  createAcademicYear: vi.fn(),
  updateAcademicYear: vi.fn(),
  createGradeLevel: vi.fn(),
  updateGradeLevel: vi.fn(),
  createTerm: (...args: unknown[]) => mockCreateTerm(...args),
  updateTerm: (...args: unknown[]) => mockUpdateTerm(...args),
  MasterDataApiError: class MasterDataApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.name = "MasterDataApiError";
      this.status = status;
      this.body = body;
    }
  },
}));

vi.mock("@/lib/academic-structure-api", () => ({
  getAcademicStructureSummary: (...args: unknown[]) => mockGetAcademicStructureSummary(...args),
  getTeacherAssignmentSummary: (...args: unknown[]) => mockGetTeacherAssignmentSummary(...args),
  listClasses: (...args: unknown[]) => mockListClasses(...args),
  listSubjectOfferings: (...args: unknown[]) => mockListSubjectOfferings(...args),
  listTeacherAssignments: (...args: unknown[]) => mockListTeacherAssignments(...args),
  createClass: vi.fn(),
  updateClass: vi.fn(),
  createTeacherAssignment: vi.fn(),
  updateTeacherAssignment: vi.fn(),
  AcademicStructureApiError: class AcademicStructureApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.name = "AcademicStructureApiError";
      this.status = status;
      this.body = body;
    }
  },
}));

vi.mock("@/lib/enrolment-api", () => ({
  getEnrolmentSummary: (...args: unknown[]) => mockGetEnrolmentSummary(...args),
  listEnrolments: (...args: unknown[]) => mockListEnrolments(...args),
  getReconciliationDiagnostics: (...args: unknown[]) => mockGetReconciliationDiagnostics(...args),
  createEnrolment: vi.fn(),
  updateEnrolment: vi.fn(),
  transferEnrolment: vi.fn(),
  EnrolmentApiError: class EnrolmentApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.name = "EnrolmentApiError";
      this.status = status;
      this.body = body;
    }
  },
}));

// ─── Fixtures ──────────────────────────────────────────────────────────────────

const EMPTY_MD_SUMMARY = {
  campus_count: 0, active_campus_count: 0,
  academic_year_count: 0, active_academic_year_count: 0,
  current_academic_year: null,
  term_count: 0, grade_level_count: 0, active_grade_level_count: 0,
};

const POPULATED_MD_SUMMARY = {
  campus_count: 1, active_campus_count: 1,
  academic_year_count: 1, active_academic_year_count: 1,
  current_academic_year: { id: "year1", name: "2026–2027" },
  term_count: 3, grade_level_count: 6, active_grade_level_count: 6,
};

const EMPTY_AS_SUMMARY = {
  canonical_class_count: 0, legacy_class_count: 2,
  inactive_canonical_class_count: 0,
  active_subject_offering_count: 0, inactive_subject_offering_count: 0,
  subject_offering_by_grade_level: [],
};

const POPULATED_AS_SUMMARY = {
  canonical_class_count: 4, legacy_class_count: 2,
  inactive_canonical_class_count: 0,
  active_subject_offering_count: 8, inactive_subject_offering_count: 0,
  subject_offering_by_grade_level: [],
};

const EMPTY_TA_SUMMARY = {
  active_assignment_count: 0, inactive_assignment_count: 0,
  homeroom_assignment_count: 0, subject_teacher_assignment_count: 0,
  canonical_coverage_count: 0, total_active_teachers: 0,
  canonical_assignment_coverage_percentage: 0, teachers: [],
};

const EMPTY_ENROL_SUMMARY = {
  total_enrollments: 0, active_enrollments: 0,
  transferred_enrollments: 0, withdrawn_enrollments: 0, completed_enrollments: 0,
  students_with_active_canonical_enrollment: 0,
  students_with_legacy_class_id_but_no_canonical_enrollment: 3,
  students_with_terminal_canonical_history_and_stale_class_id: 0,
  students_with_class_id_conflicting_active_enrollment: 0,
  students_with_multiple_active_enrollments: 0,
  active_enrollments_by_class: [], active_enrollments_by_grade_level: [],
};

const CAMPUS_ALPHA = { id: "c1", name: "Alpha Campus", code: "ALPHA", description: null, is_active: true, created_at: null, updated_at: null };
const CAMPUS_BETA = { id: "c2", name: "Beta Campus", code: "BETA", description: "Second campus", is_active: false, created_at: null, updated_at: null };

const CANONICAL_CLASS = {
  id: "cls1", tenant_id: "t1", campus_id: "c1", academic_year_id: "year1", grade_level_id: "g1",
  class_teacher_id: null, code: "5A", is_active: true, grade: "Grade 5", section: "A",
  academic_year: "2026–2027", campus_name: "Alpha Campus", academic_year_name: "2026–2027",
  grade_level_name: "Grade 5", class_teacher_name: null, updated_at: null,
};

const LEGACY_CLASS = {
  id: "cls2", tenant_id: "t1", campus_id: null, academic_year_id: null, grade_level_id: null,
  class_teacher_id: null, code: "OldClass", is_active: true, grade: null, section: null,
  academic_year: "2025-2026", campus_name: null, academic_year_name: null,
  grade_level_name: null, class_teacher_name: null, updated_at: null,
};

const ACTIVE_ENROLMENT = {
  id: "enr1", student_id: "s1", student_name: "Alice Banda", academic_year_id: "year1",
  academic_year_name: "2026–2027", grade_level_id: "g1", grade_level_name: "Grade 5",
  class_id: "cls1", class_code: "5A", class_section: "A",
  status: "active" as const, enrolled_on: "2026-09-01", exited_on: null, exit_reason: null,
};

const RECONCILIATION_ROW = {
  student_id: "s2", display_name: "Bob Moyo",
  legacy_class_id: "cls2", canonical_active_class_id: null,
  issue_code: "legacy_only",
  recommended_action: "Create a canonical enrolment for this student.",
};

const YEAR_2026 = {
  id: "year1",
  name: "2026–2027",
  start_date: "2026-01-01",
  end_date: "2026-12-31",
  is_current: true,
  is_active: true,
  created_at: null,
  updated_at: null,
};

const TERM_1 = {
  id: "term1",
  academic_year_id: "year1",
  name: "Term 1",
  code: "T1",
  start_date: "2026-01-10",
  end_date: "2026-04-10",
  sequence: 1,
  is_active: true,
  created_at: null,
  updated_at: null,
};

function setupOverviewMocks(overrides?: Partial<{
  md: unknown; as_: unknown; ta: unknown; en: unknown;
}>) {
  mockGetMasterDataSetupSummary.mockResolvedValue(overrides?.md ?? POPULATED_MD_SUMMARY);
  mockGetAcademicStructureSummary.mockResolvedValue(overrides?.as_ ?? POPULATED_AS_SUMMARY);
  mockGetTeacherAssignmentSummary.mockResolvedValue(overrides?.ta ?? EMPTY_TA_SUMMARY);
  mockGetEnrolmentSummary.mockResolvedValue(overrides?.en ?? EMPTY_ENROL_SUMMARY);
}

// ─── Import subject under test ─────────────────────────────────────────────────

import AcademicStructurePage from "@/app/academic-structure/page";

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("AcademicStructurePage — access control", () => {
  it("renders the page for principal role", async () => {
    setupOverviewMocks();
    render(<AcademicStructurePage />);
    await waitFor(() => {
      expect(screen.queryByText(/permission denied/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText("Academic Structure")).toBeInTheDocument();
  });

  it("shows permission denied for non-leadership role", async () => {
    mockedUseAuth.mockReturnValueOnce({
      user: { role: "teacher", id: "u2", email: "t@s.test" },
      isHydrating: false,
    });
    render(<AcademicStructurePage />);
    expect(screen.getByRole("alert")).toHaveTextContent(/permission denied/i);
  });

  it("shows loading during hydration", () => {
    mockedUseAuth.mockReturnValueOnce({ user: null, isHydrating: true });
    render(<AcademicStructurePage />);
    expect(screen.getByText(/loading session/i)).toBeInTheDocument();
  });
});

describe("AcademicStructurePage — navigation tabs", () => {
  beforeEach(() => { setupOverviewMocks(); });

  it("renders all 9 navigation tabs", async () => {
    render(<AcademicStructurePage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Overview" })).toBeInTheDocument());
    const tabs = ["Overview", "Campuses", "Academic Years", "Grade Levels", "Classes", "Subject Offerings", "Assignments", "Enrolments", "Reconciliation"];
    for (const tab of tabs) {
      expect(screen.getByRole("button", { name: tab })).toBeInTheDocument();
    }
  });

  it("defaults to Overview tab", async () => {
    render(<AcademicStructurePage />);
    await waitFor(() => expect(mockGetMasterDataSetupSummary).toHaveBeenCalled());
  });
});

describe("AcademicStructurePage — Academic Years term management", () => {
  beforeEach(() => {
    setupOverviewMocks();
    mockCreateTerm.mockClear();
    mockUpdateTerm.mockClear();
    mockListAcademicYears.mockResolvedValue([YEAR_2026]);
    mockListTerms.mockResolvedValue([TERM_1]);
    mockCreateTerm.mockResolvedValue({ ...TERM_1, id: "term2", name: "Term 2", code: "T2", sequence: 2, start_date: "2026-05-01", end_date: "2026-08-01" });
    mockUpdateTerm.mockResolvedValue({ ...TERM_1 });
  });

  it("lists terms with academic-year association", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getByText("2026–2027")).toBeInTheDocument());
    expect(screen.getByText(/Term 1/)).toBeInTheDocument();
    expect(screen.getByText(/2026-01-10/)).toBeInTheDocument();
  });

  it("creates a term via createTerm API", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Term" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ Term" }));
    fireEvent.change(screen.getByPlaceholderText("Term 1"), { target: { value: "Term 2" } });
    fireEvent.change(screen.getByPlaceholderText("T1"), { target: { value: "T2" } });
    const dateInputs = screen.getAllByDisplayValue(/2026-/);
    fireEvent.change(dateInputs[0], { target: { value: "2026-05-01" } });
    fireEvent.change(dateInputs[1], { target: { value: "2026-08-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Term" }));
    await waitFor(() => {
      expect(mockCreateTerm).toHaveBeenCalled();
    });
  });

  it("edits a term via updateTerm API", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit Term" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Edit Term" }));
    fireEvent.change(screen.getByPlaceholderText("Term 1"), { target: { value: "Term 1 Revised" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Term" }));
    await waitFor(() => {
      expect(mockUpdateTerm).toHaveBeenCalledWith("term1", expect.objectContaining({ name: "Term 1 Revised" }));
    });
  });

  it("activates/deactivates term via updateTerm API", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Deactivate" }).length).toBeGreaterThan(1));
    fireEvent.click(screen.getAllByRole("button", { name: "Deactivate" })[0]);
    await waitFor(() => {
      expect(mockUpdateTerm).toHaveBeenCalledWith("term1", { is_active: false });
    });
  });

  it("validates term dates before API call", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Term" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ Term" }));
    fireEvent.change(screen.getByPlaceholderText("Term 1"), { target: { value: "Bad Dates" } });
    fireEvent.change(screen.getByPlaceholderText("T1"), { target: { value: "BD" } });
    const dateInputs = document.querySelectorAll('input[type="date"]');
    fireEvent.change(dateInputs[0], { target: { value: "2026-10-01" } });
    fireEvent.change(dateInputs[1], { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Term" }));
    await waitFor(() => expect(screen.getByText(/start date cannot be after end date/i)).toBeInTheDocument());
    expect(mockCreateTerm).not.toHaveBeenCalled();
  });

  it("shows controlled API conflict errors", async () => {
    mockCreateTerm.mockRejectedValueOnce(new Error("API 409: {\"detail\":\"Term code already exists\"}"));
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Term" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ Term" }));
    fireEvent.change(screen.getByPlaceholderText("Term 1"), { target: { value: "Term 2" } });
    fireEvent.change(screen.getByPlaceholderText("T1"), { target: { value: "T1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Term" }));
    await waitFor(() => expect(screen.getByText(/term code already exists/i)).toBeInTheDocument());
  });

  it("does not show any delete action for terms", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Academic Years" }));
    await waitFor(() => expect(screen.getByText(/Term 1/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /delete term|delete/i })).not.toBeInTheDocument();
  });
});

describe("AcademicStructurePage — Overview tab", () => {
  it("shows setup readiness chips when data is populated", async () => {
    setupOverviewMocks();
    render(<AcademicStructurePage />);
    await waitFor(() => {
      expect(screen.getByText("2026–2027")).toBeInTheDocument();
    });
    const configuredChips = screen.getAllByText("Configured");
    expect(configuredChips.length).toBeGreaterThan(0);
  });

  it("shows 'Action Required' when campuses are not configured", async () => {
    setupOverviewMocks({ md: EMPTY_MD_SUMMARY });
    render(<AcademicStructurePage />);
    await waitFor(() => {
      const chips = screen.getAllByText("Action Required");
      expect(chips.length).toBeGreaterThan(0);
    });
  });

  it("shows loading state then overview data", async () => {
    setupOverviewMocks();
    render(<AcademicStructurePage />);
    expect(screen.getByText(/loading overview/i)).toBeInTheDocument();
    await waitFor(() => expect(mockGetMasterDataSetupSummary).toHaveBeenCalled());
  });

  it("shows error alert on API failure with retry", async () => {
    mockGetMasterDataSetupSummary.mockRejectedValueOnce(new Error("API 503: Service unavailable"));
    mockGetAcademicStructureSummary.mockResolvedValue(POPULATED_AS_SUMMARY);
    mockGetTeacherAssignmentSummary.mockResolvedValue(EMPTY_TA_SUMMARY);
    mockGetEnrolmentSummary.mockResolvedValue(EMPTY_ENROL_SUMMARY);
    render(<AcademicStructurePage />);
    await waitFor(() => expect(screen.getByText(/service unavailable/i)).toBeInTheDocument());
  });

  it("shows legacy-only count in compatibility section", async () => {
    setupOverviewMocks({ en: { ...EMPTY_ENROL_SUMMARY, students_with_legacy_class_id_but_no_canonical_enrollment: 3 } });
    render(<AcademicStructurePage />);
    await waitFor(() => {
      const matches = screen.getAllByText("3");
      expect(matches.length).toBeGreaterThan(0);
    });
  });
});

describe("AcademicStructurePage — Campuses tab", () => {
  beforeEach(() => {
    setupOverviewMocks();
    mockListCampuses.mockResolvedValue([CAMPUS_ALPHA, CAMPUS_BETA]);
  });

  it("lists campuses with status badges", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Campuses" }));
    await waitFor(() => {
      expect(screen.getByText("Alpha Campus")).toBeInTheDocument();
      expect(screen.getByText("Beta Campus")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Inactive").length).toBeGreaterThan(0);
  });

  it("shows empty state when no campuses configured", async () => {
    mockListCampuses.mockResolvedValue([]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Campuses" }));
    await waitFor(() => expect(screen.getByText(/no campuses configured/i)).toBeInTheDocument());
  });

  it("shows deactivation confirmation dialog before deactivating", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Campuses" }));
    await waitFor(() => expect(screen.getByText("Alpha Campus")).toBeInTheDocument());
    const deactivateBtns = screen.getAllByRole("button", { name: /deactivate/i });
    fireEvent.click(deactivateBtns[0]);
    await waitFor(() => {
      expect(screen.getByText(/existing records are not affected/i)).toBeInTheDocument();
    });
  });

  it("creates a new campus via inline form", async () => {
    mockCreateCampus.mockResolvedValue({ ...CAMPUS_ALPHA, id: "c3", name: "New Campus", code: "NEW" });
    mockListCampuses.mockResolvedValueOnce([CAMPUS_ALPHA, CAMPUS_BETA]).mockResolvedValueOnce([CAMPUS_ALPHA, CAMPUS_BETA, { ...CAMPUS_ALPHA, id: "c3", name: "New Campus", code: "NEW" }]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Campuses" }));
    await waitFor(() => expect(screen.getByText("Alpha Campus")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ Add Campus" }));
    const nameInput = screen.getByPlaceholderText("Main Campus");
    fireEvent.change(nameInput, { target: { value: "New Campus" } });
    const codeInput = screen.getByPlaceholderText("MAIN");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockCreateCampus).toHaveBeenCalledWith(expect.objectContaining({ name: "New Campus", code: "NEW" })));
  });
});

describe("AcademicStructurePage — Classes tab", () => {
  beforeEach(() => {
    setupOverviewMocks();
    mockListClasses.mockResolvedValue([CANONICAL_CLASS, LEGACY_CLASS]);
    mockListCampuses.mockResolvedValue([CAMPUS_ALPHA]);
    mockListAcademicYears.mockResolvedValue([]);
    mockListGradeLevels.mockResolvedValue([]);
  });

  it("shows canonical and legacy class badges", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Classes" }));
    await waitFor(() => {
      expect(screen.getByText("5A")).toBeInTheDocument();
      expect(screen.getByText("OldClass")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Canonical").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Legacy").length).toBeGreaterThan(0);
  });

  it("shows 'Legacy — read-only' label for legacy classes", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Classes" }));
    await waitFor(() => expect(screen.getByText(/legacy — read-only/i)).toBeInTheDocument());
  });

  it("shows create class form when button clicked", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Classes" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Create Canonical Class" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ Create Canonical Class" }));
    expect(screen.getByText("New Canonical Class")).toBeInTheDocument();
  });
});

describe("AcademicStructurePage — Assignments tab", () => {
  beforeEach(() => {
    setupOverviewMocks();
    mockListTeacherAssignments.mockResolvedValue([{
      id: "ta1", tenant_id: "t1", academic_year_id: "year1",
      teacher_id: "te1", class_id: "cls1", subject_offering_id: null,
      assignment_type: "homeroom" as const, start_date: "2026-09-01", end_date: null, is_active: true,
      teacher_name: "Ms Dube", class_code: "5A", class_grade_level_name: "Grade 5", class_section: "A",
      academic_year_name: "2026–2027", subject_offering: null, subject_id: null, subject_code: null, subject_name: null,
    }]);
  });

  it("lists teacher assignments", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Assignments" }));
    await waitFor(() => expect(screen.getByText("Ms Dube")).toBeInTheDocument());
    expect(screen.getByText("Homeroom")).toBeInTheDocument();
  });

  it("shows warning about non-patchable structural fields", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Assignments" }));
    await waitFor(() => {
      expect(screen.getByText(/structural fields.*teacher.*class.*subject.*cannot be silently rewritten/i)).toBeInTheDocument();
    });
  });

  it("filters assignments by Active / Inactive / All", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Assignments" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(mockListTeacherAssignments).toHaveBeenCalled();
  });
});

describe("AcademicStructurePage — Enrolments tab", () => {
  beforeEach(() => {
    setupOverviewMocks();
    mockListEnrolments.mockResolvedValue([ACTIVE_ENROLMENT]);
  });

  it("lists active enrolments with student names", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Enrolments" }));
    await waitFor(() => expect(screen.getByText("Alice Banda")).toBeInTheDocument());
    const activeMatches = screen.getAllByText("active");
    expect(activeMatches.length).toBeGreaterThan(0);
  });

  it("shows Transfer and Withdraw buttons for active enrolments", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Enrolments" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Transfer" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  });

  it("shows transfer form when Transfer is clicked", async () => {
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Enrolments" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Transfer" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Transfer" }));
    expect(screen.getByText("Transfer Student")).toBeInTheDocument();
    expect(screen.getByText(/transferring preserves the original enrolment history/i)).toBeInTheDocument();
  });

  it("shows empty enrolments state", async () => {
    mockListEnrolments.mockResolvedValue([]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Enrolments" }));
    await waitFor(() => expect(screen.getByText(/no enrolments found/i)).toBeInTheDocument());
  });
});

describe("AcademicStructurePage — Reconciliation tab", () => {
  beforeEach(() => { setupOverviewMocks(); });

  it("shows read-only diagnostic notice", async () => {
    mockGetReconciliationDiagnostics.mockResolvedValue([]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Reconciliation" }));
    await waitFor(() => expect(screen.getByText(/no automatic repairs are performed/i)).toBeInTheDocument());
  });

  it("shows reconciliation issues when they exist", async () => {
    mockGetReconciliationDiagnostics.mockResolvedValue([RECONCILIATION_ROW]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Reconciliation" }));
    await waitFor(() => {
      expect(screen.getByText("Bob Moyo")).toBeInTheDocument();
      expect(screen.getByText("Legacy only")).toBeInTheDocument();
      expect(screen.getByText("Create a canonical enrolment for this student.")).toBeInTheDocument();
    });
  });

  it("shows no issues message when reconciliation is clean", async () => {
    mockGetReconciliationDiagnostics.mockResolvedValue([]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Reconciliation" }));
    await waitFor(() => {
      expect(screen.getByText(/no reconciliation issues found/i)).toBeInTheDocument();
    });
  });

  it("does not show an automatic repair button", async () => {
    mockGetReconciliationDiagnostics.mockResolvedValue([RECONCILIATION_ROW]);
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Reconciliation" }));
    await waitFor(() => expect(screen.getByText("Bob Moyo")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /auto.*repair|repair all|fix all/i })).not.toBeInTheDocument();
  });

  it("shows API failure for reconciliation endpoint", async () => {
    mockGetReconciliationDiagnostics.mockRejectedValue(new Error("API 500: Internal server error"));
    render(<AcademicStructurePage />);
    fireEvent.click(screen.getByRole("button", { name: "Reconciliation" }));
    await waitFor(() => expect(screen.getByText(/internal server error/i)).toBeInTheDocument());
  });
});

describe("Sidebar — Academic Structure link", () => {
  it("renders Academic Structure link for principal nav", async () => {
    mockedUseAuth.mockReturnValueOnce({ user: { role: "principal", id: "u1", email: "p@s.test" }, isHydrating: false });
    mockedUsePathname.mockReturnValueOnce("/");
    const SidebarModule = await import("@/components/sidebar");
    const Sidebar = SidebarModule.default;
    render(<Sidebar />);
    await waitFor(() => {
      expect(screen.getByText("Academic Structure")).toBeInTheDocument();
    });
  });
});

