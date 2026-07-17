export const PARENT_SESSION_TOKEN_KEY = "schoolos.parent.accessToken";

/**
 * Transitional client-side auth storage for Phase 8.2.
 *
 * Tokens are intentionally stored in sessionStorage only for current development.
 * This will be replaced by secure cookie-based session handling in a later phase.
 */
export function readParentToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(PARENT_SESSION_TOKEN_KEY);
}

export function writeParentToken(token: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(PARENT_SESSION_TOKEN_KEY, token);
}

export function clearParentToken(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(PARENT_SESSION_TOKEN_KEY);
}
