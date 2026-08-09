import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";

type QueryValue = string | number | boolean | undefined | null;
type HttpMethod = "GET" | "POST" | "PATCH";

interface RequestOptions {
  method?: HttpMethod;
  params?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

export class TimetableGenerationApiError extends Error {
  status: number;
  body: unknown;
  code?: string;

  constructor(status: number, message: string, body: unknown, code?: string) {
    super(message);
    this.name = "TimetableGenerationApiError";
    this.status = status;
    this.body = body;
    this.code = code;
  }
}

export interface GenerationConfiguration {
  id: string;
  academic_year_id: string;
  term_id: string;
  campus_id: string | null;
  name: string;
  generation_mode: "standard" | "customized" | "repair" | string;
  stability_mode: "very_high" | "high" | "balanced" | "flexible" | string;
  lifecycle_status: "draft" | "ready_for_review" | "approved" | "superseded" | "cancelled" | string;
  baseline_timetable_version_id: string | null;
  objective_priorities: Array<{ objective_key: string; priority_level: "critical" | "high" | "normal" | "low" | string }>;
  repair_scope: Record<string, unknown>;
  validation_summary?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface GenerationConfigurationSummary {
  configuration: GenerationConfiguration;
  validation: {
    is_valid: boolean;
    errors: string[];
    policy_generation_allowed: boolean;
    policy_readiness_status?: string;
    policy_blocker_count?: number;
    validated_at?: string;
  };
  policy_readiness_generation_allowed: boolean;
  preference_count: number;
  hard_preference_count: number;
  override_count: number;
  lock_count: number;
  parallel_block_count: number;
  repair_settings: Record<string, unknown>;
  future_solver_eligibility: boolean;
  explicit_non_actions: Record<string, boolean>;
}

export interface TeacherPreference {
  id: string;
  teacher_id: string;
  academic_year_id: string;
  term_id: string;
  campus_id: string | null;
  preference_type: string;
  strength: "hard" | "strong" | "normal" | "low" | string;
  weekdays: number[];
  period_numbers: number[];
  effective_start_date: string | null;
  effective_end_date: string | null;
  leadership_note: string | null;
  is_active: boolean;
}

export interface GenerationLock {
  id: string;
  configuration_id: string;
  lock_state: "locked" | "prefer_to_keep" | "flexible" | string;
  target_type: "session_reference" | "teacher" | "class" | "subject" | "grade" | "room" | "day" | "period" | "period_range" | string;
  target_reference_id: string | null;
  target_reference_code: string | null;
  day_of_week: number | null;
  period_number: number | null;
  period_end_number: number | null;
  is_manual_hard_lock: boolean;
  is_active: boolean;
}

export interface CandidatePreviewRequest {
  candidate_count?: number;
  max_solver_time_seconds?: number;
  candidate_profiles?: string[];
  include_comparison?: boolean;
  include_explanation_facts?: boolean;
  response_mode?: "summary" | "detailed";
}

export interface CandidatePreviewResponse {
  summary: Record<string, unknown>;
  candidate_result: {
    problem_id: string;
    problem_fingerprint: string;
    requested_count: number;
    generated_count: number;
    candidates: Candidate[];
    comparison: CandidateComparison | null;
    attempts: Array<Record<string, unknown>>;
    warnings: Array<{ code?: string; message?: string; [key: string]: unknown }>;
    diagnostics: Array<{ code?: string; message?: string; severity?: string; [key: string]: unknown }>;
    duration_ms: number;
    deterministic: boolean;
    provenance: Record<string, unknown>;
  };
  explicit_non_actions: Record<string, boolean>;
}

export interface Candidate {
  candidate_id: string;
  candidate_profile: string;
  feasible: boolean;
  optimal: boolean;
  solver_status: string;
  quality_score: number | null;
  quality_band: string;
  assignment_fingerprint: string;
  preference_summary: Record<string, unknown>;
  fairness_summary: Record<string, unknown>;
  workload_summary: Record<string, unknown>;
  gap_summary: Record<string, unknown>;
  subject_distribution_summary: Record<string, unknown>;
  room_summary: Record<string, unknown>;
  repair_impact_summary: Record<string, unknown>;
  hard_constraint_summary?: Record<string, unknown>;
  diagnostics: Array<Record<string, unknown>>;
  warnings: Array<Record<string, unknown>>;
  quality_components?: Array<{ key: string; score: number | null; max_score: number | null; priority: string; evidence: Record<string, unknown> }>;
  explanation_facts?: Array<Record<string, unknown>>;
  assignments?: AssignmentRow[];
  class_facing_assignments?: AssignmentRow[];
}

export interface AssignmentRow {
  occurrence_id: string;
  requirement_id?: string | null;
  class_id: string;
  subject_id?: string | null;
  day_key: string;
  period_key: string;
  teacher_id?: string | null;
  room_id?: string | null;
  parallel_block_id?: string | null;
  parallel_child_id?: string | null;
  fixed?: boolean;
  lock_state?: string | null;
  periods_per_session?: number;
  occupied_period_keys?: string[];
}

export interface CandidateComparison {
  recommended_candidate_id: string | null;
  recommendation_reason_codes: string[];
  pairwise: Array<{
    left_candidate_id: string;
    right_candidate_id: string;
    relation: string;
    assignment_difference_count: number;
    assignment_difference_ratio: number;
    differences: Array<Record<string, unknown>>;
    class_facing_differences: Array<Record<string, unknown>>;
    metric_deltas: Record<string, unknown>;
    reason_codes: string[];
  }>;
  explanation_facts?: Array<Record<string, unknown>>;
}

export interface RepairImpactRequest {
  repair_reason: string;
  scope_level: "minimum" | "affected_entities" | "grade" | "whole_school" | string;
  trigger_teacher_ids?: string[];
  trigger_class_ids?: string[];
  trigger_room_ids?: string[];
  trigger_requirement_ids?: string[];
  trigger_occurrence_ids?: string[];
  trigger_parallel_block_ids?: string[];
}

export interface RepairImpactPreview {
  baseline_version_id: string;
  repair_reason: string;
  repair_scope: string;
  direct_count: number;
  conditionally_movable_count: number;
  protected_count: number;
  manual_lock_count: number;
  direct_assignments: Array<Record<string, unknown>>;
  affected_teachers: string[];
  affected_classes: string[];
  affected_rooms: string[];
  affected_parallel_blocks: string[];
  stability: string;
  blockers: Array<Record<string, unknown>>;
  warnings: Array<Record<string, unknown>>;
  suggested_next_scope: string | null;
}

export interface TimetableContainer {
  id: string;
  academic_year_id: string;
  term_id: string;
  campus_id: string | null;
  name: string;
  status: string;
  is_active: boolean;
  version_count: number;
  created_at: string | null;
}

export interface TimetableVersionSummary {
  id: string;
  timetable_id: string;
  version_number: number;
  generation_configuration_id: string | null;
  source_candidate_id: string | null;
  source_problem_fingerprint: string | null;
  source_assignment_fingerprint: string | null;
  generation_mode: string | null;
  baseline_version_id: string | null;
  lifecycle_status: "candidate" | "under_review" | "approved" | "published" | "superseded" | "cancelled" | string;
  effective_from: string | null;
  effective_until: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  published_at: string | null;
  superseded_at: string | null;
  superseded_by_version_id: string | null;
  candidate_profile: string | null;
  quality_snapshot: Record<string, unknown>;
  repair_impact_snapshot: Record<string, unknown>;
  diff_summary_snapshot: Record<string, unknown>;
  solver_provenance: Record<string, unknown>;
  assignment_count: number;
  created_at: string | null;
  created_by_user_id: string | null;
  assignments?: Array<Record<string, unknown>>;
}

export interface VersionDiffPayload {
  moved: number;
  teacher_changes: number;
  room_changes: number;
  counts: Record<string, number>;
  affected_teachers: string[];
  affected_classes: string[];
  affected_rooms: string[];
  unchanged_percentage: number;
  details: Array<Record<string, unknown>>;
}

function buildUrl(path: string, params?: Record<string, QueryValue>): string {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
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

function readError(body: unknown, status: number): { message: string; code?: string } {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return { message: detail };
    }
    if (typeof detail === "object" && detail !== null) {
      const message = "message" in detail ? String((detail as { message?: unknown }).message) : `Request failed with status ${status}.`;
      const code = "code" in detail ? String((detail as { code?: unknown }).code) : undefined;
      return { message, code };
    }
  }
  if (typeof body === "string" && body.trim()) {
    return { message: body };
  }
  return { message: `Request failed with status ${status}.` };
}

async function request<T>(path: string, options?: RequestOptions): Promise<T> {
  const headers = new Headers();
  const token = readAccessToken();
  headers.set("X-Tenant-Slug", readTenantSlug());
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (options?.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options?.params), {
      method: options?.method || "GET",
      headers,
      body: options?.body instanceof FormData ? options.body : options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options?.signal,
    });
  } catch {
    throw new TimetableGenerationApiError(0, "Network request failed.", null);
  }

  const body = await parseBody(response);
  if (!response.ok) {
    const parsed = readError(body, response.status);
    throw new TimetableGenerationApiError(response.status, parsed.message, body, parsed.code);
  }
  return body as T;
}

export function listGenerationConfigurations(params?: { lifecycle_status?: string; signal?: AbortSignal }): Promise<GenerationConfiguration[]> {
  const { signal, ...filters } = params || {};
  return request<GenerationConfiguration[]>("/leadership/timetable-generation/configurations", { params: filters, signal });
}

export function getGenerationConfigurationSummary(configurationId: string, signal?: AbortSignal): Promise<GenerationConfigurationSummary> {
  return request<GenerationConfigurationSummary>(`/leadership/timetable-generation/configurations/${configurationId}/summary`, { signal });
}

export function listTeacherPreferences(params?: { active_only?: boolean; signal?: AbortSignal }): Promise<TeacherPreference[]> {
  const { signal, ...filters } = params || {};
  return request<TeacherPreference[]>("/leadership/timetable-generation/preferences", { params: filters, signal });
}

export function listGenerationLocks(configurationId: string, signal?: AbortSignal): Promise<GenerationLock[]> {
  return request<GenerationLock[]>(`/leadership/timetable-generation/configurations/${configurationId}/locks`, { signal });
}

export function previewTimetableCandidates(configurationId: string, body: CandidatePreviewRequest, signal?: AbortSignal): Promise<CandidatePreviewResponse> {
  return request<CandidatePreviewResponse>(`/leadership/timetable-generation/configurations/${configurationId}/candidates/preview`, {
    method: "POST",
    body,
    signal,
  });
}

export function previewRepairImpact(configurationId: string, body: RepairImpactRequest, signal?: AbortSignal): Promise<RepairImpactPreview> {
  return request<RepairImpactPreview>(`/leadership/timetable-generation/configurations/${configurationId}/repair/impact-preview`, {
    method: "POST",
    body,
    signal,
  });
}

export function materializeVersionFromCandidate(
  configurationId: string,
  body: {
    candidate_id: string;
    expected_problem_fingerprint: string;
    expected_assignment_fingerprint?: string;
    candidate_count?: number;
    candidate_profiles?: string[];
    candidate_profile?: string;
    effective_from?: string;
    label?: string;
  },
  signal?: AbortSignal,
): Promise<{ timetable: TimetableContainer; version: TimetableVersionSummary; explicit_non_actions: Record<string, unknown> }> {
  return request(`/leadership/timetable-generation/configurations/${configurationId}/versions/from-candidate`, {
    method: "POST",
    body,
    signal,
  });
}

export function listTimetables(signal?: AbortSignal): Promise<{ items: TimetableContainer[]; count: number }> {
  return request<{ items: TimetableContainer[]; count: number }>("/leadership/timetable-generation/timetables", { signal });
}

export function listTimetableVersions(timetableId: string, signal?: AbortSignal): Promise<{ items: TimetableVersionSummary[]; count: number }> {
  return request<{ items: TimetableVersionSummary[]; count: number }>(`/leadership/timetable-generation/timetables/${timetableId}/versions`, { signal });
}

export function getTimetableVersion(versionId: string, includeAssignments = false, signal?: AbortSignal): Promise<TimetableVersionSummary> {
  return request<TimetableVersionSummary>(`/leadership/timetable-generation/timetable-versions/${versionId}`, {
    params: { include_assignments: includeAssignments },
    signal,
  });
}

export function submitTimetableVersion(versionId: string, signal?: AbortSignal): Promise<TimetableVersionSummary> {
  return request<TimetableVersionSummary>(`/leadership/timetable-generation/timetable-versions/${versionId}/submit`, { method: "POST", signal });
}

export function approveTimetableVersion(versionId: string, signal?: AbortSignal): Promise<TimetableVersionSummary> {
  return request<TimetableVersionSummary>(`/leadership/timetable-generation/timetable-versions/${versionId}/approve`, { method: "POST", signal });
}

export function publishTimetableVersion(versionId: string, effectiveFrom: string, signal?: AbortSignal): Promise<TimetableVersionSummary> {
  return request<TimetableVersionSummary>(`/leadership/timetable-generation/timetable-versions/${versionId}/publish`, {
    method: "POST",
    body: { effective_from: effectiveFrom },
    signal,
  });
}

export function cancelTimetableVersion(versionId: string, signal?: AbortSignal): Promise<TimetableVersionSummary> {
  return request<TimetableVersionSummary>(`/leadership/timetable-generation/timetable-versions/${versionId}/cancel`, { method: "POST", signal });
}

export function getVersionDiff(
  versionId: string,
  otherVersionId: string,
  params?: { include_details?: boolean; signal?: AbortSignal },
): Promise<VersionDiffPayload> {
  const { signal, ...query } = params || {};
  return request<VersionDiffPayload>(`/leadership/timetable-generation/timetable-versions/${versionId}/diff/${otherVersionId}`, {
    params: query,
    signal,
  });
}

export function getEffectiveTimetableVersion(
  timetableId: string,
  on: string,
  includeAssignments = false,
  signal?: AbortSignal,
): Promise<{ effective_on: string; version: TimetableVersionSummary | null }> {
  return request<{ effective_on: string; version: TimetableVersionSummary | null }>(`/leadership/timetable-generation/timetables/${timetableId}/effective-version`, {
    params: { on, include_assignments: includeAssignments },
    signal,
  });
}