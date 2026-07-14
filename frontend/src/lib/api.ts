const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";
const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";

export async function api<T = unknown>(
  path: string,
  options?: RequestInit & { params?: Record<string, string> }
): Promise<T> {
  const { params, ...init } = options || {};
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString(), {
    ...init,
    headers: {
      "X-Tenant-Slug": TENANT,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export function apiUpload<T = unknown>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return api<T>(path, { method: "POST", body: form });
}

export function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface CopilotRunRequest {
  intent: string;
  message: string;
  structured_input?: Record<string, unknown>;
  conversation_id?: string;
}

export interface CopilotContinueRequest {
  request_id: string;
  message?: string;
  structured_input?: Record<string, unknown>;
}

export interface CopilotApproveRequest {
  request_id: string;
  approved: boolean;
  notes?: string;
}

export interface CopilotResponse {
  status: "needs_clarification" | "pending_review" | "approved" | "unsupported_intent" | "error";
  request_id: string;
  conversation_id?: string | null;
  intent?: string | null;
  message: string;
  missing_fields?: string[];
  clarification_question?: string | null;
  result?: Record<string, unknown> | null;
  execution: {
    workflow: string;
    current_step: string;
    validation_passed: boolean;
    retry_count: number;
  };
}

export function copilotRun(body: CopilotRunRequest): Promise<CopilotResponse> {
  return apiPost<CopilotResponse>("/ai/copilot/run", body);
}

export function copilotContinue(body: CopilotContinueRequest): Promise<CopilotResponse> {
  return apiPost<CopilotResponse>("/ai/copilot/continue", body);
}

export function copilotApprove(body: CopilotApproveRequest): Promise<CopilotResponse> {
  return apiPost<CopilotResponse>("/ai/copilot/approve", body);
}

export function copilotStatus(requestId: string): Promise<CopilotResponse> {
  return api<CopilotResponse>(`/ai/copilot/status/${requestId}`);
}
