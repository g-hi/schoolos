"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import RoleGuard from "@/components/auth/role-guard";
import { useAuth } from "@/components/auth/auth-provider";
import { toFriendlyError } from "@/app/leadership/calendar/calendar-utils";
import {
  TimetableGenerationApiError,
  approveTimetableVersion,
  cancelTimetableVersion,
  getEffectiveTimetableVersion,
  getGenerationConfigurationSummary,
  getTimetableVersion,
  getVersionDiff,
  listGenerationConfigurations,
  listGenerationLocks,
  listTeacherPreferences,
  listTimetableVersions,
  listTimetables,
  materializeVersionFromCandidate,
  previewRepairImpact,
  previewTimetableCandidates,
  publishTimetableVersion,
  submitTimetableVersion,
  type AssignmentRow,
  type Candidate,
  type CandidatePreviewResponse,
  type GenerationConfiguration,
  type GenerationConfigurationSummary,
  type GenerationLock,
  type RepairImpactPreview,
  type TeacherPreference,
  type TimetableVersionSummary,
  type VersionDiffPayload,
} from "@/lib/timetable-generation-api";

type GenerationModeUi = "standard" | "customized" | "repair";
type PreviewView = "class" | "teacher" | "room";

const PRIORITY_LABELS: Record<string, string> = {
  critical: "Critical",
  high: "High",
  normal: "Normal",
  low: "Low",
};

const STABILITY_LABELS: Record<string, string> = {
  very_high: "Very High",
  high: "High",
  balanced: "Balanced",
  flexible: "Flexible",
};

const REPAIR_REASONS = [
  "teacher_replacement",
  "teacher_availability_change",
  "class_requirement_change",
  "room_change",
  "subject_requirement_change",
  "bell_structure_change",
  "manual_adjustment",
];

const REPAIR_SCOPE_OPTIONS: Array<{ value: string; label: string; description: string }> = [
  { value: "minimum", label: "Minimum disruption", description: "Change only directly affected timetable areas where possible." },
  { value: "affected_entities", label: "Affected teachers/classes", description: "Allow closely related sessions to move." },
  { value: "grade", label: "Grade", description: "Allow timetable movement inside the affected grade." },
  { value: "whole_school", label: "Whole school", description: "Allow broader rearrangement while respecting hard locks." },
];

function toneForLifecycle(status: string): string {
  switch (status) {
    case "candidate":
      return "bg-slate-100 text-slate-700 border-slate-200";
    case "under_review":
      return "bg-amber-100 text-amber-800 border-amber-200";
    case "approved":
      return "bg-sky-100 text-sky-800 border-sky-200";
    case "published":
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case "superseded":
      return "bg-violet-100 text-violet-800 border-violet-200";
    case "cancelled":
      return "bg-rose-100 text-rose-800 border-rose-200";
    default:
      return "bg-gray-100 text-gray-700 border-gray-200";
  }
}

function toneForReadiness(ready: boolean): string {
  return ready ? "bg-emerald-50 text-emerald-800 border-emerald-200" : "bg-rose-50 text-rose-800 border-rose-200";
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function parseApiError(error: unknown): { message: string; code?: string } {
  if (error instanceof TimetableGenerationApiError) {
    return { message: error.message, code: error.code };
  }
  return { message: toFriendlyError(error) };
}

function periodNumberFromKey(periodKey: string): number {
  const match = periodKey.match(/P(\d+)/i);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function formatPeriodSpan(row: AssignmentRow): string {
  const occupied = row.occupied_period_keys && row.occupied_period_keys.length > 0 ? row.occupied_period_keys : [row.period_key];
  const sorted = [...occupied].sort((a, b) => periodNumberFromKey(a) - periodNumberFromKey(b));
  const first = sorted[0]?.match(/P\d+/i)?.[0] || "P?";
  const last = sorted[sorted.length - 1]?.match(/P\d+/i)?.[0] || first;
  return first === last ? first.toUpperCase() : `${first.toUpperCase()}-${last.toUpperCase()}`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function lifecycleLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function valueOrNA(value: unknown): string {
  if (value === null || value === undefined) return "N/A";
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (!normalized || normalized === "not_available" || normalized === "not_applicable") {
      return "N/A";
    }
    return value;
  }
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "N/A";
  return "N/A";
}

function candidateSelectable(candidate: Candidate): boolean {
  if (!candidate.feasible) return false;
  const diagnostics = candidate.diagnostics || [];
  if (diagnostics.some((item) => String(item.severity || "").toLowerCase() === "blocker")) {
    return false;
  }
  const hard = candidate.hard_constraint_summary || {};
  const hardViolations = asNumber((hard as Record<string, unknown>).hard_violations ?? (hard as Record<string, unknown>).violation_count ?? 0) ?? 0;
  return hardViolations <= 0;
}

function compareMetric(candidate: Candidate, key: string): string {
  if (key === "quality") {
    if (candidate.quality_score === null || candidate.quality_score === undefined) return "N/A";
    return `${Math.round(candidate.quality_score * 100)}`;
  }
  if (key === "preferences") {
    const score = asNumber(candidate.preference_summary?.score);
    const maxScore = asNumber(candidate.preference_summary?.max_score);
    if (score === null || maxScore === null || maxScore <= 0) return "N/A";
    return `${Math.max(0, Math.min(100, Math.round((1 - score / maxScore) * 100)))}%`;
  }
  if (key === "gaps") {
    return valueOrNA(candidate.gap_summary?.gap_count);
  }
  if (key === "fairness") {
    return valueOrNA(candidate.fairness_summary?.teacher_gap_count);
  }
  if (key === "subject_distribution") {
    return valueOrNA(candidate.subject_distribution_summary?.max_daily_sessions_same_subject);
  }
  if (key === "room_quality") {
    return valueOrNA(candidate.room_summary?.max_room_sessions);
  }
  if (key === "changed_sessions") {
    return valueOrNA(candidate.repair_impact_summary?.changed);
  }
  if (key === "affected_teachers") {
    const ids = candidate.repair_impact_summary?.affected_teacher_ids;
    return Array.isArray(ids) ? String(ids.length) : "N/A";
  }
  if (key === "affected_classes") {
    const ids = candidate.repair_impact_summary?.affected_class_ids;
    return Array.isArray(ids) ? String(ids.length) : "N/A";
  }
  if (key === "stability") {
    return valueOrNA(candidate.repair_impact_summary?.status);
  }
  if (key === "solver_status") {
    return valueOrNA(candidate.solver_status);
  }
  return "N/A";
}

function SectionCard({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        {right}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${toneForLifecycle(value)}`}>{lifecycleLabel(value)}</span>;
}

export default function LeadershipTimetableWorkspacePage() {
  const { isHydrating, isAuthenticated, user } = useAuth();

  const [configurations, setConfigurations] = useState<GenerationConfiguration[]>([]);
  const [selectedConfigurationId, setSelectedConfigurationId] = useState<string>("");
  const [summary, setSummary] = useState<GenerationConfigurationSummary | null>(null);
  const [preferences, setPreferences] = useState<TeacherPreference[]>([]);
  const [locks, setLocks] = useState<GenerationLock[]>([]);

  const [mode, setMode] = useState<GenerationModeUi>("standard");
  const [candidateCount, setCandidateCount] = useState<number>(3);
  const [candidatePreview, setCandidatePreview] = useState<CandidatePreviewResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>("");
  const [compareCandidateIds, setCompareCandidateIds] = useState<string[]>([]);

  const [repairReason, setRepairReason] = useState<string>("teacher_replacement");
  const [repairScope, setRepairScope] = useState<string>("minimum");
  const [repairImpact, setRepairImpact] = useState<RepairImpactPreview | null>(null);
  const [loadingRepairImpact, setLoadingRepairImpact] = useState(false);

  const [previewView, setPreviewView] = useState<PreviewView>("class");
  const [previewEntityId, setPreviewEntityId] = useState<string>("");

  const [selectedTimetableId, setSelectedTimetableId] = useState<string>("");
  const [versions, setVersions] = useState<TimetableVersionSummary[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");
  const [selectedVersionDetail, setSelectedVersionDetail] = useState<TimetableVersionSummary | null>(null);
  const [effectiveTodayVersion, setEffectiveTodayVersion] = useState<TimetableVersionSummary | null>(null);
  const [leftDiffVersionId, setLeftDiffVersionId] = useState<string>("");
  const [rightDiffVersionId, setRightDiffVersionId] = useState<string>("");
  const [versionDiff, setVersionDiff] = useState<VersionDiffPayload | null>(null);

  const [effectiveFromDate, setEffectiveFromDate] = useState<string>("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const hasLeadershipAccess = Boolean(isAuthenticated && user && user.is_active && (user.role === "principal" || user.role === "school_admin"));
  const isPrincipal = user?.role === "principal";

  const selectedConfiguration = useMemo(
    () => configurations.find((item) => item.id === selectedConfigurationId) || null,
    [configurations, selectedConfigurationId],
  );

  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const selectedCandidate = useMemo(
    () => candidatePreview?.candidate_result.candidates.find((item) => item.candidate_id === selectedCandidateId) || null,
    [candidatePreview, selectedCandidateId],
  );

  const compareCandidates = useMemo(() => {
    if (!candidatePreview) return [];
    return candidatePreview.candidate_result.candidates.filter((item) => compareCandidateIds.includes(item.candidate_id));
  }, [candidatePreview, compareCandidateIds]);

  const publishedVersions = useMemo(() => versions.filter((item) => item.lifecycle_status === "published" || item.lifecycle_status === "superseded"), [versions]);

  const futurePublishedVersion = useMemo(() => {
    return publishedVersions
      .filter((item) => item.effective_from && item.effective_from > todayIso)
      .sort((a, b) => String(a.effective_from).localeCompare(String(b.effective_from)))[0] || null;
  }, [publishedVersions, todayIso]);

  const lockRows = useMemo(() => {
    return locks.filter((item) => item.target_type !== "department");
  }, [locks]);

  const assignmentsForPreview = useMemo(() => {
    const rows = selectedCandidate?.assignments || [];
    return rows;
  }, [selectedCandidate]);

  const previewDays = useMemo(() => {
    const dayOrder = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    const days = Array.from(new Set(assignmentsForPreview.map((item) => item.day_key)));
    return days.sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b));
  }, [assignmentsForPreview]);

  const previewPeriods = useMemo(() => {
    const keys = Array.from(new Set(assignmentsForPreview.map((item) => item.period_key)));
    return keys.sort((a, b) => periodNumberFromKey(a) - periodNumberFromKey(b));
  }, [assignmentsForPreview]);

  const previewEntities = useMemo(() => {
    if (!selectedCandidate) return [] as string[];
    if (previewView === "class") {
      return Array.from(new Set((selectedCandidate.assignments || []).map((item) => item.class_id))).sort();
    }
    if (previewView === "teacher") {
      return Array.from(new Set((selectedCandidate.assignments || []).map((item) => item.teacher_id).filter(Boolean) as string[])).sort();
    }
    return Array.from(new Set((selectedCandidate.assignments || []).map((item) => item.room_id).filter(Boolean) as string[])).sort();
  }, [selectedCandidate, previewView]);

  useEffect(() => {
    if (previewEntities.length === 0) {
      setPreviewEntityId("");
      return;
    }
    if (!previewEntities.includes(previewEntityId)) {
      setPreviewEntityId(previewEntities[0]);
    }
  }, [previewEntities, previewEntityId]);

  const loadVersionsForTimetable = useCallback(async (timetableId: string, includeCurrent = true) => {
    const versionResponse = await listTimetableVersions(timetableId);
    setVersions(versionResponse.items);
    if (versionResponse.items.length > 0) {
      setSelectedVersionId((current) => current || versionResponse.items[versionResponse.items.length - 1].id);
    }
    if (includeCurrent) {
      const effective = await getEffectiveTimetableVersion(timetableId, todayIso, false);
      setEffectiveTodayVersion(effective.version);
    }
  }, [todayIso]);

  const refreshWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [configs, preferenceRows, timetableRows] = await Promise.all([
        listGenerationConfigurations(),
        listTeacherPreferences({ active_only: true }),
        listTimetables(),
      ]);
      setConfigurations(configs);
      setPreferences(preferenceRows);

      const selectedConfig = configs.find((item) => item.lifecycle_status === "approved") || configs[0] || null;
      if (!selectedConfig) {
        setSelectedConfigurationId("");
        setSummary(null);
        setLocks([]);
        setVersions([]);
        setSelectedTimetableId("");
        setEffectiveTodayVersion(null);
        return;
      }

      setSelectedConfigurationId(selectedConfig.id);
      setMode((selectedConfig.generation_mode as GenerationModeUi) || "standard");

      const [summaryPayload, lockRows] = await Promise.all([
        getGenerationConfigurationSummary(selectedConfig.id),
        listGenerationLocks(selectedConfig.id),
      ]);
      setSummary(summaryPayload);
      setLocks(lockRows);

      const matchingTimetable = timetableRows.items.find(
        (item) =>
          item.academic_year_id === selectedConfig.academic_year_id &&
          item.term_id === selectedConfig.term_id &&
          (item.campus_id || null) === (selectedConfig.campus_id || null),
      ) || timetableRows.items[0] || null;

      if (matchingTimetable) {
        setSelectedTimetableId(matchingTimetable.id);
        await loadVersionsForTimetable(matchingTimetable.id);
      } else {
        setVersions([]);
        setSelectedTimetableId("");
        setEffectiveTodayVersion(null);
      }
    } catch (loadError) {
      setError(parseApiError(loadError).message);
    } finally {
      setLoading(false);
    }
  }, [loadVersionsForTimetable]);

  async function loadConfigurationDetail(configurationId: string) {
    setError(null);
    try {
      const [summaryPayload, lockRows] = await Promise.all([
        getGenerationConfigurationSummary(configurationId),
        listGenerationLocks(configurationId),
      ]);
      setSummary(summaryPayload);
      setLocks(lockRows);
      setCandidatePreview(null);
      setSelectedCandidateId("");
      setCompareCandidateIds([]);
      setRepairImpact(null);
    } catch (loadError) {
      setError(parseApiError(loadError).message);
    }
  }

  useEffect(() => {
    if (isHydrating || !hasLeadershipAccess) return;
    void refreshWorkspace();
  }, [isHydrating, hasLeadershipAccess, refreshWorkspace]);

  useEffect(() => {
    if (!selectedTimetableId || !selectedVersionId) {
      setSelectedVersionDetail(null);
      return;
    }
    void getTimetableVersion(selectedVersionId, true)
      .then((payload) => setSelectedVersionDetail(payload))
      .catch((loadError) => setError(parseApiError(loadError).message));
  }, [selectedTimetableId, selectedVersionId]);

  async function handlePreviewCandidates() {
    if (!selectedConfigurationId) return;
    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      const profileByMode: Record<GenerationModeUi, string[]> = {
        standard: ["configured", "balanced", "preference_focused"],
        customized: ["configured", "preference_focused", "distribution_focused"],
        repair: ["configured", "stability_focused", "balanced"],
      };
      const payload = await previewTimetableCandidates(selectedConfigurationId, {
        candidate_count: Math.max(1, Math.min(5, candidateCount)),
        candidate_profiles: profileByMode[mode],
        include_comparison: true,
        include_explanation_facts: true,
        response_mode: "detailed",
      });
      setCandidatePreview(payload);
      const firstSelectable = payload.candidate_result.candidates.find((item) => candidateSelectable(item));
      setSelectedCandidateId(firstSelectable?.candidate_id || "");
      setCompareCandidateIds(
        payload.candidate_result.candidates
          .slice(0, Math.min(2, payload.candidate_result.candidates.length))
          .map((item) => item.candidate_id),
      );
    } catch (previewError) {
      setError(parseApiError(previewError).message);
    } finally {
      setGenerating(false);
    }
  }

  async function handlePreviewRepairImpact() {
    if (!selectedConfigurationId) return;
    setLoadingRepairImpact(true);
    setError(null);
    setNotice(null);
    try {
      const payload = await previewRepairImpact(selectedConfigurationId, {
        repair_reason: repairReason,
        scope_level: repairScope,
      });
      setRepairImpact(payload);
    } catch (previewError) {
      const parsed = parseApiError(previewError);
      if (parsed.code === "repair_requires_baseline") {
        setError("No repair baseline is available. Select a canonical published version before repair.");
      } else if (parsed.code === "repair_scope_invalid") {
        setError("The selected repair scope is not supported.");
      } else {
        setError(parsed.message);
      }
    } finally {
      setLoadingRepairImpact(false);
    }
  }

  async function handleSaveCandidateAsVersion() {
    if (!selectedConfigurationId || !candidatePreview || !selectedCandidate) return;
    setError(null);
    setNotice(null);
    try {
      const response = await materializeVersionFromCandidate(selectedConfigurationId, {
        candidate_id: selectedCandidate.candidate_id,
        expected_problem_fingerprint: candidatePreview.candidate_result.problem_fingerprint,
        expected_assignment_fingerprint: selectedCandidate.assignment_fingerprint,
        candidate_count: Math.max(1, Math.min(5, candidateCount)),
        candidate_profiles: candidatePreview.candidate_result.attempts
          .map((item) => String(item.profile || ""))
          .filter(Boolean),
        candidate_profile: selectedCandidate.candidate_profile,
      });
      setNotice(`Candidate version created: Version ${response.version.version_number} (${lifecycleLabel(response.version.lifecycle_status)}).`);
      setSelectedVersionId(response.version.id);
      if (selectedTimetableId) {
        await loadVersionsForTimetable(selectedTimetableId);
      }
    } catch (saveError) {
      const parsed = parseApiError(saveError);
      if (parsed.code === "stale_candidate_preview") {
        setSelectedCandidateId("");
        setCompareCandidateIds([]);
        setError("The timetable inputs changed after this candidate was generated. Generate candidates again before continuing.");
      } else {
        setError(parsed.message);
      }
    }
  }

  async function handleVersionTransition(action: "submit" | "approve" | "publish" | "cancel") {
    if (!selectedVersionId) return;
    setError(null);
    setNotice(null);
    try {
      let updated: TimetableVersionSummary;
      if (action === "submit") {
        const ok = window.confirm("Submit this timetable version for Principal review?");
        if (!ok) return;
        updated = await submitTimetableVersion(selectedVersionId);
      } else if (action === "approve") {
        const ok = window.confirm("Approval confirms this timetable is ready for publication. It does not become operational until published.");
        if (!ok) return;
        updated = await approveTimetableVersion(selectedVersionId);
      } else if (action === "cancel") {
        const ok = window.confirm("Cancel this timetable version?");
        if (!ok) return;
        updated = await cancelTimetableVersion(selectedVersionId);
      } else {
        if (!effectiveFromDate) {
          setError("Select Effective from date before publishing.");
          return;
        }
        const ok = window.confirm(`Publish timetable version with effective date ${effectiveFromDate}?`);
        if (!ok) return;
        updated = await publishTimetableVersion(selectedVersionId, effectiveFromDate);
      }

      setNotice(`Version ${updated.version_number} is now ${lifecycleLabel(updated.lifecycle_status)}.`);
      if (selectedTimetableId) {
        await loadVersionsForTimetable(selectedTimetableId);
      }
      setSelectedVersionId(updated.id);
    } catch (transitionError) {
      const parsed = parseApiError(transitionError);
      if (parsed.code === "invalid_transition") {
        setError("This version cannot move to that lifecycle state from its current status.");
      } else {
        setError(parsed.message);
      }
    }
  }

  async function handleLoadDiff() {
    if (!leftDiffVersionId || !rightDiffVersionId) return;
    setError(null);
    try {
      const payload = await getVersionDiff(leftDiffVersionId, rightDiffVersionId, { include_details: true });
      setVersionDiff(payload);
    } catch (diffError) {
      setError(parseApiError(diffError).message);
    }
  }

  if (!isHydrating && !hasLeadershipAccess) {
    return (
      <RoleGuard allowedRoles={["principal", "school_admin"]} forbiddenMessage="Permission denied. Leadership access is required for this route.">
        <div />
      </RoleGuard>
    );
  }

  if (isHydrating || loading) {
    return <p className="text-sm text-slate-600">Loading timetable command centre...</p>;
  }

  const readinessReady = Boolean(summary?.validation.is_valid && summary?.validation.policy_generation_allowed);

  return (
    <RoleGuard allowedRoles={["principal", "school_admin"]} forbiddenMessage="Permission denied. Leadership access is required for this route.">
      <div className="space-y-6">
        <header className="rounded-3xl border border-slate-200 bg-linear-to-br from-slate-950 via-slate-900 to-blue-950 p-6 text-white shadow-lg">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-300">Timetable Command Centre</p>
              <h1 className="mt-1 text-3xl font-bold tracking-tight">Timetable</h1>
              {selectedConfiguration ? (
                <p className="mt-2 text-sm text-slate-200">
                  Academic year {selectedConfiguration.academic_year_id} · Term {selectedConfiguration.term_id}
                  {selectedConfiguration.campus_id ? ` · Campus ${selectedConfiguration.campus_id}` : ""}
                </p>
              ) : null}
              <p className={`mt-3 inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${toneForReadiness(readinessReady)}`}>
                {readinessReady ? "READY TO GENERATE" : "BLOCKED"}
              </p>
            </div>

            <div className="min-w-[260px] rounded-2xl border border-white/20 bg-white/10 p-4 text-sm">
              {effectiveTodayVersion ? (
                <>
                  <p className="font-semibold">Current effective timetable</p>
                  <p className="mt-1">Version {effectiveTodayVersion.version_number}</p>
                  <p className="text-slate-200">Effective {formatDate(effectiveTodayVersion.effective_from)} to {formatDate(effectiveTodayVersion.effective_until)}</p>
                </>
              ) : (
                <p className="font-semibold">No timetable published yet.</p>
              )}
              {futurePublishedVersion ? (
                <p className="mt-3 text-slate-200">Scheduled: Version {futurePublishedVersion.version_number} effective {formatDate(futurePublishedVersion.effective_from)}</p>
              ) : null}
            </div>
          </div>
        </header>

        {error ? (
          <section role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-rose-800">
            {error}
          </section>
        ) : null}
        {notice ? <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">{notice}</section> : null}

        <SectionCard
          title="Timetable status"
          right={
            <select
              aria-label="Select generation configuration"
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={selectedConfigurationId}
              onChange={(event) => {
                const nextId = event.target.value;
                setSelectedConfigurationId(nextId);
                const config = configurations.find((item) => item.id === nextId);
                setMode((config?.generation_mode as GenerationModeUi) || "standard");
                void loadConfigurationDetail(nextId);
              }}
            >
              {configurations.map((item) => (
                <option key={item.id} value={item.id}>{item.name} ({item.lifecycle_status})</option>
              ))}
            </select>
          }
        >
          {!selectedConfiguration ? (
            <p className="text-sm text-slate-600">No timetable configuration yet. Complete setup and policy readiness before timetable generation.</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Configuration</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">{selectedConfiguration.name}</p>
                <StatusBadge value={selectedConfiguration.lifecycle_status} />
              </div>
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Generation mode</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">{lifecycleLabel(mode)}</p>
              </div>
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Stability</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">{STABILITY_LABELS[selectedConfiguration.stability_mode] || selectedConfiguration.stability_mode}</p>
              </div>
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Future solver eligibility</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">{summary?.future_solver_eligibility ? "Eligible" : "Blocked"}</p>
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Timetable readiness">
          {!summary ? (
            <p className="text-sm text-slate-600">No readiness summary available.</p>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                  <p className="text-slate-500">Validation</p>
                  <p className="font-semibold text-slate-900">{summary.validation.is_valid ? "Valid" : "Invalid"}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                  <p className="text-slate-500">Policy gate</p>
                  <p className="font-semibold text-slate-900">{summary.validation.policy_generation_allowed ? "Passed" : "Blocked"}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                  <p className="text-slate-500">Preferences</p>
                  <p className="font-semibold text-slate-900">{summary.preference_count}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                  <p className="text-slate-500">Manual locks</p>
                  <p className="font-semibold text-slate-900">{lockRows.filter((item) => item.is_manual_hard_lock).length}</p>
                </div>
              </div>

              {summary.validation.errors.length > 0 ? (
                <div className="rounded-xl border border-rose-200 bg-rose-50 p-3">
                  <p className="text-sm font-semibold text-rose-800">Generation blocked</p>
                  <ul className="mt-2 list-disc pl-5 text-sm text-rose-800">
                    {summary.validation.errors.map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {!summary.validation.is_valid || !summary.validation.policy_generation_allowed ? (
                <p className="text-sm text-slate-700">Resolve blockers before candidate preview and version creation.</p>
              ) : null}
            </div>
          )}
        </SectionCard>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <SectionCard title="Generation mode">
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-3">
                <button
                  type="button"
                  onClick={() => setMode("standard")}
                  className={`rounded-xl border p-3 text-left ${mode === "standard" ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white"}`}
                >
                  <p className="text-sm font-semibold text-slate-900">Standard</p>
                  <p className="mt-1 text-xs text-slate-600">Generate using approved rules and balanced default priorities.</p>
                </button>
                <button
                  type="button"
                  onClick={() => setMode("customized")}
                  className={`rounded-xl border p-3 text-left ${mode === "customized" ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white"}`}
                >
                  <p className="text-sm font-semibold text-slate-900">Customized</p>
                  <p className="mt-1 text-xs text-slate-600">Adjust scheduling priorities, preferences, and protections before generating.</p>
                </button>
                <button
                  type="button"
                  onClick={() => setMode("repair")}
                  className={`rounded-xl border p-3 text-left ${mode === "repair" ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white"}`}
                >
                  <p className="text-sm font-semibold text-slate-900">Repair existing timetable</p>
                  <p className="mt-1 text-xs text-slate-600">Make the smallest necessary changes to an existing published timetable.</p>
                </button>
              </div>

              {mode === "customized" ? (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-sm font-semibold text-slate-900">Leadership priorities</p>
                  <p className="mt-1 text-xs text-slate-600">Symbolic priorities map to backend optimization behavior. Numeric solver weights are not exposed in this workspace.</p>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {(selectedConfiguration?.objective_priorities || []).map((item) => (
                      <div key={item.objective_key} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                        <span>{item.objective_key.replaceAll("_", " ")}</span>
                        <span className="font-semibold">{PRIORITY_LABELS[item.priority_level] || item.priority_level}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {mode === "standard" ? (
                <p className="text-sm text-slate-700">Standard generation uses approved defaults for objectives, stability, and policy constraints.</p>
              ) : null}

              <div className="flex flex-wrap items-center gap-3">
                <label className="text-sm text-slate-700" htmlFor="candidate-count">Generate up to</label>
                <input
                  id="candidate-count"
                  type="number"
                  min={1}
                  max={5}
                  value={candidateCount}
                  onChange={(event) => setCandidateCount(Number(event.target.value) || 1)}
                  className="w-20 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <span className="text-sm text-slate-700">alternatives</span>
                <button
                  type="button"
                  onClick={() => void handlePreviewCandidates()}
                  disabled={!readinessReady || generating || !selectedConfigurationId}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-indigo-300"
                >
                  {generating ? "Generating timetable candidates..." : "Preview timetable candidates"}
                </button>
              </div>
              {generating ? <p className="text-sm text-slate-600">This may take a little while for larger schools.</p> : null}
            </div>
          </SectionCard>

          <SectionCard title="Teacher scheduling preferences">
            <p className="text-xs text-slate-600">Teachers do not submit scheduling requests here. This section is Principal-controlled timetable preference governance.</p>
            {!isPrincipal ? (
              <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">School admin can view preferences but cannot run Principal-only personal preference governance actions in this workspace.</p>
            ) : null}
            <div className="mt-3 space-y-2">
              {preferences.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-600">No teacher preferences recorded for this timetable context.</p>
              ) : (
                preferences.slice(0, 8).map((item) => (
                  <article key={item.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-semibold text-slate-900">Teacher {item.teacher_id}</p>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold">{PRIORITY_LABELS[item.strength] || item.strength}</span>
                    </div>
                    <p className="mt-1 text-slate-600">{item.preference_type.replaceAll("_", " ")}</p>
                    <p className="mt-1 text-xs text-slate-500">Effective {formatDate(item.effective_start_date)} to {formatDate(item.effective_end_date)}</p>
                  </article>
                ))
              )}
            </div>
            <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <summary className="cursor-pointer text-sm font-semibold text-slate-800">Preference strength guidance</summary>
              <div className="mt-2 space-y-1 text-xs text-slate-700">
                <p>Hard: Must be respected. May make generation impossible.</p>
                <p>Strong: Important preference. Solver should strongly favor it.</p>
                <p>Normal: Prefer when reasonably possible.</p>
                <p>Low: Minor preference.</p>
              </div>
            </details>
          </SectionCard>
        </div>

        <SectionCard title="Protection locks">
          <p className="text-sm text-slate-700">Locked / Prefer to keep / Flexible controls are enforced through backend lock policies. Department lock target is intentionally not offered.</p>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-3 py-2 text-left">State</th>
                  <th className="px-3 py-2 text-left">Target</th>
                  <th className="px-3 py-2 text-left">Reference</th>
                  <th className="px-3 py-2 text-left">Day/Period</th>
                  <th className="px-3 py-2 text-left">Manual hard lock</th>
                </tr>
              </thead>
              <tbody>
                {lockRows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-4 text-slate-600">No active generation locks.</td>
                  </tr>
                ) : (
                  lockRows.map((item) => (
                    <tr key={item.id} className="border-t border-slate-100">
                      <td className="px-3 py-2">{item.lock_state.replaceAll("_", " ")}</td>
                      <td className="px-3 py-2">{item.target_type.replaceAll("_", " ")}</td>
                      <td className="px-3 py-2">{item.target_reference_code || item.target_reference_id || "-"}</td>
                      <td className="px-3 py-2">{item.day_of_week ?? "-"}/{item.period_number ?? "-"}{item.period_end_number ? `-${item.period_end_number}` : ""}</td>
                      <td className="px-3 py-2">{item.is_manual_hard_lock ? "Yes" : "No"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {mode === "repair" ? (
          <SectionCard title="Repair baseline and impact">
            {selectedConfiguration?.baseline_timetable_version_id ? (
              <p className="text-sm text-slate-700">Repair baseline version: {selectedConfiguration.baseline_timetable_version_id}</p>
            ) : (
              <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">No repair baseline available. Select a canonical timetable version first.</p>
            )}

            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label className="text-sm">
                <span className="mb-1 block text-slate-700">Repair reason</span>
                <select value={repairReason} onChange={(event) => setRepairReason(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2">
                  {REPAIR_REASONS.map((item) => (
                    <option key={item} value={item}>{item.replaceAll("_", " ")}</option>
                  ))}
                </select>
              </label>
              <label className="text-sm md:col-span-2 xl:col-span-2">
                <span className="mb-1 block text-slate-700">Repair scope</span>
                <select value={repairScope} onChange={(event) => setRepairScope(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2">
                  {REPAIR_SCOPE_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500">{REPAIR_SCOPE_OPTIONS.find((item) => item.value === repairScope)?.description}</p>
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-slate-700">Stability</span>
                <select
                  value={selectedConfiguration?.stability_mode || "balanced"}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2"
                  disabled
                >
                  <option value="very_high">Very High</option>
                  <option value="high">High</option>
                  <option value="balanced">Balanced</option>
                  <option value="flexible">Flexible</option>
                </select>
              </label>
            </div>

            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handlePreviewRepairImpact()}
                disabled={loadingRepairImpact || !selectedConfigurationId}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-400"
              >
                {loadingRepairImpact ? "Loading impact..." : "Preview repair impact"}
              </button>
              {repairImpact?.suggested_next_scope ? (
                <button
                  type="button"
                  onClick={() => setRepairScope(repairImpact.suggested_next_scope || repairScope)}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
                >
                  Try broader scope
                </button>
              ) : null}
            </div>

            {repairImpact ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <h3 className="text-sm font-semibold text-slate-900">Repair impact</h3>
                <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4 text-sm">
                  <p>Directly affected: <span className="font-semibold">{repairImpact.direct_count}</span></p>
                  <p>Conditionally movable: <span className="font-semibold">{repairImpact.conditionally_movable_count}</span></p>
                  <p>Protected: <span className="font-semibold">{repairImpact.protected_count}</span></p>
                  <p>Manual locks: <span className="font-semibold">{repairImpact.manual_lock_count}</span></p>
                </div>
                <p className="mt-2 text-sm text-slate-700">
                  Affected: {repairImpact.affected_teachers.length} teachers, {repairImpact.affected_classes.length} classes, {repairImpact.affected_rooms.length} rooms
                </p>
                {repairImpact.blockers.length > 0 ? (
                  <p className="mt-2 text-sm text-rose-700">Minimum-disruption repair could not produce a feasible timetable.</p>
                ) : null}
              </div>
            ) : null}
          </SectionCard>
        ) : null}

        <SectionCard title="Candidate preview and comparison">
          {!candidatePreview ? (
            <p className="text-sm text-slate-600">No candidate generated yet. Use Preview timetable candidates to start.</p>
          ) : (
            <div className="space-y-5">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {candidatePreview.candidate_result.candidates.map((candidate) => {
                  const selectable = candidateSelectable(candidate);
                  const isSelected = selectedCandidateId === candidate.candidate_id;
                  return (
                    <article key={candidate.candidate_id} className={`rounded-xl border p-4 ${isSelected ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="text-sm font-semibold text-slate-900">{candidate.candidate_id}</h3>
                        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold">{candidate.candidate_profile.replaceAll("_", " ")}</span>
                      </div>
                      <p className="mt-2 text-sm text-slate-700">Overall quality {candidate.quality_score !== null && candidate.quality_score !== undefined ? `${Math.round(candidate.quality_score * 100)} / 100` : "N/A"}</p>
                      <div className="mt-2 grid gap-1 text-xs text-slate-600">
                        <p>Teacher preferences: {compareMetric(candidate, "preferences")}</p>
                        <p>Teacher gaps: {compareMetric(candidate, "gaps")}</p>
                        <p>Subject distribution: {compareMetric(candidate, "subject_distribution")}</p>
                        <p>Solver status: {candidate.solver_status}</p>
                      </div>

                      {!selectable ? <p className="mt-2 text-xs text-rose-700">This candidate is not selectable due to blocker diagnostics.</p> : null}

                      <div className="mt-3 flex items-center justify-between gap-2">
                        <label className="text-xs text-slate-700">
                          <input
                            type="checkbox"
                            className="mr-2"
                            checked={compareCandidateIds.includes(candidate.candidate_id)}
                            onChange={(event) => {
                              setCompareCandidateIds((current) => {
                                if (event.target.checked) {
                                  if (current.length >= 5) return current;
                                  return [...current, candidate.candidate_id];
                                }
                                return current.filter((id) => id !== candidate.candidate_id);
                              });
                            }}
                          />
                          Compare
                        </label>
                        <button
                          type="button"
                          disabled={!selectable}
                          onClick={() => setSelectedCandidateId(candidate.candidate_id)}
                          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 disabled:opacity-50"
                        >
                          Select
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>

              {candidatePreview.candidate_result.warnings.some((item) => item.code === "no_distinct_alternative") ? (
                <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">No distinct alternative: generated feasible candidates were equivalent duplicates.</p>
              ) : null}

              {candidatePreview.candidate_result.comparison?.recommended_candidate_id ? (
                <p className="text-sm text-emerald-700">Recommended: {candidatePreview.candidate_result.comparison.recommended_candidate_id} based on deterministic comparison evidence.</p>
              ) : null}
              {candidatePreview.candidate_result.comparison?.recommendation_reason_codes?.includes("tradeoff_no_universal_winner") ? (
                <p className="text-sm text-slate-700">Trade-off: no universal winner. Leadership judgment is required.</p>
              ) : null}

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="px-3 py-2 text-left">Metric</th>
                      {compareCandidates.map((candidate) => (
                        <th key={candidate.candidate_id} className="px-3 py-2 text-left">{candidate.candidate_id}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["Quality", "quality"],
                      ["Teacher preference satisfaction", "preferences"],
                      ["Teacher gaps", "gaps"],
                      ["Fairness", "fairness"],
                      ["Subject distribution", "subject_distribution"],
                      ["Room quality", "room_quality"],
                      ["Changed sessions", "changed_sessions"],
                      ["Affected teachers", "affected_teachers"],
                      ["Affected classes", "affected_classes"],
                      ["Stability", "stability"],
                      ["Solver status", "solver_status"],
                    ].map(([label, key]) => (
                      <tr key={key} className="border-t border-slate-100">
                        <td className="px-3 py-2 font-medium text-slate-800">{label}</td>
                        {compareCandidates.map((candidate) => (
                          <td key={`${candidate.candidate_id}-${key}`} className="px-3 py-2 text-slate-700">
                            {compareMetric(candidate, key)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void handleSaveCandidateAsVersion()}
                  disabled={!selectedCandidate}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-indigo-300"
                >
                  Save as timetable version
                </button>
                {selectedCandidate ? <p className="text-xs text-slate-600">Selected candidate: {selectedCandidate.candidate_id}</p> : null}
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Timetable visual preview">
          {!selectedCandidate ? (
            <p className="text-sm text-slate-600">Select a candidate to preview class, teacher, or room grid views.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-sm text-slate-700" htmlFor="preview-view">View by</label>
                <select id="preview-view" value={previewView} onChange={(event) => setPreviewView(event.target.value as PreviewView)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="class">Class</option>
                  <option value="teacher">Teacher</option>
                  <option value="room">Room</option>
                </select>
                <select value={previewEntityId} onChange={(event) => setPreviewEntityId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  {previewEntities.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-[760px] w-full border border-slate-200 text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="w-28 border border-slate-200 px-2 py-2 text-left">Period</th>
                      {previewDays.map((day) => (
                        <th key={day} className="border border-slate-200 px-2 py-2 text-left">{day}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewPeriods.map((periodKey) => (
                      <tr key={periodKey}>
                        <td className="border border-slate-200 bg-slate-50 px-2 py-2 align-top text-xs font-semibold text-slate-700">{periodKey.match(/P\d+/i)?.[0] || periodKey}</td>
                        {previewDays.map((day) => {
                          const slotAssignments = assignmentsForPreview.filter((row) => {
                            if (row.day_key !== day || row.period_key !== periodKey) return false;
                            if (previewView === "class") return row.class_id === previewEntityId;
                            if (previewView === "teacher") return row.teacher_id === previewEntityId;
                            return row.room_id === previewEntityId;
                          });

                          const parallelGroups = new Map<string, AssignmentRow[]>();
                          const normalRows: AssignmentRow[] = [];
                          for (const row of slotAssignments) {
                            if (row.parallel_block_id) {
                              const key = row.parallel_block_id;
                              const current = parallelGroups.get(key) || [];
                              current.push(row);
                              parallelGroups.set(key, current);
                            } else {
                              normalRows.push(row);
                            }
                          }

                          return (
                            <td key={`${periodKey}-${day}`} className="border border-slate-200 px-2 py-2 align-top">
                              {slotAssignments.length === 0 ? <span className="text-xs text-slate-400">-</span> : null}

                              {normalRows.map((row) => (
                                <article key={`${row.occurrence_id}-${row.parallel_child_id || "n"}`} className="mb-2 rounded-lg border border-slate-200 bg-white p-2 text-xs last:mb-0">
                                  <p className="font-semibold text-slate-900">{row.subject_id || "Lesson"}</p>
                                  <p className="text-slate-600">{row.class_id}</p>
                                  <p className="text-slate-600">Teacher {row.teacher_id || "-"}</p>
                                  <p className="text-slate-600">Room {row.room_id || "-"}</p>
                                  <p className="text-slate-500">{formatPeriodSpan(row)}</p>
                                </article>
                              ))}

                              {[...parallelGroups.entries()].map(([blockId, rows]) => {
                                const first = rows[0];
                                return (
                                  <details key={blockId} className="mb-2 rounded-lg border border-slate-200 bg-blue-50 p-2 text-xs last:mb-0">
                                    <summary className="cursor-pointer font-semibold text-slate-900">Foreign Language · {first.class_id} · {formatPeriodSpan(first)}</summary>
                                    <div className="mt-2 space-y-1">
                                      {rows.map((row) => (
                                        <p key={`${row.occurrence_id}-${row.parallel_child_id || "child"}`} className="text-slate-700">
                                          {row.subject_id || "Track"} - Teacher {row.teacher_id || "-"} - Room {row.room_id || "-"}
                                        </p>
                                      ))}
                                    </div>
                                  </details>
                                );
                              })}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Review, approval, and publication">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div>
              {selectedVersionDetail ? (
                <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-semibold text-slate-900">Version {selectedVersionDetail.version_number}</p>
                    <StatusBadge value={selectedVersionDetail.lifecycle_status} />
                  </div>
                  <p>Mode: {selectedVersionDetail.generation_mode || "-"}</p>
                  <p>Candidate profile: {selectedVersionDetail.candidate_profile || "-"}</p>
                  <p>Baseline: {selectedVersionDetail.baseline_version_id || "-"}</p>
                  <p>Created: {formatDate(selectedVersionDetail.created_at)}</p>
                  <p>Created by: {selectedVersionDetail.created_by_user_id || "-"}</p>
                  <p>Assignment count: {selectedVersionDetail.assignment_count}</p>
                  {selectedVersionDetail.baseline_version_id ? <p>Repair: Baseline V{selectedVersionDetail.baseline_version_id} → Candidate V{selectedVersionDetail.version_number}</p> : null}
                </div>
              ) : (
                <p className="text-sm text-slate-600">No version selected for review.</p>
              )}

              {selectedVersionDetail ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={() => void handleVersionTransition("submit")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">Submit for review</button>
                  {isPrincipal ? (
                    <>
                      <button type="button" onClick={() => void handleVersionTransition("approve")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">Approve timetable</button>
                      <button type="button" onClick={() => void handleVersionTransition("cancel")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">Cancel version</button>
                    </>
                  ) : (
                    <p className="text-xs text-amber-700">Approve and publish controls are Principal-only.</p>
                  )}
                </div>
              ) : null}
            </div>

            <div className="rounded-xl border border-slate-200 p-4">
              <h3 className="text-sm font-semibold text-slate-900">Publication</h3>
              <p className="mt-1 text-xs text-slate-600">Approval confirms readiness. Publication changes operational timetable status.</p>
              <label className="mt-3 block text-sm text-slate-700" htmlFor="effective-from">
                Effective from
              </label>
              <input
                id="effective-from"
                type="date"
                value={effectiveFromDate}
                onChange={(event) => setEffectiveFromDate(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              {effectiveTodayVersion ? (
                <p className="mt-2 text-xs text-slate-600">Current Version {effectiveTodayVersion.version_number} remains active until {effectiveFromDate || "the selected effective date"}.</p>
              ) : null}

              <button
                type="button"
                disabled={!isPrincipal || !selectedVersionId}
                onClick={() => void handleVersionTransition("publish")}
                className="mt-3 w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-indigo-300"
              >
                Publish timetable
              </button>
              {!isPrincipal ? <p className="mt-2 text-xs text-amber-700">Principal authority is required for publish.</p> : null}
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Version history">
          {versions.length === 0 ? (
            <p className="text-sm text-slate-600">No timetable version history yet.</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="px-3 py-2 text-left">Version</th>
                      <th className="px-3 py-2 text-left">Status</th>
                      <th className="px-3 py-2 text-left">Mode</th>
                      <th className="px-3 py-2 text-left">Created</th>
                      <th className="px-3 py-2 text-left">Effective from</th>
                      <th className="px-3 py-2 text-left">Effective until</th>
                      <th className="px-3 py-2 text-left">Baseline</th>
                      <th className="px-3 py-2 text-left">Quality</th>
                      <th className="px-3 py-2 text-left">Created by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.map((item) => (
                      <tr key={item.id} className="border-t border-slate-100">
                        <td className="px-3 py-2">
                          <button type="button" onClick={() => setSelectedVersionId(item.id)} className="text-indigo-700 underline-offset-2 hover:underline">Version {item.version_number}</button>
                        </td>
                        <td className="px-3 py-2"><StatusBadge value={item.lifecycle_status} /></td>
                        <td className="px-3 py-2">{item.generation_mode || "-"}</td>
                        <td className="px-3 py-2">{formatDate(item.created_at)}</td>
                        <td className="px-3 py-2">{formatDate(item.effective_from)}</td>
                        <td className="px-3 py-2">{formatDate(item.effective_until)}</td>
                        <td className="px-3 py-2">{item.baseline_version_id || "-"}</td>
                        <td className="px-3 py-2">{valueOrNA(item.quality_snapshot?.quality_score)}</td>
                        <td className="px-3 py-2">{item.created_by_user_id || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <select aria-label="Left version" value={leftDiffVersionId} onChange={(event) => setLeftDiffVersionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="">Select left version</option>
                  {versions.map((item) => (
                    <option key={`left-${item.id}`} value={item.id}>V{item.version_number}</option>
                  ))}
                </select>
                <select aria-label="Right version" value={rightDiffVersionId} onChange={(event) => setRightDiffVersionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="">Select right version</option>
                  {versions.map((item) => (
                    <option key={`right-${item.id}`} value={item.id}>V{item.version_number}</option>
                  ))}
                </select>
                <button type="button" onClick={() => void handleLoadDiff()} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">View changes</button>
              </div>

              {versionDiff ? (
                <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
                  <p className="font-semibold text-slate-900">Version comparison</p>
                  <p className="mt-1 text-slate-700">Changed lessons: {versionDiff.counts.moved_period_or_span + versionDiff.counts.teacher_changes + versionDiff.counts.room_changes}</p>
                  <p className="text-slate-700">Teacher changes: {versionDiff.teacher_changes}</p>
                  <p className="text-slate-700">Room changes: {versionDiff.room_changes}</p>
                  <p className="text-slate-700">Affected teachers/classes: {versionDiff.affected_teachers.length}/{versionDiff.affected_classes.length}</p>
                  <p className="text-slate-700">Unchanged: {versionDiff.unchanged_percentage}%</p>
                </div>
              ) : null}
            </>
          )}
        </SectionCard>

        <SectionCard title="AI assistance (advisory only)">
          <p className="text-sm text-slate-700">Ask for explanations of candidate trade-offs, repair impact, and version differences. AI suggestions are advisory and cannot approve, publish, or mutate canonical timetable state.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" disabled className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-500">Explain candidate trade-off</button>
            <button type="button" disabled className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-500">Explain version changes</button>
            <button type="button" disabled className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-500">Suggest less disruptive scope</button>
          </div>
          <p className="mt-2 text-xs text-slate-500">Notifications are handled by downstream timetable operations and are not part of this batch.</p>
        </SectionCard>
      </div>
    </RoleGuard>
  );
}
