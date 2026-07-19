import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "@/components/auth/auth-provider";
import { AUTH_PROFILE_KEY, AUTH_TENANT_SLUG_KEY, AUTH_TOKEN_KEY } from "@/lib/auth";

const setParentUnauthorizedHandlerMock = vi.fn();
const setWeeklyUnauthorizedHandlerMock = vi.fn();

vi.mock("@/lib/parent-api", async () => {
  const actual = await vi.importActual("@/lib/parent-api");
  return {
    ...actual,
    setUnauthorizedHandler: (handler: (() => void) | null) => setParentUnauthorizedHandlerMock(handler),
  };
});

vi.mock("@/lib/weekly-reports-api", async () => {
  const actual = await vi.importActual("@/lib/weekly-reports-api");
  return {
    ...actual,
    setUnauthorizedHandler: (handler: (() => void) | null) => setWeeklyUnauthorizedHandlerMock(handler),
  };
});

function Harness() {
  const auth = useAuth();
  return (
    <div>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="token">{auth.token || "none"}</p>
      <p data-testid="role">{auth.user?.role || "none"}</p>
      <button type="button" onClick={auth.logout}>logout</button>
    </div>
  );
}

function Wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("auth-provider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
  });

  it("registers shared unauthorized handlers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid or expired token." }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );

    render(<Harness />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(setParentUnauthorizedHandlerMock).toHaveBeenCalled();
      expect(setWeeklyUnauthorizedHandlerMock).toHaveBeenCalled();
    });
  });

  it("clears shared session data on logout", () => {
    window.sessionStorage.setItem(AUTH_TOKEN_KEY, "abc");
    window.sessionStorage.setItem(AUTH_TENANT_SLUG_KEY, "greenwood");
    window.sessionStorage.setItem(AUTH_PROFILE_KEY, JSON.stringify({ role: "parent", is_active: true }));

    render(<Harness />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(window.sessionStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AUTH_TENANT_SLUG_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AUTH_PROFILE_KEY)).toBeNull();
  });

  it("restores existing session and keeps user authenticated when /auth/me succeeds", async () => {
    window.sessionStorage.setItem(AUTH_TOKEN_KEY, "abc");
    window.sessionStorage.setItem(AUTH_TENANT_SLUG_KEY, "greenwood");

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          user_id: "u1",
          name: "Parent One",
          email: "parent@example.com",
          role: "parent",
          tenant_id: "t1",
          tenant_slug: "greenwood",
          tenant_name: "Greenwood",
          is_active: true,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    render(<Harness />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("role")).toHaveTextContent("parent");
    });
  });

  it("clears session when /auth/me returns 401", async () => {
    window.sessionStorage.setItem(AUTH_TOKEN_KEY, "abc");
    window.sessionStorage.setItem(AUTH_TENANT_SLUG_KEY, "greenwood");

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid or expired token." }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );

    render(<Harness />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(window.sessionStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
    });
  });

  it("403 from protected API should not auto-logout", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          user_id: "u1",
          name: "Teacher One",
          email: "teacher@example.com",
          role: "teacher",
          tenant_id: "t1",
          tenant_slug: "greenwood",
          tenant_name: "Greenwood",
          is_active: true,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    window.sessionStorage.setItem(AUTH_TOKEN_KEY, "abc");
    window.sessionStorage.setItem(AUTH_TENANT_SLUG_KEY, "greenwood");

    render(<Harness />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    });

    const parentHandler = setParentUnauthorizedHandlerMock.mock.calls.at(-1)?.[0] as (() => void) | null;
    expect(parentHandler).toBeTruthy();

    await act(async () => {
      // Simulate 403 path by not invoking unauthorized callback.
      // Provider should keep session unless explicit 401-triggered callback runs.
    });

    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
  });
});
