import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";

export type ScopeType =
  | "whole_school"
  | "campus"
  | "grade_levels"
  | "classes"
  | "departments"
  | "staff_roles"
  | "selected_users"
  | "public_information";

export type EventReviewStatus = "pending_review" | "approved" | "rejected";
export type EventLifecycleStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "published"
  | "rescheduled"
  | "cancelled"
  | "superseded"
  | "archived"
  | "rejected";

export type EventSourceType =
  | "manual"
  | "excel_import"
  | "csv_import"
  | "pdf_extraction"
  | "agent_recommendation"
  | "system_generated";

export type CandidateStatus = "proposed" | "edited" | "approved" | "rejected" | "committed";
export type DateParseStatus = "parsed" | "ambiguous" | "hijri_unresolved" | "invalid_range" | "missing";

export interface EventScope {
  scope_type: ScopeType;
  campus?: string | null;
  grade_levels?: string[];
  classes?: string[];
  departments?: string[];
  staff_roles?: string[];
  selected_users?: string[];
  public_information?: boolean;
  contains_confidential_staffing?: boolean;
}

export interface ManualEventCreateRequest {
  event_name: string;
  description?: string | null;
  start_date: string;
  end_date: string;
  event_type: string;
  teaching_day_effect: string;
  scope: EventScope;
  source_reference?: string | null;
}

export interface ManualEventPatchRequest {
  event_name?: string;
  description?: string | null;
  start_date?: string;
  end_date?: string;
  event_type?: string;
  teaching_day_effect?: string;
  scope?: EventScope;
  reason?: string | null;
}

export interface ManualEvent {
  id: string;
  event_name: string;
  description: string | null;
  start_date: string;
  end_date: string;
  event_type: string;
  teaching_day_effect: string;
  source_type: EventSourceType;
  review_status: EventReviewStatus;
  lifecycle_status: EventLifecycleStatus;
  version_number: number;
  change_reason: string | null;
  impact_scope_json: EventScope;
  notification_plan_status: string;
  notification_plan_json: Record<string, unknown>;
  published_at: string | null;
  is_active: boolean;
}

export interface EventRescheduleRequest {
  new_start_date: string;
  new_end_date: string;
  reason: string;
}

export interface EventStatusReasonRequest {
  reason: string;
}

export interface NotificationPlanDraftRequest {
  trigger_reason: string;
  subject: string;
  proposed_message: string;
  channels: string[];
  urgency?: "low" | "normal" | "high" | "critical";
  scheduled_at?: string | null;
  reminder_settings?: Record<string, unknown> | null;
}

export interface EventVersion {
  id: string;
  event_id: string;
  version_number: number;
  change_type: string;
  reason: string | null;
  previous_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  changed_fields: string[];
  source_type: EventSourceType;
  affected_stakeholder_summary: EventImpact;
  notification_plan_id: string | null;
  created_at: string;
}

export interface EventImpact {
  scope_type: ScopeType;
  audience_categories: string[];
  affected_count: number;
  role_breakdown: Record<string, number>;
  grade_breakdown: Record<string, number>;
  class_breakdown: Record<string, number>;
  department_breakdown: Record<string, number>;
  tenant_safe_references: {
    class_ids: string[];
    selected_user_ids: string[];
  };
  unresolved_targeting_issues: string[];
  privacy_notes: string[];
  recommended_channels: string[];
}

export interface EventImpactResponse {
  event_id: string;
  impact: EventImpact;
}

export interface CalendarPdfUploadResponse {
  document_id: string;
  import_batch_id: string | null;
  status: string;
  deduplicated: boolean;
  page_count?: number;
}

export interface CalendarPdfImportItem {
  document_id: string;
  import_batch_id: string | null;
  filename: string | null;
  status: string;
  page_count: number;
  created_at?: string;
}

export interface CalendarPdfImportDetail {
  document_id: string;
  import_batch_id: string | null;
  filename: string | null;
  status: string;
  page_count: number;
  extracted_char_count: number;
  error: string | null;
}

export interface CalendarPdfPageEvidence {
  page_number: number;
  text_excerpt: string | null;
  extracted_char_count: number;
}

export interface PagedResponse<T> {
  page: number;
  page_size: number;
  total: number;
  items: T[];
}

export interface CandidateEditRequest {
  proposed_event_name?: string;
  proposed_description?: string | null;
  proposed_start_date?: string;
  proposed_end_date?: string;
  proposed_event_type?: string;
  proposed_teaching_day_effect?: string;
}

export interface CalendarEventCandidate {
  id: string;
  source_document_id: string | null;
  source_page_id: string | null;
  proposed_event_name: string;
  proposed_description: string | null;
  proposed_start_date: string | null;
  proposed_end_date: string | null;
  proposed_event_type: string;
  proposed_teaching_day_effect: string;
  confidence_score: number | null;
  candidate_status: CandidateStatus;
  date_parse_status: DateParseStatus;
  uncertainty_note: string | null;
  classification_json: Record<string, unknown>;
  validation_issues_json: {
    warnings?: string[];
    blockers?: string[];
    [key: string]: unknown;
  };
  source_payload: Record<string, unknown>;
  applied_event_id: string | null;
}

export interface ValidatePdfBatchResponse {
  document_id: string;
  batch_id: string;
  status: string;
  approved_candidates: number;
  blocker_count: number;
  warning_count: number;
}

export interface CommitApprovedCandidatesRequest {
  default_scope?: EventScope | null;
}

export interface CommitPdfBatchResponse {
  batch_id: string;
  status: string;
  created_events: number;
  skipped: number;
  readiness?: Record<string, unknown>;
}

export interface CalendarPdfDiagnostics {
  document_id: string;
  diagnostics: Array<{
    candidate_id: string;
    status: CandidateStatus;
    warnings: string[];
    blockers: string[];
    date_parse_status: DateParseStatus;
    uncertainty_note: string | null;
  }>;
  blocker_count: number;
  warning_count: number;
}

export interface CalendarNotificationPlanSummary {
  id: string;
  event_id: string;
  event_version_number: number;
  trigger_reason: string;
  affected_count: number;
  approval_required: boolean;
  approval_status: string;
  outbox_status: string;
}

export interface CalendarNotificationPlanDetail {
  id: string;
  event_id: string;
  event_version_number: number;
  trigger_reason: string;
  audience_scope: EventScope;
  affected_count: number;
  subject: string;
  proposed_message: string;
  channels: string[];
  scheduled_at: string | null;
  reminder_settings: Record<string, unknown>;
  urgency: string;
  approval_required: boolean;
  approval_status: string;
  outbox_status: string;
  delivery_summary: Record<string, unknown>;
  audit_reference_json: Record<string, unknown>;
}

export interface NotificationPlanDecisionResponse {
  id: string;
  approval_status: string;
  outbox_status: string;
}

export interface DraftEventNotificationPlanResponse {
  plan_id: string;
  approval_required: boolean;
  approval_status: string;
}

export class TimetableCalendarApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "TimetableCalendarApiError";
    this.status = status;
    this.body = body;
  }
}

function buildUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function toQueryParams(input: Record<string, string | number | undefined>): string {
  const url = new URL("http://calendar.local");
  Object.entries(input).forEach(([key, value]) => {
    if (value !== undefined && String(value) !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  const query = url.searchParams.toString();
  return query ? `?${query}` : "";
}

async function parseBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return response.text();
  }
}

function readErrorMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    return String((body as { detail?: unknown }).detail);
  }
  if (typeof body === "string" && body.trim().length > 0) {
    return body;
  }
  return `Request failed with status ${status}.`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = readAccessToken();
  const tenantSlug = readTenantSlug();
  const headers = new Headers(init?.headers || {});
  headers.set("X-Tenant-Slug", tenantSlug);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      ...init,
      headers,
    });
  } catch {
    throw new TimetableCalendarApiError(0, "Network request failed.", null);
  }

  const body = await parseBody(response);
  if (!response.ok) {
    throw new TimetableCalendarApiError(response.status, readErrorMessage(body, response.status), body);
  }

  return body as T;
}

function toJsonBody(input: unknown): string {
  return JSON.stringify(input);
}

export function listManualEvents(filters: { lifecycle_status?: string } = {}): Promise<ManualEvent[]> {
  const query = toQueryParams({ lifecycle_status: filters.lifecycle_status });
  return request<ManualEvent[]>(`/leadership/timetable-setup/calendar/events${query}`, { method: "GET" });
}

export function createManualEvent(body: ManualEventCreateRequest): Promise<ManualEvent> {
  return request<ManualEvent>("/leadership/timetable-setup/calendar/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(body),
  });
}

export function getManualEvent(eventId: string): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}`, { method: "GET" });
}

export function patchManualEvent(eventId: string, body: ManualEventPatchRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(body),
  });
}

export function submitManualEvent(eventId: string, reason: EventStatusReasonRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function approveManualEvent(eventId: string, reason: EventStatusReasonRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function publishManualEvent(eventId: string, reason: EventStatusReasonRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function rescheduleManualEvent(eventId: string, body: EventRescheduleRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/reschedule`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(body),
  });
}

export function cancelManualEvent(eventId: string, reason: EventStatusReasonRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function restoreManualEvent(eventId: string, reason: EventStatusReasonRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function archiveManualEvent(eventId: string, reason: EventStatusReasonRequest): Promise<ManualEvent> {
  return request<ManualEvent>(`/leadership/timetable-setup/calendar/events/${eventId}/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function listEventVersions(eventId: string): Promise<EventVersion[]> {
  return request<EventVersion[]>(`/leadership/timetable-setup/calendar/events/${eventId}/versions`, { method: "GET" });
}

export function getEventImpact(eventId: string): Promise<EventImpactResponse> {
  return request<EventImpactResponse>(`/leadership/timetable-setup/calendar/events/${eventId}/impact`, { method: "GET" });
}

export function draftEventNotificationPlan(eventId: string, body: NotificationPlanDraftRequest): Promise<DraftEventNotificationPlanResponse> {
  return request<DraftEventNotificationPlanResponse>(`/leadership/timetable-setup/calendar/events/${eventId}/notification-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(body),
  });
}

export function uploadCalendarPdf(file: File): Promise<CalendarPdfUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<CalendarPdfUploadResponse>("/leadership/timetable-setup/calendar/pdf-intake/upload", {
    method: "POST",
    body: form,
  });
}

export function listCalendarPdfImports(): Promise<CalendarPdfImportItem[]> {
  return request<CalendarPdfImportItem[]>("/leadership/timetable-setup/calendar/pdf-intake/imports", { method: "GET" });
}

export function getCalendarPdfImport(documentId: string): Promise<CalendarPdfImportDetail> {
  return request<CalendarPdfImportDetail>(`/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}`, { method: "GET" });
}

export function getCalendarPdfPages(documentId: string, page: number, pageSize: number): Promise<PagedResponse<CalendarPdfPageEvidence>> {
  const query = toQueryParams({ page, page_size: pageSize });
  return request<PagedResponse<CalendarPdfPageEvidence>>(`/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/pages${query}`, {
    method: "GET",
  });
}

export function extractCalendarPdfCandidates(documentId: string): Promise<{ document_id: string; candidate_count: number; status: string }> {
  return request<{ document_id: string; candidate_count: number; status: string }>(
    `/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/extract`,
    { method: "POST" },
  );
}

export function listCalendarPdfCandidates(documentId: string, page = 1, pageSize = 20): Promise<PagedResponse<CalendarEventCandidate>> {
  const query = toQueryParams({ page, page_size: pageSize });
  return request<PagedResponse<CalendarEventCandidate>>(
    `/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/candidates${query}`,
    { method: "GET" },
  );
}

export function editCalendarCandidate(candidateId: string, body: CandidateEditRequest): Promise<CalendarEventCandidate> {
  return request<CalendarEventCandidate>(`/leadership/timetable-setup/calendar/pdf-intake/candidates/${candidateId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(body),
  });
}

export function approveCalendarCandidate(candidateId: string): Promise<CalendarEventCandidate> {
  return request<CalendarEventCandidate>(`/leadership/timetable-setup/calendar/pdf-intake/candidates/${candidateId}/approve`, {
    method: "POST",
  });
}

export function rejectCalendarCandidate(candidateId: string, reason: EventStatusReasonRequest): Promise<CalendarEventCandidate> {
  return request<CalendarEventCandidate>(`/leadership/timetable-setup/calendar/pdf-intake/candidates/${candidateId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function validateCalendarPdfBatch(documentId: string, requireApprovedOnly = true): Promise<ValidatePdfBatchResponse> {
  return request<ValidatePdfBatchResponse>(`/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody({ require_approved_only: requireApprovedOnly }),
  });
}

export function commitCalendarPdfBatch(documentId: string, body: CommitApprovedCandidatesRequest): Promise<CommitPdfBatchResponse> {
  return request<CommitPdfBatchResponse>(`/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(body),
  });
}

export function getCalendarPdfDiagnostics(documentId: string): Promise<CalendarPdfDiagnostics> {
  return request<CalendarPdfDiagnostics>(`/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/diagnostics`, {
    method: "GET",
  });
}

export function cancelCalendarPdfBatch(documentId: string, reason: EventStatusReasonRequest): Promise<{ batch_id: string; status: string }> {
  return request<{ batch_id: string; status: string }>(`/leadership/timetable-setup/calendar/pdf-intake/imports/${documentId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function listNotificationPlans(eventId?: string): Promise<CalendarNotificationPlanSummary[]> {
  const query = toQueryParams({ event_id: eventId });
  return request<CalendarNotificationPlanSummary[]>(`/leadership/timetable-setup/calendar/notification-plans${query}`, { method: "GET" });
}

export function getNotificationPlan(planId: string): Promise<CalendarNotificationPlanDetail> {
  return request<CalendarNotificationPlanDetail>(`/leadership/timetable-setup/calendar/notification-plans/${planId}`, { method: "GET" });
}

export function approveNotificationPlan(planId: string, reason: EventStatusReasonRequest): Promise<NotificationPlanDecisionResponse> {
  return request<NotificationPlanDecisionResponse>(`/leadership/timetable-setup/calendar/notification-plans/${planId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}

export function cancelNotificationPlan(planId: string, reason: EventStatusReasonRequest): Promise<NotificationPlanDecisionResponse> {
  return request<NotificationPlanDecisionResponse>(`/leadership/timetable-setup/calendar/notification-plans/${planId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: toJsonBody(reason),
  });
}
