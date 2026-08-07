"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import RoleGuard from "@/components/auth/role-guard";
import { useAuth } from "@/components/auth/auth-provider";
import { toFriendlyError } from "@/app/leadership/calendar/calendar-utils";
import {
  activatePolicyConstraint,
  activatePolicySet,
  approvePolicyConstraint,
  approvePolicyException,
  approvePolicySet,
  createPolicyConstraint,
  createPolicyException,
  createPolicySetDraft,
  getEffectiveConstraints,
  getEffectivePolicy,
  getPolicyDiagnostics,
  getPolicyReadiness,
  getPolicyResolutionGuidance,
  getSchedulingAuthorization,
  listConstraintTypes,
  listPolicyConstraintVersions,
  listPolicyConstraints,
  listPolicyExceptions,
  listPolicySetVersions,
  listPolicySets,
  patchPolicySet,
  rejectPolicyException,
  retirePolicyConstraint,
  retirePolicySet,
  revokePolicyException,
  submitPolicyConstraint,
  submitPolicyException,
  submitPolicySet,
  suspendPolicyConstraint,
  suspendPolicySet,
  TimetablePoliciesApiError,
  type AuthorizationPayload,
  type ConstraintTypeDefinition,
  type EffectiveConstraintsPayload,
  type PolicyConstraint,
  type PolicyDiagnosticsPayload,
  type PolicyException,
  type PolicySet,
  type PolicySetVersion,
  type ReadinessSummaryPayload,
  type ConstraintVersion,
} from "@/lib/timetable-policies-api";
import OverviewPanel from "@/app/leadership/timetable-policies/overview-panel";
import PolicySetsPanel from "@/app/leadership/timetable-policies/policy-sets-panel";
import ConstraintsPanel from "@/app/leadership/timetable-policies/constraints-panel";
import DiagnosticsPanel from "@/app/leadership/timetable-policies/diagnostics-panel";
import ReadinessPanel from "@/app/leadership/timetable-policies/readiness-panel";
import ExceptionsPanel from "@/app/leadership/timetable-policies/exceptions-panel";
import ApprovalsPanel, { type ApprovalItem } from "@/app/leadership/timetable-policies/approvals-panel";
import ConstraintLibraryPanel, { type LibraryFilters } from "@/app/leadership/timetable-policies/constraint-library-panel";

type TabKey = "overview" | "policy_sets" | "constraints" | "diagnostics" | "readiness" | "exceptions" | "approvals" | "constraint_library";

const TAB_ORDER: TabKey[] = ["overview", "policy_sets", "constraints", "diagnostics", "readiness", "exceptions", "approvals", "constraint_library"];

const TAB_LABELS: Record<TabKey, string> = {
  overview: "Overview",
  policy_sets: "Policy Sets",
  constraints: "Constraints",
  diagnostics: "Diagnostics",
  readiness: "Readiness",
  exceptions: "Exceptions",
  approvals: "Approvals",
  constraint_library: "Constraint Library",
};

function parseTab(value: string | null): TabKey {
  if (value && TAB_ORDER.includes(value as TabKey)) {
    return value as TabKey;
  }
  return "overview";
}

function parseApiError(error: unknown): string {
  if (error instanceof TimetablePoliciesApiError) {
    return error.message;
  }
  return toFriendlyError(error);
}

function safePrompt(label: string): string | null {
  const value = window.prompt(label);
  if (value === null) return null;
  return value.trim();
}

function parseValue(raw: string, descriptor: string): unknown {
  if (descriptor.startsWith("list[int]")) {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => Number(item));
  }
  if (descriptor === "int") {
    return Number(raw);
  }
  if (descriptor === "bool") {
    return raw.toLowerCase() === "true";
  }
  return raw;
}

export default function LeadershipTimetablePoliciesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isHydrating, isAuthenticated, user } = useAuth();

  const [activeTab, setActiveTab] = useState<TabKey>(() => parseTab(searchParams.get("tab")));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [policyLifecycleFilter, setPolicyLifecycleFilter] = useState("");
  const [exceptionFilter, setExceptionFilter] = useState("");

  const [policySets, setPolicySets] = useState<PolicySet[]>([]);
  const [selectedPolicySetId, setSelectedPolicySetId] = useState<string | null>(null);
  const [policySetVersions, setPolicySetVersions] = useState<PolicySetVersion[]>([]);

  const [constraints, setConstraints] = useState<PolicyConstraint[]>([]);
  const [selectedConstraintId, setSelectedConstraintId] = useState<string | null>(null);
  const [constraintVersions, setConstraintVersions] = useState<ConstraintVersion[]>([]);

  const [exceptions, setExceptions] = useState<PolicyException[]>([]);
  const [constraintTypes, setConstraintTypes] = useState<ConstraintTypeDefinition[]>([]);
  const [diagnostics, setDiagnostics] = useState<PolicyDiagnosticsPayload | null>(null);
  const [readiness, setReadiness] = useState<ReadinessSummaryPayload | null>(null);
  const [effectivePolicy, setEffectivePolicy] = useState<ReadinessSummaryPayload | null>(null);
  const [effectiveConstraints, setEffectiveConstraintsPayload] = useState<EffectiveConstraintsPayload | null>(null);
  const [authorization, setAuthorization] = useState<AuthorizationPayload | null>(null);

  const [policyDraft, setPolicyDraft] = useState({
    academic_year_id: "",
    term_id: "",
    campus_id: "",
    name: "",
    description: "",
    effective_start_date: "",
    effective_end_date: "",
    source_type: "manual",
  });

  const [constraintDraft, setConstraintDraft] = useState({
    constraint_type: "",
    scope_type: "",
    scope_reference_id: "",
    scope_reference_code: "",
    enforcement_level: "",
    weight: "",
    priority: "",
    explanation: "",
    source_type: "manual",
    confidence_score: "",
  });
  const [constraintParameters, setConstraintParameters] = useState<Record<string, string>>({});

  const [exceptionDraft, setExceptionDraft] = useState({
    policy_set_id: "",
    constraint_id: "",
    scope_type: "whole_school",
    scope_reference_id: "",
    scope_reference_code: "",
    reason: "",
    start_date: "",
    end_date: "",
    expires_at: "",
  });

  const [libraryFilters, setLibraryFilters] = useState<LibraryFilters>({
    category: "",
    enforcement: "",
    scope: "",
    approvalRequired: "",
  });

  const selectedPolicySet = useMemo(() => policySets.find((item) => item.id === selectedPolicySetId) || null, [policySets, selectedPolicySetId]);
  const selectedConstraintType = useMemo(() => constraintTypes.find((item) => item.key === constraintDraft.constraint_type) || null, [constraintTypes, constraintDraft.constraint_type]);

  const hasLeadershipAccess = Boolean(isAuthenticated && user && user.is_active && (user.role === "principal" || user.role === "school_admin"));

  async function refreshWorkspace() {
    setLoading(true);
    setError(null);
    try {
      const [setRows, exceptionRows, typeRows, diagnosticsSummary, readinessSummary, effectivePolicySummary, effectiveConstraintSummary, authorizationSummary, resolutionGuidance] = await Promise.all([
        listPolicySets({ lifecycle_status: policyLifecycleFilter || undefined }),
        listPolicyExceptions({ approval_state: exceptionFilter || undefined }),
        listConstraintTypes(),
        getPolicyDiagnostics(),
        getPolicyReadiness(),
        getEffectivePolicy(),
        getEffectiveConstraints(),
        getSchedulingAuthorization(),
        getPolicyResolutionGuidance(),
      ]);

      setPolicySets(setRows);
      setExceptions(exceptionRows);
      setConstraintTypes(typeRows);
      setDiagnostics({ ...diagnosticsSummary, resolution_guidance: resolutionGuidance.resolution_guidance });
      setReadiness(readinessSummary);
      setEffectivePolicy(effectivePolicySummary);
      setEffectiveConstraintsPayload(effectiveConstraintSummary);
      setAuthorization(authorizationSummary);

      setSelectedPolicySetId((current) => {
        if (current && setRows.some((item) => item.id === current)) return current;
        return setRows[0]?.id || null;
      });
    } catch (loadError) {
      setError(parseApiError(loadError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isHydrating || !hasLeadershipAccess) return;
    void refreshWorkspace();
  }, [isHydrating, hasLeadershipAccess, policyLifecycleFilter, exceptionFilter]);

  useEffect(() => {
    if (!selectedPolicySetId) {
      setConstraints([]);
      setPolicySetVersions([]);
      return;
    }
    void Promise.all([listPolicyConstraints(selectedPolicySetId), listPolicySetVersions(selectedPolicySetId)])
      .then(([constraintRows, versions]) => {
        setConstraints(constraintRows);
        setPolicySetVersions(versions);
        setSelectedConstraintId((current) => {
          if (current && constraintRows.some((item) => item.id === current)) return current;
          return constraintRows[0]?.id || null;
        });
      })
      .catch((loadError) => setError(parseApiError(loadError)));
  }, [selectedPolicySetId]);

  useEffect(() => {
    if (!selectedConstraintId) {
      setConstraintVersions([]);
      return;
    }
    void listPolicyConstraintVersions(selectedConstraintId)
      .then((rows) => setConstraintVersions(rows))
      .catch((loadError) => setError(parseApiError(loadError)));
  }, [selectedConstraintId]);

  const updateTab = (tab: TabKey) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    router.replace(url.pathname + url.search);
  };

  async function handlePolicyLifecycle(item: PolicySet, action: "submit" | "approve" | "activate" | "suspend" | "retire") {
    let reason: string | null = "";
    if (action !== "submit") {
      reason = safePrompt(`Reason for ${action} policy set action`);
      if (reason === null) return;
    }
    if (action === "activate") {
      const confirmed = window.confirm("Activation makes this policy set operational and may change readiness. Activation does not generate a timetable.");
      if (!confirmed) return;
    }
    try {
      if (action === "submit") await submitPolicySet(item.id, { reason });
      if (action === "approve") await approvePolicySet(item.id, { reason });
      if (action === "activate") await activatePolicySet(item.id, { reason });
      if (action === "suspend") await suspendPolicySet(item.id, { reason });
      if (action === "retire") await retirePolicySet(item.id, { reason });
      setNotice(`Policy set ${action} completed.`);
      await refreshWorkspace();
    } catch (lifecycleError) {
      setError(parseApiError(lifecycleError));
    }
  }

  async function handleConstraintLifecycle(item: PolicyConstraint, action: "submit" | "approve" | "activate" | "suspend" | "retire") {
    const reason = safePrompt(`Reason for ${action} constraint action`);
    if (reason === null) return;
    try {
      if (action === "submit") await submitPolicyConstraint(item.id, { reason });
      if (action === "approve") await approvePolicyConstraint(item.id, { reason });
      if (action === "activate") await activatePolicyConstraint(item.id, { reason });
      if (action === "suspend") await suspendPolicyConstraint(item.id, { reason });
      if (action === "retire") await retirePolicyConstraint(item.id, { reason });
      setNotice(`Constraint ${action} completed.`);
      await refreshWorkspace();
    } catch (lifecycleError) {
      setError(parseApiError(lifecycleError));
    }
  }

  async function handleExceptionAction(item: PolicyException, action: "submit" | "approve" | "reject" | "revoke") {
    const reason = safePrompt(`Reason for ${action} exception action`);
    if (reason === null) return;
    if (action === "reject" || action === "revoke") {
      const confirmed = window.confirm(`Confirm ${action}. This action does not remove unrelated blockers.`);
      if (!confirmed) return;
    }
    try {
      if (action === "submit") await submitPolicyException(item.id, { reason });
      if (action === "approve") await approvePolicyException(item.id, { reason });
      if (action === "reject") await rejectPolicyException(item.id, { reason });
      if (action === "revoke") await revokePolicyException(item.id, { reason });
      setNotice(`Exception ${action} completed.`);
      await refreshWorkspace();
    } catch (actionError) {
      setError(parseApiError(actionError));
    }
  }

  async function handleCreatePolicySet(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!policyDraft.name || !policyDraft.academic_year_id || !policyDraft.term_id) {
      setError("Policy name, academic year, and term are required.");
      return;
    }
    try {
      await createPolicySetDraft({
        academic_year_id: policyDraft.academic_year_id,
        term_id: policyDraft.term_id,
        campus_id: policyDraft.campus_id || null,
        name: policyDraft.name,
        description: policyDraft.description || null,
        effective_start_date: policyDraft.effective_start_date || null,
        effective_end_date: policyDraft.effective_end_date || null,
        source_type: policyDraft.source_type,
      });
      setNotice("Policy set draft created. Approval and activation are still required.");
      setPolicyDraft({ academic_year_id: "", term_id: "", campus_id: "", name: "", description: "", effective_start_date: "", effective_end_date: "", source_type: "manual" });
      await refreshWorkspace();
    } catch (createError) {
      setError(parseApiError(createError));
    }
  }

  async function handleUpdateSelectedPolicyDates() {
    if (!selectedPolicySet) return;
    try {
      await patchPolicySet(selectedPolicySet.id, {
        name: selectedPolicySet.name,
        description: selectedPolicySet.description,
        effective_start_date: selectedPolicySet.effective_start_date,
        effective_end_date: selectedPolicySet.effective_end_date,
      });
      setNotice("Policy set metadata refreshed through controlled patch endpoint.");
      await refreshWorkspace();
    } catch (updateError) {
      setError(parseApiError(updateError));
    }
  }

  async function handleCreateConstraint(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPolicySetId) {
      setError("Select a policy set before creating constraints.");
      return;
    }
    if (!selectedConstraintType) {
      setError("Choose a supported constraint type from the registry.");
      return;
    }
    if (!constraintDraft.scope_type || !constraintDraft.enforcement_level) {
      setError("Constraint scope and enforcement level are required.");
      return;
    }

    const parameters: Record<string, unknown> = {};
    for (const [key, descriptor] of Object.entries(selectedConstraintType.required_parameters)) {
      const raw = constraintParameters[key];
      if (!raw || !raw.trim()) {
        setError(`Required parameter missing: ${key}`);
        return;
      }
      parameters[key] = parseValue(raw, descriptor);
    }
    for (const [key, descriptor] of Object.entries(selectedConstraintType.optional_parameters)) {
      const raw = constraintParameters[key];
      if (!raw || !raw.trim()) continue;
      parameters[key] = parseValue(raw, descriptor);
    }

    try {
      await createPolicyConstraint(selectedPolicySetId, {
        constraint_type: selectedConstraintType.key,
        category: selectedConstraintType.category,
        enforcement_level: constraintDraft.enforcement_level,
        scope_type: constraintDraft.scope_type,
        scope_reference_id: constraintDraft.scope_reference_id || null,
        scope_reference_code: constraintDraft.scope_reference_code || null,
        parameters,
        weight: constraintDraft.weight ? Number(constraintDraft.weight) : undefined,
        priority: constraintDraft.priority ? Number(constraintDraft.priority) : undefined,
        explanation: constraintDraft.explanation || null,
        source_type: constraintDraft.source_type,
        confidence_score: constraintDraft.confidence_score ? Number(constraintDraft.confidence_score) : null,
      });
      setNotice("Constraint draft created. It is not operational until approved and activated.");
      setConstraintDraft({ constraint_type: "", scope_type: "", scope_reference_id: "", scope_reference_code: "", enforcement_level: "", weight: "", priority: "", explanation: "", source_type: "manual", confidence_score: "" });
      setConstraintParameters({});
      await refreshWorkspace();
    } catch (createError) {
      setError(parseApiError(createError));
    }
  }

  async function handleCreateException(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!exceptionDraft.reason.trim()) {
      setError("Exception reason is required.");
      return;
    }
    try {
      await createPolicyException({
        policy_set_id: exceptionDraft.policy_set_id || undefined,
        constraint_id: exceptionDraft.constraint_id || undefined,
        scope_type: exceptionDraft.scope_type,
        scope_reference_id: exceptionDraft.scope_reference_id || undefined,
        scope_reference_code: exceptionDraft.scope_reference_code || undefined,
        reason: exceptionDraft.reason.trim(),
        start_date: exceptionDraft.start_date || undefined,
        end_date: exceptionDraft.end_date || undefined,
        expires_at: exceptionDraft.expires_at || undefined,
      });
      setNotice("Exception request created as draft. Submit and approval are required before it becomes operational.");
      setExceptionDraft({ policy_set_id: "", constraint_id: "", scope_type: "whole_school", scope_reference_id: "", scope_reference_code: "", reason: "", start_date: "", end_date: "", expires_at: "" });
      await refreshWorkspace();
    } catch (createError) {
      setError(parseApiError(createError));
    }
  }

  async function handleRunDiagnostics() {
    const confirmed = window.confirm("Run Policy Diagnostics? This is deterministic and read-only. It does not approve, activate, or generate timetables.");
    if (!confirmed) return;
    try {
      const [summary, guidance] = await Promise.all([getPolicyDiagnostics(), getPolicyResolutionGuidance()]);
      setDiagnostics({ ...summary, resolution_guidance: guidance.resolution_guidance });
      setNotice("Diagnostics refreshed. Canonical records remain unchanged.");
    } catch (runError) {
      setError(parseApiError(runError));
    }
  }

  if (!isHydrating && !hasLeadershipAccess) {
    return (
      <RoleGuard allowedRoles={["principal", "school_admin"]} forbiddenMessage="Permission denied. Leadership access is required for this route.">
        <div />
      </RoleGuard>
    );
  }

  if (isHydrating || loading) {
    return <p className="text-sm text-slate-600">Loading timetable policy workspace...</p>;
  }

  return (
    <section className="space-y-5">
      <header className="rounded-2xl border border-slate-200 bg-white p-5">
        <h1 className="text-xl font-semibold text-slate-900">Timetable Policies</h1>
        <p className="mt-1 text-sm text-slate-600">Leadership policy workspace for deterministic policy, constraints, diagnostics, readiness, and approval orchestration.</p>
        <p className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-600">
          Agent proposal and deterministic evidence are advisory. Records are only operational after controlled lifecycle approval and activation.
        </p>
      </header>

      {error ? (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </div>
      ) : null}
      {notice ? <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div> : null}

      <nav className="flex flex-wrap gap-2" aria-label="Timetable policy workspace tabs">
        {TAB_ORDER.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => updateTab(tab)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${activeTab === tab ? "bg-indigo-600 text-white" : "bg-white text-slate-700 border border-slate-300"}`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </nav>

      {activeTab === "overview" ? <OverviewPanel readiness={effectivePolicy} authorization={authorization} /> : null}

      {activeTab === "policy_sets" ? (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">Create policy set draft</h2>
              <select aria-label="Filter policy sets by lifecycle" value={policyLifecycleFilter} onChange={(e) => setPolicyLifecycleFilter(e.target.value)} className="rounded-lg border border-slate-300 p-2 text-sm">
                <option value="">All lifecycle states</option>
                <option value="draft">draft</option>
                <option value="pending_review">pending_review</option>
                <option value="approved">approved</option>
                <option value="active">active</option>
                <option value="suspended">suspended</option>
                <option value="retired">retired</option>
              </select>
            </div>
            <form onSubmit={handleCreatePolicySet} className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <input aria-label="Policy name" value={policyDraft.name} onChange={(e) => setPolicyDraft({ ...policyDraft, name: e.target.value })} placeholder="Policy name" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Academic year id" value={policyDraft.academic_year_id} onChange={(e) => setPolicyDraft({ ...policyDraft, academic_year_id: e.target.value })} placeholder="Academic year UUID" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Term id" value={policyDraft.term_id} onChange={(e) => setPolicyDraft({ ...policyDraft, term_id: e.target.value })} placeholder="Term UUID" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Campus id" value={policyDraft.campus_id} onChange={(e) => setPolicyDraft({ ...policyDraft, campus_id: e.target.value })} placeholder="Campus UUID (optional)" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Effective start date" type="date" value={policyDraft.effective_start_date} onChange={(e) => setPolicyDraft({ ...policyDraft, effective_start_date: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Effective end date" type="date" value={policyDraft.effective_end_date} onChange={(e) => setPolicyDraft({ ...policyDraft, effective_end_date: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Description" value={policyDraft.description} onChange={(e) => setPolicyDraft({ ...policyDraft, description: e.target.value })} placeholder="Description" className="rounded-lg border border-slate-300 p-2 text-sm sm:col-span-2" />
              <button type="submit" className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white">Create draft</button>
            </form>
          </section>

          <PolicySetsPanel items={policySets} selectedPolicySetId={selectedPolicySetId} onSelect={setSelectedPolicySetId} onLifecycleAction={handlePolicyLifecycle} />

          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">Policy version history</h3>
              <button type="button" onClick={handleUpdateSelectedPolicyDates} className="rounded-lg border border-slate-300 px-2 py-1 text-xs text-slate-700">Refresh selected policy metadata</button>
            </div>
            {!policySetVersions.length ? (
              <p className="mt-2 text-sm text-slate-600">No versions found for the selected policy set.</p>
            ) : (
              <div className="mt-2 space-y-2">
                {policySetVersions.map((row) => (
                  <div key={row.id} className="rounded-lg border border-slate-100 p-2 text-xs text-slate-700">
                    <p className="font-medium">v{row.version_number} - {row.change_type}</p>
                    <p>Reason: {row.reason || "-"}</p>
                    <p>Actor: {row.actor_user_id || "-"}</p>
                    <p>Time: {new Date(row.created_at).toLocaleString()}</p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === "constraints" ? (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Create structured constraint draft</h2>
            <p className="mt-1 text-xs text-slate-500">Constraint parameters are generated from deterministic registry metadata. Free-text unsupported types are not allowed.</p>
            <form onSubmit={handleCreateConstraint} className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <select aria-label="Constraint type" value={constraintDraft.constraint_type} onChange={(e) => {
                const nextType = e.target.value;
                const definition = constraintTypes.find((item) => item.key === nextType);
                setConstraintDraft({
                  ...constraintDraft,
                  constraint_type: nextType,
                  scope_type: definition?.supported_scopes[0] || "",
                  enforcement_level: definition?.allowed_enforcement_levels[0] || "",
                  weight: definition ? String(definition.default_weight) : "",
                  priority: definition ? String(definition.default_priority) : "",
                });
              }} className="rounded-lg border border-slate-300 p-2 text-sm">
                <option value="">Select constraint type</option>
                {constraintTypes.map((item) => <option key={item.key} value={item.key}>{item.title}</option>)}
              </select>

              <select aria-label="Constraint scope" value={constraintDraft.scope_type} onChange={(e) => setConstraintDraft({ ...constraintDraft, scope_type: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm">
                <option value="">Select scope</option>
                {(selectedConstraintType?.supported_scopes || []).map((scope) => <option key={scope} value={scope}>{scope}</option>)}
              </select>

              <select aria-label="Constraint enforcement" value={constraintDraft.enforcement_level} onChange={(e) => setConstraintDraft({ ...constraintDraft, enforcement_level: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm">
                <option value="">Select enforcement</option>
                {(selectedConstraintType?.allowed_enforcement_levels || []).map((level) => <option key={level} value={level}>{level}</option>)}
              </select>

              <input aria-label="Scope reference id" value={constraintDraft.scope_reference_id} onChange={(e) => setConstraintDraft({ ...constraintDraft, scope_reference_id: e.target.value })} placeholder="Scope reference UUID" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Scope reference code" value={constraintDraft.scope_reference_code} onChange={(e) => setConstraintDraft({ ...constraintDraft, scope_reference_code: e.target.value })} placeholder="Scope reference code" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Weight" value={constraintDraft.weight} onChange={(e) => setConstraintDraft({ ...constraintDraft, weight: e.target.value })} placeholder="Weight" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Priority" value={constraintDraft.priority} onChange={(e) => setConstraintDraft({ ...constraintDraft, priority: e.target.value })} placeholder="Priority" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Confidence score" value={constraintDraft.confidence_score} onChange={(e) => setConstraintDraft({ ...constraintDraft, confidence_score: e.target.value })} placeholder="Agent confidence 0-100" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Constraint explanation" value={constraintDraft.explanation} onChange={(e) => setConstraintDraft({ ...constraintDraft, explanation: e.target.value })} placeholder="Explanation" className="rounded-lg border border-slate-300 p-2 text-sm sm:col-span-2" />

              {(selectedConstraintType ? [...Object.entries(selectedConstraintType.required_parameters), ...Object.entries(selectedConstraintType.optional_parameters)] : []).map(([key, descriptor]) => (
                <input
                  key={key}
                  aria-label={`Parameter ${key}`}
                  value={constraintParameters[key] || ""}
                  onChange={(e) => setConstraintParameters((current) => ({ ...current, [key]: e.target.value }))}
                  placeholder={`${key} (${descriptor})`}
                  className="rounded-lg border border-slate-300 p-2 text-sm"
                />
              ))}

              <button type="submit" className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white">Create draft</button>
            </form>
          </section>

          <ConstraintsPanel items={constraints} selectedConstraintId={selectedConstraintId} onSelectConstraint={setSelectedConstraintId} onLifecycleAction={handleConstraintLifecycle} />

          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="text-sm font-semibold text-slate-900">Constraint version history</h3>
            {!constraintVersions.length ? (
              <p className="mt-2 text-sm text-slate-600">No versions found for the selected constraint.</p>
            ) : (
              <div className="mt-2 space-y-2">
                {constraintVersions.map((row) => (
                  <div key={row.id} className="rounded-lg border border-slate-100 p-2 text-xs text-slate-700">
                    <p className="font-medium">v{row.version_number} - {row.change_type}</p>
                    <p>Reason: {row.reason || "-"}</p>
                    <p>Actor: {row.actor_user_id || "-"}</p>
                    <p>Time: {new Date(row.created_at).toLocaleString()}</p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === "diagnostics" ? <DiagnosticsPanel diagnostics={diagnostics} onRun={handleRunDiagnostics} /> : null}

      {activeTab === "readiness" ? <ReadinessPanel readiness={effectivePolicy} effectiveConstraints={effectiveConstraints} authorization={authorization} /> : null}

      {activeTab === "exceptions" ? (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">Create exception request</h2>
              <select aria-label="Filter exceptions by approval state" value={exceptionFilter} onChange={(e) => setExceptionFilter(e.target.value)} className="rounded-lg border border-slate-300 p-2 text-sm">
                <option value="">All approval states</option>
                <option value="draft">draft</option>
                <option value="pending_review">pending_review</option>
                <option value="approved">approved</option>
                <option value="rejected">rejected</option>
                <option value="revoked">revoked</option>
              </select>
            </div>
            <form onSubmit={handleCreateException} className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <input aria-label="Exception target policy set" value={exceptionDraft.policy_set_id} onChange={(e) => setExceptionDraft({ ...exceptionDraft, policy_set_id: e.target.value })} placeholder="Policy set UUID" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception target constraint" value={exceptionDraft.constraint_id} onChange={(e) => setExceptionDraft({ ...exceptionDraft, constraint_id: e.target.value })} placeholder="Constraint UUID" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception scope type" value={exceptionDraft.scope_type} onChange={(e) => setExceptionDraft({ ...exceptionDraft, scope_type: e.target.value })} placeholder="Scope type" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception scope reference id" value={exceptionDraft.scope_reference_id} onChange={(e) => setExceptionDraft({ ...exceptionDraft, scope_reference_id: e.target.value })} placeholder="Scope reference UUID" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception scope reference code" value={exceptionDraft.scope_reference_code} onChange={(e) => setExceptionDraft({ ...exceptionDraft, scope_reference_code: e.target.value })} placeholder="Scope reference code" className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception reason" value={exceptionDraft.reason} onChange={(e) => setExceptionDraft({ ...exceptionDraft, reason: e.target.value })} placeholder="Reason" className="rounded-lg border border-slate-300 p-2 text-sm sm:col-span-2" />
              <input aria-label="Exception start date" type="date" value={exceptionDraft.start_date} onChange={(e) => setExceptionDraft({ ...exceptionDraft, start_date: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception end date" type="date" value={exceptionDraft.end_date} onChange={(e) => setExceptionDraft({ ...exceptionDraft, end_date: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm" />
              <input aria-label="Exception expiry" type="datetime-local" value={exceptionDraft.expires_at} onChange={(e) => setExceptionDraft({ ...exceptionDraft, expires_at: e.target.value })} className="rounded-lg border border-slate-300 p-2 text-sm" />
              <button type="submit" className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white">Create request</button>
            </form>
          </section>

          <ExceptionsPanel items={exceptions} onAction={handleExceptionAction} />
        </div>
      ) : null}

      {activeTab === "approvals" ? <ApprovalsPanel items={((readiness?.calculation_breakdown?.approval_queue as ApprovalItem[] | undefined) || (authorization?.required_actions as unknown as ApprovalItem[]) || [])} /> : null}

      {activeTab === "constraint_library" ? (
        <ConstraintLibraryPanel definitions={constraintTypes} filters={libraryFilters} onFiltersChange={setLibraryFilters} />
      ) : null}
    </section>
  );
}
