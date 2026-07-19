import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://schoolos-gateway.onrender.com");
const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export const setStaffUnauthorizedHandler = setUnauthorizedHandler;

export class StaffApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "StaffApiError";
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  token?: string | null;
  params?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function staffRequest<T>(path: string, options?: RequestOptions): Promise<T> {
  const headers = new Headers();
  headers.set("X-Tenant-Slug", readTenantSlug() || TENANT);

  const token = options?.token ?? readAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (options?.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options?.params), {
      method: options?.method || "GET",
      headers,
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new StaffApiError(0, "Network request failed.", null);
  }

  const parsedBody = await parseResponseBody(response);
  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler) {
      unauthorizedHandler();
    }

    const errorMessage =
      typeof parsedBody === "object" &&
      parsedBody !== null &&
      "detail" in parsedBody &&
      typeof (parsedBody as { detail?: unknown }).detail === "string"
        ? (parsedBody as { detail: string }).detail
        : typeof parsedBody === "string"
          ? parsedBody
          : `Request failed with status ${response.status}.`;

    throw new StaffApiError(response.status, errorMessage, parsedBody);
  }

  return parsedBody as T;
}

export interface WeeklyReportStudentOption {
  student_id: string;
  student_display_name: string;
  class_name: string;
}

export interface WeeklyReportListItem {
  report_id: string;
  student_id: string;
  student_display_name: string;
  class_name: string;
  week_start: string;
  week_end: string;
  status: string;
  current_version_number: number;
  approved_version_number: number | null;
  published_version_number: number | null;
  row_version: number;
  updated_at: string;
}

export interface WeeklyReportVersionResponse {
  version_id: string;
  version_number: number;
  source_type: string;
  validation_status: string;
  created_by_user_id: string | null;
  created_at: string;
}

export interface WeeklyReportReviewEventResponse {
  event_id: string;
  report_id: string;
  report_version_id: string | null;
  actor_user_id: string | null;
  event_type: string;
  previous_status: string | null;
  new_status: string | null;
  comment: string | null;
  created_at: string;
}

export interface WeeklyReportDetailResponse {
  report_id: string;
  student_id: string;
  student_display_name: string;
  class_name: string;
  week_start: string;
  week_end: string;
  timezone_used: string;
  status: string;
  row_version: number;
  current_version_number: number;
  approved_version_number: number | null;
  published_version_number: number | null;
  current_content: {
    title?: string;
    sections?: Array<{
      section_type: string;
      content: string;
      used_evidence_ids?: string[];
    }>;
    warnings?: string[];
  };
  current_evidence_snapshot: {
    evidence_items?: Array<{
      evidence_id: string;
      source_type: string;
      available: boolean;
      unavailable_reason?: string;
    }>;
  };
  current_validation_status: string;
  current_validation_errors: Array<{ code: string; message: string }>;
  versions: WeeklyReportVersionResponse[];
}

export interface WeeklyReportActionResult {
  report_id: string;
  status: string;
  row_version: number;
  current_version_number: number;
}

export interface InitializeWeeklyReportPayload {
  student_id: string;
  week_start: string;
  timezone_override?: string | null;
  assigned_reviewer_user_id?: string | null;
  staff_evidence?: StaffEvidenceInput;
}

export interface StaffEvidenceInput {
  weekly_teacher_summary?: string | null;
  strengths_observed?: string | null;
  achievements?: string | null;
  areas_needing_support?: string | null;
  suggested_parent_support?: string | null;
  additional_factual_note?: string | null;
}

export interface EditWeeklyReportPayload {
  expected_row_version: number;
  title?: string | null;
  sections: Array<{
    section_type: string;
    content: string;
  }>;
  staff_evidence?: StaffEvidenceInput;
}

export interface GenerateDraftPayload {
  expected_row_version: number;
  use_ai: boolean;
}

export interface StatusTransitionPayload {
  expected_row_version: number;
  comment?: string | null;
}

export async function listWeeklyReportStudents(token?: string | null): Promise<WeeklyReportStudentOption[]> {
  return staffRequest<WeeklyReportStudentOption[]>("/weekly-reports/students", { token });
}

export async function listWeeklyReports(
  query?: { studentId?: string; statusFilter?: string },
  token?: string | null,
): Promise<WeeklyReportListItem[]> {
  return staffRequest<WeeklyReportListItem[]>("/weekly-reports", {
    token,
    params: {
      student_id: query?.studentId,
      status_filter: query?.statusFilter,
    },
  });
}

export async function initializeWeeklyReport(body: InitializeWeeklyReportPayload, token?: string | null): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>("/weekly-reports/init", {
    method: "POST",
    token,
    body,
  });
}

export async function getWeeklyReport(reportId: string, token?: string | null): Promise<WeeklyReportDetailResponse> {
  return staffRequest<WeeklyReportDetailResponse>(`/weekly-reports/${reportId}`, { token });
}

export async function editWeeklyReportDraft(
  reportId: string,
  body: EditWeeklyReportPayload,
  token?: string | null,
): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>(`/weekly-reports/${reportId}/draft`, {
    method: "PATCH",
    token,
    body,
  });
}

export async function generateWeeklyReportDraft(
  reportId: string,
  body: GenerateDraftPayload,
  token?: string | null,
): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>(`/weekly-reports/${reportId}/generate`, {
    method: "POST",
    token,
    body,
  });
}

export async function submitWeeklyReportForReview(
  reportId: string,
  body: StatusTransitionPayload,
  token?: string | null,
): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>(`/weekly-reports/${reportId}/submit-review`, {
    method: "POST",
    token,
    body,
  });
}

export async function requestWeeklyReportChanges(
  reportId: string,
  body: StatusTransitionPayload,
  token?: string | null,
): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>(`/weekly-reports/${reportId}/request-changes`, {
    method: "POST",
    token,
    body,
  });
}

export async function approveWeeklyReport(
  reportId: string,
  body: StatusTransitionPayload,
  token?: string | null,
): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>(`/weekly-reports/${reportId}/approve`, {
    method: "POST",
    token,
    body,
  });
}

export async function publishWeeklyReport(
  reportId: string,
  body: StatusTransitionPayload,
  token?: string | null,
): Promise<WeeklyReportActionResult> {
  return staffRequest<WeeklyReportActionResult>(`/weekly-reports/${reportId}/publish`, {
    method: "POST",
    token,
    body,
  });
}

export async function getWeeklyReportVersions(reportId: string, token?: string | null): Promise<WeeklyReportVersionResponse[]> {
  return staffRequest<WeeklyReportVersionResponse[]>(`/weekly-reports/${reportId}/versions`, { token });
}

export async function getWeeklyReportReviewEvents(reportId: string, token?: string | null): Promise<WeeklyReportReviewEventResponse[]> {
  return staffRequest<WeeklyReportReviewEventResponse[]>(`/weekly-reports/${reportId}/review-events`, { token });
}
