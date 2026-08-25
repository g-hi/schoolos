import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadershipAttendancePage from "@/app/leadership/attendance/page";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockedUseAuth = vi.fn();

const getLeadershipAttendanceDailySummary = vi.fn();
const listLeadershipAttendanceRegisters = vi.fn();
const getLeadershipAttendanceRegister = vi.fn();
const finalizeLeadershipAttendanceRegister = vi.fn();
const correctLeadershipAttendanceRegister = vi.fn();

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => mockedUseAuth(),
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

  getLeadershipAttendanceDailySummary: (...args: unknown[]) =>
    getLeadershipAttendanceDailySummary(...args),

  listLeadershipAttendanceRegisters: (...args: unknown[]) =>
    listLeadershipAttendanceRegisters(...args),

  getLeadershipAttendanceRegister: (...args: unknown[]) =>
    getLeadershipAttendanceRegister(...args),

  finalizeLeadershipAttendanceRegister: (...args: unknown[]) =>
    finalizeLeadershipAttendanceRegister(...args),

  correctLeadershipAttendanceRegister: (...args: unknown[]) =>
    correctLeadershipAttendanceRegister(...args),
}));

const registerListItem = {
  register_id: "reg-1",
  class_id: "class-1",
  class_facing_session_key: "class-1-session",
  class_code: "G5A",
  grade_level: "Grade 5",
  section: "A",
  class_display_name: "Grade 5 A",
  subject_name: "Mathematics",
  teacher_name: "Teacher One",
  start_time: "08:00",
  end_time: "08:45",
  status: "submitted",
  roster_resolution_status: "resolved",
  expected: 2,
  marked: 2,
  unmarked: 0,
  present: 1,
  absent: 1,
  late: 0,
  excused: 0,
};

const submittedRegisterDetail = {
  register_id: "reg-1",
  school_date: "2026-09-15",
  class_id: "class-1",
  class_facing_session_key: "class-1-session",
  register_status: "submitted",
  roster_resolution_status: "resolved",
  expected_count: 2,
  marked_count: 2,
  unmarked_count: 0,
  records: [
    {
      student_id: "student-1",
      student_name: "Ada Student",
      student_identifier: "ST-001",
      status: "present",
      minutes_late: null,
      marked_by: "teacher-user-1",
      marked_at: "2026-09-15T08:30:00Z",
    },
    {
      student_id: "student-2",
      student_name: "Ben Student",
      student_identifier: "ST-002",
      status: "absent",
      minutes_late: null,
      marked_by: "teacher-user-1",
      marked_at: "2026-09-15T08:30:00Z",
    },
  ],
};

describe("leadership attendance page", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockedUseAuth.mockReturnValue({
      isAuthenticated: true,
      token: "principal-token",
      isHydrating: false,
      user: {
        id: "principal-1",
        role: "principal",
        name: "Principal User",
      },
    });

    getLeadershipAttendanceDailySummary.mockResolvedValue({
      school_date: "2026-09-15",
      eligible_sessions: 8,
      not_started: 1,
      open: 2,
      submitted: 3,
      finalized: 2,
      parallel_unresolved: 0,
      expected_students: 160,
      present: 145,
      absent: 8,
      late: 4,
      excused: 3,
      unmarked: 0,
    });

    listLeadershipAttendanceRegisters.mockResolvedValue([
      registerListItem,
    ]);

    getLeadershipAttendanceRegister.mockResolvedValue(
      submittedRegisterDetail,
    );

    finalizeLeadershipAttendanceRegister.mockResolvedValue({
      register_id: "reg-1",
      register_status: "finalized",
    });

    correctLeadershipAttendanceRegister.mockResolvedValue({
      student_id: "student-2",
      attendance_status: "present",
    });
  });

  it("renders the leadership attendance summary and register metadata", async () => {
    render(<LeadershipAttendancePage />);

    expect(
      await screen.findByRole("heading", {
        name: "Attendance Command Centre",
      }),
    ).toBeInTheDocument();

    expect(screen.getByText("Eligible sessions")).toBeInTheDocument();
    expect(screen.getByText("Expected students")).toBeInTheDocument();

    expect(await screen.findByText("Grade 5 A")).toBeInTheDocument();
    expect(screen.getByText("Mathematics")).toBeInTheDocument();
    expect(screen.getByText("Teacher One")).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();
  });

  it("opens a register and renders human-readable student details", async () => {
    render(<LeadershipAttendancePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: /review/i }),
    );

    expect(await screen.findByText("Ada Student")).toBeInTheDocument();
    expect(screen.getByText("ST-001")).toBeInTheDocument();
    expect(screen.getByText("Ben Student")).toBeInTheDocument();
    expect(screen.getByText("ST-002")).toBeInTheDocument();

    expect(getLeadershipAttendanceRegister).toHaveBeenCalledWith(
      "reg-1",
      "principal-token",
    );
  });

  it("finalizes a submitted register", async () => {
    getLeadershipAttendanceRegister
      .mockResolvedValueOnce(submittedRegisterDetail)
      .mockResolvedValueOnce({
        ...submittedRegisterDetail,
        register_status: "finalized",
      });

    render(<LeadershipAttendancePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: /review/i }),
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: /finalize register/i,
      }),
    );

    await waitFor(() => {
      expect(
        finalizeLeadershipAttendanceRegister,
      ).toHaveBeenCalledWith(
        "reg-1",
        "principal-token",
      );
    });
  });

  it("requires a reason before applying an attendance correction", async () => {
    render(<LeadershipAttendancePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: /review/i }),
    );

    const correctButtons = await screen.findAllByRole("button", {
      name: /correct/i,
    });

    fireEvent.click(correctButtons[1]);

    const applyButton = screen.getByRole("button", {
      name: /apply correction/i,
    });

    expect(applyButton).toBeDisabled();

    fireEvent.change(
      screen.getByLabelText(
        /correction reason for ben student/i,
      ),
      {
        target: {
          value: "Verified against signed classroom register",
        },
      },
    );

    expect(applyButton).not.toBeDisabled();

    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(
        correctLeadershipAttendanceRegister,
      ).toHaveBeenCalledWith(
        "reg-1",
        {
          student_id: "student-2",
          new_status: "absent",
          correction_reason:
            "Verified against signed classroom register",
        },
        "principal-token",
      );
    });
  });

  it("blocks school_admin from the principal-only workspace", async () => {
    mockedUseAuth.mockReturnValue({
      isAuthenticated: true,
      token: "school-admin-token",
      isHydrating: false,
      user: {
        id: "admin-1",
        role: "school_admin",
        name: "School Admin",
      },
    });

    render(<LeadershipAttendancePage />);

    expect(
      screen.getByText(
        "Principal access is required for this workspace.",
      ),
    ).toBeInTheDocument();

    expect(
      getLeadershipAttendanceDailySummary,
    ).not.toHaveBeenCalled();

    expect(
      listLeadershipAttendanceRegisters,
    ).not.toHaveBeenCalled();
  });
});