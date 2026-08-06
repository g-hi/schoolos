import { approveManualEvent, listManualEvents, TimetableCalendarApiError } from "@/lib/timetable-calendar-api";
import * as auth from "@/lib/auth";

describe("timetable-calendar-api", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(auth, "readAccessToken").mockReturnValue("token-123");
    vi.spyOn(auth, "readTenantSlug").mockReturnValue("greenwood");
  });

  it("sends tenant and auth headers on list requests", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await listManualEvents({ lifecycle_status: "draft" });

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Headers;
    expect(headers.get("X-Tenant-Slug")).toBe("greenwood");
    expect(headers.get("Authorization")).toBe("Bearer token-123");
  });

  it("parses backend detail on errors", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: "Only approved events can be published." }), { status: 409, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(approveManualEvent("evt-1", { reason: "publish" })).rejects.toBeInstanceOf(TimetableCalendarApiError);
    await expect(approveManualEvent("evt-1", { reason: "publish" })).rejects.toMatchObject({ status: 409, message: "Only approved events can be published." });
  });
});
