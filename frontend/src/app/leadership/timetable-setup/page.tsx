"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import RoleGuard from "@/components/auth/role-guard";
import StatCard from "@/components/stat-card";
import { useAuth } from "@/components/auth/auth-provider";
import {
  getSetupCentreActivity,
  getSetupCentreApprovals,
  getSetupCentreIssues,
  getSetupCentreRecommendations,
  getSetupCentreStep,
  getSetupCentreSteps,
  getSetupCentreSummary,
  revalidateSetupCentre,
  TimetableSetupCentreApiError,
  type SetupCentreActivityItem,
  type SetupCentreApprovalQueueItem,
  type SetupCentreIssue,
  type SetupCentreRecommendation,
  type SetupCentreStep,
  type SetupCentreSummary,
} from "@/lib/timetable-setup-centre-api";
import { toFriendlyError } from "@/app/leadership/calendar/calendar-utils";

type TabKey = "overview" | "steps" | "issues" | "approvals" | "imports" | "activity";

const TAB_LABELS: Record<TabKey, string> = {
  overview: "Overview",
  steps: "Setup Steps",
  issues: "Issues",
  approvals: "Approvals",
  imports: "Imports",
  activity: "Activity",
};

const TAB_ORDER: TabKey[] = ["overview", "steps", "issues", "approvals", "imports", "activity"];

function parseTab(value: string | null): TabKey {
  if (value && TAB_ORDER.includes(value as TabKey)) {
    return value as TabKey;
  }
  return "overview";
}

function apiErrorMessage(error: unknown): string {
  if (error instanceof TimetableSetupCentreApiError) {
    return error.message;
  }
  return toFriendlyError(error);
}

function toneForGeneration(status: string, allowed: boolean): string {
  if (allowed) return "bg-emerald-50 text-emerald-800 border-emerald-200";
  if (status === "blocked") return "bg-rose-50 text-rose-800 border-rose-200";
  if (status === "awaiting_human_approval") return "bg-amber-50 text-amber-800 border-amber-200";
  if (status === "conditionally_ready") return "bg-blue-50 text-blue-800 border-blue-200";
  return "bg-gray-50 text-gray-800 border-gray-200";
}

function toneForStep(status: string): string {
  switch (status) {
    case "complete":
    case "completed":
      return "bg-emerald-50 text-emerald-800 border-emerald-200";
    case "blocked":
      return "bg-rose-50 text-rose-800 border-rose-200";
    case "needs_review":
    case "in_review":
      return "bg-amber-50 text-amber-800 border-amber-200";
    case "ready":
    case "conditionally_ready":
      return "bg-blue-50 text-blue-800 border-blue-200";
    case "not_applicable":
      return "bg-gray-100 text-gray-600 border-gray-200";
    default:
      return "bg-slate-50 text-slate-700 border-slate-200";
  }
}

function toneForSeverity(severity: string): string {
  switch (severity) {
    case "blocker":
      return "bg-rose-100 text-rose-800";
    case "warning":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function toneForUrgency(urgency: string): string {
  switch (urgency) {
    case "critical":
      return "bg-rose-100 text-rose-800";
    case "high":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function ToneBadge({ children, className }: { children: React.ReactNode; className: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${className}`}>{children}</span>;
}

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function StatusLine({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 last:border-0">
      <span className="text-sm text-slate-600">{label}</span>
      <span className="text-sm font-medium text-slate-900 text-right">{value ?? "—"}</span>
    </div>
  );
}

function BreadcrumbLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-sm font-medium text-indigo-700 hover:underline">
      {children}
    </Link>
  );
}

export default function TimetableSetupCentrePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isHydrating, isAuthenticated, user } = useAuth();

  const [activeTab, setActiveTab] = useState<TabKey>(() => parseTab(searchParams.get("tab")));
  const [summary, setSummary] = useState<SetupCentreSummary | null>(null);
  const [steps, setSteps] = useState<SetupCentreStep[]>([]);
  const [stepDetail, setStepDetail] = useState<SetupCentreStep | null>(null);
  const [stepDetailIssues, setStepDetailIssues] = useState<SetupCentreIssue[]>([]);
  const [issues, setIssues] = useState<SetupCentreIssue[]>([]);
  const [approvals, setApprovals] = useState<SetupCentreApprovalQueueItem[]>([]);
  const [activity, setActivity] = useState<SetupCentreActivityItem[]>([]);
  const [recommendations, setRecommendations] = useState<SetupCentreRecommendation[]>([]);
  const [selectedStepKey, setSelectedStepKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [issueSeverity, setIssueSeverity] = useState("");
  const [issueStep, setIssueStep] = useState("");
  const [issueSource, setIssueSource] = useState("");
  const [issueResolved, setIssueResolved] = useState("");
  const [issueRequiresApproval, setIssueRequiresApproval] = useState("");
  const [approvalType, setApprovalType] = useState("");
  const [approvalUrgency, setApprovalUrgency] = useState("");
  const [approvalStep, setApprovalStep] = useState("");
  const [activityAction, setActivityAction] = useState("");
  const [activityEntity, setActivityEntity] = useState("");
  const [activityFrom, setActivityFrom] = useState("");
  const [activityTo, setActivityTo] = useState("");
  const [issuesPage, setIssuesPage] = useState(1);
  const [approvalsPage, setApprovalsPage] = useState(1);
  const [activityPage, setActivityPage] = useState(1);
  const [revalidating, setRevalidating] = useState(false);
  const [revalidateError, setRevalidateError] = useState<string | null>(null);
  const [revalidateNotice, setRevalidateNotice] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const pageHeading = "Timetable Setup Centre";
  const hasLeadershipAccess = Boolean(isAuthenticated && user && user.is_active && (user.role === "principal" || user.role === "school_admin"));

  useEffect(() => {
    if (isHydrating || !isAuthenticated) return;
    if (!user || !user.is_active || !(user.role === "principal" || user.role === "school_admin")) {
      return;
    }

    let alive = true;
    setLoading(true);
    setPageError(null);

    Promise.all([
      getSetupCentreSummary(),
      getSetupCentreSteps(),
      getSetupCentreIssues({ page: issuesPage, page_size: 12, severity: issueSeverity || undefined, setup_step: issueStep || undefined, source: issueSource || undefined, resolved: issueResolved === "true" ? true : issueResolved === "false" ? false : undefined, requires_approval: issueRequiresApproval === "true" ? true : issueRequiresApproval === "false" ? false : undefined }),
      getSetupCentreApprovals({ page: approvalsPage, page_size: 12, type: approvalType || undefined, urgency: approvalUrgency || undefined, setup_step: approvalStep || undefined }),
      getSetupCentreActivity({ page: activityPage, page_size: 12, action_type: activityAction || undefined, entity_type: activityEntity || undefined, start_date: activityFrom || undefined, end_date: activityTo || undefined }),
      getSetupCentreRecommendations(),
    ])
      .then(([summaryResponse, stepsResponse, issuesResponse, approvalsResponse, activityResponse, recommendationsResponse]) => {
        if (!alive) return;
        setSummary(summaryResponse);
        setSteps(stepsResponse.steps);
        setIssues(issuesResponse.items);
        setApprovals(approvalsResponse.items);
        setActivity(activityResponse.items);
        setRecommendations(recommendationsResponse.recommendations);
      })
      .catch((error) => {
        if (alive) {
          setPageError(apiErrorMessage(error));
        }
      })
      .finally(() => {
        if (alive) {
          setLoading(false);
        }
      });

    return () => {
      alive = false;
    };
  }, [isHydrating, isAuthenticated, user, issuesPage, issueSeverity, issueStep, issueSource, issueResolved, issueRequiresApproval, approvalsPage, approvalType, approvalUrgency, approvalStep, activityPage, activityAction, activityEntity, activityFrom, activityTo]);

  useEffect(() => {
    if (selectedStepKey) {
      void getSetupCentreStep(selectedStepKey)
        .then((detail) => {
          setStepDetail(detail.step);
          setStepDetailIssues(detail.related_issues);
        })
        .catch((error) => setPageError(apiErrorMessage(error)));
    }
  }, [selectedStepKey]);

  const updateTab = (tab: TabKey) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    router.replace(url.pathname + url.search);
  };

  const handleRevalidate = async () => {
    const confirmed = window.confirm("Revalidate setup? This recalculates readiness only and does not modify canonical records, approve imports, commit imports, publish events, or generate a timetable.");
    if (!confirmed) return;
    setRevalidating(true);
    setRevalidateError(null);
    try {
      const result = await revalidateSetupCentre();
      setSummary((current) => current ? { ...current, generated_at: result.generated_at, generation: result.generation, progress: result.progress } : current);
      setRevalidateNotice("Setup readiness recalculated. Canonical records were unchanged.");
    } catch (error) {
      setRevalidateError(apiErrorMessage(error));
    } finally {
      setRevalidating(false);
    }
  };

  if (!isHydrating && !hasLeadershipAccess) {
    return (
      <RoleGuard allowedRoles={["principal", "school_admin"]} forbiddenMessage="Permission denied. Leadership access is required for this route.">
        <div />
      </RoleGuard>
    );
  }

  if (isHydrating || loading) {
    return <p className="text-sm text-slate-600">Loading timetable setup centre...</p>;
  }

  if (pageError) {
    return (
      <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-rose-800" role="alert">
        <h1 className="text-lg font-semibold">{pageHeading}</h1>
        <p className="mt-2 text-sm">{pageError}</p>
        <button type="button" onClick={() => router.refresh()} className="mt-4 rounded-lg bg-white px-3 py-2 text-sm font-medium text-rose-800 border border-rose-200">
          Retry
        </button>
      </section>
    );
  }

  if (!summary) return null;

  const generation = summary.generation;
  const readyMessage = generation.generation_allowed
    ? "Setup validation is complete. The school is ready to proceed to timetable generation in the next phase."
    : generation.readiness_status === "blocked"
      ? "Timetable generation is currently blocked. Resolve the required issues below."
      : generation.readiness_status === "awaiting_human_approval"
        ? "Configuration is substantially complete, but human review is still required."
        : "Setup is progressing, but readiness still has outstanding conditions.";

  return (
    <RoleGuard allowedRoles={["principal", "school_admin"]} forbiddenMessage="Permission denied. Leadership access is required for this route.">
      <div className="space-y-6">
        <header className="rounded-3xl border border-slate-200 bg-linear-to-br from-slate-950 via-slate-900 to-indigo-950 p-6 text-white shadow-lg">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <div className="flex flex-wrap gap-2 text-xs text-slate-200">
                <BreadcrumbLink href="/leadership/calendar">Academic Calendar</BreadcrumbLink>
                <span>•</span>
                <BreadcrumbLink href="/leadership/timetable-setup">Timetable Setup</BreadcrumbLink>
              </div>
              <h1 className="text-3xl font-bold tracking-tight">{pageHeading}</h1>
              <p className="max-w-3xl text-sm text-slate-200">
                Deterministic readiness, human approval boundaries, import status, provenance, and correction links in one leadership workspace.
              </p>
              <p className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${toneForGeneration(generation.readiness_status, generation.generation_allowed)}`}>
                {readyMessage}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <StatCard title="Setup %" value={`${summary.progress.progress_percentage}%`} subtitle={`${summary.progress.completed_weight}/${summary.progress.total_weight} applicable weight`} color="indigo" />
              <StatCard title="Readiness" value={generation.readiness_status.replaceAll("_", " ")} subtitle={`generation_allowed: ${generation.generation_allowed ? "true" : "false"}`} color={generation.generation_allowed ? "green" : "amber"} />
              <StatCard title="Pending approvals" value={generation.pending_approval_count} subtitle={`Blockers: ${generation.blocker_count}`} color={generation.blocker_count > 0 ? "red" : "gray"} />
            </div>
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard title="Blockers" value={generation.blocker_count} color="red" />
            <StatCard title="Warnings" value={generation.warning_count} color="amber" />
            <StatCard title="Information" value={generation.information_count} color="gray" />
            <StatCard title="Last calculated" value={new Date(summary.generated_at).toLocaleString()} color="indigo" />
          </div>
          <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="Timetable setup sections">
            {TAB_ORDER.map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => updateTab(tab)}
                className={`rounded-full px-4 py-2 text-sm font-medium transition ${activeTab === tab ? "bg-white text-slate-900" : "bg-white/10 text-slate-200 hover:bg-white/20"}`}
                role="tab"
                aria-selected={activeTab === tab}
                aria-controls={`timetable-setup-panel-${tab}`}
                id={`timetable-setup-tab-${tab}`}
              >
                {TAB_LABELS[tab]}
              </button>
            ))}
          </div>
        </header>

        <SectionCard
          title="Progress calculation"
          action={<button type="button" disabled={revalidating} onClick={handleRevalidate} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-indigo-300">{revalidating ? "Revalidating..." : "Revalidate Setup"}</button>}
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-700">Readiness percentage does not override hard blockers.</p>
            <div className="h-3 rounded-full bg-slate-100">
              <div className="h-3 rounded-full bg-indigo-600" style={{ width: `${Math.min(100, Math.max(0, summary.progress.progress_percentage))}%` }} />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <StatusLine label="Completed applicable weight" value={summary.progress.completed_weight} />
                <StatusLine label="Total applicable weight" value={summary.progress.total_weight} />
                <StatusLine label="Completed applicable steps" value={summary.progress.completed_steps} />
              </div>
              <div>
                <StatusLine label="Excluded not-applicable weight" value={summary.progress.excluded_weight ?? 0} />
                <StatusLine label="Applicable steps" value={summary.progress.total_steps} />
                <StatusLine label="Calculation explanation" value={summary.progress.explanation || summary.progress_explanation || "—"} />
              </div>
            </div>
          </div>
        </SectionCard>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
          <SectionCard title="Generation readiness">
            <div className="space-y-3">
              <StatusLine label="generation_allowed" value={generation.generation_allowed ? "true" : "false"} />
              <StatusLine label="readiness_status" value={generation.readiness_status} />
              <StatusLine label="blocker_count" value={generation.blocker_count} />
              <StatusLine label="pending mandatory approvals" value={generation.pending_approval_count} />
              <StatusLine label="policy explanation" value={generation.generation_allowed ? "No hard blockers remain." : "Hard blockers or required human approvals remain."} />
              <StatusLine label="required actions" value={generation.required_actions.length === 0 ? "None" : `${generation.required_actions.length} action(s)`} />
            </div>
            {!generation.generation_allowed ? (
              <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                Generation is blocked because required blockers or approvals are still present.
              </p>
            ) : null}
          </SectionCard>

          <SectionCard title="Recommended next actions">
            <div className="space-y-3">
              {recommendations.slice(0, 4).map((item, index) => (
                <article key={item.recommendation_key} className="rounded-xl border border-slate-200 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Rank {index + 1}</p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-900">{item.title}</h3>
                  <p className="mt-1 text-sm text-slate-600">{item.why}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <ToneBadge className={toneForSeverity(item.requires_human_authorization ? "warning" : "information")}>{item.requires_human_authorization ? "Requires human action" : "Deterministic evidence"}</ToneBadge>
                    <ToneBadge className={toneForSeverity(item.requires_human_authorization ? "warning" : "information")}>Agent recommendation</ToneBadge>
                  </div>
                  <div className="mt-2 text-xs text-slate-600">Route: {item.setup_route}</div>
                </article>
              ))}
            </div>
          </SectionCard>
        </div>

        {activeTab === "overview" ? (
          <div className="grid gap-6 lg:grid-cols-2" id="timetable-setup-panel-overview" role="tabpanel" aria-labelledby="timetable-setup-tab-overview">
            <SectionCard title="Provenance summary">
              <StatusLine label="Manual records" value={summary.provenance.manual_count} />
              <StatusLine label="Excel imports" value={summary.provenance.excel_import_count} />
              <StatusLine label="PDF extractions" value={summary.provenance.pdf_extraction_count} />
              <StatusLine label="Agent recommendations" value={summary.provenance.agent_recommendation_count} />
              <StatusLine label="System generated" value={summary.provenance.system_generated_count} />
              <StatusLine label="Inactive records" value={summary.provenance.inactive_count} />
            </SectionCard>
            <SectionCard title="Import summaries">
              <StatusLine label="Workbook pending" value={summary.import_summaries.workbook.pending_count} />
              <StatusLine label="Workbook unresolved mapping" value={summary.import_summaries.workbook.unresolved_mapping_count} />
              <StatusLine label="Workbook committed" value={summary.import_summaries.workbook.committed_count} />
              <StatusLine label="PDF pending" value={summary.import_summaries.pdf.pending_count} />
              <StatusLine label="PDF review count" value={summary.import_summaries.pdf.review_count} />
              <StatusLine label="PDF committed" value={summary.import_summaries.pdf.committed_count} />
            </SectionCard>
          </div>
        ) : null}

        {activeTab === "steps" ? (
          <SectionCard title="Setup steps">
            <div className="grid gap-4 xl:grid-cols-2">
              {steps.map((step) => (
                <button key={step.step_key} type="button" onClick={() => setSelectedStepKey(step.step_key)} className="rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300 hover:shadow-md">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-base font-semibold text-slate-900">{step.title}</h3>
                      <p className="mt-1 text-sm text-slate-600">{step.route}</p>
                    </div>
                    <ToneBadge className={toneForStep(step.status)}>{step.status.replaceAll("_", " ")}</ToneBadge>
                  </div>
                  <div className="mt-3 grid gap-2 text-sm">
                    <StatusLine label="Completion percentage" value={step.status === "not_applicable" ? "N/A" : `${step.approved_count}/${Math.max(step.required_minimum, 1)}`} />
                    <StatusLine label="Blocker count" value={step.status === "blocked" ? 1 : 0} />
                    <StatusLine label="Warning count" value={step.pending_count > 0 ? 1 : 0} />
                    <StatusLine label="Information count" value={step.status === "not_applicable" ? 1 : 0} />
                    <StatusLine label="Pending-review count" value={step.pending_count} />
                    <StatusLine label="Record count" value={step.approved_count + step.pending_count} />
                    <StatusLine label="Approved-record count" value={step.approved_count} />
                    <StatusLine label="Source breakdown" value={Object.entries(step.source_summary).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"} />
                    <StatusLine label="Review-state summary" value={Object.entries(step.review_summary).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"} />
                    <StatusLine label="Last updated" value={summary.generated_at} />
                    <StatusLine label="Recommended next action" value={step.status === "blocked" ? "Resolve prerequisites" : "Continue setup"} />
                    <StatusLine label="Responsible roles" value={step.authorized_roles.join(", ")} />
                    <StatusLine label="Prerequisites" value={step.prerequisites.length ? step.prerequisites.join(", ") : "None"} />
                    <StatusLine label="Policy explanation" value={step.policy_rule} />
                    <StatusLine label="Direct route" value={step.route} />
                  </div>
                </button>
              ))}
            </div>
            {stepDetail ? (
              <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <h3 className="text-base font-semibold text-slate-900">Step detail: {stepDetail.title}</h3>
                <div className="mt-3 grid gap-2 text-sm">
                  <StatusLine label="Step status" value={stepDetail.status} />
                  <StatusLine label="Step route" value={stepDetail.route} />
                  <StatusLine label="Source summary" value={Object.entries(stepDetail.source_summary).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"} />
                  <StatusLine label="Review summary" value={Object.entries(stepDetail.review_summary).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"} />
                  <StatusLine label="Lifecycle summary" value={Object.entries(stepDetail.lifecycle_summary).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <BreadcrumbLink href={stepDetail.route}>Open correction workflow</BreadcrumbLink>
                </div>
                {stepDetailIssues.length ? <p className="mt-3 text-sm text-slate-600">Related issues: {stepDetailIssues.length}</p> : null}
              </div>
            ) : null}
          </SectionCard>
        ) : null}

        {activeTab === "issues" ? (
          <SectionCard title="Issues">
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
              <select aria-label="Filter by severity" value={issueSeverity} onChange={(event) => { setIssueSeverity(event.target.value); setIssuesPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="">All severities</option>
                <option value="blocker">Blocker</option>
                <option value="warning">Warning</option>
                <option value="information">Information</option>
              </select>
              <input aria-label="Filter by setup step" value={issueStep} onChange={(event) => { setIssueStep(event.target.value); setIssuesPage(1); }} placeholder="Setup step" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <input aria-label="Filter by source" value={issueSource} onChange={(event) => { setIssueSource(event.target.value); setIssuesPage(1); }} placeholder="Source" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <select aria-label="Resolved state" value={issueResolved} onChange={(event) => { setIssueResolved(event.target.value); setIssuesPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="">All states</option>
                <option value="true">Resolved</option>
                <option value="false">Unresolved</option>
              </select>
              <select aria-label="Requires approval" value={issueRequiresApproval} onChange={(event) => { setIssueRequiresApproval(event.target.value); setIssuesPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="">All approval states</option>
                <option value="true">Requires approval</option>
                <option value="false">No approval needed</option>
              </select>
              <button type="button" onClick={() => setIssuesPage((current) => current + 1)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Next page</button>
            </div>
            <div className="mt-4 space-y-3">
              {issues.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">No issues match the current filters.</p>
              ) : (
                issues.map((issue) => (
                  <article key={issue.issue_key} className="rounded-2xl border border-slate-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900">{issue.title}</h3>
                        <p className="mt-1 text-sm text-slate-600">{issue.explanation}</p>
                      </div>
                      <ToneBadge className={toneForSeverity(issue.severity)}>{issue.severity}</ToneBadge>
                    </div>
                    <div className="mt-3 grid gap-1 text-sm">
                      <StatusLine label="Setup step" value={issue.step_key} />
                      <StatusLine label="Source" value={issue.source} />
                      <StatusLine label="Affected count" value={issue.affected_count} />
                      <StatusLine label="Responsible role" value={issue.authorized_roles.join(", ")} />
                      <StatusLine label="Recommended action" value={issue.recommended_action} />
                      <StatusLine label="Target route" value={issue.setup_route} />
                      <StatusLine label="Approval requirement" value={issue.requires_human_authorization ? "Requires human approval" : "No approval required"} />
                      <StatusLine label="Policy rule" value={issue.policy_rule} />
                      <StatusLine label="Detected time" value={issue.created_at || "—"} />
                      <StatusLine label="Resolved state" value={issue.resolved ? "Resolved" : "Open"} />
                      <StatusLine label="Provenance" value={issue.related_entity ? `${issue.related_entity.type}` : "—"} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <BreadcrumbLink href={issue.setup_route}>Repair route</BreadcrumbLink>
                      <ToneBadge className={toneForSeverity(issue.severity)}>{issue.severity === "blocker" ? "Blocker" : issue.severity === "warning" ? "Warning" : "Information"}</ToneBadge>
                    </div>
                  </article>
                ))
              )}
            </div>
          </SectionCard>
        ) : null}

        {activeTab === "approvals" ? (
          <SectionCard title="Approvals">
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-4">
              <select aria-label="Approval type" value={approvalType} onChange={(event) => { setApprovalType(event.target.value); setApprovalsPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="">All types</option>
                <option value="calendar_event_pending_approval">Calendar event</option>
                <option value="calendar_candidate_pending_review">Calendar candidate</option>
                <option value="workbook_mappings_requiring_confirmation">Workbook mapping</option>
                <option value="validated_workbook_awaiting_commit">Workbook commit</option>
                <option value="pdf_import_ready_for_controlled_commit">PDF commit</option>
                <option value="notification_plan_pending_approval">Notification plan</option>
            </select>
              <select aria-label="Approval urgency" value={approvalUrgency} onChange={(event) => { setApprovalUrgency(event.target.value); setApprovalsPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="">All urgency</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="normal">Normal</option>
              </select>
              <input aria-label="Approval setup step" value={approvalStep} onChange={(event) => { setApprovalStep(event.target.value); setApprovalsPage(1); }} placeholder="Setup step" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <button type="button" onClick={() => setApprovalsPage((current) => current + 1)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Next page</button>
            </div>
            <div className="mt-4 space-y-3">
              {approvals.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">No pending approvals.</p>
              ) : (
                approvals.map((item) => (
                  <article key={`${item.type || item.approval_key}-${item.title}`} className="rounded-2xl border border-slate-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
                        <p className="mt-1 text-sm text-slate-600">{item.summary}</p>
                      </div>
                      <ToneBadge className={toneForUrgency(item.urgency)}>{item.urgency}</ToneBadge>
                    </div>
                    <div className="mt-3 grid gap-1 text-sm">
                      <StatusLine label="Type" value={item.type || item.approval_key} />
                      <StatusLine label="Setup step" value={item.setup_step} />
                      <StatusLine label="Source" value={item.source} />
                      <StatusLine label="Created time" value={item.created_at} />
                      <StatusLine label="Required approver roles" value={(item.required_approver_roles || item.authorized_roles || []).join(", ")} />
                      <StatusLine label="Recommended action" value={item.recommended_action} />
                      <StatusLine label="Target route" value={item.route || item.setup_route || "—"} />
                      <StatusLine label="Blocker relationship" value={item.blocker_relationship} />
                      <StatusLine label="Approval requirement" value={item.requires_human_authorization ? "Human approval required" : "No approval required"} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <BreadcrumbLink href={item.route || item.setup_route || "/leadership/timetable-setup/centre"}>Open controlled workflow</BreadcrumbLink>
                    </div>
                  </article>
                ))
              )}
            </div>
          </SectionCard>
        ) : null}

        {activeTab === "imports" ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <SectionCard title="Workbook imports">
              <StatusLine label="Uploaded" value={summary.import_summaries.workbook.status_counts.uploaded || 0} />
              <StatusLine label="Parsing" value={summary.import_summaries.workbook.status_counts.parsing || 0} />
              <StatusLine label="Mapping required" value={summary.import_summaries.workbook.status_counts.mapping_required || 0} />
              <StatusLine label="Preview ready" value={summary.import_summaries.workbook.status_counts.preview_ready || 0} />
              <StatusLine label="Validation failed" value={summary.import_summaries.workbook.status_counts.validation_failed || 0} />
              <StatusLine label="Validated" value={summary.import_summaries.workbook.status_counts.validated || 0} />
              <StatusLine label="Committed" value={summary.import_summaries.workbook.status_counts.committed || 0} />
              <StatusLine label="Failed" value={summary.import_summaries.workbook.failed_count} />
              <StatusLine label="Cancelled" value={summary.import_summaries.workbook.status_counts.cancelled || 0} />
              <StatusLine label="Latest import" value={summary.import_summaries.workbook.latest_import?.original_filename || summary.import_summaries.workbook.latest_status || "—"} />
              <StatusLine label="Pending count" value={summary.import_summaries.workbook.pending_count} />
              <StatusLine label="Unresolved mapping count" value={summary.import_summaries.workbook.unresolved_mapping_count} />
              <StatusLine label="Blocker count" value={summary.import_summaries.workbook.blocker_count} />
              <StatusLine label="Review count" value={summary.import_summaries.workbook.review_count} />
              <StatusLine label="Committed count" value={summary.import_summaries.workbook.committed_count} />
              <StatusLine label="Direct route" value={summary.import_summaries.workbook.direct_route} />
              <p className="mt-3 text-sm text-slate-600">Validated imports are not committed until a leadership-controlled workflow executes the commit.</p>
            </SectionCard>
            <SectionCard title="Calendar PDF imports">
              <StatusLine label="Uploaded" value={summary.import_summaries.pdf.status_counts.uploaded || 0} />
              <StatusLine label="Preflighting" value={summary.import_summaries.pdf.pdf_state_counts?.preflighting || 0} />
              <StatusLine label="Extracting" value={summary.import_summaries.pdf.pdf_state_counts?.extracting || 0} />
              <StatusLine label="Extraction failed" value={summary.import_summaries.pdf.pdf_state_counts?.extraction_failed || 0} />
              <StatusLine label="OCR required" value={summary.import_summaries.pdf.status_counts.ocr_required || 0} />
              <StatusLine label="Review ready" value={summary.import_summaries.pdf.status_counts.review_ready || 0} />
              <StatusLine label="Partially reviewed" value={summary.import_summaries.pdf.pdf_state_counts?.partially_reviewed || 0} />
              <StatusLine label="Ready to commit" value={summary.import_summaries.pdf.pdf_state_counts?.ready_to_commit || 0} />
              <StatusLine label="Committed" value={summary.import_summaries.pdf.committed_count} />
              <StatusLine label="Cancelled" value={summary.import_summaries.pdf.status_counts.cancelled || 0} />
              <StatusLine label="Latest import" value={summary.import_summaries.pdf.latest_import?.original_filename || "—"} />
              <StatusLine label="Pending count" value={summary.import_summaries.pdf.pending_count} />
              <StatusLine label="Unresolved mapping count" value={summary.import_summaries.pdf.unresolved_mapping_count} />
              <StatusLine label="Blocker count" value={summary.import_summaries.pdf.blocker_count} />
              <StatusLine label="Review count" value={summary.import_summaries.pdf.review_count} />
              <StatusLine label="Committed count" value={summary.import_summaries.pdf.committed_count} />
              <StatusLine label="Direct route" value={summary.import_summaries.pdf.direct_route} />
              <p className="mt-3 text-sm text-slate-600">Validated and review-ready PDF imports still require authorised commit before they affect operational state.</p>
            </SectionCard>
          </div>
        ) : null}

        {activeTab === "activity" ? (
          <SectionCard title="Recent activity">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              <input aria-label="Filter by action type" value={activityAction} onChange={(event) => { setActivityAction(event.target.value); setActivityPage(1); }} placeholder="Action type" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <input aria-label="Filter by entity type" value={activityEntity} onChange={(event) => { setActivityEntity(event.target.value); setActivityPage(1); }} placeholder="Entity type" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <input aria-label="Start date" type="date" value={activityFrom} onChange={(event) => { setActivityFrom(event.target.value); setActivityPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <input aria-label="End date" type="date" value={activityTo} onChange={(event) => { setActivityTo(event.target.value); setActivityPage(1); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <button type="button" onClick={() => setActivityPage((current) => current + 1)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Next page</button>
            </div>
            <div className="mt-4 space-y-3">
              {activity.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">No recent setup activity.</p>
              ) : (
                activity.map((item) => (
                  <article key={item.id} className="rounded-2xl border border-slate-200 p-4">
                    <div className="grid gap-1 text-sm">
                      <StatusLine label="Action" value={item.action} />
                      <StatusLine label="Entity type" value={item.entity_type} />
                      <StatusLine label="Actor" value={item.actor_id || "—"} />
                      <StatusLine label="Timestamp" value={item.created_at} />
                      <StatusLine label="Source" value={item.detail_summary?.source_type ? String(item.detail_summary.source_type) : "—"} />
                      <StatusLine label="Summary" value={Object.entries(item.detail_summary || {}).map(([key, value]) => `${key}: ${String(value)}`).join(", ") || "—"} />
                    </div>
                  </article>
                ))
              )}
            </div>
          </SectionCard>
        ) : null}

        {revalidateNotice ? <p className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{revalidateNotice}</p> : null}
        {revalidateError ? <p className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{revalidateError}</p> : null}

        {dialogOpen ? null : null}
      </div>
    </RoleGuard>
  );
}