import {
  TimetableGenerationApiError,
  getEffectiveTimetableVersion,
  listGenerationConfigurations,
  materializeVersionFromCandidate,
  publishTimetableVersion,
  previewTimetableCandidates,
} from "@/lib/timetable-generation-api";

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

describe("timetable-generation-api", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readAccessTokenMock.mockReturnValue("token-xyz");
    readTenantSlugMock.mockReturnValue("greenwood");
  });

  it("sends auth headers and list filters without tenant query override", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listGenerationConfigurations({ lifecycle_status: "approved" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/leadership/timetable-generation/configurations");
    expect(url).toContain("lifecycle_status=approved");
    expect(url).not.toContain("tenant=");

    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token-xyz");
    expect(headers.get("X-Tenant-Slug")).toBe("greenwood");
  });

  it("posts candidate preview body with deterministic controls", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          summary: {},
          candidate_result: {
            problem_id: "p1",
            problem_fingerprint: "fp1",
            requested_count: 3,
            generated_count: 1,
            candidates: [],
            comparison: null,
            attempts: [],
            warnings: [],
            diagnostics: [],
            duration_ms: 0,
            deterministic: true,
            provenance: {},
          },
          explicit_non_actions: {},
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await previewTimetableCandidates("cfg-1", {
      candidate_count: 3,
      candidate_profiles: ["configured", "balanced"],
      include_comparison: true,
      include_explanation_facts: true,
      response_mode: "detailed",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/leadership/timetable-generation/configurations/cfg-1/candidates/preview");
    expect(init.method).toBe("POST");
    expect(init.body).toContain("\"candidate_count\":3");
    expect(init.body).toContain("\"response_mode\":\"detailed\"");
  });

  it("materialization sends candidate IDs and fingerprints only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ timetable: { id: "t1" }, version: { id: "v1" }, explicit_non_actions: {} }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await materializeVersionFromCandidate("cfg-1", {
      candidate_id: "cand_1",
      expected_problem_fingerprint: "pf-1",
      expected_assignment_fingerprint: "af-1",
      candidate_profiles: ["configured", "balanced"],
      candidate_count: 3,
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.candidate_id).toBe("cand_1");
    expect(body.expected_problem_fingerprint).toBe("pf-1");
    expect(body.expected_assignment_fingerprint).toBe("af-1");
    expect("assignments" in body).toBe(false);
  });

  it("posts effective date for publish transition", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "v4", lifecycle_status: "published" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await publishTimetableVersion("v4", "2026-10-01");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/leadership/timetable-generation/timetable-versions/v4/publish");
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"effective_from":"2026-10-01"}');
  });

  it("encodes effective version date query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ effective_on: "2026-08-08", version: null }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getEffectiveTimetableVersion("tt-1", "2026-08-08", true);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("on=2026-08-08");
    expect(url).toContain("include_assignments=true");
  });

  it("parses structured backend detail code for stale candidate", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "stale_candidate_preview",
            message: "Scheduling problem changed since candidate preview.",
          },
        }),
        {
          status: 409,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      materializeVersionFromCandidate("cfg-1", {
        candidate_id: "cand_1",
        expected_problem_fingerprint: "old",
      }),
    ).rejects.toEqual(
      expect.objectContaining<TimetableGenerationApiError>({
        status: 409,
        code: "stale_candidate_preview",
        message: "Scheduling problem changed since candidate preview.",
      }),
    );
  });
});