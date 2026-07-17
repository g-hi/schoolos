import {
  ParentApiError,
  getParentAssistantStatus,
  runParentAssistant,
  setParentUnauthorizedHandler,
} from "@/lib/parent-api";

describe("parent assistant api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setParentUnauthorizedHandler(null);
  });

  it("sends bearer token and tenant header for assistant requests", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        status: "completed",
        request_id: "req-1",
        conversation_id: "conv-1",
        message: "You have 1 linked child: Ahmed Hassan.",
        sources: [{ type: "student_profile", label: "Student Profile" }],
        suggested_questions: [],
        execution: {
          workflow: "parent_assistant",
          current_step: "parent_response",
          validation_passed: true,
          retry_count: 0,
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await runParentAssistant("token-parent", {
      message: "Summarize my family.",
      context: { active_student_id: "student-1" },
    });

    const [, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token-parent");
    expect(headers.get("X-Tenant-Slug")).toBeTruthy();
  });

  it("triggers unauthorized handler for assistant status requests", async () => {
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

    await expect(getParentAssistantStatus("bad-token", "req-1")).rejects.toBeInstanceOf(ParentApiError);
    expect(unauthorizedCalled).toBe(true);
  });
});