import {
  AUTH_PROFILE_KEY,
  AUTH_TENANT_SLUG_KEY,
  AUTH_TOKEN_KEY,
  clearAuthSession,
  getMe,
  login,
  readAccessToken,
  readAuthProfile,
  readTenantSlug,
  writeAccessToken,
  writeAuthProfile,
  writeTenantSlug,
} from "@/lib/auth";

describe("auth lib", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("stores and reads token in sessionStorage", () => {
    writeAccessToken("token-1");
    expect(readAccessToken()).toBe("token-1");
    expect(window.sessionStorage.getItem(AUTH_TOKEN_KEY)).toBe("token-1");
  });

  it("stores and reads tenant slug in sessionStorage", () => {
    writeTenantSlug(" GREENWOOD ");
    expect(readTenantSlug()).toBe("greenwood");
    expect(window.sessionStorage.getItem(AUTH_TENANT_SLUG_KEY)).toBe("greenwood");
  });

  it("stores and reads auth profile in sessionStorage", () => {
    writeAuthProfile({
      user_id: "u1",
      name: "User One",
      email: "u1@example.com",
      role: "parent",
      tenant_id: "t1",
      tenant_slug: "greenwood",
      tenant_name: "Greenwood",
      is_active: true,
    });

    expect(readAuthProfile()?.role).toBe("parent");
    expect(window.sessionStorage.getItem(AUTH_PROFILE_KEY)).toContain("User One");
  });

  it("clears unified auth session keys", () => {
    writeAccessToken("token-1");
    writeTenantSlug("greenwood");
    writeAuthProfile({
      user_id: "u1",
      name: "User One",
      email: "u1@example.com",
      role: "parent",
      tenant_id: "t1",
      tenant_slug: "greenwood",
      tenant_name: "Greenwood",
      is_active: true,
    });

    clearAuthSession();

    expect(window.sessionStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AUTH_TENANT_SLUG_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AUTH_PROFILE_KEY)).toBeNull();
  });

  it("never writes auth data to localStorage", () => {
    writeAccessToken("token-1");
    writeTenantSlug("greenwood");
    writeAuthProfile({
      user_id: "u1",
      name: "User One",
      email: "u1@example.com",
      role: "parent",
      tenant_id: "t1",
      tenant_slug: "greenwood",
      tenant_name: "Greenwood",
      is_active: true,
    });
    expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(window.localStorage.getItem(AUTH_TENANT_SLUG_KEY)).toBeNull();
    expect(window.localStorage.getItem(AUTH_PROFILE_KEY)).toBeNull();
  });

  it("calls /auth/token without X-User headers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ access_token: "abc", token_type: "bearer", expires_in: 3600 }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    await login("teacher@example.com", "secret", "greenwood");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/auth/token");
    const headers = init?.headers as Headers;
    expect(headers.get("X-User-Id")).toBeNull();
    expect(headers.get("X-User-Role")).toBeNull();
  });

  it("calls /auth/me with bearer + tenant and no trusted role headers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
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

    await getMe("token-abc", "greenwood");

    const [, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token-abc");
    expect(headers.get("X-Tenant-Slug")).toBe("greenwood");
    expect(headers.get("X-User-Id")).toBeNull();
    expect(headers.get("X-User-Role")).toBeNull();
  });
});
