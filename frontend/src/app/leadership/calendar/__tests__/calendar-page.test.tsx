import { render, screen, waitFor } from "@testing-library/react";
import LeadershipCalendarPage from "@/app/leadership/calendar/page";

const replaceMock = vi.fn();
const useAuthMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/leadership/calendar",
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/lib/timetable-calendar-api", async () => {
  const actual = await vi.importActual("@/lib/timetable-calendar-api");
  return {
    ...actual,
    listManualEvents: vi.fn(async () => []),
    listCalendarPdfImports: vi.fn(async () => []),
    listNotificationPlans: vi.fn(async () => []),
    getManualEvent: vi.fn(async () => null),
    listEventVersions: vi.fn(async () => []),
    getEventImpact: vi.fn(async () => null),
    getCalendarPdfImport: vi.fn(async () => null),
    getCalendarPdfPages: vi.fn(async () => ({ page: 1, page_size: 5, total: 0, items: [] })),
    listCalendarPdfCandidates: vi.fn(async () => ({ page: 1, page_size: 10, total: 0, items: [] })),
    getCalendarPdfDiagnostics: vi.fn(async () => ({ document_id: "doc", diagnostics: [], blocker_count: 0, warning_count: 0 })),
  };
});

describe("leadership calendar page authorization and shell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows unauthorized state for teacher role", async () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "teacher", is_active: true } });
    render(<LeadershipCalendarPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/only authorised leadership/i);
  });

  it("renders leadership tabs for principal", async () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: true, user: { role: "principal", is_active: true } });
    render(<LeadershipCalendarPage />);
    expect(await screen.findByText("Academic Calendar")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Notification Plans" })).toBeInTheDocument();
  });

  it("redirects unauthenticated users via role guard", async () => {
    useAuthMock.mockReturnValue({ isHydrating: false, isAuthenticated: false, user: null });
    render(<LeadershipCalendarPage />);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
  });
});
