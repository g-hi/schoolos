import type { PolicyConstraint } from "@/lib/timetable-policies-api";

function actionAllowed(item: PolicyConstraint, action: "submit" | "approve" | "activate" | "suspend" | "retire"): boolean {
  if (action === "submit") return item.lifecycle_status === "draft";
  if (action === "approve") return item.lifecycle_status === "pending_review";
  if (action === "activate") return item.lifecycle_status === "approved" || item.lifecycle_status === "suspended";
  if (action === "suspend") return item.lifecycle_status === "active";
  if (action === "retire") return item.lifecycle_status === "approved" || item.lifecycle_status === "active" || item.lifecycle_status === "suspended";
  return false;
}

function enforcementLabel(level: string): string {
  if (level === "hard") return "Hard rule";
  if (level === "soft") return "Soft rule";
  if (level === "preference") return "Preference";
  return level;
}

export default function ConstraintsPanel({ items, selectedConstraintId, onSelectConstraint, onLifecycleAction }: { items: PolicyConstraint[]; selectedConstraintId: string | null; onSelectConstraint: (constraintId: string) => void; onLifecycleAction: (constraint: PolicyConstraint, action: "submit" | "approve" | "activate" | "suspend" | "retire") => void }) {
  if (!items.length) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">No constraints exist for the selected policy set.</p>;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <article key={item.id} className={`rounded-xl border p-4 ${selectedConstraintId === item.id ? "border-indigo-300 bg-indigo-50/30" : "border-slate-200 bg-white"}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-900">{item.constraint_type}</h3>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{enforcementLabel(item.enforcement_level)}</span>
              <button type="button" onClick={() => onSelectConstraint(item.id)} className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700">Inspect</button>
            </div>
          </div>
          <p className="mt-1 text-xs text-slate-600">{item.explanation || "No explanation."}</p>
          <div className="mt-2 grid gap-1 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
            <span>Category: {item.category}</span>
            <span>Lifecycle: {item.lifecycle_status}</span>
            <span>Scope: {item.scope_type}</span>
            <span>Target: {item.scope_reference_id || item.scope_reference_code || "-"}</span>
            <span>Priority: {item.priority}</span>
            <span>Weight: {item.weight}</span>
            <span>Source: {item.source_type}</span>
            <span>Approval state: {item.approved_at ? "approved" : "not approved"}</span>
          </div>
          <p className="mt-2 text-xs text-slate-500">Parameters: {JSON.stringify(item.parameters)}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <LifecycleButton enabled={actionAllowed(item, "submit")} label="Submit" onClick={() => onLifecycleAction(item, "submit")} />
            <LifecycleButton enabled={actionAllowed(item, "approve")} label="Approve" onClick={() => onLifecycleAction(item, "approve")} />
            <LifecycleButton enabled={actionAllowed(item, "activate")} label="Activate" onClick={() => onLifecycleAction(item, "activate")} />
            <LifecycleButton enabled={actionAllowed(item, "suspend")} label="Suspend" onClick={() => onLifecycleAction(item, "suspend")} />
            <LifecycleButton enabled={actionAllowed(item, "retire")} label="Retire" onClick={() => onLifecycleAction(item, "retire")} />
          </div>
        </article>
      ))}
    </div>
  );
}

function LifecycleButton({ enabled, label, onClick }: { enabled: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" disabled={!enabled} onClick={onClick} className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-40">
      {label}
    </button>
  );
}
