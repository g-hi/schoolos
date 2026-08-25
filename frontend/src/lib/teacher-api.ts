import { api } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type PickupStatus = "requested" | "acknowledged" | "called" | "prepared" | "completed" | "cancelled" | "released" | "rejected_outside_geofence";

export class TeacherApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "TeacherApiError";
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

function toQueryParams(params?: RequestOptions["params"]): Record<string, string> | undefined {
  if (!params) return undefined;
  const mapped = Object.entries(params).reduce<Record<string, string>>((acc, [key, value]) => {
    if (value === undefined || value === null) return acc;
    acc[key] = String(value);
    return acc;
  }, {});
  return Object.keys(mapped).length > 0 ? mapped : undefined;
}

function parseApiError(error: unknown): TeacherApiError {
  if (!(error instanceof Error)) {
    return new TeacherApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) {
    return new TeacherApiError(0, error.message || "Request failed.", null);
  }
  const status = Number(match[1]);
  const bodyText = match[2] ?? "";
  let parsedBody: unknown = bodyText;
  try {
    parsedBody = JSON.parse(bodyText);
  } catch {
    parsedBody = bodyText;
  }
  const detail =
    typeof parsedBody === "object" &&
    parsedBody !== null &&
    "detail" in parsedBody &&
    typeof (parsedBody as { detail?: unknown }).detail === "string"
      ? (parsedBody as { detail: string }).detail
      : bodyText;
  return new TeacherApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

async function teacherRequest<T>(path: string, options?: RequestOptions): Promise<T> {
  const token = options?.token ?? readAccessToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (options?.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  try {
    return await api<T>(path, {
      method: options?.method ?? "GET",
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      params: toQueryParams(options?.params),
    });
  } catch (error) {
    throw parseApiError(error);
  }
}

// Teacher Pickup Types
export interface PickupRequest {
  pickup_id: string;
  student_id: string;
  parent_id: string;
  class_id: string;
  teacher_id: string | null;
  status: PickupStatus;
  channel: string | null;
  requested_at: string | null;
  acknowledged_at: string | null;
  called_at: string | null;
  prepared_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  verified_by: string | null;
  verified_at: string | null;
  verification_method: string | null;
  verification_note: string | null;
  notes: string | null;
  within_geofence: boolean;
  distance_meters: number | null;
  early_pickup: boolean;
}

export interface PickupListResponse {
  items: PickupRequest[];
  page: number;
  page_size: number;
}

export interface PickupTransitionRequest {
  note?: string | null;
}

export interface PickupCompleteRequest extends PickupTransitionRequest {
  verification_method: string;
  verification_note: string;
}

export interface TeacherMyClassesAssignment {
  assignment_type: "homeroom" | "subject_teacher";
  subject_id: string | null;
  subject_code: string | null;
  subject_name: string | null;
  start_date: string | null;
  end_date: string | null;
}

export interface TeacherMyClassesSchedule {
  weekly_periods: number;
  next_period: {
    day_of_week: number;
    period_name: string;
    start_time: string;
    end_time: string;
    subject_name?: string | null;
  } | null;
}

export interface TeacherMyClassItem {
  class_id: string;
  code: string | null;
  grade_level: string;
  section: string;
  academic_year_id: string | null;
  academic_year: string;
  campus_id: string | null;
  campus: string | null;
  is_active: boolean;
  student_count: number;
  assignment_source: "canonical" | "legacy";
  assignments: TeacherMyClassesAssignment[];
  schedule: TeacherMyClassesSchedule;
}

export interface TeacherMyClassesSummary {
  total_classes: number;
  homeroom_classes: number;
  subject_classes: number;
  canonical_classes: number;
  legacy_classes: number;
}

export interface TeacherMyClassesResponse {
  effective_date: string;
  teacher: {
    id: string;
    display_name: string;
  };
  summary: TeacherMyClassesSummary;
  classes: TeacherMyClassItem[];
}

// Teacher operational attendance API surface (Phase 10D-3A)
export interface TeacherAttendanceSessionItem {
  daily_session_id: string;
  class_facing_session_key: string;
  school_date: string;
  class_id: string;
  subject_id: string;
  class_code: string | null;
  grade_level: string | null;
  section: string | null;
  class_display_name: string;
  subject_name: string | null;
  teacher_id: string;
  start_time: string;
  end_time: string;
  session_status: string;
  attendance_eligible: boolean;
  attendance_register_id: string | null;
  attendance_status: string;
  expected_count: number;
  marked_count: number;
  unmarked_count: number;
}

export interface TeacherAttendanceTodayResponse {
  school_date: string;
  items: TeacherAttendanceSessionItem[];
}

export interface TeacherAttendanceRegisterRecord {
  student_id: string;
  student_name: string;
  student_identifier: string | null;
  attendance_status: "present" | "absent" | "late" | "excused" | "unmarked" | string;
  minutes_late: number | null;
  marked_at: string | null;
}

export interface TeacherAttendanceRegisterDetail {
  register_id: string;
  class_facing_session_key: string;
  school_date: string;
  register_status: "open" | "submitted" | "finalized" | string;
  roster_resolution_status?: string;
  expected_count: number;
  marked_count: number;
  unmarked_count: number;
  records: TeacherAttendanceRegisterRecord[];
}

export async function getTeacherAttendanceToday(
  options?: { school_date?: string },
  token?: string | null,
): Promise<TeacherAttendanceTodayResponse> {
  return teacherRequest<TeacherAttendanceTodayResponse>("/teacher/operations/attendance/today", {
    method: "GET",
    token,
    params: {
      school_date: options?.school_date,
    },
  });
}

export async function getTeacherAttendanceSessions(
  school_date: string,
  token?: string | null,
): Promise<TeacherAttendanceTodayResponse> {
  return teacherRequest<TeacherAttendanceTodayResponse>("/teacher/operations/attendance/sessions", {
    method: "GET",
    token,
    params: {
      school_date,
    },
  });
}

export async function ensureTeacherAttendanceRegister(
  daily_session_id: string,
  token?: string | null,
): Promise<{ register_id: string; register_status: string }> {
  return teacherRequest<{ register_id: string; register_status: string }>("/teacher/operations/attendance/registers/ensure", {
    method: "POST",
    token,
    body: {
      daily_session_id,
    },
  });
}

export async function getTeacherAttendanceRegister(
  register_id: string,
  token?: string | null,
): Promise<TeacherAttendanceRegisterDetail> {
  return teacherRequest<TeacherAttendanceRegisterDetail>(`/teacher/operations/attendance/registers/${register_id}`, {
    method: "GET",
    token,
  });
}

export async function bulkMarkTeacherAttendance(
  register_id: string,
  marks: Array<{ student_id: string; status: string; minutes_late?: number | null }>,
  token?: string | null,
): Promise<{ register_id: string; register_status: string }> {
  return teacherRequest<{ register_id: string; register_status: string }>(`/teacher/operations/attendance/registers/${register_id}/bulk-mark`, {
    method: "POST",
    token,
    body: {
      marks,
    },
  });
}

export async function markAllPresentTeacherAttendance(
  register_id: string,
  token?: string | null,
): Promise<{ register_id: string; register_status: string }> {
  return teacherRequest<{ register_id: string; register_status: string }>(`/teacher/operations/attendance/registers/${register_id}/mark-all-present`, {
    method: "POST",
    token,
  });
}

export async function submitTeacherAttendanceRegister(
  register_id: string,
  token?: string | null,
): Promise<{ register_id: string; register_status: string }> {
  return teacherRequest<{ register_id: string; register_status: string }>(`/teacher/operations/attendance/registers/${register_id}/submit`, {
    method: "POST",
    token,
  });
}

// Leadership operational attendance API surface (Phase 10D-3B2)

export interface LeadershipAttendanceDailySummary {
  school_date: string;
  eligible_sessions: number;
  not_started: number;
  open: number;
  submitted: number;
  finalized: number;
  parallel_unresolved: number;
  expected_students: number;
  present: number;
  absent: number;
  late: number;
  excused: number;
  unmarked: number;
}

export interface LeadershipAttendanceRegisterListItem {
  register_id: string;
  class_id: string;
  class_facing_session_key: string;
  class_code: string | null;
  grade_level: string | null;
  section: string | null;
  class_display_name: string;
  subject_name: string | null;
  teacher_name: string | null;
  start_time: string | null;
  end_time: string | null;
  status: "open" | "submitted" | "finalized" | string;
  roster_resolution_status: string;
  expected: number;
  marked: number;
  unmarked: number;
  present: number;
  absent: number;
  late: number;
  excused: number;
}

export interface LeadershipAttendanceRegisterRecord {
  student_id: string;
  student_name: string;
  student_identifier: string | null;
  status: "present" | "absent" | "late" | "excused" | "unmarked" | string;
  minutes_late: number | null;
  marked_by: string | null;
  marked_at: string | null;
}


export interface LeadershipAttendanceRegisterDetail {
  register_id: string;
  school_date: string;
  class_id: string;
  class_facing_session_key: string;
  register_status: "open" | "submitted" | "finalized" | string;
  roster_resolution_status: string;
  expected_count: number;
  records: LeadershipAttendanceRegisterRecord[];
  marked_count: number;
  unmarked_count: number;
}

export async function getLeadershipAttendanceDailySummary(
  school_date: string,
  token?: string | null,
): Promise<LeadershipAttendanceDailySummary> {
  return teacherRequest<LeadershipAttendanceDailySummary>(
    "/leadership/operations/attendance/daily-summary",
    {
      method: "GET",
      token,
      params: {
        school_date,
      },
    },
  );
}

export async function listLeadershipAttendanceRegisters(
  school_date: string,
  token?: string | null,
): Promise<LeadershipAttendanceRegisterListItem[]> {
  return teacherRequest<LeadershipAttendanceRegisterListItem[]>(
    "/leadership/operations/attendance/registers",
    {
      method: "GET",
      token,
      params: {
        school_date,
      },
    },
  );
}

export async function getLeadershipAttendanceRegister(
  register_id: string,
  token?: string | null,
): Promise<LeadershipAttendanceRegisterDetail> {
  return teacherRequest<LeadershipAttendanceRegisterDetail>(
    `/leadership/operations/attendance/registers/${register_id}`,
    {
      method: "GET",
      token,
    },
  );
}

export async function finalizeLeadershipAttendanceRegister(
  register_id: string,
  token?: string | null,
): Promise<{ register_id: string; register_status: string }> {
  return teacherRequest<{ register_id: string; register_status: string }>(
    `/leadership/operations/attendance/registers/${register_id}/finalize`,
    {
      method: "POST",
      token,
    },
  );
}

export async function correctLeadershipAttendanceRegister(
  register_id: string,
  correction: {
    student_id: string;
    new_status: "present" | "absent" | "late" | "excused" | string;
    correction_reason: string;
  },
  token?: string | null,
): Promise<{ student_id: string; attendance_status: string }> {
  return teacherRequest<{ student_id: string; attendance_status: string }>(
    `/leadership/operations/attendance/registers/${register_id}/correct`,
    {
      method: "POST",
      token,
      body: correction,
    },
  );
}

// Teacher Pickup Endpoints
export async function listTeacherPickupRequests(
  query?: { status?: PickupStatus; page?: number; page_size?: number },
  token?: string | null,
): Promise<PickupListResponse> {
  return teacherRequest<PickupListResponse>("/teacher/pickup-requests", {
    method: "GET",
    token,
    params: {
      status: query?.status,
      page: query?.page ?? 1,
      page_size: query?.page_size ?? 20,
    },
  });
}

export async function getTeacherPickupRequest(
  pickupId: string,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/teacher/pickup-requests/${pickupId}`, {
    method: "GET",
    token,
  });
}

export async function acknowledgeTeacherPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/teacher/pickup-requests/${pickupId}/acknowledge`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}

export async function callTeacherPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/teacher/pickup-requests/${pickupId}/call`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}

export async function prepareTeacherPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/teacher/pickup-requests/${pickupId}/prepare`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}

export async function getTeacherMyClasses(
  options?: { effective_date?: string },
  token?: string | null,
): Promise<TeacherMyClassesResponse> {
  return teacherRequest<TeacherMyClassesResponse>("/teacher/my-classes", {
    method: "GET",
    token,
    params: {
      effective_date: options?.effective_date,
    },
  });
}

// Leadership Pickup Endpoints
export async function listLeadershipPickupRequests(
  query?: { status?: PickupStatus; page?: number; page_size?: number },
  token?: string | null,
): Promise<PickupListResponse> {
  return teacherRequest<PickupListResponse>("/leadership/pickup-requests", {
    method: "GET",
    token,
    params: {
      status: query?.status,
      page: query?.page ?? 1,
      page_size: query?.page_size ?? 20,
    },
  });
}

export async function getLeadershipPickupRequest(
  pickupId: string,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/leadership/pickup-requests/${pickupId}`, {
    method: "GET",
    token,
  });
}

export async function acknowledgeLeadershipPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/leadership/pickup-requests/${pickupId}/acknowledge`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}

export async function callLeadershipPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/leadership/pickup-requests/${pickupId}/call`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}

export async function prepareLeadershipPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/leadership/pickup-requests/${pickupId}/prepare`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}

export async function completeLeadershipPickupRequest(
  pickupId: string,
  body: PickupCompleteRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/leadership/pickup-requests/${pickupId}/complete`, {
    method: "POST",
    token,
    body,
  });
}

export async function cancelLeadershipPickupRequest(
  pickupId: string,
  body?: PickupTransitionRequest,
  token?: string | null,
): Promise<PickupRequest> {
  return teacherRequest<PickupRequest>(`/leadership/pickup-requests/${pickupId}/cancel`, {
    method: "POST",
    token,
    body: body ?? {},
  });
}
