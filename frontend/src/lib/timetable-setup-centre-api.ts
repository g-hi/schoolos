import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";

type QueryValue = string | number | boolean | undefined | null;

export class TimetableSetupCentreApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "TimetableSetupCentreApiError";
    this.status = status;
    this.body = body;
  }
}

export interface SetupCentreProgress {
  completed_steps: number;
  total_steps: number;
  completed_weight: number;
  total_weight: number;
  applicable_weight?: number;
  excluded_weight?: number;
  progress_percentage: number;
  explanation?: string | null;
}

export interface SetupCentreGenerationAction {
  issue_key: string;
  title: string;
  recommended_action: string;
  setup_route: string;
  requires_human_authorization: boolean;
  authorized_roles: string[];
}

export interface SetupCentreGeneration {
  generation_allowed: boolean;
  readiness_status: string;
  blocker_count: number;
  warning_count: number;
  information_count: number;
  pending_approval_count: number;
  conditional_ready?: boolean;
  required_actions: SetupCentreGenerationAction[];
}

export interface SetupCentreStep {
  step_key: string;
  title: string;
  status: string;
  weight: number;
  applicable: boolean;
  approved_count: number;
  pending_count: number;
  required_minimum: number;
  prerequisites: string[];
  route: string;
  policy_rule: string;
  authorized_roles: string[];
  source_summary: Record<string, number>;
  review_summary: Record<string, number>;
  lifecycle_summary: Record<string, number>;
}

export interface SetupCentreIssue {
  issue_key: string;
  source: string;
  step_key: string;
  severity: "blocker" | "warning" | "information" | string;
  status: string;
  title: string;
  summary: string;
  policy_rule: string;
  explanation: string;
  affected_count: number;
  recommended_action: string;
  setup_route: string;
  authorized_roles: string[];
  requires_human_authorization: boolean;
  resolved: boolean;
  related_entity?: { type: string; id: string };
  created_at?: string | null;
  blocker_relationship?: string;
  tenant_safe_references?: Record<string, unknown>;
}

export interface SetupCentreApprovalQueueItem {
  approval_key?: string;
  type?: string;
  title: string;
  summary: string;
  urgency: string;
  setup_step: string;
  source: string;
  created_at: string;
  required_approver_roles?: string[];
  recommended_action: string;
  route?: string;
  setup_route?: string;
  blocker_relationship: string;
  related_entity?: { type: string; id: string };
  tenant_safe_references?: Record<string, unknown>;
  requires_human_authorization: boolean;
  pending_count?: number;
  policy_rule?: string;
  next_action?: string;
  authorized_roles?: string[];
  blocks_generation?: boolean;
}

export interface SetupCentreImportRecord {
  id?: string;
  original_filename?: string | null;
  status?: string | null;
  source_type?: string | null;
  extraction_status?: string | null;
  page_count?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SetupCentreImportSummary {
  direct_route: string;
  latest_import: SetupCentreImportRecord | null;
  status_counts: Record<string, number>;
  pending_count: number;
  unresolved_mapping_count: number;
  blocker_count: number;
  review_count: number;
  committed_count: number;
  failed_count: number;
  latest_status?: string | null;
  pdf_state_counts?: Record<string, number>;
  candidate_review_counts?: Record<string, number>;
}

export interface SetupCentreImportSummaries {
  workbook: SetupCentreImportSummary;
  pdf: SetupCentreImportSummary;
  total_pending: number;
  total_failed: number;
  total_committed: number;
  latest_imports: {
    workbook: SetupCentreImportRecord | null;
    pdf: SetupCentreImportRecord | null;
  };
}

export interface SetupCentreProvenance {
  source_breakdown: Record<string, number>;
  review_breakdown: Record<string, number>;
  lifecycle_counts: Record<string, number>;
  manual_count: number;
  excel_import_count: number;
  pdf_extraction_count: number;
  agent_recommendation_count: number;
  system_generated_count: number;
  inactive_count: number;
}

export interface SetupCentrePolicy {
  authorized_roles: string[];
  agent_allowed_actions: string[];
  agent_prohibited_actions: string[];
  human_approval_required_for: string[];
}

export interface SetupCentreSummary {
  generated_at: string;
  progress: SetupCentreProgress;
  generation: SetupCentreGeneration;
  provenance: SetupCentreProvenance;
  source_breakdown: Record<string, number>;
  review_breakdown: Record<string, number>;
  import_summaries: SetupCentreImportSummaries;
  approval_queue: {
    items: SetupCentreApprovalQueueItem[];
    pending_total: number;
    direct_route: string;
  };
  policy: SetupCentrePolicy;
  counts: Record<string, number>;
  progress_explanation?: string | null;
}

export interface SetupCentreStepDetail {
  generated_at: string;
  step: SetupCentreStep;
  related_issues: SetupCentreIssue[];
}

export interface SetupCentreIssuesResponse {
  generated_at: string;
  total: number;
  page: number;
  page_size: number;
  items: SetupCentreIssue[];
  direct_route: string;
}

export interface SetupCentreApprovalsResponse {
  generated_at: string;
  pending_total: number;
  items: SetupCentreApprovalQueueItem[];
  total: number;
  page: number;
  page_size: number;
  direct_route: string;
}

export interface SetupCentreActivityItem {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_id: string | null;
  created_at: string;
  detail_summary: Record<string, unknown>;
}

export interface SetupCentreActivityResponse {
  items: SetupCentreActivityItem[];
  total: number;
  page: number;
  page_size: number;
  direct_route: string;
}

export interface SetupCentreRecommendation {
  recommendation_key: string;
  priority_score: number;
  title: string;
  why?: string;
  recommended_action: string;
  setup_route: string;
  authorized_roles: string[];
  requires_human_authorization: boolean;
  agent_can_execute: boolean;
}

export interface SetupCentreRecommendationsResponse {
  generated_at: string;
  generation: SetupCentreGeneration;
  recommendations: SetupCentreRecommendation[];
  policy: SetupCentrePolicy;
}

export interface SetupCentreRevalidateResponse {
  revalidated: boolean;
  generated_at: string;
  generation: SetupCentreGeneration;
  progress: SetupCentreProgress;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  params?: Record<string, QueryValue>;
  signal?: AbortSignal;
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

function readMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    return String((body as { detail?: unknown }).detail);
  }
  if (typeof body === "string" && body.trim()) {
    return body;
  }
  return `Request failed with status ${status}.`;
}

async function request<T>(path: string, options?: RequestOptions): Promise<T> {
  const headers = new Headers(options?.body !== undefined && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined);
  const token = readAccessToken();
  headers.set("X-Tenant-Slug", readTenantSlug());
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
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
    throw new TimetableSetupCentreApiError(0, "Network request failed.", null);
  }

  const body = await parseBody(response);
  if (!response.ok) {
    throw new TimetableSetupCentreApiError(response.status, readMessage(body, response.status), body);
  }

  return body as T;
}

export function getSetupCentreSummary(signal?: AbortSignal): Promise<SetupCentreSummary> {
  return request<SetupCentreSummary>("/leadership/timetable-setup/centre/summary", { signal });
}

export function getSetupCentreSteps(signal?: AbortSignal): Promise<{ generated_at: string; progress: SetupCentreProgress; steps: SetupCentreStep[]; progress_explanation?: string | null }> {
  return request("/leadership/timetable-setup/centre/steps", { signal });
}

export function getSetupCentreStep(stepKey: string, signal?: AbortSignal): Promise<SetupCentreStepDetail> {
  return request<SetupCentreStepDetail>(`/leadership/timetable-setup/centre/steps/${stepKey}`, { signal });
}

export function getSetupCentreIssues(params?: {
  severity?: string;
  setup_step?: string;
  source?: string;
  resolved?: boolean;
  requires_approval?: boolean;
  page?: number;
  page_size?: number;
  signal?: AbortSignal;
}): Promise<SetupCentreIssuesResponse> {
  const { signal, ...filters } = params || {};
  return request<SetupCentreIssuesResponse>("/leadership/timetable-setup/centre/issues", {
    params: filters,
    signal,
  });
}

export function getSetupCentreApprovals(params?: {
  type?: string;
  urgency?: string;
  setup_step?: string;
  page?: number;
  page_size?: number;
  signal?: AbortSignal;
}): Promise<SetupCentreApprovalsResponse> {
  const { signal, ...filters } = params || {};
  return request<SetupCentreApprovalsResponse>("/leadership/timetable-setup/centre/approvals", {
    params: filters,
    signal,
  });
}

export function getSetupCentreActivity(params?: {
  action_type?: string;
  entity_type?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  page_size?: number;
  signal?: AbortSignal;
}): Promise<SetupCentreActivityResponse> {
  const { signal, ...filters } = params || {};
  return request<SetupCentreActivityResponse>("/leadership/timetable-setup/centre/activity", {
    params: filters,
    signal,
  });
}

export function getSetupCentreRecommendations(signal?: AbortSignal): Promise<SetupCentreRecommendationsResponse> {
  return request<SetupCentreRecommendationsResponse>("/leadership/timetable-setup/centre/recommendations", { signal });
}

export function revalidateSetupCentre(signal?: AbortSignal): Promise<SetupCentreRevalidateResponse> {
  return request<SetupCentreRevalidateResponse>("/leadership/timetable-setup/centre/revalidate", {
    method: "POST",
    signal,
  });
}