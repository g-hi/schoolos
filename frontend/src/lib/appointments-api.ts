import { api } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type AppointmentStatus = "requested" | "confirmed" | "declined" | "cancelled" | "completed";
export type AppointmentMeetingMode = "in_person" | "video" | "phone";

export class AppointmentsApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "AppointmentsApiError";
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

function parseApiError(error: unknown): AppointmentsApiError {
  if (!(error instanceof Error)) {
    return new AppointmentsApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) {
    return new AppointmentsApiError(0, error.message || "Request failed.", null);
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
  return new AppointmentsApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

async function appointmentsRequest<T>(path: string, options?: RequestOptions): Promise<T> {
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

export interface AppointmentSummary {
  id: string;
  status: AppointmentStatus;
  scheduled_start_at: string;
}

export type ParentAppointmentDetail = AppointmentSummary;

export interface TeacherAppointmentDetail extends AppointmentSummary {
  duration_minutes: number;
  timezone: string;
  meeting_mode: AppointmentMeetingMode;
  location_or_link: string | null;
  parent_notes: string | null;
  staff_notes: string | null;
}

export interface LeadershipAppointmentSummary extends AppointmentSummary {
  parent_notes: string | null;
  staff_notes: string | null;
}

export interface LeadershipAppointmentDetail {
  id: string;
  status: AppointmentStatus;
  parent_notes: string | null;
  staff_notes: string | null;
}

export interface AppointmentListResponse<TItem> {
  items: TItem[];
  page: number;
  page_size: number;
}

export interface EligibleAppointmentTeacherOption {
  teacher_id: string;
  teacher_name: string;
  subject_id: string | null;
  subject_name: string | null;
  timetable_entry_id: string | null;
  mode: "homeroom" | "timetable";
}

export interface EligibleAppointmentTeachersResponse {
  student_id: string;
  options: EligibleAppointmentTeacherOption[];
}

export interface CreateParentAppointmentRequest {
  student_id: string;
  teacher_id: string;
  subject_id?: string | null;
  timetable_entry_id?: string | null;
  requested_start_at: string;
  duration_minutes: number;
  timezone: string;
  meeting_mode: AppointmentMeetingMode;
  location_or_link?: string | null;
  reason?: string | null;
  parent_notes?: string | null;
}

export interface CreateParentAppointmentResponse {
  appointment: {
    id: string;
    status: AppointmentStatus;
    scheduled_start_at: string;
  };
}

export interface AppointmentRescheduleRequest {
  scheduled_start_at?: string | null;
  duration_minutes?: number | null;
  timezone?: string | null;
  meeting_mode?: AppointmentMeetingMode | null;
  location_or_link?: string | null;
}

export interface TeacherAppointmentRescheduleRequest extends AppointmentRescheduleRequest {
  staff_notes?: string | null;
}

export interface AppointmentStatusResponse {
  status: AppointmentStatus;
}

export interface ParentAppointmentsListQuery {
  status?: AppointmentStatus;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export interface TeacherAppointmentsListQuery {
  status?: AppointmentStatus;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export interface LeadershipAppointmentsListQuery {
  status?: AppointmentStatus;
  teacher_id?: string;
  student_id?: string;
  class_id?: string;
  subject_id?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export function getEligibleAppointmentTeachers(
  studentId: string,
  token?: string | null,
): Promise<EligibleAppointmentTeachersResponse> {
  return appointmentsRequest<EligibleAppointmentTeachersResponse>(`/parent/students/${studentId}/eligible-appointment-teachers`, {
    token,
  });
}

export function createParentAppointment(
  body: CreateParentAppointmentRequest,
  token?: string | null,
): Promise<CreateParentAppointmentResponse> {
  return appointmentsRequest<CreateParentAppointmentResponse>("/parent/appointments", {
    method: "POST",
    token,
    body,
  });
}

export function listParentAppointments(
  query?: ParentAppointmentsListQuery,
  token?: string | null,
): Promise<AppointmentListResponse<AppointmentSummary>> {
  return appointmentsRequest<AppointmentListResponse<AppointmentSummary>>("/parent/appointments", {
    token,
    params: {
      status: query?.status,
      date_from: query?.date_from,
      date_to: query?.date_to,
      page: query?.page,
      page_size: query?.page_size,
    },
  });
}

export function getParentAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<ParentAppointmentDetail> {
  return appointmentsRequest<ParentAppointmentDetail>(`/parent/appointments/${appointmentId}`, {
    token,
  });
}

export function cancelParentAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/parent/appointments/${appointmentId}/cancel`, {
    method: "POST",
    token,
  });
}

export function rescheduleParentAppointment(
  appointmentId: string,
  body: AppointmentRescheduleRequest,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/parent/appointments/${appointmentId}/reschedule`, {
    method: "POST",
    token,
    body,
  });
}

export function listTeacherAppointments(
  query?: TeacherAppointmentsListQuery,
  token?: string | null,
): Promise<AppointmentListResponse<AppointmentSummary>> {
  return appointmentsRequest<AppointmentListResponse<AppointmentSummary>>("/teacher/appointments", {
    token,
    params: {
      status: query?.status,
      date_from: query?.date_from,
      date_to: query?.date_to,
      page: query?.page,
      page_size: query?.page_size,
    },
  });
}

export function getTeacherAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<TeacherAppointmentDetail> {
  return appointmentsRequest<TeacherAppointmentDetail>(`/teacher/appointments/${appointmentId}`, {
    token,
  });
}

export function confirmTeacherAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/teacher/appointments/${appointmentId}/confirm`, {
    method: "POST",
    token,
  });
}

export function declineTeacherAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/teacher/appointments/${appointmentId}/decline`, {
    method: "POST",
    token,
  });
}

export function cancelTeacherAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/teacher/appointments/${appointmentId}/cancel`, {
    method: "POST",
    token,
  });
}

export function completeTeacherAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/teacher/appointments/${appointmentId}/complete`, {
    method: "POST",
    token,
  });
}

export function rescheduleTeacherAppointment(
  appointmentId: string,
  body: TeacherAppointmentRescheduleRequest,
  token?: string | null,
): Promise<AppointmentStatusResponse> {
  return appointmentsRequest<AppointmentStatusResponse>(`/teacher/appointments/${appointmentId}/reschedule`, {
    method: "POST",
    token,
    body,
  });
}

export function listLeadershipAppointments(
  query?: LeadershipAppointmentsListQuery,
  token?: string | null,
): Promise<AppointmentListResponse<LeadershipAppointmentSummary>> {
  return appointmentsRequest<AppointmentListResponse<LeadershipAppointmentSummary>>("/leadership/appointments", {
    token,
    params: {
      status: query?.status,
      teacher_id: query?.teacher_id,
      student_id: query?.student_id,
      class_id: query?.class_id,
      subject_id: query?.subject_id,
      date_from: query?.date_from,
      date_to: query?.date_to,
      page: query?.page,
      page_size: query?.page_size,
    },
  });
}

export function getLeadershipAppointment(
  appointmentId: string,
  token?: string | null,
): Promise<LeadershipAppointmentDetail> {
  return appointmentsRequest<LeadershipAppointmentDetail>(`/leadership/appointments/${appointmentId}`, {
    token,
  });
}
