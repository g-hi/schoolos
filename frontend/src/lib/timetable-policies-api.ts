import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";

type QueryValue = string | number | boolean | undefined | null;

type HttpMethod = "GET" | "POST" | "PATCH";

export class TimetablePoliciesApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "TimetablePoliciesApiError";
    this.status = status;
    this.body = body;
  }
}

export interface LifecycleReasonRequest {
  reason?: string | null;
}

export interface PolicySet {
  id: string;
  tenant_id: string;
  academic_year_id: string;
  term_id: string;
  campus_id: string | null;
  name: string;
  description: string | null;
  lifecycle_status: "draft" | "pending_review" | "approved" | "active" | "suspended" | "retired" | string;
  version_number: number;
  is_active: boolean;
  effective_start_date: string | null;
  effective_end_date: string | null;
  source_type: string;
  created_by_user_id: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PolicySetCreateRequest {
  academic_year_id: string;
  term_id: string;
  campus_id?: string | null;
  name: string;
  description?: string | null;
  effective_start_date?: string | null;
  effective_end_date?: string | null;
  source_type?: string;
}

export interface PolicySetPatchRequest {
  name?: string;
  description?: string | null;
  effective_start_date?: string | null;
  effective_end_date?: string | null;
}

export interface PolicySetVersion {
  id: string;
  policy_set_id: string;
  version_number: number;
  change_type: string;
  reason: string | null;
  previous_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  actor_user_id: string | null;
  approval_actor_user_id: string | null;
  created_at: string;
}

export interface PolicyConstraint {
  id: string;
  tenant_id: string;
  policy_set_id: string;
  constraint_type: string;
  category: string;
  enforcement_level: "hard" | "soft" | "preference" | "advisory" | string;
  lifecycle_status: "draft" | "pending_review" | "approved" | "active" | "suspended" | "retired" | string;
  scope_type: string;
  scope_reference_id: string | null;
  scope_reference_code: string | null;
  parameters: Record<string, unknown>;
  weight: number;
  priority: number;
  is_active: boolean;
  effective_start_date: string | null;
  effective_end_date: string | null;
  explanation: string | null;
  source_type: string;
  confidence_score: number | null;
  requires_approval: boolean;
  created_by_user_id: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConstraintCreateRequest {
  constraint_type: string;
  category: string;
  enforcement_level: string;
  scope_type: string;
  scope_reference_id?: string | null;
  scope_reference_code?: string | null;
  parameters: Record<string, unknown>;
  weight?: number | null;
  priority?: number | null;
  explanation?: string | null;
  source_type?: string;
  confidence_score?: number | null;
  requires_approval?: boolean | null;
  effective_start_date?: string | null;
  effective_end_date?: string | null;
}

export interface ConstraintPatchRequest {
  enforcement_level?: string;
  scope_type?: string;
  scope_reference_id?: string | null;
  scope_reference_code?: string | null;
  parameters?: Record<string, unknown>;
  weight?: number;
  priority?: number;
  explanation?: string | null;
  effective_start_date?: string | null;
  effective_end_date?: string | null;
}

export interface ConstraintVersion {
  id: string;
  constraint_id: string;
  version_number: number;
  change_type: string;
  reason: string | null;
  previous_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  actor_user_id: string | null;
  approval_actor_user_id: string | null;
  created_at: string;
}

export interface PolicyException {
  id: string;
  tenant_id: string;
  policy_set_id: string | null;
  constraint_id: string | null;
  scope_type: string;
  scope_reference_id: string | null;
  scope_reference_code: string | null;
  reason: string;
  start_date: string | null;
  end_date: string | null;
  approval_state: "draft" | "pending_review" | "approved" | "rejected" | "revoked" | string;
  requested_by_user_id: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ExceptionCreateRequest {
  policy_set_id?: string | null;
  constraint_id?: string | null;
  scope_type: string;
  scope_reference_id?: string | null;
  scope_reference_code?: string | null;
  reason: string;
  start_date?: string | null;
  end_date?: string | null;
  expires_at?: string | null;
}

export interface ConstraintTypeDefinition {
  key: string;
  title: string;
  category: string;
  allowed_enforcement_levels: string[];
  required_parameters: Record<string, string>;
  optional_parameters: Record<string, string>;
  supported_scopes: string[];
  validation_rules: string[];
  default_priority: number;
  default_weight: number;
  explanation: string;
  solver_mapping: string;
  approval_required: boolean;
}

export interface ReadinessContextFilters {
  academic_year_id?: string;
  term_id?: string;
  campus_id?: string;
  grade_id?: string;
  class_id?: string;
  subject_id?: string;
  teacher_id?: string;
  room_id?: string;
  effective_at?: string;
}

export interface PolicyDiagnosticsPayload {
  generated_at: string;
  summary: Record<string, unknown>;
  generation: Record<string, unknown>;
  policy_counts: Record<string, unknown>;
  conflicts: Array<Record<string, unknown>>;
  feasibility: Array<Record<string, unknown>>;
  impact: Array<Record<string, unknown>>;
  resolution_guidance: Array<Record<string, unknown>>;
}

export interface ReadinessSummaryPayload {
  generated_at: string;
  calculation_id: string;
  readiness_status: string;
  generation_allowed: boolean;
  policy_set_id: string | null;
  policy_set_status: string | null;
  policy_set_version: number | null;
  policy_explanation: Record<string, unknown>;
  source_and_provenance_summary: Record<string, unknown>;
  policy_blocker_count: number;
  policy_warning_count: number;
  policy_pending_approval_count: number;
  policy_readiness_status: string;
  overall_policy_score: number;
  calculation_breakdown: Record<string, unknown>;
}

export interface EffectiveConstraintsPayload {
  generated_at: string;
  policy_set_id: string | null;
  policy_set_status: string | null;
  effective_constraint_count: number;
  coverage: Record<string, unknown>;
  effective_constraints: Array<Record<string, unknown>>;
  exception_readiness: Record<string, unknown>;
  policy_score: Record<string, unknown>;
}

export interface AuthorizationPayload {
  generated_at: string;
  calculation_id: string;
  readiness_status: string;
  generation_allowed: boolean;
  policy_readiness_status: string;
  policy_blocker_count: number;
  policy_warning_count: number;
  policy_pending_approval_count: number;
  overall_policy_score: number;
  required_actions: Array<Record<string, unknown>>;
  readiness_blockers: Array<Record<string, unknown>>;
  readiness_warnings: Array<Record<string, unknown>>;
}

function buildUrl(path: string, params?: Record<string, QueryValue>): string {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") {
        return;
      }
      url.searchParams.set(key, String(value));
    });
  }
  return url.toString();
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function readMessage(body: unknown, status: number): string {
  if (typeof body === "string" && body.trim().length > 0) {
    return body;
  }
  if (typeof body === "object" && body !== null) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message.trim().length > 0) {
        return message;
      }
    }
  }
  return `Request failed with status ${status}.`;
}

async function request<T>(
  path: string,
  options?: {
    method?: HttpMethod;
    params?: Record<string, QueryValue>;
    body?: unknown;
    signal?: AbortSignal;
  },
): Promise<T> {
  const token = readAccessToken();
  const tenant = readTenantSlug();
  const headers = new Headers();

  headers.set("X-Tenant-Slug", tenant);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!(options?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options?.params), {
      method: options?.method ?? "GET",
      headers,
      body: options?.body instanceof FormData ? options.body : options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options?.signal,
    });
  } catch {
    throw new TimetablePoliciesApiError(0, "Network request failed.", null);
  }

  const body = await parseBody(response);
  if (!response.ok) {
    throw new TimetablePoliciesApiError(response.status, readMessage(body, response.status), body);
  }
  return body as T;
}

export function listPolicySets(params?: { lifecycle_status?: string; signal?: AbortSignal }): Promise<PolicySet[]> {
  const { signal, ...filters } = params || {};
  return request<PolicySet[]>("/leadership/timetable-policies/policy-sets", { params: filters, signal });
}

export function createPolicySetDraft(body: PolicySetCreateRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>("/leadership/timetable-policies/policy-sets", { method: "POST", body, signal });
}

export function getPolicySet(policySetId: string, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}`, { signal });
}

export function patchPolicySet(policySetId: string, body: PolicySetPatchRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}`, { method: "PATCH", body, signal });
}

export function listPolicySetVersions(policySetId: string, signal?: AbortSignal): Promise<PolicySetVersion[]> {
  return request<PolicySetVersion[]>(`/leadership/timetable-policies/policy-sets/${policySetId}/versions`, { signal });
}

export function submitPolicySet(policySetId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}/submit`, { method: "POST", body, signal });
}

export function approvePolicySet(policySetId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}/approve`, { method: "POST", body, signal });
}

export function activatePolicySet(policySetId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}/activate`, { method: "POST", body, signal });
}

export function suspendPolicySet(policySetId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}/suspend`, { method: "POST", body, signal });
}

export function retirePolicySet(policySetId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicySet> {
  return request<PolicySet>(`/leadership/timetable-policies/policy-sets/${policySetId}/retire`, { method: "POST", body, signal });
}

export function listPolicyConstraints(policySetId: string, signal?: AbortSignal): Promise<PolicyConstraint[]> {
  return request<PolicyConstraint[]>(`/leadership/timetable-policies/policy-sets/${policySetId}/constraints`, { signal });
}

export function createPolicyConstraint(policySetId: string, body: ConstraintCreateRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/policy-sets/${policySetId}/constraints`, { method: "POST", body, signal });
}

export function getPolicyConstraint(constraintId: string, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}`, { signal });
}

export function patchPolicyConstraint(constraintId: string, body: ConstraintPatchRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}`, { method: "PATCH", body, signal });
}

export function listPolicyConstraintVersions(constraintId: string, signal?: AbortSignal): Promise<ConstraintVersion[]> {
  return request<ConstraintVersion[]>(`/leadership/timetable-policies/constraints/${constraintId}/versions`, { signal });
}

export function submitPolicyConstraint(constraintId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}/submit`, { method: "POST", body, signal });
}

export function approvePolicyConstraint(constraintId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}/approve`, { method: "POST", body, signal });
}

export function activatePolicyConstraint(constraintId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}/activate`, { method: "POST", body, signal });
}

export function suspendPolicyConstraint(constraintId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}/suspend`, { method: "POST", body, signal });
}

export function retirePolicyConstraint(constraintId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyConstraint> {
  return request<PolicyConstraint>(`/leadership/timetable-policies/constraints/${constraintId}/retire`, { method: "POST", body, signal });
}

export function listPolicyExceptions(params?: { approval_state?: string; signal?: AbortSignal }): Promise<PolicyException[]> {
  const { signal, ...filters } = params || {};
  return request<PolicyException[]>("/leadership/timetable-policies/exceptions", { params: filters, signal });
}

export function createPolicyException(body: ExceptionCreateRequest, signal?: AbortSignal): Promise<PolicyException> {
  return request<PolicyException>("/leadership/timetable-policies/exceptions", { method: "POST", body, signal });
}

export function getPolicyException(exceptionId: string, signal?: AbortSignal): Promise<PolicyException> {
  return request<PolicyException>(`/leadership/timetable-policies/exceptions/${exceptionId}`, { signal });
}

export function submitPolicyException(exceptionId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyException> {
  return request<PolicyException>(`/leadership/timetable-policies/exceptions/${exceptionId}/submit`, { method: "POST", body, signal });
}

export function approvePolicyException(exceptionId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyException> {
  return request<PolicyException>(`/leadership/timetable-policies/exceptions/${exceptionId}/approve`, { method: "POST", body, signal });
}

export function rejectPolicyException(exceptionId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyException> {
  return request<PolicyException>(`/leadership/timetable-policies/exceptions/${exceptionId}/reject`, { method: "POST", body, signal });
}

export function revokePolicyException(exceptionId: string, body: LifecycleReasonRequest, signal?: AbortSignal): Promise<PolicyException> {
  return request<PolicyException>(`/leadership/timetable-policies/exceptions/${exceptionId}/revoke`, { method: "POST", body, signal });
}

export function listConstraintTypes(signal?: AbortSignal): Promise<ConstraintTypeDefinition[]> {
  return request<ConstraintTypeDefinition[]>("/leadership/timetable-policies/constraint-types", { signal });
}

export function getConstraintType(constraintType: string, signal?: AbortSignal): Promise<ConstraintTypeDefinition> {
  return request<ConstraintTypeDefinition>(`/leadership/timetable-policies/constraint-types/${constraintType}`, { signal });
}

export function getPolicyDiagnostics(signal?: AbortSignal): Promise<PolicyDiagnosticsPayload> {
  return request<PolicyDiagnosticsPayload>("/leadership/timetable-policies/diagnostics", { signal });
}

export function getPolicyConflicts(signal?: AbortSignal): Promise<{ generated_at: string; summary: Record<string, unknown>; conflicts: Array<Record<string, unknown>>; generation: Record<string, unknown> }> {
  return request("/leadership/timetable-policies/diagnostics/conflicts", { signal });
}

export function getPolicyFeasibility(signal?: AbortSignal): Promise<{ generated_at: string; summary: Record<string, unknown>; feasibility: Array<Record<string, unknown>>; generation: Record<string, unknown> }> {
  return request("/leadership/timetable-policies/diagnostics/feasibility", { signal });
}

export function getPolicyImpact(signal?: AbortSignal): Promise<{ generated_at: string; summary: Record<string, unknown>; impact: Array<Record<string, unknown>>; generation: Record<string, unknown> }> {
  return request("/leadership/timetable-policies/diagnostics/impact", { signal });
}

export function getPolicyResolutionGuidance(signal?: AbortSignal): Promise<{ generated_at: string; summary: Record<string, unknown>; resolution_guidance: Array<Record<string, unknown>>; generation: Record<string, unknown> }> {
  return request("/leadership/timetable-policies/diagnostics/resolution-guidance", { signal });
}

export function getPolicyReadiness(filters?: ReadinessContextFilters & { signal?: AbortSignal }): Promise<ReadinessSummaryPayload> {
  const { signal, ...params } = filters || {};
  return request<ReadinessSummaryPayload>("/leadership/timetable-policies/readiness", { params, signal });
}

export function getEffectivePolicy(filters?: ReadinessContextFilters & { signal?: AbortSignal }): Promise<ReadinessSummaryPayload> {
  const { signal, ...params } = filters || {};
  return request<ReadinessSummaryPayload>("/leadership/timetable-policies/readiness/effective-policy", { params, signal });
}

export function getEffectiveConstraints(filters?: ReadinessContextFilters & { signal?: AbortSignal }): Promise<EffectiveConstraintsPayload> {
  const { signal, ...params } = filters || {};
  return request<EffectiveConstraintsPayload>("/leadership/timetable-policies/readiness/effective-constraints", { params, signal });
}

export function getSchedulingAuthorization(filters?: ReadinessContextFilters & { signal?: AbortSignal }): Promise<AuthorizationPayload> {
  const { signal, ...params } = filters || {};
  return request<AuthorizationPayload>("/leadership/timetable-policies/readiness/authorization", { params, signal });
}
