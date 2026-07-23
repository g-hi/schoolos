import { api } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type AnnouncementStatus = "draft" | "scheduled" | "publishing" | "published" | "archived";
export type AnnouncementTargetType = "school" | "grade" | "class" | "family" | "student";
export type AnnouncementLookupTargetType = Exclude<AnnouncementTargetType, "school">;
export type NotificationDeliveryStatus = "pending" | "delivered" | "partial" | "failed" | "skipped";

export class AnnouncementsApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "AnnouncementsApiError";
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

function parseApiError(error: unknown): AnnouncementsApiError {
  if (!(error instanceof Error)) {
    return new AnnouncementsApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) {
    return new AnnouncementsApiError(0, error.message || "Request failed.", null);
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
  return new AnnouncementsApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

async function announcementsRequest<T>(path: string, options?: RequestOptions): Promise<T> {
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

export interface AnnouncementTargetRequest {
  target_type: AnnouncementTargetType;
  grade?: string | null;
  class_id?: string | null;
  family_id?: string | null;
  student_id?: string | null;
}

export interface AnnouncementTargetOption {
  target_type: AnnouncementLookupTargetType;
  target_value: string;
  label: string;
  secondary_label: string | null;
}

export interface AnnouncementTargetOptionsResponse {
  items: AnnouncementTargetOption[];
}

export interface AnnouncementTargetOptionsQuery {
  target_type: AnnouncementLookupTargetType;
  q?: string;
  grade?: string;
  class_id?: string;
  limit?: number;
}

export interface AnnouncementSummary {
  id: string;
  title: string;
  body: string;
  status: AnnouncementStatus;
  timezone: string;
  scheduled_at: string | null;
  published_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnnouncementDetail extends AnnouncementSummary {
  targets: AnnouncementTargetRequest[];
}

export interface AnnouncementListResponse {
  items: AnnouncementSummary[];
  page: number;
  page_size: number;
}

export interface AnnouncementCreateRequest {
  title: string;
  body: string;
  timezone?: string;
  targets: AnnouncementTargetRequest[];
}

export interface AnnouncementUpdateRequest {
  title?: string;
  body?: string;
  timezone?: string;
  targets?: AnnouncementTargetRequest[];
}

export interface AnnouncementListQuery {
  status?: AnnouncementStatus;
  date_from?: string;
  date_to?: string;
  target_type?: AnnouncementTargetType;
  page?: number;
  page_size?: number;
}

export interface ParentAnnouncementListQuery {
  status?: AnnouncementStatus;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export interface ParentAnnouncementSummary extends AnnouncementSummary {
  read_at: string | null;
}

export interface ParentAnnouncementListResponse {
  items: ParentAnnouncementSummary[];
  page: number;
  page_size: number;
}

export interface NotificationSummary {
  id: string;
  announcement_id: string | null;
  title: string;
  body: string;
  read_at: string | null;
  delivery_status: NotificationDeliveryStatus;
}

export interface ParentNotificationListResponse {
  items: NotificationSummary[];
  page: number;
  page_size: number;
}

export interface ParentUnreadNotificationCountResponse {
  unread_count: number;
}

export interface ParentNotificationListQuery {
  read?: boolean;
  page?: number;
  page_size?: number;
}

export interface AnnouncementDeliverySummary {
  id: string;
  recipient_user_id: string;
  delivery_status: NotificationDeliveryStatus;
  read_at: string | null;
  attempt_count: number;
  last_error_code: string | null;
}

export interface AnnouncementDeliveriesResponse {
  items: AnnouncementDeliverySummary[];
  page: number;
  page_size: number;
}

export interface AnnouncementDeliveriesQuery {
  page?: number;
  page_size?: number;
}

export interface NotificationReadResponse {
  id: string;
  read_at: string | null;
}

export interface NotificationsReadAllResponse {
  updated: number;
}

export function createAnnouncement(
  body: AnnouncementCreateRequest,
  token?: string | null,
): Promise<AnnouncementSummary> {
  return announcementsRequest<AnnouncementSummary>("/announcements", {
    method: "POST",
    token,
    body,
  });
}

export function listAnnouncementTargetOptions(
  query: AnnouncementTargetOptionsQuery,
  token?: string | null,
): Promise<AnnouncementTargetOptionsResponse> {
  return announcementsRequest<AnnouncementTargetOptionsResponse>("/announcements/target-options", {
    token,
    params: {
      target_type: query.target_type,
      q: query.q,
      grade: query.grade,
      class_id: query.class_id,
      limit: query.limit,
    },
  });
}

export function listAnnouncements(
  query?: AnnouncementListQuery,
  token?: string | null,
): Promise<AnnouncementListResponse> {
  return announcementsRequest<AnnouncementListResponse>("/announcements", {
    token,
    params: {
      status: query?.status,
      date_from: query?.date_from,
      date_to: query?.date_to,
      target_type: query?.target_type,
      page: query?.page,
      page_size: query?.page_size,
    },
  });
}

export function getAnnouncement(
  announcementId: string,
  token?: string | null,
): Promise<AnnouncementDetail> {
  return announcementsRequest<AnnouncementDetail>(`/announcements/${announcementId}`, {
    token,
  });
}

export function updateAnnouncement(
  announcementId: string,
  body: AnnouncementUpdateRequest,
  token?: string | null,
): Promise<AnnouncementSummary> {
  return announcementsRequest<AnnouncementSummary>(`/announcements/${announcementId}`, {
    method: "PATCH",
    token,
    body,
  });
}

export function scheduleAnnouncement(
  announcementId: string,
  query: { scheduled_at: string; timezone?: string },
  token?: string | null,
): Promise<AnnouncementSummary> {
  return announcementsRequest<AnnouncementSummary>(`/announcements/${announcementId}/schedule`, {
    method: "POST",
    token,
    params: {
      scheduled_at: query.scheduled_at,
      timezone: query.timezone,
    },
  });
}

export function unscheduleAnnouncement(
  announcementId: string,
  token?: string | null,
): Promise<AnnouncementSummary> {
  return announcementsRequest<AnnouncementSummary>(`/announcements/${announcementId}/unschedule`, {
    method: "POST",
    token,
  });
}

export function publishAnnouncement(
  announcementId: string,
  token?: string | null,
): Promise<AnnouncementSummary> {
  return announcementsRequest<AnnouncementSummary>(`/announcements/${announcementId}/publish`, {
    method: "POST",
    token,
  });
}

export function archiveAnnouncement(
  announcementId: string,
  token?: string | null,
): Promise<AnnouncementSummary> {
  return announcementsRequest<AnnouncementSummary>(`/announcements/${announcementId}/archive`, {
    method: "POST",
    token,
  });
}

export function listAnnouncementDeliveries(
  announcementId: string,
  query?: AnnouncementDeliveriesQuery,
  token?: string | null,
): Promise<AnnouncementDeliveriesResponse> {
  return announcementsRequest<AnnouncementDeliveriesResponse>(`/announcements/${announcementId}/deliveries`, {
    token,
    params: {
      page: query?.page,
      page_size: query?.page_size,
    },
  });
}

export function listParentAnnouncements(
  query?: ParentAnnouncementListQuery,
  token?: string | null,
): Promise<ParentAnnouncementListResponse> {
  return announcementsRequest<ParentAnnouncementListResponse>("/parent/announcements", {
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

export function getParentAnnouncement(
  announcementId: string,
  token?: string | null,
): Promise<ParentAnnouncementSummary> {
  return announcementsRequest<ParentAnnouncementSummary>(`/parent/announcements/${announcementId}`, {
    token,
  });
}

export function listParentNotifications(
  query?: ParentNotificationListQuery,
  token?: string | null,
): Promise<ParentNotificationListResponse> {
  return announcementsRequest<ParentNotificationListResponse>("/parent/notifications", {
    token,
    params: {
      read: query?.read,
      page: query?.page,
      page_size: query?.page_size,
    },
  });
}

export function listParentUnreadNotifications(
  query?: Omit<ParentNotificationListQuery, "read">,
  token?: string | null,
): Promise<ParentNotificationListResponse> {
  return announcementsRequest<ParentNotificationListResponse>("/parent/notifications", {
    token,
    params: {
      page: query?.page,
      page_size: query?.page_size,
      read: false,
    },
  });
}

export function getParentUnreadNotificationCount(
  token?: string | null,
): Promise<ParentUnreadNotificationCountResponse> {
  return announcementsRequest<ParentUnreadNotificationCountResponse>("/parent/notifications/unread-count", {
    token,
  });
}

export function markParentNotificationRead(
  notificationId: string,
  token?: string | null,
): Promise<NotificationReadResponse> {
  return announcementsRequest<NotificationReadResponse>(`/parent/notifications/${notificationId}/read`, {
    method: "POST",
    token,
  });
}

export function markAllParentNotificationsRead(
  token?: string | null,
): Promise<NotificationsReadAllResponse> {
  return announcementsRequest<NotificationsReadAllResponse>("/parent/notifications/read-all", {
    method: "POST",
    token,
  });
}
