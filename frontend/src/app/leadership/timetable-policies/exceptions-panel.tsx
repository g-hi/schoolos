import type { PolicyException } from "@/lib/timetable-policies-api";

function can(action: "submit" | "approve" | "reject" | "revoke", state: string): boolean {
  if (action === "submit") return state === "draft";
  if (action === "approve" || action === "reject") return state === "pending_review";
  if (action === "revoke") return state === "approved";
  return false;
}

export default function ExceptionsPanel({ items, onAction }: { items: PolicyException[]; onAction: (item: PolicyException, action: "submit" | "approve" | "reject" | "revoke") => void }) {
  if (!items.length) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">No exception requests are currently recorded.</p>;
  }

  return (
    <div className="space-y-3">
      <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Exceptions relax only their explicit target. Pending or expired exceptions do not alter operational enforcement.</p>
      {items.map((item) => (
        <article key={item.id} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-900">Exception {item.id.slice(0, 8)}</h3>
            <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{item.approval_state}</span>
          </div>
          <p className="mt-1 text-sm text-slate-700">{item.reason}</p>
          <div className="mt-2 grid gap-1 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
            <span>Target policy: {item.policy_set_id || "-"}</span>
            <span>Target constraint: {item.constraint_id || "-"}</span>
            <span>Scope: {item.scope_type}</span>
            <span>Scope target: {item.scope_reference_id || item.scope_reference_code || "-"}</span>
            <span>Requested by: {item.requested_by_user_id || "-"}</span>
            <span>Approved by: {item.approved_by_user_id || "-"}</span>
            <span>Expires: {item.expires_at || "-"}</span>
            <span>Active: {item.is_active ? "Yes" : "No"}</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <ActionButton enabled={can("submit", item.approval_state)} label="Submit" onClick={() => onAction(item, "submit")} />
            <ActionButton enabled={can("approve", item.approval_state)} label="Approve" onClick={() => onAction(item, "approve")} />
            <ActionButton enabled={can("reject", item.approval_state)} label="Reject" onClick={() => onAction(item, "reject")} />
            <ActionButton enabled={can("revoke", item.approval_state)} label="Revoke" onClick={() => onAction(item, "revoke")} />
          </div>
        </article>
      ))}
    </div>
  );
}

function ActionButton({ enabled, label, onClick }: { enabled: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" disabled={!enabled} onClick={onClick} className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-40">
      {label}
    </button>
  );
}
