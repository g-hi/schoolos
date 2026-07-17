import {
  ParentApiError,
  getParentDashboard,
  setParentUnauthorizedHandler,
} from "@/lib/parent-api";

describe("parent-api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setParentUnauthorizedHandler(null);
  });

  it("sends tenant and authorization headers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        family_name: null,
        family_id: null,
        students: [],
        timeline_preview: [],
        pickup: { available: true, active_requests: [] },
        academics: { available: false, reason: "n/a" },
        attendance: { available: false, reason: "n/a" },
        homework: { available: false, reason: "n/a" },
        reports: { available: false, reason: "n/a" },
        messages: { available: false, reason: "n/a" },
        payments: { available: false, reason: "n/a" },
        announcements: { available: false, reason: "n/a" },
        notifications: { available: false, reason: "n/a" },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await getParentDashboard("token-abc");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/parent/dashboard");

    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token-abc");
    expect(headers.get("X-Tenant-Slug")).toBeTruthy();
  });

  it("triggers unauthorized handler on 401", async () => {
    let unauthorizedCalled = false;
    setParentUnauthorizedHandler(() => {
      unauthorizedCalled = true;
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid or expired token." }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(getParentDashboard("bad-token")).rejects.toBeInstanceOf(ParentApiError);
    expect(unauthorizedCalled).toBe(true);
  });
});
