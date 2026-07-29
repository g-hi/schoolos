import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import StudentPickupPage from "@/app/teacher/student-pickup/page";
import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  listTeacherPickupRequests,
  acknowledgeTeacherPickupRequest,
  callTeacherPickupRequest,
  prepareTeacherPickupRequest,
} from "@/lib/teacher-api";

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/lib/teacher-api", () => ({
  TeacherApiError: class TeacherApiError extends Error {
    status: number;
    body: unknown;

    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
  listTeacherPickupRequests: vi.fn(),
  acknowledgeTeacherPickupRequest: vi.fn(),
  callTeacherPickupRequest: vi.fn(),
  prepareTeacherPickupRequest: vi.fn(),
}));

const mockAuth = {
  isAuthenticated: true,
  isHydrating: false,
  token: "mock-token",
  user: {
    id: "teacher-1",
    role: "teacher",
    name: "Mr. Smith",
  },
};

function pickup(status: string, id: string) {
  return {
    pickup_id: id,
    student_id: "student-1",
    parent_id: "parent-1",
    class_id: "class-1",
    teacher_id: "teacher-1",
    status: status as any,
    channel: "app",
    requested_at: "2026-07-29T08:00:00Z",
    acknowledged_at: status !== "requested" ? "2026-07-29T08:05:00Z" : null,
    called_at: ["called", "prepared", "completed"].includes(status) ? "2026-07-29T08:10:00Z" : null,
    prepared_at: ["prepared", "completed"].includes(status) ? "2026-07-29T08:15:00Z" : null,
    completed_at: status === "completed" ? "2026-07-29T08:20:00Z" : null,
    cancelled_at: status === "cancelled" ? "2026-07-29T08:20:00Z" : null,
    verified_by: status === "completed" ? "teacher-1" : null,
    verified_at: status === "completed" ? "2026-07-29T08:20:00Z" : null,
    verification_method: status === "completed" ? "id_check" : null,
    verification_note: status === "completed" ? "Student verified" : null,
    notes: "At the main gate",
    within_geofence: false,
    distance_meters: 100,
    early_pickup: false,
  };
}

describe("teacher student pickup page", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue(mockAuth);

    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
    });
  });

  it("renders loading state initially", async () => {
    render(<StudentPickupPage />);
    await waitFor(() => {
      expect(screen.getByText("Student Pickup")).toBeInTheDocument();
    });
  });

  it("renders empty state when no pickups exist", async () => {
    render(<StudentPickupPage />);
    await waitFor(() => {
      expect(screen.getByText("No active pickup requests.")).toBeInTheDocument();
    });
  });

  it("renders active pickups with requested status", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Student ID: student-1")).toBeInTheDocument();
      expect(screen.getAllByText("Requested").some((el) => el.textContent?.includes("Requested"))).toBeTruthy();
    });
  });

  it("allows teacher to acknowledge a requested pickup", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        items: [pickup("requested", "pickup-1")],
        page: 1,
        page_size: 20,
      })
      .mockResolvedValueOnce({
        items: [pickup("acknowledged", "pickup-1")],
        page: 1,
        page_size: 20,
      });

    (acknowledgeTeacherPickupRequest as ReturnType<typeof vi.fn>).mockResolvedValue(
      pickup("acknowledged", "pickup-1"),
    );

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Mark as acknowledge")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Mark as acknowledge"));

    await waitFor(() => {
      expect(acknowledgeTeacherPickupRequest).toHaveBeenCalledWith(
        "pickup-1",
        {},
        "mock-token",
      );
    });
  });

  it("allows teacher to call an acknowledged pickup", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("acknowledged", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    (callTeacherPickupRequest as ReturnType<typeof vi.fn>).mockResolvedValue(
      pickup("called", "pickup-1"),
    );

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Mark as call")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Mark as call"));

    await waitFor(() => {
      expect(callTeacherPickupRequest).toHaveBeenCalledWith("pickup-1", {}, "mock-token");
    });
  });

  it("allows teacher to prepare a called pickup", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("called", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    (prepareTeacherPickupRequest as ReturnType<typeof vi.fn>).mockResolvedValue(
      pickup("prepared", "pickup-1"),
    );

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Mark as prepare")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Mark as prepare"));

    await waitFor(() => {
      expect(prepareTeacherPickupRequest).toHaveBeenCalledWith(
        "pickup-1",
        {},
        "mock-token",
      );
    });
  });

  it("does not show completion button for teacher", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("prepared", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Student ID: student-1")).toBeInTheDocument();
    });

    // Should not have complete button for teacher - check for action buttons on the prepared pickup
    const actionButtons = screen.queryAllByRole("button").filter((btn) =>
      ["complete", "verify", "release"].some((action) => btn.textContent?.toLowerCase().includes(action))
    );
    expect(actionButtons).toHaveLength(0);
  });

  it("shows terminal status as read-only without actions", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("completed", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Completed")).toBeInTheDocument();
    });

    // Should not have any action buttons for completed pickup
    const actionButtons = screen.queryAllByRole("button").filter((btn) =>
      ["acknowledge", "call", "prepare", "complete"].some((action) =>
        btn.textContent?.includes(action),
      ),
    );
    expect(actionButtons).toHaveLength(0);
  });

  it("displays pickup history section for completed pickups", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        pickup("requested", "pickup-1"),
        pickup("completed", "pickup-2"),
      ],
      page: 1,
      page_size: 20,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Pickup history")).toBeInTheDocument();
    });
  });

  it("handles API error gracefully", async () => {
    const apiError = new TeacherApiError(500, "Server error", null);
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockRejectedValue(apiError);

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Error loading pickups")).toBeInTheDocument();
    });
  });

  it("handles 403 forbidden error", async () => {
    const apiError = new TeacherApiError(403, "You do not have access to this resource.", null);
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockRejectedValue(apiError);

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("You do not have access to this pickup request.")).toBeInTheDocument();
    });
  });

  it("handles 404 not found error", async () => {
    const apiError = new TeacherApiError(404, "Pickup request not found.", null);
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockRejectedValue(apiError);

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("The pickup request was not found.")).toBeInTheDocument();
    });
  });

  it("allows refresh of pickups", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Student ID: student-1")).toBeInTheDocument();
    });

    const refreshButton = screen.getByText("Refresh");
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(listTeacherPickupRequests).toHaveBeenCalledTimes(2);
    });
  });

  it("filters pickups by status", async () => {
    (listTeacherPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("All statuses")).toBeInTheDocument();
    });

    const statusSelect = screen.getByDisplayValue("All statuses");
    fireEvent.change(statusSelect, { target: { value: "acknowledged" } });

    await waitFor(() => {
      expect(listTeacherPickupRequests).toHaveBeenCalledWith(
        {
          status: "acknowledged",
          page: 1,
          page_size: 50,
        },
        "mock-token",
      );
    });
  });

  it("redirects unauthenticated users", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      ...mockAuth,
      isAuthenticated: false,
    });

    render(<StudentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Please log in to view pickup requests.")).toBeInTheDocument();
    });
  });
});
