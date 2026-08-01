import { readAccessToken } from "@/lib/auth";
import { api } from "@/lib/api";

// ─── Error helper ────────────────────────────────────────────────────────────

export class MasterDataApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "MasterDataApiError";
    this.status = status;
    this.body = body;
  }
}

function parseApiError(error: unknown): MasterDataApiError {
  if (!(error instanceof Error)) {
    return new MasterDataApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) return new MasterDataApiError(0, error.message, null);
  const status = Number(match[1]);
  const bodyText = match[2] ?? "";
  let parsedBody: unknown = bodyText;
  try { parsedBody = JSON.parse(bodyText); } catch { /* noop */ }
  const detail =
    typeof parsedBody === "object" && parsedBody !== null && "detail" in parsedBody
      ? String((parsedBody as { detail?: unknown }).detail)
      : bodyText;
  return new MasterDataApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

function authHeaders(): Record<string, string> {
  const token = readAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function mdRequest<T>(
  path: string,
  options?: { method?: "GET" | "POST" | "PATCH"; body?: unknown; params?: Record<string, string> },
): Promise<T> {
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...(options?.body !== undefined ? { "Content-Type": "application/json" } : {}),
  };
  try {
    return await api<T>(path, {
      method: options?.method ?? "GET",
      headers,
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      params: options?.params,
    });
  } catch (err) {
    throw parseApiError(err);
  }
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Campus {
  id: string;
  name: string;
  code: string;
  description: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface AcademicYear {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface Term {
  id: string;
  academic_year_id: string;
  name: string;
  code: string;
  start_date: string;
  end_date: string;
  sequence: number;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface GradeLevel {
  id: string;
  name: string;
  code: string;
  sequence: number;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface MasterDataSetupSummary {
  campus_count: number;
  active_campus_count: number;
  academic_year_count: number;
  active_academic_year_count: number;
  current_academic_year: { id: string; name: string } | null;
  term_count: number;
  grade_level_count: number;
  active_grade_level_count: number;
}

// ─── Campuses ─────────────────────────────────────────────────────────────────

export function listCampuses(): Promise<Campus[]> {
  return mdRequest<Campus[]>("/leadership/master-data/campuses");
}

export function createCampus(body: { name: string; code: string; description?: string; is_active: boolean }): Promise<Campus> {
  return mdRequest<Campus>("/leadership/master-data/campuses", { method: "POST", body });
}

export function updateCampus(id: string, body: Partial<{ name: string; code: string; description: string | null; is_active: boolean }>): Promise<Campus> {
  return mdRequest<Campus>(`/leadership/master-data/campuses/${id}`, { method: "PATCH", body });
}

// ─── Academic Years ───────────────────────────────────────────────────────────

export function listAcademicYears(): Promise<AcademicYear[]> {
  return mdRequest<AcademicYear[]>("/leadership/master-data/academic-years");
}

export function createAcademicYear(body: { name: string; start_date: string; end_date: string; is_current: boolean; is_active: boolean }): Promise<AcademicYear> {
  return mdRequest<AcademicYear>("/leadership/master-data/academic-years", { method: "POST", body });
}

export function updateAcademicYear(id: string, body: Partial<{ name: string; start_date: string; end_date: string; is_current: boolean; is_active: boolean }>): Promise<AcademicYear> {
  return mdRequest<AcademicYear>(`/leadership/master-data/academic-years/${id}`, { method: "PATCH", body });
}

// ─── Terms ────────────────────────────────────────────────────────────────────

export function listTerms(): Promise<Term[]> {
  return mdRequest<Term[]>("/leadership/master-data/terms");
}

export function createTerm(body: { academic_year_id: string; name: string; code: string; start_date: string; end_date: string; sequence: number; is_active: boolean }): Promise<Term> {
  return mdRequest<Term>("/leadership/master-data/terms", { method: "POST", body });
}

export function updateTerm(id: string, body: Partial<{ name: string; code: string; start_date: string; end_date: string; sequence: number; is_active: boolean }>): Promise<Term> {
  return mdRequest<Term>(`/leadership/master-data/terms/${id}`, { method: "PATCH", body });
}

// ─── Grade Levels ─────────────────────────────────────────────────────────────

export function listGradeLevels(): Promise<GradeLevel[]> {
  return mdRequest<GradeLevel[]>("/leadership/master-data/grade-levels");
}

export function createGradeLevel(body: { name: string; code: string; sequence: number; is_active: boolean }): Promise<GradeLevel> {
  return mdRequest<GradeLevel>("/leadership/master-data/grade-levels", { method: "POST", body });
}

export function updateGradeLevel(id: string, body: Partial<{ name: string; code: string; sequence: number; is_active: boolean }>): Promise<GradeLevel> {
  return mdRequest<GradeLevel>(`/leadership/master-data/grade-levels/${id}`, { method: "PATCH", body });
}

// ─── Summary ──────────────────────────────────────────────────────────────────

export function getMasterDataSetupSummary(): Promise<MasterDataSetupSummary> {
  return mdRequest<MasterDataSetupSummary>("/leadership/master-data/setup-summary");
}
