import {
  listPolicySets,
  getPolicyReadiness,
  submitPolicySet,
  TimetablePoliciesApiError,
} from "@/lib/timetable-policies-api";

const readAccessTokenMock = vi.fn();
const readTenantSlugMock = vi.fn();

vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return {
    ...actual,
    readAccessToken: () => readAccessTokenMock(),
    readTenantSlug: () => readTenantSlugMock(),
  };
});

describe("timetable-policies-api", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readAccessTokenMock.mockReturnValue("token-123");
    readTenantSlugMock.mockReturnValue("greenwood");
  });

  it("sends auth headers and no tenant query for listPolicySets", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listPolicySets({ lifecycle_status: "active" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/leadership/timetable-policies/policy-sets");
    expect(url).toContain("lifecycle_status=active");
    expect(url).not.toContain("tenant=");

    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token-123");
    expect(headers.get("X-Tenant-Slug")).toBe("greenwood");
  });

  it("encodes readiness filters and forwards AbortSignal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ generation_allowed: false }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const controller = new AbortController();
    await getPolicyReadiness({ academic_year_id: "year-1", term_id: "term-1", signal: controller.signal });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("academic_year_id=year-1");
    expect(url).toContain("term_id=term-1");
    expect(init.signal).toBe(controller.signal);
  });

  it("uses POST for lifecycle methods", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "set-1", lifecycle_status: "pending_review" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await submitPolicySet("set-1", { reason: "ready for review" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/leadership/timetable-policies/policy-sets/set-1/submit");
    expect(init.method).toBe("POST");
  });

  it("parses backend errors into TimetablePoliciesApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Unsupported lifecycle_status." }), {
        status: 422,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPolicySets({ lifecycle_status: "bad" })).rejects.toEqual(
      expect.objectContaining<TimetablePoliciesApiError>({
        status: 422,
        message: "Unsupported lifecycle_status.",
      }),
    );
  });
});
