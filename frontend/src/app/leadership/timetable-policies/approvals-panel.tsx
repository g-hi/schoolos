export interface ApprovalItem {
  rank?: number;
  type?: string;
  title?: string;
  summary?: string;
  urgency?: string;
  setup_step?: string;
  responsible_roles?: string[];
  required_action?: string;
  target_route?: string;
  blocker_relationship?: string;
  created_at?: string;
}

function urgencyTone(urgency: string): string {
  if (urgency === "critical") return "bg-rose-100 text-rose-800";
  if (urgency === "high") return "bg-amber-100 text-amber-800";
  if (urgency === "medium") return "bg-sky-100 text-sky-800";
  return "bg-slate-100 text-slate-700";
}

export default function ApprovalsPanel({ items }: { items: ApprovalItem[] }) {
  if (!items.length) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">No exception requests require review.</p>;
  }

  return (
    <div className="space-y-3">
      {items.map((item, idx) => (
        <article key={`${item.type || "approval"}-${idx}`} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-900">{item.title || item.type || "Approval item"}</h3>
            <span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${urgencyTone(item.urgency || "low")}`}>{item.urgency || "low"}</span>
          </div>
          <p className="mt-1 text-sm text-slate-700">{item.summary || item.required_action || "Review this item through its controlled lifecycle route."}</p>
          <div className="mt-2 grid gap-1 text-xs text-slate-500 sm:grid-cols-2">
            <span>Type: {item.type || "-"}</span>
            <span>Step: {item.setup_step || "approvals_and_readiness"}</span>
            <span>Roles: {(item.responsible_roles || []).join(", ") || "principal, school_admin"}</span>
            <span>Route: {item.target_route || "/leadership/timetable-policies/readiness"}</span>
          </div>
        </article>
      ))}
    </div>
  );
}
