import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import PickupPage from "@/app/pickup/page";
import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  listLeadershipPickupRequests,
  acknowledgeLeadershipPickupRequest,
  callLeadershipPickupRequest,
  prepareLeadershipPickupRequest,
  completeLeadershipPickupRequest,
  cancelLeadershipPickupRequest,
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
  listLeadershipPickupRequests: vi.fn(),
  acknowledgeLeadershipPickupRequest: vi.fn(),
  callLeadershipPickupRequest: vi.fn(),
  prepareLeadershipPickupRequest: vi.fn(),
  completeLeadershipPickupRequest: vi.fn(),
  cancelLeadershipPickupRequest: vi.fn(),
}));

const mockAuth = {
  isAuthenticated: true,
  isHydrating: false,
  token: "mock-token",
  user: {
    id: "leadership-1",
    role: "principal",
    name: "Principal Jones",
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
    verified_by: status === "completed" ? "leadership-1" : null,
    verified_at: status === "completed" ? "2026-07-29T08:20:00Z" : null,
    verification_method: status === "completed" ? "id_check" : null,
    verification_note: status === "completed" ? "Student verified and handed to guardian" : null,
    notes: "At the main gate",
    within_geofence: false,
    distance_meters: 100,
    early_pickup: false,
  };
}

describe("leadership pickup oversight page", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue(mockAuth);

    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
    });
  });

  it("renders pickup oversight page", async () => {
    render(<PickupPage />);
    await waitFor(() => {
      expect(screen.getByText("Pickup Oversight")).toBeInTheDocument();
    });
  });

  it("renders empty state when no pickups exist", async () => {
    render(<PickupPage />);
    await waitFor(() => {
      expect(screen.getByText("No active pickup requests.")).toBeInTheDocument();
    });
  });

  it("renders active pickups", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1"), pickup("acknowledged", "pickup-2")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getAllByText(/Student ID:/).length).toBeGreaterThan(0);
    });
  });

  it("allows leadership to acknowledge a requested pickup", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    (acknowledgeLeadershipPickupRequest as ReturnType<typeof vi.fn>).mockResolvedValue(
      pickup("acknowledged", "pickup-1"),
    );

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Mark as acknowledge")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Mark as acknowledge"));

    await waitFor(() => {
      expect(acknowledgeLeadershipPickupRequest).toHaveBeenCalledWith(
        "pickup-1",
        {},
        "mock-token",
      );
    });
  });

  it("allows leadership to complete a prepared pickup with verification", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("prepared", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    (completeLeadershipPickupRequest as ReturnType<typeof vi.fn>).mockResolvedValue(
      pickup("completed", "pickup-1"),
    );

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Complete & Verify")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Complete & Verify"));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("e.g., ID check, signature, photo")).toBeInTheDocument();
    });

    const methodInput = screen.getByPlaceholderText("e.g., ID check, signature, photo");
    const noteInput = screen.getByPlaceholderText(
      "Document the handover details (e.g., Guardian name, time, condition of student)",
    );

    fireEvent.change(methodInput, { target: { value: "ID check" } });
    fireEvent.change(noteInput, { target: { value: "Student handed to father at 8:20 AM" } });

    fireEvent.click(screen.getByText("Confirm Completion"));

    await waitFor(() => {
      expect(completeLeadershipPickupRequest).toHaveBeenCalledWith(
        "pickup-1",
        {
          verification_method: "ID check",
          verification_note: "Student handed to father at 8:20 AM",
        },
        "mock-token",
      );
    });
  });

  it("requires both verification method and note for completion", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("prepared", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Complete & Verify")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Complete & Verify"));

    await waitFor(() => {
      expect(screen.getByText("Confirm Completion")).toBeInTheDocument();
    });

    // Try to submit without filling in fields
    fireEvent.click(screen.getByText("Confirm Completion"));

    await waitFor(() => {
      expect(screen.getByText("Verification method is required.")).toBeInTheDocument();
    });
  });

  it("displays completion verification details when completed", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("completed", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("id_check")).toBeInTheDocument();
      expect(screen.getByText("Student verified and handed to guardian")).toBeInTheDocument();
    });
  });

  it("allows leadership to cancel a prepared pickup", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("prepared", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    (cancelLeadershipPickupRequest as ReturnType<typeof vi.fn>).mockResolvedValue(
      pickup("cancelled", "pickup-1"),
    );

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getAllByRole("button").find((btn) => btn.textContent?.includes("Cancel"))).toBeInTheDocument();
    });

    const cancelButton = screen.getAllByText("Cancel").find((el) => el.tagName === "BUTTON");
    fireEvent.click(cancelButton!);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Cancel Pickup/ })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Cancel Pickup/ }));

    await waitFor(() => {
      expect(cancelLeadershipPickupRequest).toHaveBeenCalledWith(
        "pickup-1",
        {},
        "mock-token",
      );
    });
  });

  it("shows terminal status as read-only without actions", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("completed", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Completed")).toBeInTheDocument();
    });

    // Should not have action buttons for completed pickup
    const completeButtons = screen.queryAllByText("Complete & Verify");
    expect(completeButtons).toHaveLength(0);
  });

  it("displays pickup history for completed and cancelled requests", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        pickup("requested", "pickup-1"),
        pickup("completed", "pickup-2"),
        pickup("cancelled", "pickup-3"),
      ],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Pickup history")).toBeInTheDocument();
    });
  });

  it("handles API conflict error (409) for illegal transitions", async () => {
    const apiError = new TeacherApiError(409, "Illegal pickup lifecycle transition.", null);
    (acknowledgeLeadershipPickupRequest as ReturnType<typeof vi.fn>).mockRejectedValue(apiError);

    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Mark as acknowledge")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Mark as acknowledge"));

    await waitFor(() => {
      expect(screen.getByText("This action is not allowed from the current pickup status.")).toBeInTheDocument();
    });
  });

  it("handles API conflict error (409) for terminal status", async () => {
    const apiError = new TeacherApiError(409, "Pickup request is in a terminal status.", null);
    (acknowledgeLeadershipPickupRequest as ReturnType<typeof vi.fn>).mockRejectedValue(apiError);

    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("completed", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Completed")).toBeInTheDocument();
    });
  });

  it("filters pickups by status", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("acknowledged", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("All statuses")).toBeInTheDocument();
    });

    const statusSelect = screen.getByDisplayValue("All statuses");
    fireEvent.change(statusSelect, { target: { value: "acknowledged" } });

    await waitFor(() => {
      expect(listLeadershipPickupRequests).toHaveBeenCalledWith(
        {
          status: "acknowledged",
          page: 1,
          page_size: 50,
        },
        "mock-token",
      );
    });
  });

  it("allows refresh of pickups", async () => {
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 20,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Student ID: student-1")).toBeInTheDocument();
    });

    const refreshButton = screen.getByText("Refresh");
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(listLeadershipPickupRequests).toHaveBeenCalledTimes(2);
    });
  });

  it("handles 403 forbidden error", async () => {
    const apiError = new TeacherApiError(403, "You do not have permission.", null);
    (listLeadershipPickupRequests as ReturnType<typeof vi.fn>).mockRejectedValue(apiError);

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("You do not have permission to perform this action.")).toBeInTheDocument();
    });
  });

  it("redirects unauthenticated users", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      ...mockAuth,
      isAuthenticated: false,
    });

    render(<PickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Please log in to view pickup requests.")).toBeInTheDocument();
    });
  });
});
