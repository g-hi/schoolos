import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadershipTimetableWorkspacePage from "@/app/leadership/timetable/page";
import { TimetableGenerationApiError } from "@/lib/timetable-generation-api";

const useAuthMock = vi.fn();
const listConfigsMock = vi.fn();
const listPreferencesMock = vi.fn();
const listTimetablesMock = vi.fn();
const getSummaryMock = vi.fn();
const listLocksMock = vi.fn();
const listVersionsMock = vi.fn();
const getEffectiveMock = vi.fn();
const getVersionMock = vi.fn();
const previewCandidatesMock = vi.fn();
const previewRepairImpactMock = vi.fn();
const materializeMock = vi.fn();
const submitVersionMock = vi.fn();
const approveVersionMock = vi.fn();
const publishVersionMock = vi.fn();
const cancelVersionMock = vi.fn();
const getDiffMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/leadership/timetable",
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/lib/timetable-generation-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/timetable-generation-api")>("@/lib/timetable-generation-api");
  return {
    ...actual,
    listGenerationConfigurations: (...args: unknown[]) => listConfigsMock(...args),
    listTeacherPreferences: (...args: unknown[]) => listPreferencesMock(...args),
    listTimetables: (...args: unknown[]) => listTimetablesMock(...args),
    getGenerationConfigurationSummary: (...args: unknown[]) => getSummaryMock(...args),
    listGenerationLocks: (...args: unknown[]) => listLocksMock(...args),
    listTimetableVersions: (...args: unknown[]) => listVersionsMock(...args),
    getEffectiveTimetableVersion: (...args: unknown[]) => getEffectiveMock(...args),
    getTimetableVersion: (...args: unknown[]) => getVersionMock(...args),
    previewTimetableCandidates: (...args: unknown[]) => previewCandidatesMock(...args),
    previewRepairImpact: (...args: unknown[]) => previewRepairImpactMock(...args),
    materializeVersionFromCandidate: (...args: unknown[]) => materializeMock(...args),
    submitTimetableVersion: (...args: unknown[]) => submitVersionMock(...args),
    approveTimetableVersion: (...args: unknown[]) => approveVersionMock(...args),
    publishTimetableVersion: (...args: unknown[]) => publishVersionMock(...args),
    cancelTimetableVersion: (...args: unknown[]) => cancelVersionMock(...args),
    getVersionDiff: (...args: unknown[]) => getDiffMock(...args),
  };
});

function baseCandidatePayload() {
  return {
    summary: {},
    candidate_result: {
      problem_id: "p1",
      problem_fingerprint: "fp-1",
      requested_count: 3,
      generated_count: 2,
      candidates: [
        {
          candidate_id: "cand_a",
          candidate_profile: "balanced",
          feasible: true,
          optimal: false,
          solver_status: "feasible",
          quality_score: 0.91,
          quality_band: "good",
          assignment_fingerprint: "af-a",
          preference_summary: { score: 6, max_score: 100 },
          fairness_summary: { teacher_gap_count: 2 },
          workload_summary: { spread: 1 },
          gap_summary: { gap_count: 18 },
          subject_distribution_summary: { max_daily_sessions_same_subject: "Strong" },
          room_summary: { max_room_sessions: 4 },
          repair_impact_summary: { changed: 6, affected_teacher_ids: ["Teacher F", "Teacher G"], affected_class_ids: ["Grade 8A", "Grade 8B"], status: "available" },
          hard_constraint_summary: { hard_violations: 0 },
          diagnostics: [],
          warnings: [],
          assignments: [
            {
              occurrence_id: "occ-1",
              class_id: "Grade 8A",
              subject_id: "Mathematics",
              day_key: "Tuesday",
              period_key: "Tuesday:P3",
              teacher_id: "Teacher A",
              room_id: "Room 204",
              periods_per_session: 2,
              occupied_period_keys: ["Tuesday:P3", "Tuesday:P4"],
            },
            {
              occurrence_id: "occ-2",
              class_id: "Grade 8A",
              subject_id: "French",
              day_key: "Tuesday",
              period_key: "Tuesday:P5",
              teacher_id: "Teacher F",
              room_id: "Room 301",
              parallel_block_id: "pb-1",
              parallel_child_id: "c-french",
              periods_per_session: 1,
              occupied_period_keys: ["Tuesday:P5"],
            },
            {
              occurrence_id: "occ-3",
              class_id: "Grade 8A",
              subject_id: "German",
              day_key: "Tuesday",
              period_key: "Tuesday:P5",
              teacher_id: "Teacher G",
              room_id: "Room 302",
              parallel_block_id: "pb-1",
              parallel_child_id: "c-german",
              periods_per_session: 1,
              occupied_period_keys: ["Tuesday:P5"],
            },
            {
              occurrence_id: "occ-4",
              class_id: "Grade 8A",
              subject_id: "Spanish",
              day_key: "Tuesday",
              period_key: "Tuesday:P5",
              teacher_id: "Teacher S",
              room_id: "Room 303",
              parallel_block_id: "pb-1",
              parallel_child_id: "c-spanish",
              periods_per_session: 1,
              occupied_period_keys: ["Tuesday:P5"],
            },
          ],
          class_facing_assignments: [],
        },
        {
          candidate_id: "cand_b",
          candidate_profile: "configured",
          feasible: true,
          optimal: false,
          solver_status: "feasible",
          quality_score: null,
          quality_band: "fair",
          assignment_fingerprint: "af-b",
          preference_summary: { score: null, max_score: null },
          fairness_summary: {},
          workload_summary: {},
          gap_summary: { gap_count: null },
          subject_distribution_summary: { max_daily_sessions_same_subject: "not_available" },
          room_summary: { max_room_sessions: null },
          repair_impact_summary: { changed: null, status: "not_available" },
          hard_constraint_summary: { hard_violations: 0 },
          diagnostics: [],
          warnings: [],
          assignments: [],
          class_facing_assignments: [],
        },
      ],
      comparison: {
        recommended_candidate_id: null,
        recommendation_reason_codes: ["tradeoff_no_universal_winner"],
        pairwise: [],
        explanation_facts: [],
      },
      attempts: [{ profile: "configured" }, { profile: "balanced" }],
      warnings: [{ code: "no_distinct_alternative", message: "All generated feasible candidates were equivalent duplicates." }],
      diagnostics: [],
      duration_ms: 0,
      deterministic: true,
      provenance: {},
    },
    explicit_non_actions: {},
  };
}

function configureBaseMocks() {
  useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "principal", is_active: true } });
  listConfigsMock.mockResolvedValue([
    {
      id: "cfg-1",
      academic_year_id: "AY-2026",
      term_id: "T1",
      campus_id: "Main",
      name: "Term 1 Generation",
      generation_mode: "standard",
      stability_mode: "balanced",
      lifecycle_status: "approved",
      baseline_timetable_version_id: "ver-1",
      objective_priorities: [
        { objective_key: "teacher_preferences", priority_level: "critical" },
        { objective_key: "minimize_teacher_gaps", priority_level: "high" },
      ],
      repair_scope: { scope_level: "minimum" },
    },
  ]);
  listPreferencesMock.mockResolvedValue([
    { id: "pref-1", teacher_id: "Ms A", academic_year_id: "AY-2026", term_id: "T1", campus_id: "Main", preference_type: "avoid_last_period", strength: "hard", weekdays: [2], period_numbers: [8], effective_start_date: "2026-08-20", effective_end_date: null, leadership_note: null, is_active: true },
  ]);
  listTimetablesMock.mockResolvedValue({
    items: [
      {
        id: "tt-1",
        academic_year_id: "AY-2026",
        term_id: "T1",
        campus_id: "Main",
        name: "Main timetable",
        status: "active",
        is_active: true,
        version_count: 2,
        created_at: "2026-08-01",
      },
    ],
    count: 1,
  });
  getSummaryMock.mockResolvedValue({
    configuration: {
      id: "cfg-1",
      academic_year_id: "AY-2026",
      term_id: "T1",
      campus_id: "Main",
      name: "Term 1 Generation",
      generation_mode: "standard",
      stability_mode: "balanced",
      lifecycle_status: "approved",
      baseline_timetable_version_id: "ver-1",
      objective_priorities: [
        { objective_key: "teacher_preferences", priority_level: "critical" },
        { objective_key: "minimize_teacher_gaps", priority_level: "high" },
      ],
      repair_scope: { scope_level: "minimum" },
    },
    validation: {
      is_valid: true,
      errors: [],
      policy_generation_allowed: true,
      policy_readiness_status: "ready",
      policy_blocker_count: 0,
    },
    policy_readiness_generation_allowed: true,
    preference_count: 1,
    hard_preference_count: 1,
    override_count: 0,
    lock_count: 2,
    parallel_block_count: 1,
    repair_settings: { scope_level: "minimum" },
    future_solver_eligibility: true,
    explicit_non_actions: {},
  });
  listLocksMock.mockResolvedValue([
    { id: "lock-1", configuration_id: "cfg-1", lock_state: "locked", target_type: "session_reference", target_reference_id: null, target_reference_code: "occ-1", day_of_week: null, period_number: null, period_end_number: null, is_manual_hard_lock: true, is_active: true },
    { id: "lock-2", configuration_id: "cfg-1", lock_state: "prefer_to_keep", target_type: "teacher", target_reference_id: "teacher-1", target_reference_code: null, day_of_week: null, period_number: null, period_end_number: null, is_manual_hard_lock: false, is_active: true },
  ]);
  listVersionsMock.mockResolvedValue({
    items: [
      {
        id: "ver-1",
        timetable_id: "tt-1",
        version_number: 1,
        generation_configuration_id: "cfg-1",
        source_candidate_id: "cand_old",
        source_problem_fingerprint: "fp-old",
        source_assignment_fingerprint: "af-old",
        generation_mode: "standard",
        baseline_version_id: null,
        lifecycle_status: "superseded",
        effective_from: "2026-08-20",
        effective_until: "2026-10-01",
        submitted_at: null,
        approved_at: null,
        published_at: "2026-08-19",
        superseded_at: "2026-09-30",
        superseded_by_version_id: "ver-2",
        candidate_profile: "configured",
        quality_snapshot: { quality_score: 0.88 },
        repair_impact_snapshot: {},
        diff_summary_snapshot: {},
        solver_provenance: {},
        assignment_count: 100,
        created_at: "2026-08-19",
        created_by_user_id: "principal-1",
      },
      {
        id: "ver-2",
        timetable_id: "tt-1",
        version_number: 2,
        generation_configuration_id: "cfg-1",
        source_candidate_id: "cand_new",
        source_problem_fingerprint: "fp-new",
        source_assignment_fingerprint: "af-new",
        generation_mode: "repair",
        baseline_version_id: "ver-1",
        lifecycle_status: "published",
        effective_from: "2026-10-01",
        effective_until: null,
        submitted_at: null,
        approved_at: null,
        published_at: "2026-09-28",
        superseded_at: null,
        superseded_by_version_id: null,
        candidate_profile: "stability_focused",
        quality_snapshot: { quality_score: 0.91 },
        repair_impact_snapshot: { changed: 6 },
        diff_summary_snapshot: {},
        solver_provenance: {},
        assignment_count: 100,
        created_at: "2026-09-28",
        created_by_user_id: "principal-1",
      },
    ],
    count: 2,
  });
  getEffectiveMock.mockResolvedValue({
    effective_on: "2026-08-08",
    version: {
      id: "ver-1",
      timetable_id: "tt-1",
      version_number: 1,
      generation_configuration_id: "cfg-1",
      source_candidate_id: "cand_old",
      source_problem_fingerprint: "fp-old",
      source_assignment_fingerprint: "af-old",
      generation_mode: "standard",
      baseline_version_id: null,
      lifecycle_status: "superseded",
      effective_from: "2026-08-20",
      effective_until: "2026-10-01",
      submitted_at: null,
      approved_at: null,
      published_at: "2026-08-19",
      superseded_at: "2026-09-30",
      superseded_by_version_id: "ver-2",
      candidate_profile: "configured",
      quality_snapshot: { quality_score: 0.88 },
      repair_impact_snapshot: {},
      diff_summary_snapshot: {},
      solver_provenance: {},
      assignment_count: 100,
      created_at: "2026-08-19",
      created_by_user_id: "principal-1",
    },
  });
  getVersionMock.mockResolvedValue({
    id: "ver-2",
    timetable_id: "tt-1",
    version_number: 2,
    generation_configuration_id: "cfg-1",
    source_candidate_id: "cand_new",
    source_problem_fingerprint: "fp-new",
    source_assignment_fingerprint: "af-new",
    generation_mode: "repair",
    baseline_version_id: "ver-1",
    lifecycle_status: "candidate",
    effective_from: null,
    effective_until: null,
    submitted_at: null,
    approved_at: null,
    published_at: null,
    superseded_at: null,
    superseded_by_version_id: null,
    candidate_profile: "stability_focused",
    quality_snapshot: { quality_score: 0.91 },
    repair_impact_snapshot: { changed: 6 },
    diff_summary_snapshot: {},
    solver_provenance: {},
    assignment_count: 100,
    created_at: "2026-09-28",
    created_by_user_id: "principal-1",
    assignments: [],
  });
  previewCandidatesMock.mockResolvedValue(baseCandidatePayload());
  previewRepairImpactMock.mockResolvedValue({
    baseline_version_id: "ver-1",
    repair_reason: "teacher_replacement",
    repair_scope: "minimum",
    direct_count: 4,
    conditionally_movable_count: 9,
    protected_count: 812,
    manual_lock_count: 22,
    direct_assignments: [],
    affected_teachers: ["Teacher A", "Teacher B"],
    affected_classes: ["Grade 8A", "Grade 8B"],
    affected_rooms: ["Room 101"],
    affected_parallel_blocks: [],
    stability: "balanced",
    blockers: [],
    warnings: [{ code: "repair_scope_tight" }],
    suggested_next_scope: "affected_entities",
  });
  materializeMock.mockResolvedValue({ timetable: { id: "tt-1" }, version: { id: "ver-3", version_number: 3, lifecycle_status: "candidate" }, explicit_non_actions: {} });
  submitVersionMock.mockResolvedValue({ id: "ver-2", version_number: 2, lifecycle_status: "under_review" });
  approveVersionMock.mockResolvedValue({ id: "ver-2", version_number: 2, lifecycle_status: "approved" });
  publishVersionMock.mockResolvedValue({ id: "ver-2", version_number: 2, lifecycle_status: "published" });
  cancelVersionMock.mockResolvedValue({ id: "ver-2", version_number: 2, lifecycle_status: "cancelled" });
  getDiffMock.mockResolvedValue({ moved: 2, teacher_changes: 1, room_changes: 1, counts: { moved_period_or_span: 2, teacher_changes: 1, room_changes: 1 }, affected_teachers: ["Teacher A"], affected_classes: ["Grade 8A"], affected_rooms: ["Room 1"], unchanged_percentage: 98.7, details: [] });
}

describe("LeadershipTimetableWorkspacePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("confirm", vi.fn(() => true));
    configureBaseMocks();
  });

  it("renders readiness READY and enables candidate preview", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    expect(await screen.findByText("READY TO GENERATE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /preview timetable candidates/i })).toBeEnabled();
  });

  it("renders BLOCKED readiness and disables generation when backend validation fails", async () => {
    getSummaryMock.mockResolvedValueOnce({
      configuration: {
        id: "cfg-1",
        academic_year_id: "AY-2026",
        term_id: "T1",
        campus_id: "Main",
        name: "Term 1 Generation",
        generation_mode: "standard",
        stability_mode: "balanced",
        lifecycle_status: "approved",
        baseline_timetable_version_id: "ver-1",
        objective_priorities: [],
        repair_scope: { scope_level: "minimum" },
      },
      validation: { is_valid: false, errors: ["invalid generation configuration"], policy_generation_allowed: false },
      policy_readiness_generation_allowed: false,
      preference_count: 1,
      hard_preference_count: 1,
      override_count: 0,
      lock_count: 2,
      parallel_block_count: 1,
      repair_settings: { scope_level: "minimum" },
      future_solver_eligibility: false,
      explicit_non_actions: {},
    });

    render(<LeadershipTimetableWorkspacePage />);
    expect(await screen.findByText("BLOCKED")).toBeInTheDocument();
    expect(screen.getByText(/invalid generation configuration/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /preview timetable candidates/i })).toBeDisabled();
  });

  it("supports mode switching and customized priority panel", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    await screen.findByText("Timetable status");

    fireEvent.click(screen.getByRole("button", { name: /customized/i }));
    expect(screen.getByText("Leadership priorities")).toBeInTheDocument();
    expect(screen.getByText(/teacher preferences/)).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /repair existing timetable/i }));
    expect(screen.getByText(/repair baseline version/i)).toBeInTheDocument();
  });

  it("renders principal preference controls and lock states", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    expect(await screen.findByText(/principal-controlled timetable preference governance/i)).toBeInTheDocument();
    expect(screen.getByText(/teacher ms a/i)).toBeInTheDocument();
    expect(screen.getByText(/hard: must be respected/i)).toBeInTheDocument();
    expect(screen.getByText(/teachers do not submit scheduling requests here/i)).toBeInTheDocument();
    expect(screen.getByText("locked")).toBeInTheDocument();
    expect(screen.getByText("prefer to keep")).toBeInTheDocument();
    expect(screen.getByText(/department lock target is intentionally not offered/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/department/i)).not.toBeInTheDocument();
  });

  it("shows repair impact with default minimum scope and explicit broader-scope action", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    await screen.findByText("Timetable status");
    fireEvent.click(screen.getByRole("button", { name: /repair existing timetable/i }));

    const scopeSelect = screen.getByLabelText(/repair scope/i) as HTMLSelectElement;
    expect(scopeSelect.value).toBe("minimum");

    fireEvent.click(screen.getByRole("button", { name: /preview repair impact/i }));
    expect(await screen.findByText(/directly affected/i)).toBeInTheDocument();
    expect(screen.getByText(/4/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try broader scope/i })).toBeInTheDocument();
    expect(previewRepairImpactMock).toHaveBeenCalledTimes(1);
  });

  it("renders candidate cards, tradeoff, N/A metrics, parallel details, and multi-period block", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    await screen.findByText("Timetable status");

    fireEvent.click(screen.getByRole("button", { name: /preview timetable candidates/i }));
    expect((await screen.findAllByRole("button", { name: /^select$/i })).length).toBeGreaterThan(0);
    expect(screen.getByText(/trade-off: no universal winner/i)).toBeInTheDocument();
    expect(screen.getByText(/no distinct alternative/i)).toBeInTheDocument();

    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: /^select$/i })[0]);
    expect(await screen.findByText(/timetable visual preview/i)).toBeInTheDocument();
    expect(screen.getByText("P3-P4")).toBeInTheDocument();
    expect(screen.getByText(/foreign language/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/foreign language/i));
    expect(screen.getByText(/French - Teacher Teacher F/)).toBeInTheDocument();
    expect(screen.getByText(/German - Teacher Teacher G/)).toBeInTheDocument();
    expect(screen.getByText(/Spanish - Teacher Teacher S/)).toBeInTheDocument();
  });

  it("materializes selected candidate using fingerprints and handles stale preview", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    await screen.findByText("Timetable status");

    fireEvent.click(screen.getByRole("button", { name: /preview timetable candidates/i }));
    expect((await screen.findAllByRole("button", { name: /^select$/i })).length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: /^select$/i })[0]);
    fireEvent.click(screen.getByRole("button", { name: /save as timetable version/i }));

    await waitFor(() => expect(materializeMock).toHaveBeenCalledTimes(1));
    const materializeArg = materializeMock.mock.calls[0][1];
    expect(materializeArg.candidate_id).toBe("cand_a");
    expect(materializeArg.expected_problem_fingerprint).toBe("fp-1");
    expect(materializeArg.expected_assignment_fingerprint).toBe("af-a");
    expect(materializeArg.assignments).toBeUndefined();

    materializeMock.mockRejectedValueOnce(
      new TimetableGenerationApiError(
        409,
        "Scheduling problem changed since candidate preview.",
        { detail: { code: "stale_candidate_preview" } },
        "stale_candidate_preview",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /save as timetable version/i }));
    expect(await screen.findByText(/inputs changed after this candidate was generated/i)).toBeInTheDocument();
  });

  it("supports lifecycle submit, approve, publish and version diff", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    expect(await screen.findByText(/version 2/i)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /submit for review/i }));
    await waitFor(() => expect(submitVersionMock).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /approve timetable/i }));
    await waitFor(() => expect(approveVersionMock).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/effective from/i), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("button", { name: /publish timetable/i }));
    await waitFor(() => expect(publishVersionMock).toHaveBeenCalledWith("ver-2", "2026-10-01"));

    fireEvent.change(screen.getByLabelText(/left version/i), { target: { value: "ver-1" } });
    fireEvent.change(screen.getByLabelText(/right version/i), { target: { value: "ver-2" } });
    fireEvent.click(screen.getByRole("button", { name: /view changes/i }));
    expect(await screen.findByText(/unchanged: 98.7%/i)).toBeInTheDocument();
  });

  it("shows current vs scheduled published versions distinctly", async () => {
    render(<LeadershipTimetableWorkspacePage />);
    expect(await screen.findByText(/current effective timetable/i)).toBeInTheDocument();
    expect(screen.getAllByText(/version 1/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/scheduled: version/i)).toBeInTheDocument();
    expect(screen.getByText(/superseded/)).toBeInTheDocument();
  });

  it("hides principal-only final actions for school_admin", async () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "school_admin", is_active: true } });
    render(<LeadershipTimetableWorkspacePage />);
    expect(await screen.findByText(/approve and publish controls are principal-only/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /publish timetable/i })).toBeDisabled();
  });
});
