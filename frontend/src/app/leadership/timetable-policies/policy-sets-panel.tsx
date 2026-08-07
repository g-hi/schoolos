import type { PolicySet } from "@/lib/timetable-policies-api";

interface PolicySetsPanelProps {
  items: PolicySet[];
  selectedPolicySetId: string | null;
  onSelect: (id: string) => void;
  onLifecycleAction: (policySet: PolicySet, action: "submit" | "approve" | "activate" | "suspend" | "retire") => void;
}

function isActionAllowed(item: PolicySet, action: "submit" | "approve" | "activate" | "suspend" | "retire"): boolean {
  if (action === "submit") return item.lifecycle_status === "draft";
  if (action === "approve") return item.lifecycle_status === "pending_review";
  if (action === "activate") return item.lifecycle_status === "approved" || item.lifecycle_status === "suspended";
  if (action === "suspend") return item.lifecycle_status === "active";
  if (action === "retire") return item.lifecycle_status === "approved" || item.lifecycle_status === "active" || item.lifecycle_status === "suspended";
  return false;
}

export default function PolicySetsPanel({ items, selectedPolicySetId, onSelect, onLifecycleAction }: PolicySetsPanelProps) {
  if (!items.length) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">No policy set has been configured.</p>;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const selected = item.id === selectedPolicySetId;
        return (
          <article key={item.id} className={`rounded-xl border p-4 ${selected ? "border-indigo-300 bg-indigo-50/30" : "border-slate-200 bg-white"}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">{item.name}</h3>
                <p className="text-xs text-slate-600">{item.description || "No description."}</p>
              </div>
              <button type="button" onClick={() => onSelect(item.id)} className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700">
                {selected ? "Selected" : "Inspect"}
              </button>
            </div>
            <div className="mt-2 grid gap-1 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
              <span>Lifecycle: {item.lifecycle_status}</span>
              <span>Version: {item.version_number}</span>
              <span>Active: {item.is_active ? "Yes" : "No"}</span>
              <span>Source: {item.source_type}</span>
              <span>Academic year: {item.academic_year_id}</span>
              <span>Term: {item.term_id}</span>
              <span>Campus: {item.campus_id || "Whole scope"}</span>
              <span>Updated: {new Date(item.updated_at).toLocaleString()}</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <LifecycleButton enabled={isActionAllowed(item, "submit")} label="Submit" onClick={() => onLifecycleAction(item, "submit")} />
              <LifecycleButton enabled={isActionAllowed(item, "approve")} label="Approve" onClick={() => onLifecycleAction(item, "approve")} />
              <LifecycleButton enabled={isActionAllowed(item, "activate")} label="Activate" onClick={() => onLifecycleAction(item, "activate")} />
              <LifecycleButton enabled={isActionAllowed(item, "suspend")} label="Suspend" onClick={() => onLifecycleAction(item, "suspend")} />
              <LifecycleButton enabled={isActionAllowed(item, "retire")} label="Retire" onClick={() => onLifecycleAction(item, "retire")} />
            </div>
          </article>
        );
      })}
    </div>
  );
}

function LifecycleButton({ enabled, label, onClick }: { enabled: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={!enabled}
      onClick={onClick}
      className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {label}
    </button>
  );
}
