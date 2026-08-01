import { api } from "@/lib/api";
import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";

export type ImportBatchStatus =
  | "uploaded"
  | "validating"
  | "preview_ready"
  | "invalid"
  | "committing"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled";

export type ImportRowStatus = "valid" | "invalid" | "conflict" | "created" | "updated" | "skipped" | "failed";
export type ImportRowAction = "create" | "update" | "skip" | "none";
export type ImportEntityType = "subjects" | "classes" | "teachers" | "students" | "parents";

export interface DuplicateFileDiagnostic {
  is_duplicate: boolean;
  previous_batch_id?: string | null;
  message?: string | null;
}

export interface ImportBatch {
  id: string;
  tenant_id: string;
  entity_type: ImportEntityType;
  original_filename: string | null;
  file_sha256: string;
  status: ImportBatchStatus;
  mode: "preview" | "commit";
  created_by_user_id: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  created_rows: number;
  updated_rows: number;
  skipped_rows: number;
  conflict_rows: number;
  started_at: string | null;
  completed_at: string | null;
  committed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  creator_name?: string | null;
  available_actions?: Array<"commit" | "cancel" | "download_errors" | "view_rows">;
  duplicate_file_diagnostic?: DuplicateFileDiagnostic | null;
}

export interface ImportRowDiagnostic {
  id?: string;
  import_batch_id?: string;
  row_number: number;
  status: ImportRowStatus;
  action: ImportRowAction;
  entity_reference_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  field_errors?: Record<string, unknown>;
  normalized_data?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ImportPreviewResponse {
  batch: ImportBatch;
  rows: ImportRowDiagnostic[];
}

export interface ImportCommitResponse {
  batch: ImportBatch;
  rows: ImportRowDiagnostic[];
}

export interface ImportSummary {
  total_batches: number;
  by_entity_type: Record<string, number>;
  by_status: Record<string, number>;
  by_mode: Record<string, number>;
}

export interface ImportBatchFilters {
  entity_type?: ImportEntityType;
  status?: ImportBatchStatus;
  mode?: "preview" | "commit";
  created_from?: string;
  created_to?: string;
  created_by_user_id?: string;
  page?: number;
  page_size?: number;
}

export interface ImportRowFilters {
  status?: ImportRowStatus;
  action?: ImportRowAction;
  error_code?: string;
  page?: number;
  page_size?: number;
}

export interface PagedRows {
  items: ImportRowDiagnostic[];
  total: number;
  page: number;
  pageSize: number;
}

export interface PagedBatches {
  items: ImportBatch[];
  total: number;
  page: number;
  pageSize: number;
}

export class ImportsApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ImportsApiError";
    this.status = status;
    this.body = body;
  }
}

function parseApiError(error: unknown): ImportsApiError {
  if (!(error instanceof Error)) {
    return new ImportsApiError(0, "Unknown request failure.", null);
  }
  const match = error.message.match(/^API\s(\d+):\s([\s\S]*)$/);
  if (!match) return new ImportsApiError(0, error.message, null);
  const status = Number(match[1]);
  const bodyText = match[2] ?? "";
  let parsedBody: unknown = bodyText;
  try {
    parsedBody = JSON.parse(bodyText);
  } catch {
    // noop
  }
  const detail =
    typeof parsedBody === "object" && parsedBody !== null && "detail" in parsedBody
      ? String((parsedBody as { detail?: unknown }).detail)
      : bodyText;
  return new ImportsApiError(status, detail || `Request failed with status ${status}.`, parsedBody);
}

function authHeaders(): Record<string, string> {
  const token = readAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function toQueryParams(filters: Record<string, string | number | undefined>): Record<string, string> {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") {
      params[key] = String(value);
    }
  }
  return params;
}

function paginate<T>(items: T[], page = 1, pageSize = 20): { items: T[]; total: number; page: number; pageSize: number } {
  const total = items.length;
  const start = Math.max(0, (page - 1) * pageSize);
  return {
    items: items.slice(start, start + pageSize),
    total,
    page,
    pageSize,
  };
}

export async function previewImport(entityType: ImportEntityType, file: File): Promise<ImportPreviewResponse> {
  const form = new FormData();
  form.append("entity_type", entityType);
  form.append("file", file);
  try {
    return await api<ImportPreviewResponse>("/leadership/imports/preview", {
      method: "POST",
      headers: { ...authHeaders() },
      body: form,
    });
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function commitImport(batchId: string): Promise<ImportCommitResponse> {
  try {
    return await api<ImportCommitResponse>(`/leadership/imports/${batchId}/commit`, {
      method: "POST",
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function cancelImport(batchId: string): Promise<ImportBatch> {
  try {
    return await api<ImportBatch>(`/leadership/imports/${batchId}/cancel`, {
      method: "POST",
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function listImportBatches(filters: ImportBatchFilters = {}): Promise<PagedBatches> {
  try {
    const params = toQueryParams({
      entity_type: filters.entity_type,
      status: filters.status,
      mode: filters.mode,
      created_from: filters.created_from,
      created_to: filters.created_to,
      created_by_user_id: filters.created_by_user_id,
    });
    const all = await api<ImportBatch[]>("/leadership/imports", {
      method: "GET",
      headers: { ...authHeaders() },
      params,
    });
    const page = filters.page ?? 1;
    const pageSize = filters.page_size ?? 20;
    return paginate(all, page, pageSize);
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function getImportSummary(): Promise<ImportSummary> {
  try {
    return await api<ImportSummary>("/leadership/imports/summary", {
      method: "GET",
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function getImportBatch(batchId: string): Promise<ImportBatch> {
  try {
    return await api<ImportBatch>(`/leadership/imports/${batchId}`, {
      method: "GET",
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function listImportRows(batchId: string, filters: ImportRowFilters = {}): Promise<PagedRows> {
  try {
    const all = await api<ImportRowDiagnostic[]>(`/leadership/imports/${batchId}/rows`, {
      method: "GET",
      headers: { ...authHeaders() },
    });

    const filtered = all.filter((row) => {
      if (filters.status && row.status !== filters.status) return false;
      if (filters.action && row.action !== filters.action) return false;
      if (filters.error_code && row.error_code !== filters.error_code) return false;
      return true;
    });

    const page = filters.page ?? 1;
    const pageSize = filters.page_size ?? 50;
    return paginate(filtered, page, pageSize);
  } catch (err) {
    throw parseApiError(err);
  }
}

export async function downloadImportErrors(batchId: string): Promise<string> {
  const tenantSlug = readTenantSlug();
  const token = readAccessToken();
  const response = await fetch(`${API_BASE}/leadership/imports/${batchId}/errors.csv`, {
    method: "GET",
    headers: {
      "X-Tenant-Slug": tenantSlug,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail?: unknown }).detail)
        : typeof body === "string"
          ? body
          : `Request failed with status ${response.status}.`;
    throw new ImportsApiError(response.status, detail, body);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || response.headers.get("content-disposition") || "";
  const filenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const parsedFilename = decodeURIComponent(filenameMatch?.[1] || filenameMatch?.[2] || "").trim();
  const filename = parsedFilename && !/[\\/]/.test(parsedFilename) ? parsedFilename : `import-errors-${batchId}.csv`;

  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  } finally {
    URL.revokeObjectURL(url);
  }

  return filename;
}
