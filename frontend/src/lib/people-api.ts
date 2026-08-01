import { api } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type PeopleRoleFilter = "teacher" | "parent" | "student" | "principal" | "school_admin";
export type PeopleStatusFilter = "active" | "inactive";
export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export class PeopleApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "PeopleApiError";
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  params?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
}

export interface PaginatedResponse<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface ListPeopleFilters {
  role?: PeopleRoleFilter;
  status?: PeopleStatusFilter;
  search?: string;
  has_account?: boolean;
  profile_status?: string;
  limit?: number;
  offset?: number;
}

export interface PersonDirectoryItem {
  person_id: string;
  user_id: string | null;
  display_name: string;
  email: string | null;
  role: string;
  profile_type: string;
  is_active: boolean;
  invitation_status: InvitationStatus | null;
  profile_consistency_status: string;
  created_at: string | null;
  has_account: boolean;
}

export interface PeopleSummary {
  total_active_users: number;
  active_teachers: number;
  active_parents: number;
  active_students: number;
  teachers_without_user_accounts: number;
  parents_without_user_accounts: number;
  users_without_matching_role_profiles: number;
  inactive_users_with_active_profiles: number;
  pending_invitations: number;
  expired_invitations: number;
  accepted_invitations: number;
  revoked_invitations: number;
}

export interface TeacherProvisionBody {
  display_name: string;
  email: string;
  employee_id?: string | null;
  max_weekly_hours?: number;
  send_invitation?: boolean;
}

export interface ParentRelationshipSeed {
  student_id: string;
  relationship_type: "mother" | "father" | "guardian" | "sponsor" | "other";
  is_primary?: boolean;
}

export interface ParentProvisionBody {
  display_name: string;
  email: string;
  phone?: string | null;
  send_invitation?: boolean;
  relationships?: ParentRelationshipSeed[];
}

export interface StudentRelationshipSeed {
  parent_id: string;
  relationship_type: "mother" | "father" | "guardian" | "sponsor" | "other";
  is_primary?: boolean;
}

export interface StudentProvisionBody {
  name: string;
  class_id: string;
  student_code?: string | null;
  relationships?: StudentRelationshipSeed[];
  initial_enrollment?: {
    class_id: string;
    enrolled_on: string;
  } | null;
}

export interface ProvisionTeacherResponse {
  teacher_id: string;
  user_id: string;
  email: string;
  invitation_id: string | null;
  activation_token: string | null;
  activation_token_one_time: boolean;
}

export interface ProvisionParentResponse {
  parent_user_id: string;
  email: string;
  invitation_id: string | null;
  activation_token: string | null;
  activation_token_one_time: boolean;
}

export interface ProvisionStudentResponse {
  student_id: string;
  class_id: string;
  enrollment_id: string | null;
}

export interface UserStatusUpdateBody {
  is_active: boolean;
  reason?: string | null;
}

export interface UserStatusResponse {
  user_id: string;
  is_active: boolean;
}

export interface IssueInvitationResponse {
  invitation_id: string;
  user_id: string;
  role: string;
  expires_at: string;
  activation_token: string;
  activation_token_one_time: true;
}

export interface InvitationListItem {
  id: string;
  user_id: string;
  invited_email: string;
  role: string;
  status: InvitationStatus;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
  is_expired: boolean;
}

export interface ListInvitationsFilters {
  status?: InvitationStatus;
  role?: "teacher" | "parent";
  limit?: number;
  offset?: number;
}

export interface RevokeInvitationResponse {
  invitation_id: string;
  status: "revoked";
}

function mapParams(params?: RequestOptions["params"]): Record<string, string> | undefined {
  if (!params) return undefined;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    out[key] = String(value);
  }
  return Object.keys(out).length ? out : undefined;
}

function parseApiError(error: unknown): PeopleApiError {
  if (!(error instanceof Error)) {
    return new PeopleApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) {
    return new PeopleApiError(0, error.message || "Request failed.", null);
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

  return new PeopleApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

async function peopleRequest<T>(path: string, options?: RequestOptions): Promise<T> {
  const token = readAccessToken();
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
      headers,
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      params: mapParams(options?.params),
    });
  } catch (error) {
    throw parseApiError(error);
  }
}

export function listPeople(filters?: ListPeopleFilters): Promise<PaginatedResponse<PersonDirectoryItem>> {
  return peopleRequest<PaginatedResponse<PersonDirectoryItem>>("/leadership/people", {
    params: {
      role: filters?.role,
      status: filters?.status,
      search: filters?.search,
      has_account: filters?.has_account,
      profile_status: filters?.profile_status,
      limit: filters?.limit ?? 50,
      offset: filters?.offset ?? 0,
    },
  });
}

export function getPeopleSummary(): Promise<PeopleSummary> {
  return peopleRequest<PeopleSummary>("/leadership/people/summary");
}

export function provisionTeacher(body: TeacherProvisionBody): Promise<ProvisionTeacherResponse> {
  return peopleRequest<ProvisionTeacherResponse>("/leadership/people/teachers", {
    method: "POST",
    body,
  });
}

export function provisionParent(body: ParentProvisionBody): Promise<ProvisionParentResponse> {
  return peopleRequest<ProvisionParentResponse>("/leadership/people/parents", {
    method: "POST",
    body,
  });
}

export function provisionStudent(body: StudentProvisionBody): Promise<ProvisionStudentResponse> {
  return peopleRequest<ProvisionStudentResponse>("/leadership/people/students", {
    method: "POST",
    body,
  });
}

export function updateUserStatus(userId: string, body: UserStatusUpdateBody): Promise<UserStatusResponse> {
  return peopleRequest<UserStatusResponse>(`/leadership/people/users/${userId}/status`, {
    method: "PATCH",
    body,
  });
}

export function issueInvitation(userId: string): Promise<IssueInvitationResponse> {
  return peopleRequest<IssueInvitationResponse>(`/leadership/people/users/${userId}/invite`, {
    method: "POST",
    body: {},
  });
}

export function listInvitations(filters?: ListInvitationsFilters): Promise<PaginatedResponse<InvitationListItem>> {
  return peopleRequest<PaginatedResponse<InvitationListItem>>("/leadership/people/invitations", {
    params: {
      status: filters?.status,
      role: filters?.role,
      limit: filters?.limit ?? 50,
      offset: filters?.offset ?? 0,
    },
  });
}

export function revokeInvitation(invitationId: string, reason?: string): Promise<RevokeInvitationResponse> {
  return peopleRequest<RevokeInvitationResponse>(`/leadership/people/invitations/${invitationId}/revoke`, {
    method: "POST",
    body: { reason: reason ?? null },
  });
}
