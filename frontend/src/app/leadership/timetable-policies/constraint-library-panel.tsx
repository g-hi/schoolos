import type { ConstraintTypeDefinition } from "@/lib/timetable-policies-api";

export interface LibraryFilters {
  category: string;
  enforcement: string;
  scope: string;
  approvalRequired: string;
}

export default function ConstraintLibraryPanel({ definitions, filters, onFiltersChange }: { definitions: ConstraintTypeDefinition[]; filters: LibraryFilters; onFiltersChange: (next: LibraryFilters) => void }) {
  const categories = Array.from(new Set(definitions.map((item) => item.category))).sort();
  const scoped = Array.from(new Set(definitions.flatMap((item) => item.supported_scopes))).sort();
  const enforcementLevels = Array.from(new Set(definitions.flatMap((item) => item.allowed_enforcement_levels))).sort();

  const filtered = definitions.filter((item) => {
    if (filters.category && item.category !== filters.category) return false;
    if (filters.enforcement && !item.allowed_enforcement_levels.includes(filters.enforcement)) return false;
    if (filters.scope && !item.supported_scopes.includes(filters.scope)) return false;
    if (filters.approvalRequired === "yes" && !item.approval_required) return false;
    if (filters.approvalRequired === "no" && item.approval_required) return false;
    return true;
  });

  return (
    <section className="space-y-3">
      <div className="grid gap-2 rounded-xl border border-slate-200 bg-white p-3 md:grid-cols-4">
        <select aria-label="Filter library by category" value={filters.category} onChange={(e) => onFiltersChange({ ...filters, category: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm">
          <option value="">All categories</option>
          {categories.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select aria-label="Filter library by enforcement" value={filters.enforcement} onChange={(e) => onFiltersChange({ ...filters, enforcement: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm">
          <option value="">All enforcement</option>
          {enforcementLevels.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select aria-label="Filter library by scope" value={filters.scope} onChange={(e) => onFiltersChange({ ...filters, scope: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm">
          <option value="">All scopes</option>
          {scoped.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select aria-label="Filter library by approval requirement" value={filters.approvalRequired} onChange={(e) => onFiltersChange({ ...filters, approvalRequired: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm">
          <option value="">All approval states</option>
          <option value="yes">Requires approval</option>
          <option value="no">Does not require approval</option>
        </select>
      </div>

      <div className="space-y-3">
        {filtered.map((item) => (
          <article key={item.key} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">{item.key}</span>
              <span className="rounded-full bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700">{item.category}</span>
            </div>
            <p className="mt-2 text-sm text-slate-700">{item.explanation}</p>
            <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
              <p>Enforcement: {item.allowed_enforcement_levels.join(", ")}</p>
              <p>Scopes: {item.supported_scopes.join(", ")}</p>
              <p>Default priority: {item.default_priority}</p>
              <p>Default weight: {item.default_weight}</p>
              <p>Approval required: {item.approval_required ? "Yes" : "No"}</p>
              <p>Required parameters: {Object.keys(item.required_parameters).join(", ") || "None"}</p>
              <p>Optional parameters: {Object.keys(item.optional_parameters).join(", ") || "None"}</p>
              <p>Validation rules: {item.validation_rules.join(", ") || "None"}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
