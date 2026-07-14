import { api, apiPost } from "@/lib/api";

const BASE = "/ai/exam-marking";

// ── Types ────────────────────────────────────────────────────────────────────

export type PaperType = "scantron" | "printed_mcq" | "mixed" | "open_ended";
export type InputMethod = "smart_scan" | "upload" | "office_scanner";
export type SessionStatus =
  | "draft"
  | "scanning"
  | "uploading"
  | "processing"
  | "needs_clarification"
  | "pending_review"
  | "partially_approved"
  | "approved"
  | "rejected"
  | "failed";

export interface MarkingSession {
  session_id: string;
  tenant_id: string;
  teacher_id: string;
  exam_title: string;
  subject: string;
  grade: string;
  class_name: string;
  curriculum: string;
  academic_year: string;
  term: string;
  exam_date: string | null;
  total_marks: number;
  paper_type: PaperType;
  input_method: InputMethod;
  language: string;
  total_students: number;
  captured_students: number;
  processed_students: number;
  pending_students: number;
  flagged_students: number;
  approved_students: number;
  average_confidence: number | null;
  status: SessionStatus;
  teacher_notes: string;
  created_at: string;
  updated_at: string;
}

export interface CreateSessionRequest {
  exam_title: string;
  subject?: string;
  grade?: string;
  class_name?: string;
  curriculum?: string;
  academic_year?: string;
  term?: string;
  exam_date?: string | null;
  total_marks?: number;
  time_allowed_minutes?: number | null;
  expected_pages_per_student?: number;
  paper_type?: PaperType;
  input_method?: InputMethod;
  language?: string;
  total_students?: number;
  teacher_notes?: string;
}

export interface PageUploadResponse {
  page_id: string;
  submission_id: string;
  session_id: string;
  page_number: number;
  storage_key: string;
  quality_score: number | null;
  quality_warnings: string[];
  retake_required: boolean;
  accepted_for_processing: boolean;
  page_status: string;
}

export interface SubmissionSummary {
  submission_id: string;
  session_id: string;
  student_name: string;
  student_code: string;
  paper_type: PaperType;
  status: string;
  proposed_total: number | null;
  teacher_final_total: number | null;
  max_marks: number | null;
  percentage: number | null;
  confidence_score: number | null;
  copilot_request_id: string | null;
}

export interface AnswerKeyItem {
  question_number: number;
  question_type: string;
  question_text?: string;
  correct_answer: string;
  max_marks: number;
  accepted_alternatives?: string[];
  numeric_tolerance?: number | null;
  partial_credit?: number | null;
  rubric_criteria?: { criterion: string; max_marks: number; description?: string }[];
}

export interface ProcessRequest {
  submission_ids?: string[];
  answer_key: AnswerKeyItem[];
  marking_scheme?: Record<string, unknown>;
  teacher_guidance?: string;
  paper_type_override?: PaperType | null;
}

export interface QuestionOverride {
  question_number: number;
  teacher_final_marks: number;
  teacher_comment?: string;
}

export interface ReviewRequest {
  submission_id: string;
  overrides: QuestionOverride[];
  teacher_comments?: string;
}

export interface ApproveRequest {
  submission_ids: string[];
  approved: boolean;
  notes?: string;
}

// ── API functions ─────────────────────────────────────────────────────────────

export function createSession(body: CreateSessionRequest): Promise<MarkingSession> {
  return apiPost<MarkingSession>(`${BASE}/sessions`, body);
}

export function listSessions(): Promise<MarkingSession[]> {
  return api<MarkingSession[]>(`${BASE}/sessions`);
}

export function getSession(sessionId: string): Promise<MarkingSession> {
  return api<MarkingSession>(`${BASE}/sessions/${sessionId}`);
}

export function listSubmissions(sessionId: string): Promise<SubmissionSummary[]> {
  return api<SubmissionSummary[]>(`${BASE}/sessions/${sessionId}/submissions`);
}

export async function uploadPage(
  sessionId: string,
  file: File,
  pageNumber: number,
  submissionId?: string,
  studentName?: string,
  studentCode?: string,
): Promise<PageUploadResponse> {
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";
  const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";

  const form = new FormData();
  form.append("file", file);
  form.append("page_number", String(pageNumber));
  if (submissionId) form.append("submission_id", submissionId);
  if (studentName) form.append("student_name", studentName);
  if (studentCode) form.append("student_code", studentCode);

  const res = await fetch(`${API_BASE}${BASE}/sessions/${sessionId}/pages`, {
    method: "POST",
    headers: { "X-Tenant-Slug": TENANT },
    body: form,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Upload failed ${res.status}: ${body}`);
  }
  return res.json();
}

export function deletePage(sessionId: string, pageId: string): Promise<void> {
  return api<void>(`${BASE}/sessions/${sessionId}/pages/${pageId}`, { method: "DELETE" });
}

export function markStudentComplete(sessionId: string, submissionId: string): Promise<unknown> {
  return apiPost(`${BASE}/sessions/${sessionId}/students/${submissionId}/complete`, {});
}

export function processSession(
  sessionId: string,
  body: ProcessRequest,
): Promise<{ copilot_request_id: string; status: string; message: string }> {
  return apiPost(`${BASE}/sessions/${sessionId}/process`, body);
}

export function submitReview(sessionId: string, body: ReviewRequest): Promise<unknown> {
  return api(`${BASE}/sessions/${sessionId}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function approveSubmissions(sessionId: string, body: ApproveRequest): Promise<unknown> {
  return apiPost(`${BASE}/sessions/${sessionId}/approve`, body);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export function statusLabel(status: SessionStatus | string): string {
  const map: Record<string, string> = {
    draft: "Draft",
    scanning: "Scanning",
    uploading: "Uploading",
    processing: "Processing",
    needs_clarification: "Needs Clarification",
    pending_review: "Pending Review",
    partially_approved: "Partially Approved",
    approved: "Approved",
    rejected: "Rejected",
    failed: "Failed",
  };
  return map[status] ?? status;
}

export function statusColor(status: SessionStatus | string): string {
  const map: Record<string, string> = {
    draft: "bg-gray-100 text-gray-700",
    scanning: "bg-blue-100 text-blue-700",
    uploading: "bg-blue-100 text-blue-700",
    processing: "bg-yellow-100 text-yellow-700",
    needs_clarification: "bg-orange-100 text-orange-700",
    pending_review: "bg-purple-100 text-purple-700",
    partially_approved: "bg-indigo-100 text-indigo-700",
    approved: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
    failed: "bg-red-100 text-red-700",
  };
  return map[status] ?? "bg-gray-100 text-gray-700";
}

export function paperTypeLabel(type: PaperType | string): string {
  const map: Record<string, string> = {
    scantron: "Scantron / Bubble Sheet",
    printed_mcq: "Printed MCQ",
    mixed: "Mixed Paper",
    open_ended: "Open-Ended",
  };
  return map[type] ?? type;
}

export function confidenceColor(score: number | null): string {
  if (score === null) return "text-gray-400";
  if (score >= 0.9) return "text-green-600";
  if (score >= 0.7) return "text-yellow-600";
  return "text-red-600";
}
