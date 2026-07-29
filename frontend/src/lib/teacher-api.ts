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
