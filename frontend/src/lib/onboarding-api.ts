import { readAccessToken, readTenantSlug } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";

export type OnboardingRunStatus = "not_started" | "in_progress" | "paused" | "ready" | "completed" | "cancelled";
export type OnboardingStepStatus = "not_started" | "in_progress" | "blocked" | "completed" | "skipped";
export type OnboardingCompletionSource = "computed" | "manual" | "imported";
export type ReadinessCheckStatus = "complete" | "blocking" | "warning" | "informational";
export type OnboardingAction = "start" | "pause" | "resume" | "complete" | "cancel" | "set_current_step" | "acknowledge_step" | "skip_optional_step";
export type SafeActionRoute = "/academic-structure" | "/people" | "/data" | "/timetable";

export interface OnboardingRunSummary {
  id: string;
  status: Exclude<OnboardingRunStatus, "not_started">;
  current_step_key: string | null;
  started_by_user_id: string;
  completed_by_user_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  paused_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface OrderedStep {
  step_key: string;
  status: OnboardingStepStatus;
  persisted_status?: OnboardingStepStatus;
  completion_source?: OnboardingCompletionSource | null;
  acknowledged_by_user_id?: string | null;
  acknowledged_at?: string | null;
  blocked_reason?: string | null;
}

export interface GroupedProgress {
  total: number;
  completed: number;
  blocked: number;
  in_progress: number;
  not_started: number;
}

export interface OnboardingStatusResponse {
  run: OnboardingRunSummary | null;
  run_status: OnboardingRunStatus;
  current_step: string | null;
  started_at: string | null;
  completed_at: string | null;
  readiness_percentage: number;
  completed_step_count: number;
  blocked_step_count: number;
  warning_count: number;
  next_recommended_step: string | null;
  ordered_steps: OrderedStep[];
  grouped_progress: Record<string, GroupedProgress>;
  available_actions: OnboardingAction[];
}

export interface ReadinessCheck {
  check_key: string;
  step_key: string;
  title: string;
  status: ReadinessCheckStatus;
  current_value: string | number;
  required_value: string | number;
  message: string;
  recommended_action: string;
  action_route: SafeActionRoute;
  evidence_source: string;
}

export interface RecommendedAction {
  step_key: string;
  check_key: string;
  message: string;
  action_route: SafeActionRoute;
}

export interface OnboardingReadinessResponse {
  state: OnboardingRunStatus | "blocked";
  readiness_percentage: number;
  blocker_count: number;
  warning_count: number;
  informational_count: number;
  grouped_readiness_checks: Record<string, ReadinessCheck[]>;
  recommended_next_actions: RecommendedAction[];
  safe_routes: SafeActionRoute[];
}

export interface OnboardingHistoryItem {
  run_id: string;
  status: Exclude<OnboardingRunStatus, "not_started">;
  started_at: string | null;
  completed_at: string | null;
  paused_at: string | null;
  started_by_user_id: string;
  completed_by_user_id: string | null;
  completion_percentage: number;
  blocker_count: number;
  warning_count: number;
}

export interface OnboardingHistoryResponse {
  items: OnboardingHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface OnboardingHistoryFilters {
  page?: number;
  page_size?: number;
}

export class OnboardingApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "OnboardingApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== "") {
        url.searchParams.set(key, value);
      }
    }
  }

  const token = readAccessToken();
  const tenantSlug = readTenantSlug();
  const headers = new Headers(init?.headers || {});
  headers.set("X-Tenant-Slug", tenantSlug);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      ...init,
      headers,
    });
  } catch {
    throw new OnboardingApiError(0, "Network request failed.", null);
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = await response.text();
  }

  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail?: unknown }).detail)
        : typeof body === "string"
          ? body
          : `Request failed with status ${response.status}.`;
    throw new OnboardingApiError(response.status, detail, body);
  }

  return body as T;
}

export function getOnboardingStatus(): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>("/leadership/onboarding/status", { method: "GET" });
}

export function getOnboardingReadiness(): Promise<OnboardingReadinessResponse> {
  return request<OnboardingReadinessResponse>("/leadership/onboarding/readiness", { method: "GET" });
}

export function listOnboardingHistory(filters: OnboardingHistoryFilters = {}): Promise<OnboardingHistoryResponse> {
  return request<OnboardingHistoryResponse>(
    "/leadership/onboarding/history",
    { method: "GET" },
    {
      page: String(filters.page ?? 1),
      page_size: String(filters.page_size ?? 10),
    },
  );
}

export function startOnboarding(): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>("/leadership/onboarding/start", { method: "POST" });
}

export function updateCurrentStep(stepKey: string): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>("/leadership/onboarding/current-step", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step_key: stepKey }),
  });
}

export function acknowledgeOnboardingStep(stepKey: string, note?: string): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>(`/leadership/onboarding/steps/${encodeURIComponent(stepKey)}/acknowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note: note ?? null }),
  });
}

export function skipOnboardingStep(stepKey: string, reason: string): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>(`/leadership/onboarding/steps/${encodeURIComponent(stepKey)}/skip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function pauseOnboarding(): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>("/leadership/onboarding/pause", { method: "POST" });
}

export function resumeOnboarding(): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>("/leadership/onboarding/resume", { method: "POST" });
}

export function completeOnboarding(): Promise<OnboardingStatusResponse> {
  return request<OnboardingStatusResponse>("/leadership/onboarding/complete", { method: "POST" });
}

export function cancelOnboarding(): Promise<{ run_id: string; status: "cancelled"; completed_at: string | null }> {
  return request<{ run_id: string; status: "cancelled"; completed_at: string | null }>("/leadership/onboarding/cancel", { method: "POST" });
}
