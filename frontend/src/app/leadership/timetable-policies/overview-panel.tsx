import type { AuthorizationPayload, ReadinessSummaryPayload } from "@/lib/timetable-policies-api";

function statusTone(status: string, allowed: boolean): string {
  if (allowed && status === "ready") return "bg-emerald-50 border-emerald-200 text-emerald-900";
  if (status === "blocked") return "bg-rose-50 border-rose-200 text-rose-900";
  if (status === "needs_review") return "bg-amber-50 border-amber-200 text-amber-900";
  if (status === "conditionally_ready") return "bg-sky-50 border-sky-200 text-sky-900";
  return "bg-slate-50 border-slate-200 text-slate-900";
}

function authorizationBanner(status: string): string {
  if (status === "ready") return "Policy and canonical timetable inputs are authorized for the future scheduling phase.";
  if (status === "blocked") return "Scheduling authorization is blocked by mandatory policy or configuration issues.";
  if (status === "needs_review") return "Human review or activation is required before scheduling can proceed.";
  if (status === "conditionally_ready") return "Scheduling is permitted, but quality warnings remain.";
  return "Policy readiness has not been fully evaluated yet.";
}

export default function OverviewPanel({ readiness, authorization }: { readiness: ReadinessSummaryPayload | null; authorization: AuthorizationPayload | null }) {
  if (!readiness || !authorization) {
    return <p className="text-sm text-slate-600">Policy overview is unavailable. Run readiness to evaluate this workspace.</p>;
  }

  const nextAction = authorization.required_actions?.[0] as Record<string, unknown> | undefined;

  return (
    <section className="space-y-4">
      <div className={`rounded-2xl border p-4 ${statusTone(authorization.readiness_status, authorization.generation_allowed)}`}>
        <p className="text-xs font-semibold uppercase tracking-wide">Scheduling authorization</p>
        <p className="mt-1 text-sm">{authorizationBanner(authorization.readiness_status)}</p>
        <p className="mt-2 text-xs">Score does not override blockers.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Readiness Status" value={String(authorization.readiness_status)} />
        <Stat label="Generation Allowed" value={authorization.generation_allowed ? "Yes" : "No"} />
        <Stat label="Policy Score" value={String(authorization.overall_policy_score)} />
        <Stat label="Policy Set Version" value={readiness.policy_set_version ? String(readiness.policy_set_version) : "-"} />
        <Stat label="Policy Blockers" value={String(authorization.policy_blocker_count)} />
        <Stat label="Policy Warnings" value={String(authorization.policy_warning_count)} />
        <Stat label="Pending Approvals" value={String(authorization.policy_pending_approval_count)} />
        <Stat label="Last Evaluated" value={new Date(readiness.generated_at).toLocaleString()} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Recommended next action</h3>
        {nextAction ? (
          <div className="mt-2 space-y-1 text-sm text-slate-700">
            <p>{String(nextAction.action || "Resolve highest-ranked readiness issue.")}</p>
            <p className="text-xs text-slate-500">Requires human decision: {String(nextAction.approval_requirement || "leadership")}</p>
            <p className="text-xs text-slate-500">Target route: {String(nextAction.target_route || "/leadership/timetable-policies/readiness")}</p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-600">No additional action is currently ranked as mandatory.</p>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}
