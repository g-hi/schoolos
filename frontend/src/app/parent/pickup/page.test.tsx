import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ParentPickupPage from "@/app/parent/pickup/page";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import {
  ParentApiError,
  cancelParentPickupRequest,
  createParentPickupRequest,
  getParentStudents,
  listParentPickupRequests,
} from "@/lib/parent-api";

vi.mock("@/components/parent/parent-auth-provider", () => ({
  useParentAuth: vi.fn(),
}));

vi.mock("@/components/parent/parent-login-panel", () => ({
  default: () => <div>Parent login panel</div>,
}));

vi.mock("@/lib/parent-api", () => ({
  ParentApiError: class ParentApiError extends Error {
    status: number;
    body: unknown;

    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
  getParentStudents: vi.fn(),
  listParentPickupRequests: vi.fn(),
  createParentPickupRequest: vi.fn(),
  getParentPickupRequest: vi.fn(),
  cancelParentPickupRequest: vi.fn(),
}));

const defaultStudent = {
  student_id: "student-1",
  name: "Ahmed Hassan",
  student_code: "S001",
  grade: "5",
  section: "A",
  class_name: "Grade 5-A",
  homeroom_teacher: "Ms. Ali",
  is_primary_guardian: true,
  can_pickup: true,
  can_view_academics: true,
  can_view_behaviour: true,
};

function pickup(status: string, id: string) {
  return {
    pickup_id: id,
    student_id: "student-1",
    parent_id: "parent-1",
    class_id: "class-1",
    teacher_id: "teacher-1",
    status,
    channel: "app",
    requested_at: "2026-07-29T08:00:00Z",
    acknowledged_at: null,
    called_at: null,
    prepared_at: null,
    completed_at: null,
    cancelled_at: null,
    verified_by: null,
    verified_at: null,
    verification_method: null,
    verification_note: null,
    notes: "At the main gate",
    within_geofence: false,
    distance_meters: 0,
    early_pickup: false,
  };
}

describe("parent pickup page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    (useParentAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      token: "parent-token",
      login: vi.fn(),
      logout: vi.fn(),
      status: "authenticated",
    });

    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      students: [defaultStudent],
    });

    (listParentPickupRequests as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
    });

    (createParentPickupRequest as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(pickup("requested", "pickup-1"));
    (cancelParentPickupRequest as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(pickup("cancelled", "pickup-1"));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state", async () => {
    let resolveStudents: (value: unknown) => void = () => {};
    const pendingStudents = new Promise((resolve) => {
      resolveStudents = resolve;
    });
    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockReturnValue(pendingStudents);

    render(<ParentPickupPage />);
    expect(screen.getByText("Loading pickup")).toBeInTheDocument();

    resolveStudents({ students: [defaultStudent] });

    await waitFor(() => {
      expect(screen.getByText("Parent Pickup")).toBeInTheDocument();
    });
  });

  it("renders empty state when there are no pickup requests", async () => {
    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("No active pickup requests")).toBeInTheDocument();
    });
    expect(screen.getByText("No pickup history")).toBeInTheDocument();
  });

  it("renders eligible student selector and excludes non-eligible students", async () => {
    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      students: [
        defaultStudent,
        { ...defaultStudent, student_id: "student-2", name: "Fatimah", class_name: "Grade 5-B", can_pickup: false },
      ],
    });

    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Eligible student")).toBeInTheDocument();
    });

    expect(screen.getByRole("option", { name: /Ahmed Hassan \(Grade 5-A\)/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Fatimah \(Grade 5-B\)/i })).not.toBeInTheDocument();
  });

  it("creates a pickup request", async () => {
    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Pickup note")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Pickup note"), { target: { value: "Please prepare Ahmed at gate 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit pickup request" }));

    await waitFor(() => {
      expect(createParentPickupRequest).toHaveBeenCalledWith(
        {
          student_id: "student-1",
          command_text: "Please prepare Ahmed at gate 1",
        },
        "parent-token",
      );
    });

    expect(await screen.findByText(/Pickup request submitted/i)).toBeInTheDocument();
  });

  it("renders active requests and lifecycle status labels", async () => {
    (listParentPickupRequests as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        pickup("requested", "p1"),
        pickup("acknowledged", "p2"),
        pickup("called", "p3"),
        pickup("prepared", "p4"),
        pickup("completed", "p5"),
        pickup("cancelled", "p6"),
        pickup("released", "p7"),
        pickup("rejected_outside_geofence", "p8"),
      ],
      page: 1,
      page_size: 50,
    });

    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Active pickup requests")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Requested").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Acknowledged").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Called").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Prepared").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Cancelled").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Released").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Rejected Outside Geofence").length).toBeGreaterThan(0);
  });

  it("cancels an active pickup request", async () => {
    (listParentPickupRequests as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("requested", "pickup-1")],
      page: 1,
      page_size: 50,
    });

    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Cancel request" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));

    await waitFor(() => {
      expect(cancelParentPickupRequest).toHaveBeenCalledWith("pickup-1", {}, "parent-token");
    });
  });

  it("does not show cancel action for terminal statuses", async () => {
    (listParentPickupRequests as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [pickup("completed", "pickup-1")],
      page: 1,
      page_size: 50,
    });

    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    });

    expect(screen.queryByRole("button", { name: "Cancel request" })).not.toBeInTheDocument();
  });

  it("shows controlled API error state", async () => {
    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ParentApiError(401, "Invalid or expired token.", { detail: "Invalid or expired token." }),
    );

    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("Unable to load pickup requests")).toBeInTheDocument();
    });

    expect(screen.getByText(/session has expired/i)).toBeInTheDocument();
  });

  it("shows controlled no-eligible-student state", async () => {
    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      students: [{ ...defaultStudent, can_pickup: false }],
    });

    render(<ParentPickupPage />);

    await waitFor(() => {
      expect(screen.getByText("No eligible linked students")).toBeInTheDocument();
    });
  });
});
