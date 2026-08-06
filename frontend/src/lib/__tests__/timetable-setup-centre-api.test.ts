import * as auth from "@/lib/auth";
import {
  getSetupCentreActivity,
  getSetupCentreApprovals,
  getSetupCentreIssues,
  getSetupCentreRecommendations,
  getSetupCentreSummary,
  revalidateSetupCentre,
  TimetableSetupCentreApiError,
} from "@/lib/timetable-setup-centre-api";

describe("timetable-setup-centre-api", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(auth, "readAccessToken").mockReturnValue("token-123");
    vi.spyOn(auth, "readTenantSlug").mockReturnValue("greenwood");
  });

  it("sends auth headers and encodes filters without a tenant query parameter", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ generated_at: "2026-01-01T00:00:00Z", progress: {}, generation: {}, provenance: {}, source_breakdown: {}, review_breakdown: {}, import_summaries: { workbook: {}, pdf: {}, total_pending: 0, total_failed: 0, total_committed: 0, latest_imports: { workbook: null, pdf: null } }, approval_queue: { items: [], pending_total: 0, direct_route: "/leadership/timetable-setup/centre/approvals" }, policy: {}, counts: {} }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await getSetupCentreSummary();
    await getSetupCentreIssues({ severity: "blocker", page: 2, page_size: 10 });
    await getSetupCentreApprovals({ type: "calendar_candidate_pending_review", page: 1, page_size: 5 });
    await getSetupCentreActivity({ action_type: "timetable_setup.calendar", entity_type: "OperationalCalendarEvent", page: 1, page_size: 5 });
    await getSetupCentreRecommendations();
    await revalidateSetupCentre();

    const firstUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(firstUrl.pathname).toBe("/leadership/timetable-setup/centre/summary");
    expect(firstUrl.searchParams.get("tenant")).toBeNull();

    const issuesUrl = new URL(fetchMock.mock.calls[1][0] as string);
    expect(issuesUrl.searchParams.get("severity")).toBe("blocker");
    expect(issuesUrl.searchParams.get("page")).toBe("2");
    expect(issuesUrl.searchParams.get("page_size")).toBe("10");

    const approvalsUrl = new URL(fetchMock.mock.calls[2][0] as string);
    expect(approvalsUrl.searchParams.get("type")).toBe("calendar_candidate_pending_review");

    const activityUrl = new URL(fetchMock.mock.calls[3][0] as string);
    expect(activityUrl.searchParams.get("action_type")).toBe("timetable_setup.calendar");
    expect(activityUrl.searchParams.get("entity_type")).toBe("OperationalCalendarEvent");

    expect(fetchMock.mock.calls[5][1]?.method).toBe("POST");
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("X-Tenant-Slug")).toBe("greenwood");
    expect(headers.get("Authorization")).toBe("Bearer token-123");
  });

  it("parses backend detail on errors", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: "Generation is blocked." }), { status: 409, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSetupCentreSummary()).rejects.toBeInstanceOf(TimetableSetupCentreApiError);
    await expect(getSetupCentreSummary()).rejects.toMatchObject({ status: 409, message: "Generation is blocked." });
  });
});