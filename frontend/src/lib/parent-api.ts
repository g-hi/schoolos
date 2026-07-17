const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://schoolos-gateway.onrender.com");
const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";

let unauthorizedHandler: (() => void) | null = null;

export function setParentUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export class ParentApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ParentApiError";
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
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
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parentRequest<T>(path: string, options?: RequestOptions): Promise<T> {
  const headers = new Headers();
  headers.set("X-Tenant-Slug", TENANT);

  if (options?.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
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
    throw new ParentApiError(0, "Network request failed.", null);
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

    throw new ParentApiError(response.status, errorMessage, parsedBody);
  }

  return parsedBody as T;
}

export interface ParentLoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface ParentProfileResponse {
  user_id: string;
  name: string;
  email: string;
  role: string;
  family_id: string | null;
  family_name: string | null;
  preferred_language: string;
  timezone: string;
  theme: string;
  email_notifications: boolean;
  in_app_notifications: boolean;
}

export interface ParentStudentSummary {
  student_id: string;
  name: string;
  student_code: string;
  grade: string;
  section: string;
  class_name: string;
  homeroom_teacher: string | null;
  is_primary_guardian: boolean;
  can_pickup: boolean;
  can_view_academics: boolean;
  can_view_behaviour: boolean;
}

export interface ModuleUnavailable {
  available: false;
  reason: string;
}

export interface ParentDashboardTimelinePreview {
  event_id: string;
  event_type: string;
  title: string;
  occurred_at: string;
  priority: string | null;
  action_url: string | null;
}

export interface ParentDashboardResponse {
  family_name: string | null;
  family_id: string | null;
  students: ParentStudentSummary[];
  timeline_preview: ParentDashboardTimelinePreview[];
  pickup: {
    available: boolean;
    active_requests: Array<{
      pickup_id: string;
      student_id: string;
      status: string;
      requested_at: string | null;
    }>;
  };
  academics: ModuleUnavailable;
  attendance: ModuleUnavailable;
  homework: ModuleUnavailable;
  reports: ModuleUnavailable;
  messages: ModuleUnavailable;
  payments: ModuleUnavailable;
  announcements: ModuleUnavailable;
  notifications: ModuleUnavailable;
}

export interface ParentStudentOverviewResponse {
  student_id: string;
  name: string;
  student_code: string;
  grade: string;
  section: string;
  class_name: string;
  homeroom_teacher: string | null;
  academics: ModuleUnavailable;
  attendance: ModuleUnavailable;
  homework: ModuleUnavailable;
  behaviour: ModuleUnavailable;
  assessment_results: ModuleUnavailable;
}

export interface ParentStudentsResponse {
  students: ParentStudentSummary[];
}

export interface FamilyMember {
  parent_id: string;
  name: string;
  email: string;
  is_primary: boolean;
  student_ids: string[];
}

export interface FamilyMeResponse {
  family_id: string;
  family_name: string;
  is_active: boolean;
  members: FamilyMember[];
  students: Array<{
    student_id: string;
    name: string;
    student_code: string;
  }>;
}

export interface FamilyTimelineEvent {
  event_id: string;
  event_type: string;
  event_category: string;
  title: string;
  description: string | null;
  occurred_at: string;
  student_id: string | null;
  source_module: string;
  priority: string | null;
  action_url: string | null;
  visibility: string;
}

export interface FamilyTimelineResponse {
  events: FamilyTimelineEvent[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface FamilyTimelineQuery {
  token: string;
  limit?: number;
  cursor?: string;
  studentId?: string;
  category?: string;
}

export async function loginParent(email: string, password: string, tenantSlug: string = TENANT): Promise<ParentLoginResponse> {
  return parentRequest<ParentLoginResponse>("/auth/token", {
    method: "POST",
    body: {
      email,
      password,
      tenant_slug: tenantSlug,
    },
  });
}

export async function getParentMe(token: string): Promise<ParentProfileResponse> {
  return parentRequest<ParentProfileResponse>("/parent/me", { token });
}

export async function getParentDashboard(token: string): Promise<ParentDashboardResponse> {
  return parentRequest<ParentDashboardResponse>("/parent/dashboard", { token });
}

export async function getParentStudents(token: string): Promise<ParentStudentsResponse> {
  return parentRequest<ParentStudentsResponse>("/parent/students", { token });
}

export async function getParentStudentOverview(token: string, studentId: string): Promise<ParentStudentOverviewResponse> {
  return parentRequest<ParentStudentOverviewResponse>(`/parent/students/${studentId}`, { token });
}

export async function getFamilyMe(token: string): Promise<FamilyMeResponse> {
  return parentRequest<FamilyMeResponse>("/families/me", { token });
}

export async function getFamilyTimeline(query: FamilyTimelineQuery): Promise<FamilyTimelineResponse> {
  return parentRequest<FamilyTimelineResponse>("/families/me/timeline", {
    token: query.token,
    params: {
      limit: query.limit,
      cursor: query.cursor,
      student_id: query.studentId,
      category: query.category,
    },
  });
}
