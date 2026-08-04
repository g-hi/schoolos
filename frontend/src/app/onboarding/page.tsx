"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import RoleGuard from "@/components/auth/role-guard";
import {
  OnboardingApiError,
  OnboardingHistoryItem,
  OnboardingReadinessResponse,
  OnboardingStatusResponse,
  OrderedStep,
  ReadinessCheck,
  SafeActionRoute,
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

const STEP_GROUPS = {
  Foundation: ["campus", "academic_year", "terms", "grade_levels", "subjects"],
  "Academic Structure": ["classes", "subject_offerings"],
  People: ["people", "family_relationships"],
  "Academic Operations": ["teacher_assignments", "student_enrolments", "timetable"],
  Data: ["data_imports"],
  Completion: ["readiness_review"],
} as const;

const STEP_LABELS: Record<string, string> = {
  campus: "Campus",
  academic_year: "Academic Year",
  terms: "Terms",
  grade_levels: "Grade Levels",
  subjects: "Subjects",
  classes: "Classes",
  subject_offerings: "Subject Offerings",
  people: "People",
  family_relationships: "Family Relationships",
  teacher_assignments: "Teacher Assignments",
  student_enrolments: "Student Enrolments",
  timetable: "Timetable",
  data_imports: "Data Imports",
  readiness_review: "Readiness Review",
};

const OPTIONAL_SKIP_STEPS = new Set(["data_imports"]);
const SECTION_TABS = ["Overview", "Guided Setup", "Readiness Review", "History"] as const;

type SectionTab = (typeof SECTION_TABS)[number];
type ReadinessFilter = "all" | "blocking" | "warning" | "informational" | "complete";

function toMessage(error: unknown): string {
  if (error instanceof OnboardingApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function shortRef(value: string | null | undefined): string {
  if (!value) return "-";
  return `${value.slice(0, 8)}...`;
}

function statusBadgeClass(status: string): string {
  if (status === "complete" || status === "completed") return "bg-green-100 text-green-800";
  if (status === "blocking" || status === "blocked") return "bg-red-100 text-red-800";
  if (status === "warning") return "bg-amber-100 text-amber-800";
  if (status === "informational") return "bg-blue-100 text-blue-800";
  if (status === "paused") return "bg-slate-100 text-slate-700";
  if (status === "ready") return "bg-emerald-100 text-emerald-800";
  return "bg-gray-100 text-gray-700";
}

function stepAction(stepKey: string, checksByStep: Record<string, ReadinessCheck[]>): ReadinessCheck | null {
  const checks = checksByStep[stepKey] || [];
  const blocking = checks.find((item) => item.status === "blocking");
  if (blocking) return blocking;
  const warning = checks.find((item) => item.status === "warning");
  if (warning) return warning;
  return checks[0] || null;
}

function isTerminal(status: OnboardingStatusResponse["run_status"]): boolean {
  return status === "completed" || status === "cancelled";
}

function buildChecks(readiness: OnboardingReadinessResponse | null): ReadinessCheck[] {
  if (!readiness) return [];
  return Object.values(readiness.grouped_readiness_checks).flat();
}

function OnboardingWorkspace() {
  const [activeTab, setActiveTab] = useState<SectionTab>("Overview");
  const [readinessFilter, setReadinessFilter] = useState<ReadinessFilter>("all");
  const [status, setStatus] = useState<OnboardingStatusResponse | null>(null);
  const [readiness, setReadiness] = useState<OnboardingReadinessResponse | null>(null);
  const [history, setHistory] = useState<OnboardingHistoryItem[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize] = useState(5);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [submittingAction, setSubmittingAction] = useState<string | null>(null);
  const [selectedStep, setSelectedStep] = useState<string>("campus");

  const checks = useMemo(() => buildChecks(readiness), [readiness]);

  const checksByStep = useMemo(() => {
    const grouped: Record<string, ReadinessCheck[]> = {};
    for (const check of checks) {
      grouped[check.step_key] = grouped[check.step_key] || [];
      grouped[check.step_key].push(check);
    }
    return grouped;
  }, [checks]);

  const filteredChecks = useMemo(() => {
    if (readinessFilter === "all") return checks;
    return checks.filter((item) => item.status === readinessFilter);
  }, [checks, readinessFilter]);

  async function refreshOverviewAndReadiness() {
    const [statusResponse, readinessResponse] = await Promise.all([
      getOnboardingStatus(),
      getOnboardingReadiness(),
    ]);
    setStatus(statusResponse);
    setReadiness(readinessResponse);
    if (statusResponse.current_step) {
      setSelectedStep(statusResponse.current_step);
    }
  }

  async function refreshHistory(page = historyPage) {
    const historyResponse = await listOnboardingHistory({ page, page_size: historyPageSize });
    setHistory(historyResponse.items);
    setHistoryTotal(historyResponse.total);
    setHistoryPage(historyResponse.page);
  }

  async function refreshAll(page = historyPage) {
    await Promise.all([refreshOverviewAndReadiness(), refreshHistory(page)]);
  }

  useEffect(() => {
    setLoading(true);
    setError(null);
    void refreshAll()
      .catch((err) => setError(toMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (loading) return;
    void refreshHistory(historyPage).catch((err) => setError(toMessage(err)));
  }, [historyPage]);

  async function runMutation(actionName: string, task: () => Promise<void>) {
    setMutationError(null);
    setSubmittingAction(actionName);
    try {
      await task();
    } catch (err) {
      setMutationError(toMessage(err));
    } finally {
      setSubmittingAction(null);
    }
  }

  const runStatus = status?.run_status ?? "not_started";
  const terminal = isTerminal(runStatus);
  const availableActions = new Set(status?.available_actions || []);
  const hasActiveRun = Boolean(status?.run);

  const canStart = availableActions.has("start") && !hasActiveRun;
  const canPause = availableActions.has("pause") && !terminal;
  const canResume = availableActions.has("resume") && !terminal;
  const canComplete = availableActions.has("complete") && !terminal;
  const canCancel = availableActions.has("cancel") && !terminal;
  const canSetCurrentStep = availableActions.has("set_current_step") && !terminal;

  const orderedSteps: OrderedStep[] = status?.ordered_steps || [];

  if (loading) {
    return <p className="text-sm text-gray-600">Loading onboarding workspace...</p>;
  }

  if (error) {
    return (
      <section className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700" role="alert">
        {error}
      </section>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">School Setup</h1>
          <p className="text-sm text-gray-500 mt-1">Leadership onboarding workspace for guided setup readiness and lifecycle tracking.</p>
        </div>
        <div className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white p-2" role="tablist" aria-label="Onboarding sections">
          {SECTION_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              className={`rounded-md px-3 py-1.5 text-sm ${activeTab === tab ? "bg-indigo-600 text-white" : "text-gray-700 hover:bg-gray-100"}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
      </header>

      {mutationError ? (
        <section className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
          {mutationError}
        </section>
      ) : null}

      {activeTab === "Overview" ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Overview</h2>
              <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(runStatus)}`}>{runStatus.replace("_", " ")}</span>
            </div>
            {!hasActiveRun ? (
              <div className="mt-3 space-y-3 text-sm text-gray-700">
                <p>Start onboarding to track progress across existing school setup workspaces.</p>
                <button
                  type="button"
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-indigo-300"
                  disabled={!canStart || submittingAction === "start"}
                  onClick={() => {
                    if (!window.confirm("Start a new onboarding run for this school?")) return;
                    void runMutation("start", async () => {
                      await startOnboarding();
                      await refreshAll();
                    });
                  }}
                >
                  Start Onboarding
                </button>
              </div>
            ) : (
              <>
                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Onboarding progress metrics">
                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">Readiness</p>
                    <p className="text-xl font-semibold">{status?.readiness_percentage ?? 0}%</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">Completed Steps</p>
                    <p className="text-xl font-semibold">{status?.completed_step_count ?? 0}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">Blocked Steps</p>
                    <p className="text-xl font-semibold">{status?.blocked_step_count ?? 0}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">Warnings</p>
                    <p className="text-xl font-semibold">{status?.warning_count ?? 0}</p>
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 text-sm">
                  <div className="rounded-lg border border-gray-200 p-3">
                    <p><strong>Current step:</strong> {status?.current_step ? STEP_LABELS[status.current_step] || status.current_step : "-"}</p>
                    <p><strong>Next recommended step:</strong> {status?.next_recommended_step ? STEP_LABELS[status.next_recommended_step] || status.next_recommended_step : "-"}</p>
                    <p><strong>Started:</strong> {formatDate(status?.started_at)}</p>
                    <p><strong>Completed:</strong> {formatDate(status?.completed_at)}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 p-3 space-y-2">
                    <p className="font-medium">Available actions</p>
                    <div className="flex flex-wrap gap-2">
                      {(status?.available_actions || []).map((action) => (
                        <span key={action} className="rounded-full border border-gray-300 px-2 py-0.5 text-xs text-gray-700">
                          {action}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                    disabled={!canPause || submittingAction !== null}
                    onClick={() => {
                      if (!window.confirm("Pause onboarding? Operational school data remains unchanged.")) return;
                      void runMutation("pause", async () => {
                        await pauseOnboarding();
                        await refreshAll();
                      });
                    }}
                  >
                    Pause
                  </button>
                  <button
                    type="button"
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                    disabled={!canResume || submittingAction !== null}
                    onClick={() => {
                      void runMutation("resume", async () => {
                        await resumeOnboarding();
                        await refreshAll();
                      });
                    }}
                  >
                    Resume
                  </button>
                  <button
                    type="button"
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                    disabled={!canComplete || submittingAction !== null}
                    onClick={() => {
                      const blockers = readiness?.blocker_count ?? 0;
                      const warnings = readiness?.warning_count ?? 0;
                      if (
                        !window.confirm(
                          `Complete onboarding? Blockers: ${blockers}. Warnings: ${warnings}. Blockers prevent completion; warnings may remain.`,
                        )
                      ) {
                        return;
                      }
                      void runMutation("complete", async () => {
                        try {
                          await completeOnboarding();
                        } catch (err) {
                          if (err instanceof OnboardingApiError && err.status === 409) {
                            throw new OnboardingApiError(409, "Completion blocked: resolve remaining blockers first.", err.body);
                          }
                          throw err;
                        }
                        await refreshAll();
                      });
                    }}
                  >
                    Complete
                  </button>
                  <button
                    type="button"
                    className="rounded-lg border border-red-300 bg-red-50 px-3 py-1.5 text-sm text-red-700 hover:bg-red-100 disabled:bg-gray-100 disabled:text-gray-400"
                    disabled={!canCancel || submittingAction !== null}
                    onClick={() => {
                      if (
                        !window.confirm(
                          "Cancel onboarding? Run and step history are preserved and operational school data is unaffected.",
                        )
                      ) {
                        return;
                      }
                      void runMutation("cancel", async () => {
                        await cancelOnboarding();
                        await refreshAll(1);
                      });
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </section>
      ) : null}

      {activeTab === "Guided Setup" ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Guided Setup</h2>
            <p className="mt-1 text-sm text-gray-600">Select a current focus step and navigate to existing setup workspaces. Backend state remains authoritative.</p>

            <div className="mt-3 flex items-end gap-2">
              <label className="text-sm text-gray-700" htmlFor="current-step-select">Current Step</label>
              <select
                id="current-step-select"
                className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
                value={selectedStep}
                onChange={(event) => setSelectedStep(event.target.value)}
                disabled={!canSetCurrentStep || submittingAction !== null}
              >
                {Object.keys(STEP_LABELS).map((stepKey) => (
                  <option key={stepKey} value={stepKey}>{STEP_LABELS[stepKey]}</option>
                ))}
              </select>
              <button
                type="button"
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-indigo-300"
                disabled={!canSetCurrentStep || submittingAction !== null}
                onClick={() => {
                  void runMutation("set_current_step", async () => {
                    await updateCurrentStep(selectedStep);
                    await refreshOverviewAndReadiness();
                  });
                }}
              >
                Set Current Step
              </button>
            </div>
          </div>

          {Object.entries(STEP_GROUPS).map(([group, keys]) => (
            <div key={group} className="rounded-xl border border-gray-200 bg-white p-4">
              <h3 className="text-base font-semibold">{group}</h3>
              <div className="mt-3 space-y-2">
                {keys.map((stepKey) => {
                  const row = orderedSteps.find((item) => item.step_key === stepKey);
                  const check = stepAction(stepKey, checksByStep);
                  const isBlocked = row?.status === "blocked" || check?.status === "blocking";
                  const canAcknowledge =
                    availableActions.has("acknowledge_step") &&
                    !terminal &&
                    !isBlocked &&
                    row?.status !== "completed" &&
                    row?.status !== "skipped";
                  const canSkip =
                    availableActions.has("skip_optional_step") &&
                    !terminal &&
                    OPTIONAL_SKIP_STEPS.has(stepKey) &&
                    !isBlocked;

                  return (
                    <article key={stepKey} className="rounded-lg border border-gray-200 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-medium text-gray-900">{STEP_LABELS[stepKey]}</p>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-600">
                            <span className={`rounded-full px-2 py-0.5 ${statusBadgeClass(row?.status || "not_started")}`}>{row?.status || "not_started"}</span>
                            <span>Completion source: {row?.completion_source || "-"}</span>
                            <span>Acknowledged: {row?.acknowledged_at ? formatDate(row.acknowledged_at) : "-"}</span>
                          </div>
                          {row?.blocked_reason ? (
                            <p className="mt-1 text-xs text-red-700">Blocker: {row.blocked_reason}</p>
                          ) : null}
                          {check ? (
                            <p className="mt-1 text-xs text-gray-700">
                              {check.message} {" "}
                              <Link href={check.action_route as SafeActionRoute} className="text-indigo-600 hover:underline">
                                {check.recommended_action}
                              </Link>
                            </p>
                          ) : null}
                        </div>

                        <div className="flex flex-wrap gap-2">
                          {canAcknowledge ? (
                            <button
                              type="button"
                              className="rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
                              onClick={() => {
                                if (!window.confirm("Acknowledge this step? This does not override computed blockers.")) return;
                                const note = window.prompt("Optional acknowledgement note (leave blank for none):", "") || undefined;
                                void runMutation(`ack-${stepKey}`, async () => {
                                  await acknowledgeOnboardingStep(stepKey, note);
                                  await refreshOverviewAndReadiness();
                                });
                              }}
                              disabled={submittingAction !== null}
                            >
                              Acknowledge
                            </button>
                          ) : null}

                          {canSkip ? (
                            <button
                              type="button"
                              className="rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
                              onClick={() => {
                                if (!window.confirm("Skip this optional step? Skipped steps remain in onboarding history.")) return;
                                const reason = window.prompt("Reason for skipping (required):", "") || "";
                                if (!reason.trim()) {
                                  setMutationError("Skip reason is required.");
                                  return;
                                }
                                void runMutation(`skip-${stepKey}`, async () => {
                                  await skipOnboardingStep(stepKey, reason.trim());
                                  await refreshOverviewAndReadiness();
                                });
                              }}
                              disabled={submittingAction !== null}
                            >
                              Skip
                            </button>
                          ) : null}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          ))}
        </section>
      ) : null}

      {activeTab === "Readiness Review" ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Readiness Review</h2>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Readiness</p>
                <p className="text-xl font-semibold">{readiness?.readiness_percentage ?? 0}%</p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Blockers</p>
                <p className="text-xl font-semibold">{readiness?.blocker_count ?? 0}</p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Warnings</p>
                <p className="text-xl font-semibold">{readiness?.warning_count ?? 0}</p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Informational</p>
                <p className="text-xl font-semibold">{readiness?.informational_count ?? 0}</p>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Readiness filters">
              {(["all", "blocking", "warning", "informational", "complete"] as ReadinessFilter[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-md px-3 py-1.5 text-sm ${readinessFilter === value ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-700"}`}
                  onClick={() => setReadinessFilter(value)}
                >
                  {value}
                </button>
              ))}
            </div>

            <div className="mt-4 space-y-2">
              {filteredChecks.map((check) => (
                <article key={check.check_key} className="rounded-lg border border-gray-200 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium">{check.title}</p>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(check.status)}`}>{check.status}</span>
                  </div>
                  <p className="mt-1 text-sm text-gray-600">{check.message}</p>
                  <p className="mt-1 text-xs text-gray-600">Current: {String(check.current_value)} | Required: {String(check.required_value)}</p>
                  <p className="mt-1 text-xs text-gray-600">Evidence: {check.evidence_source}</p>
                  <Link href={check.action_route} className="mt-1 inline-block text-xs text-indigo-600 hover:underline">
                    {check.recommended_action}
                  </Link>
                </article>
              ))}
            </div>

            <div className="mt-4 rounded-lg border border-gray-200 p-3">
              <p className="font-medium">Recommended next actions</p>
              <ul className="mt-2 space-y-1 text-sm text-gray-700">
                {(readiness?.recommended_next_actions || []).map((item) => (
                  <li key={item.check_key}>
                    {STEP_LABELS[item.step_key] || item.step_key}: {item.message} ({item.action_route})
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "History" ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">History</h2>
            {history.length === 0 ? <p className="mt-2 text-sm text-gray-600">No onboarding runs yet.</p> : null}
            <div className="mt-3 space-y-2">
              {history.map((item) => (
                <article key={item.run_id} className="rounded-lg border border-gray-200 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium">Run {shortRef(item.run_id)}</p>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(item.status)}`}>{item.status}</span>
                  </div>
                  <p className="mt-1 text-xs text-gray-600">Started: {formatDate(item.started_at)} by {shortRef(item.started_by_user_id)}</p>
                  <p className="text-xs text-gray-600">Completed/Cancelled: {formatDate(item.completed_at)} by {shortRef(item.completed_by_user_id)}</p>
                  <p className="text-xs text-gray-600">Completion: {item.completion_percentage}% | Blockers: {item.blocker_count} | Warnings: {item.warning_count}</p>
                </article>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-400"
                disabled={historyPage <= 1}
                onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
              >
                Previous
              </button>
              <p className="text-sm text-gray-600">Page {historyPage} of {Math.max(1, Math.ceil(historyTotal / historyPageSize))}</p>
              <button
                type="button"
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-400"
                disabled={historyPage >= Math.max(1, Math.ceil(historyTotal / historyPageSize))}
                onClick={() => setHistoryPage((page) => page + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <RoleGuard
      allowedRoles={["principal", "school_admin"]}
      forbiddenMessage="Only school leadership can access School Setup."
    >
      <OnboardingWorkspace />
    </RoleGuard>
  );
}
