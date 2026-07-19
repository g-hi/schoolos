const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://schoolos-gateway.onrender.com");
const DEFAULT_TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";

export const AUTH_TOKEN_KEY = "schoolos_access_token";
export const AUTH_TENANT_SLUG_KEY = "schoolos_tenant_slug";
export const AUTH_PROFILE_KEY = "schoolos_auth_profile";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthProfile {
  user_id: string;
  name: string;
  email: string;
  role: "parent" | "teacher" | "principal" | "school_admin" | "staff" | string;
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  is_active: boolean;
}

export class AuthApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
    this.body = body;
  }
}

function readSession(key: string): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(key);
}

function writeSession(key: string, value: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(key, value);
}

function removeSession(key: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(key);
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function buildUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function readAccessToken(): string | null {
  return readSession(AUTH_TOKEN_KEY);
}

export function writeAccessToken(token: string): void {
  writeSession(AUTH_TOKEN_KEY, token);
}

export function readTenantSlug(): string {
  return readSession(AUTH_TENANT_SLUG_KEY) || DEFAULT_TENANT;
}

export function writeTenantSlug(tenantSlug: string): void {
  writeSession(AUTH_TENANT_SLUG_KEY, tenantSlug.trim().toLowerCase());
}

export function readAuthProfile(): AuthProfile | null {
  const raw = readSession(AUTH_PROFILE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthProfile;
  } catch {
    return null;
  }
}

export function writeAuthProfile(profile: AuthProfile): void {
  writeSession(AUTH_PROFILE_KEY, JSON.stringify(profile));
}

export function clearAuthSession(): void {
  removeSession(AUTH_TOKEN_KEY);
  removeSession(AUTH_TENANT_SLUG_KEY);
  removeSession(AUTH_PROFILE_KEY);
}

export async function login(email: string, password: string, tenantSlug: string): Promise<LoginResponse> {
  const headers = new Headers({ "Content-Type": "application/json" });

  let response: Response;
  try {
    response = await fetch(buildUrl("/auth/token"), {
      method: "POST",
      headers,
      body: JSON.stringify({ email, password, tenant_slug: tenantSlug.trim().toLowerCase() }),
    });
  } catch {
    throw new AuthApiError(0, "Network request failed.", null);
  }

  const body = await parseResponseBody(response);
  if (!response.ok) {
    const message =
      typeof body === "object" && body !== null && "detail" in body && typeof (body as { detail?: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : typeof body === "string"
          ? body
          : `Request failed with status ${response.status}.`;
    throw new AuthApiError(response.status, message, body);
  }

  return body as LoginResponse;
}

export async function getMe(token: string, tenantSlug: string): Promise<AuthProfile> {
  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Tenant-Slug", tenantSlug.trim().toLowerCase());

  let response: Response;
  try {
    response = await fetch(buildUrl("/auth/me"), {
      method: "GET",
      headers,
    });
  } catch {
    throw new AuthApiError(0, "Network request failed.", null);
  }

  const body = await parseResponseBody(response);
  if (!response.ok) {
    const message =
      typeof body === "object" && body !== null && "detail" in body && typeof (body as { detail?: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : typeof body === "string"
          ? body
          : `Request failed with status ${response.status}.`;
    throw new AuthApiError(response.status, message, body);
  }

  return body as AuthProfile;
}

export function isLeadershipRole(role: string | null | undefined): boolean {
  return role === "principal" || role === "school_admin";
}

export function routeForRole(role: string | null | undefined): string | null {
  if (role === "parent") return "/parent";
  if (role === "teacher") return "/teacher";
  if (role === "principal" || role === "school_admin") return "/";
  return null;
}
