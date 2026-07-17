export const PARENT_SESSION_TOKEN_KEY = "schoolos.parent.accessToken";
export const PARENT_ASSISTANT_REQUEST_ID_KEY = "schoolos.parent.assistant.requestId";
export const PARENT_ASSISTANT_CONVERSATION_ID_KEY = "schoolos.parent.assistant.conversationId";

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

export function readParentAssistantRequestId(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(PARENT_ASSISTANT_REQUEST_ID_KEY);
}

export function writeParentAssistantRequestId(requestId: string | null): void {
  if (typeof window === "undefined") return;
  if (!requestId) {
    window.sessionStorage.removeItem(PARENT_ASSISTANT_REQUEST_ID_KEY);
    return;
  }
  window.sessionStorage.setItem(PARENT_ASSISTANT_REQUEST_ID_KEY, requestId);
}

export function readParentAssistantConversationId(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(PARENT_ASSISTANT_CONVERSATION_ID_KEY);
}

export function writeParentAssistantConversationId(conversationId: string | null): void {
  if (typeof window === "undefined") return;
  if (!conversationId) {
    window.sessionStorage.removeItem(PARENT_ASSISTANT_CONVERSATION_ID_KEY);
    return;
  }
  window.sessionStorage.setItem(PARENT_ASSISTANT_CONVERSATION_ID_KEY, conversationId);
}

export function clearParentAssistantSession(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(PARENT_ASSISTANT_REQUEST_ID_KEY);
  window.sessionStorage.removeItem(PARENT_ASSISTANT_CONVERSATION_ID_KEY);
}
