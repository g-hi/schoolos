import type { PolicyDiagnosticsPayload } from "@/lib/timetable-policies-api";

export default function DiagnosticsPanel({ diagnostics, onRun }: { diagnostics: PolicyDiagnosticsPayload | null; onRun: () => void }) {
  if (!diagnostics) {
    return (
      <section className="space-y-3">
        <button type="button" onClick={onRun} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800">
          Run Policy Diagnostics
        </button>
        <p className="text-sm text-slate-600">Diagnostics are deterministic and read-only. No canonical records are modified.</p>
      </section>
    );
  }

  const conflicts = diagnostics.conflicts || [];
  const feasibility = diagnostics.feasibility || [];
  const impact = diagnostics.impact || [];
  const guidance = diagnostics.resolution_guidance || [];

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={onRun} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800">
          Run Policy Diagnostics
        </button>
        <p className="text-xs text-slate-500">Deterministic evidence only. No approvals or activations are performed.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Mini title="Blockers" value={String((diagnostics.summary.blocker_count as number | undefined) ?? 0)} />
        <Mini title="Warnings" value={String((diagnostics.summary.warning_count as number | undefined) ?? 0)} />
        <Mini title="Information" value={String((diagnostics.summary.information_count as number | undefined) ?? 0)} />
        <Mini title="Impossible" value={String((diagnostics.summary.impossible_count as number | undefined) ?? 0)} />
      </div>

      <IssueList title="Conflicts" items={conflicts} />
      <IssueList title="Feasibility" items={feasibility} />
      <IssueList title="Impact" items={impact} />

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Resolution options</h3>
        {!guidance.length ? (
          <p className="mt-2 text-sm text-slate-600">No resolution guidance is currently returned.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            {guidance.map((item, index) => (
              <li key={`guide-${index}`} className="rounded-lg border border-slate-100 p-3">
                <p className="font-medium">Recommended review action</p>
                <p>{String(item["recommended_action"] || item["summary"] || "Review deterministic conflict evidence.")}</p>
                <p className="mt-1 text-xs text-slate-500">Deterministic evidence: {String(item["explanation"] || "Not provided")}</p>
                <p className="text-xs text-slate-500">Requires human decision: yes</p>
                <p className="text-xs text-slate-500">May improve feasibility: yes</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}

function Mini({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{title}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function IssueList({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {!items.length ? (
        <p className="mt-2 text-sm text-slate-600">No policy conflicts were detected.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="rounded-lg border border-slate-100 p-3 text-sm text-slate-700">
              <p className="font-medium">{String(item.title || item.summary || item.diagnostic_key || "Diagnostic issue")}</p>
              <p className="mt-1">{String(item.explanation || item.summary || "Deterministic evidence available in payload.")}</p>
              <p className="mt-1 text-xs text-slate-500">Severity: {String(item.severity || "unknown")}</p>
              <p className="text-xs text-slate-500">Feasibility impact: {String(item.feasibility_impact || item.impact || "unknown")}</p>
              <p className="text-xs text-slate-500">Target route: {String(item.setup_route || "/leadership/timetable-policies/diagnostics")}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
