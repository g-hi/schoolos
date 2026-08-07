import type { AuthorizationPayload, EffectiveConstraintsPayload, ReadinessSummaryPayload } from "@/lib/timetable-policies-api";

export default function ReadinessPanel({ readiness, effectiveConstraints, authorization }: { readiness: ReadinessSummaryPayload | null; effectiveConstraints: EffectiveConstraintsPayload | null; authorization: AuthorizationPayload | null }) {
  if (!readiness || !effectiveConstraints || !authorization) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">Readiness data is unavailable for the current scope.</p>;
  }

  const coverage = effectiveConstraints.coverage as Record<string, unknown>;
  const score = effectiveConstraints.policy_score as Record<string, unknown>;

  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Scheduling authorization logic</h3>
        <p className="mt-2 text-sm text-slate-700">Canonical Input Ready AND Policy Ready AND Diagnostics Ready = Scheduling Authorized</p>
        <p className="mt-1 text-xs text-slate-500">Score does not override blockers.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Cell label="Readiness status" value={authorization.readiness_status} />
        <Cell label="Generation allowed" value={authorization.generation_allowed ? "Yes" : "No"} />
        <Cell label="Overall policy score" value={String(authorization.overall_policy_score)} />
        <Cell label="Effective constraints" value={String(effectiveConstraints.effective_constraint_count)} />
        <Cell label="Coverage percentage" value={String((coverage.coverage_percentage as number | undefined) ?? "-")} />
        <Cell label="Applicable weight" value={String((score.applicable_weight as number | undefined) ?? "-")} />
        <Cell label="Completed weight" value={String((score.completed_weight as number | undefined) ?? "-")} />
        <Cell label="Excluded not-applicable weight" value={String((score.excluded_not_applicable_weight as number | undefined) ?? "-")} />
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Required actions</h3>
        {authorization.required_actions.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">No required policy actions are currently returned.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            {authorization.required_actions.map((item, index) => (
              <li key={`required-${index}`} className="rounded-lg border border-slate-100 p-3">
                <p className="font-medium">{String(item.action || "Review readiness issue")}</p>
                <p className="mt-1 text-xs text-slate-500">Expected impact: {String(item.expected_readiness_impact || "Improves readiness.")}</p>
                <p className="text-xs text-slate-500">Required role: {String(item.required_role || "principal")}</p>
                <p className="text-xs text-slate-500">Target route: {String(item.target_route || "/leadership/timetable-policies/readiness")}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Effective policy and constraints</h3>
        <p className="mt-2 text-sm text-slate-700">Selected policy set: {readiness.policy_set_id || "None"}</p>
        <p className="text-sm text-slate-700">Policy lifecycle: {readiness.policy_set_status || "not configured"}</p>
        <p className="mt-2 text-xs text-slate-500">A soft rule cannot silently weaken a hard rule. Equal-priority contradictions remain blockers.</p>
      </section>
    </section>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}
