import { readAccessToken } from "@/lib/auth";
import { api } from "@/lib/api";

// ─── Error helper ────────────────────────────────────────────────────────────

export class EnrolmentApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "EnrolmentApiError";
    this.status = status;
    this.body = body;
  }
}

function parseApiError(error: unknown): EnrolmentApiError {
  if (!(error instanceof Error)) return new EnrolmentApiError(0, "Unknown request failure.", null);
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) return new EnrolmentApiError(0, error.message, null);
  const status = Number(match[1]);
  const bodyText = match[2] ?? "";
  let parsedBody: unknown = bodyText;
  try { parsedBody = JSON.parse(bodyText); } catch { /* noop */ }
  const detail =
    typeof parsedBody === "object" && parsedBody !== null && "detail" in parsedBody
      ? String((parsedBody as { detail?: unknown }).detail)
      : bodyText;
  return new EnrolmentApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

function authHeaders(): Record<string, string> {
  const token = readAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function enrolRequest<T>(
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

export interface StudentEnrolment {
  id: string;
  student_id: string;
  student_name: string;
  academic_year_id: string;
  academic_year_name: string;
  grade_level_id: string;
  grade_level_name: string;
  class_id: string;
  class_code: string | null;
  class_section: string | null;
  status: "active" | "transferred" | "withdrawn" | "completed";
  enrolled_on: string;
  exited_on: string | null;
  exit_reason: string | null;
}

export interface StudentEnrolmentSummary {
  total_enrollments: number;
  active_enrollments: number;
  transferred_enrollments: number;
  withdrawn_enrollments: number;
  completed_enrollments: number;
  students_with_active_canonical_enrollment: number;
  students_with_legacy_class_id_but_no_canonical_enrollment: number;
  students_with_terminal_canonical_history_and_stale_class_id: number;
  students_with_class_id_conflicting_active_enrollment: number;
  students_with_multiple_active_enrollments: number;
  active_enrollments_by_class: Array<{
    class_id: string;
    class_code: string | null;
    class_section: string | null;
    count: number;
  }>;
  active_enrollments_by_grade_level: Array<{
    grade_level_id: string;
    grade_level_name: string;
    count: number;
  }>;
}

export interface ReconciliationRow {
  student_id: string;
  display_name: string;
  legacy_class_id: string | null;
  canonical_active_class_id: string | null;
  issue_code: string;
  recommended_action: string;
}

// ─── Enrolments ───────────────────────────────────────────────────────────────

export function listEnrolments(params?: {
  academic_year_id?: string;
  student_id?: string;
  class_id?: string;
  grade_level_id?: string;
  status?: string;
}): Promise<StudentEnrolment[]> {
  const p: Record<string, string> = {};
  if (params?.academic_year_id) p.academic_year_id = params.academic_year_id;
  if (params?.student_id) p.student_id = params.student_id;
  if (params?.class_id) p.class_id = params.class_id;
  if (params?.grade_level_id) p.grade_level_id = params.grade_level_id;
  if (params?.status) p.status = params.status;
  return enrolRequest<StudentEnrolment[]>("/leadership/student-enrollments", {
    params: Object.keys(p).length ? p : undefined,
  });
}

export function createEnrolment(body: {
  student_id: string;
  class_id: string;
  enrolled_on: string;
  status?: string;
}): Promise<StudentEnrolment> {
  return enrolRequest<StudentEnrolment>("/leadership/student-enrollments", { method: "POST", body });
}

export function updateEnrolment(
  id: string,
  body: Partial<{ status: string; exited_on: string; exit_reason: string }>,
): Promise<StudentEnrolment> {
  return enrolRequest<StudentEnrolment>(`/leadership/student-enrollments/${id}`, { method: "PATCH", body });
}

export function transferEnrolment(
  id: string,
  body: { new_class_id: string; transfer_date: string; reason?: string },
): Promise<{ source_enrollment: StudentEnrolment; destination_enrollment: StudentEnrolment }> {
  return enrolRequest(`/leadership/student-enrollments/${id}/transfer`, { method: "POST", body });
}

export function getEnrolmentSummary(): Promise<StudentEnrolmentSummary> {
  return enrolRequest<StudentEnrolmentSummary>("/leadership/student-enrollments/summary");
}

export function getReconciliationDiagnostics(): Promise<ReconciliationRow[]> {
  return enrolRequest<ReconciliationRow[]>("/leadership/student-enrollments/reconciliation");
}
