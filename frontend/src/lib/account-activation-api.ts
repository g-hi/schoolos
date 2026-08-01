const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://schoolos-gateway.onrender.com");

export class AccountActivationApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AccountActivationApiError";
    this.status = status;
  }
}

export interface AcceptInvitationResponse {
  status: "accepted";
  user_id: string;
  tenant_id: string;
  role: string;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function toUserSafeError(status: number): AccountActivationApiError {
  if (status === 400) {
    return new AccountActivationApiError(status, "The activation link is invalid.");
  }
  if (status === 409) {
    return new AccountActivationApiError(status, "This activation link is no longer valid.");
  }
  if (status === 410) {
    return new AccountActivationApiError(status, "This activation link has expired.");
  }
  if (status === 422) {
    return new AccountActivationApiError(status, "Your password does not meet the policy requirements.");
  }
  if (status === 0) {
    return new AccountActivationApiError(status, "Network request failed.");
  }
  return new AccountActivationApiError(status, "Activation failed. Please request a new invitation.");
}

export async function acceptInvitation(token: string, newPassword: string): Promise<AcceptInvitationResponse> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE}/auth/accept-invitation`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        token,
        new_password: newPassword,
      }),
    });
  } catch {
    throw toUserSafeError(0);
  }

  const body = await parseResponseBody(response);
  if (!response.ok) {
    throw toUserSafeError(response.status);
  }

  return body as AcceptInvitationResponse;
}
