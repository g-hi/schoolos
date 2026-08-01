import { api } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type RelationshipType = "mother" | "father" | "guardian" | "sponsor" | "other";

export class FamiliesApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "FamiliesApiError";
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  params?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
}

export interface FamilyRelationship {
  relationship_id: string;
  student_id: string;
  student_name: string;
  parent_id: string;
  parent_name: string;
  relationship_type: RelationshipType;
  is_primary: boolean;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface FamilySummary {
  total_active_relationships: number;
  students_with_no_active_parent_guardian_relationship: number;
  students_with_multiple_active_relationships: number;
  primary_relationships: number;
  inactive_historical_relationships: number;
  cross_tenant_inconsistencies: number;
}

export interface ListRelationshipFilters {
  student_id?: string;
  parent_id?: string;
  active_only?: boolean;
}

export interface CreateFamilyRelationshipBody {
  parent_id: string;
  student_id: string;
  relationship_type: RelationshipType;
  is_primary?: boolean;
}

export interface UpdateFamilyRelationshipBody {
  relationship_type?: RelationshipType;
  is_primary?: boolean;
  is_active?: boolean;
}

function parseApiError(error: unknown): FamiliesApiError {
  if (!(error instanceof Error)) {
    return new FamiliesApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) {
    return new FamiliesApiError(0, error.message || "Request failed.", null);
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

  return new FamiliesApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
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

async function familiesRequest<T>(path: string, options?: RequestOptions): Promise<T> {
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

export function listFamilyRelationships(filters?: ListRelationshipFilters): Promise<FamilyRelationship[]> {
  return familiesRequest<FamilyRelationship[]>("/leadership/families/relationships", {
    params: {
      student_id: filters?.student_id,
      parent_id: filters?.parent_id,
      active_only: filters?.active_only ?? true,
    },
  });
}

export function getFamilySummary(): Promise<FamilySummary> {
  return familiesRequest<FamilySummary>("/leadership/families/summary");
}

export function createFamilyRelationship(body: CreateFamilyRelationshipBody): Promise<FamilyRelationship> {
  return familiesRequest<FamilyRelationship>("/leadership/families/relationships", {
    method: "POST",
    body,
  });
}

export function updateFamilyRelationship(
  relationshipId: string,
  body: UpdateFamilyRelationshipBody,
): Promise<FamilyRelationship> {
  return familiesRequest<FamilyRelationship>(`/leadership/families/relationships/${relationshipId}`, {
    method: "PATCH",
    body,
  });
}
