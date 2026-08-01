import { readAccessToken } from "@/lib/auth";
import { api } from "@/lib/api";

// ─── Error helper ────────────────────────────────────────────────────────────

export class AcademicStructureApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "AcademicStructureApiError";
    this.status = status;
    this.body = body;
  }
}

function parseApiError(error: unknown): AcademicStructureApiError {
  if (!(error instanceof Error)) return new AcademicStructureApiError(0, "Unknown request failure.", null);
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) return new AcademicStructureApiError(0, error.message, null);
  const status = Number(match[1]);
  const bodyText = match[2] ?? "";
  let parsedBody: unknown = bodyText;
  try { parsedBody = JSON.parse(bodyText); } catch { /* noop */ }
  const detail =
    typeof parsedBody === "object" && parsedBody !== null && "detail" in parsedBody
      ? String((parsedBody as { detail?: unknown }).detail)
      : bodyText;
  return new AcademicStructureApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

function authHeaders(): Record<string, string> {
  const token = readAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function asRequest<T>(
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

export interface CanonicalClass {
  id: string;
  tenant_id: string;
  campus_id: string | null;
  academic_year_id: string | null;
  grade_level_id: string | null;
  class_teacher_id: string | null;
  code: string | null;
  is_active: boolean;
  grade: string | null;
  section: string | null;
  academic_year: string | null;
  campus_name: string | null;
  academic_year_name: string | null;
  grade_level_name: string | null;
  class_teacher_name: string | null;
  updated_at: string | null;
}

export interface SubjectOffering {
  id: string;
  tenant_id: string;
  campus_id: string;
  academic_year_id: string;
  grade_level_id: string;
  subject_id: string;
  is_active: boolean;
  campus_name: string;
  academic_year_name: string;
  grade_level_name: string;
  subject_name: string;
  subject_code: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface TeacherAssignment {
  id: string;
  tenant_id: string;
  academic_year_id: string;
  teacher_id: string;
  class_id: string;
  subject_offering_id: string | null;
  assignment_type: "homeroom" | "subject_teacher";
  start_date: string;
  end_date: string | null;
  is_active: boolean;
  teacher_name: string;
  class_code: string | null;
  class_grade_level_name: string | null;
  class_section: string | null;
  academic_year_name: string;
  subject_offering: { id: string; subject_id: string } | null;
  subject_id: string | null;
  subject_code: string | null;
  subject_name: string | null;
}

export interface AcademicStructureSummary {
  canonical_class_count: number;
  legacy_class_count: number;
  inactive_canonical_class_count: number;
  active_subject_offering_count: number;
  inactive_subject_offering_count: number;
  subject_offering_by_grade_level: Array<{ grade_level_id: string; grade_level_name: string; offering_count: number }>;
}

export interface TeacherAssignmentSummary {
  active_assignment_count: number;
  inactive_assignment_count: number;
  homeroom_assignment_count: number;
  subject_teacher_assignment_count: number;
  canonical_coverage_count: number;
  total_active_teachers: number;
  canonical_assignment_coverage_percentage: number;
  teachers: Array<{
    teacher_id: string;
    teacher_name: string;
    homeroom_assignments: number;
    subject_assignments: number;
    total_active_assignments: number;
    coverage_source: "canonical" | "legacy" | "none";
  }>;
}

// ─── Classes ──────────────────────────────────────────────────────────────────

export function listClasses(): Promise<CanonicalClass[]> {
  return asRequest<CanonicalClass[]>("/leadership/academic-structure/classes");
}

export function createClass(body: {
  campus_id: string;
  academic_year_id: string;
  grade_level_id: string;
  code: string;
  section: string;
  class_teacher_id?: string | null;
  is_active: boolean;
}): Promise<CanonicalClass> {
  return asRequest<CanonicalClass>("/leadership/academic-structure/classes", { method: "POST", body });
}

export function updateClass(
  id: string,
  body: Partial<{
    campus_id: string | null;
    academic_year_id: string | null;
    grade_level_id: string | null;
    code: string | null;
    section: string;
    class_teacher_id: string | null;
    is_active: boolean;
  }>,
): Promise<CanonicalClass> {
  return asRequest<CanonicalClass>(`/leadership/academic-structure/classes/${id}`, { method: "PATCH", body });
}

// ─── Subject Offerings ────────────────────────────────────────────────────────

export function listSubjectOfferings(): Promise<SubjectOffering[]> {
  return asRequest<SubjectOffering[]>("/leadership/academic-structure/subject-offerings");
}

export function createSubjectOffering(body: {
  campus_id: string;
  academic_year_id: string;
  grade_level_id: string;
  subject_id: string;
  is_active: boolean;
}): Promise<SubjectOffering> {
  return asRequest<SubjectOffering>("/leadership/academic-structure/subject-offerings", { method: "POST", body });
}

export function updateSubjectOffering(
  id: string,
  body: Partial<{ campus_id: string; academic_year_id: string; grade_level_id: string; subject_id: string; is_active: boolean }>,
): Promise<SubjectOffering> {
  return asRequest<SubjectOffering>(`/leadership/academic-structure/subject-offerings/${id}`, { method: "PATCH", body });
}

// ─── Teacher Assignments ──────────────────────────────────────────────────────

export function listTeacherAssignments(params?: {
  academic_year_id?: string;
  teacher_id?: string;
  class_id?: string;
  assignment_type?: "homeroom" | "subject_teacher";
  is_active?: boolean;
}): Promise<TeacherAssignment[]> {
  const p: Record<string, string> = {};
  if (params?.academic_year_id) p.academic_year_id = params.academic_year_id;
  if (params?.teacher_id) p.teacher_id = params.teacher_id;
  if (params?.class_id) p.class_id = params.class_id;
  if (params?.assignment_type) p.assignment_type = params.assignment_type;
  if (params?.is_active !== undefined) p.is_active = String(params.is_active);
  return asRequest<TeacherAssignment[]>("/leadership/teacher-assignments", {
    params: Object.keys(p).length ? p : undefined,
  });
}

export function createTeacherAssignment(body: {
  academic_year_id: string;
  teacher_id: string;
  class_id: string;
  subject_offering_id?: string | null;
  assignment_type: "homeroom" | "subject_teacher";
  start_date: string;
  end_date?: string | null;
  is_active?: boolean;
}): Promise<TeacherAssignment> {
  return asRequest<TeacherAssignment>("/leadership/teacher-assignments", { method: "POST", body });
}

export function updateTeacherAssignment(
  id: string,
  body: Partial<{ start_date: string; end_date: string | null; is_active: boolean }>,
): Promise<TeacherAssignment> {
  return asRequest<TeacherAssignment>(`/leadership/teacher-assignments/${id}`, { method: "PATCH", body });
}

// ─── Summaries ────────────────────────────────────────────────────────────────

export function getAcademicStructureSummary(): Promise<AcademicStructureSummary> {
  return asRequest<AcademicStructureSummary>("/leadership/academic-structure/summary");
}

export function getTeacherAssignmentSummary(): Promise<TeacherAssignmentSummary> {
  return asRequest<TeacherAssignmentSummary>("/leadership/teacher-assignments/summary");
}
