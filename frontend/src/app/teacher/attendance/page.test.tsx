import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TeacherAttendancePage from "@/app/teacher/attendance/page";

import { TeacherApiError } from "@/lib/teacher-api";

const getTeacherAttendanceToday = vi.fn();
const getTeacherAttendanceSessions = vi.fn();
const ensureTeacherAttendanceRegister = vi.fn();
const getTeacherAttendanceRegister = vi.fn();
const bulkMarkTeacherAttendance = vi.fn();
const markAllPresentTeacherAttendance = vi.fn();
const submitTeacherAttendanceRegister = vi.fn();

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    token: "teacher-token",
    isHydrating: false,
    user: { id: "teacher-1", role: "teacher", name: "Teacher User" },
  }),
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
  getTeacherAttendanceToday: (...args: unknown[]) => getTeacherAttendanceToday(...args),
  getTeacherAttendanceSessions: (...args: unknown[]) => getTeacherAttendanceSessions(...args),
  ensureTeacherAttendanceRegister: (...args: unknown[]) => ensureTeacherAttendanceRegister(...args),
  getTeacherAttendanceRegister: (...args: unknown[]) => getTeacherAttendanceRegister(...args),
  bulkMarkTeacherAttendance: (...args: unknown[]) => bulkMarkTeacherAttendance(...args),
  markAllPresentTeacherAttendance: (...args: unknown[]) => markAllPresentTeacherAttendance(...args),
  submitTeacherAttendanceRegister: (...args: unknown[]) => submitTeacherAttendanceRegister(...args),
}));

describe("teacher attendance page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-1",
          class_facing_session_key: "class-1-session",
          school_date: "2026-09-15",
          class_id: "class-1",
          subject_id: "sub-1",
          class_code: "G5A",
          grade_level: "Grade 5",
          section: "A",
          class_display_name: "Grade 5 A",
          subject_name: "Mathematics",
          teacher_id: "teacher-1",
          start_time: "08:00",
          end_time: "08:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: null,
          attendance_status: "not_started",
          expected_count: 0,
          marked_count: 0,
          unmarked_count: 0,
        },
      ],
    });
  });

  it("renders today's classes", async () => {
    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Today's Classes")).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Grade 5 A" })).toBeInTheDocument();
  });

  it("renders attendance statuses from the API", async () => {
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-2",
          class_facing_session_key: "class-2-session",
          school_date: "2026-09-15",
          class_id: "class-2",
          subject_id: "sub-2",
          class_code: "G6B",
          grade_level: "Grade 6",
          section: "B",
          class_display_name: "Grade 6 B",
          subject_name: "Science",
          teacher_id: "teacher-1",
          start_time: "10:00",
          end_time: "10:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: "reg-2",
          attendance_status: "submitted",
          expected_count: 3,
          marked_count: 3,
          unmarked_count: 0,
        },
      ],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Submitted")).toBeInTheDocument();
    });
  });

  it("deduplicates parallel/class-facing sessions based on API payload", async () => {
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-a",
          class_facing_session_key: "parallel-1",
          school_date: "2026-09-15",
          class_id: "class-1",
          subject_id: "sub-1",
          class_code: "G5A",
          grade_level: "Grade 5",
          section: "A",
          class_display_name: "Grade 5 A",
          subject_name: "Mathematics",
          teacher_id: "teacher-1",
          start_time: "08:00",
          end_time: "08:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: null,
          attendance_status: "not_started",
          expected_count: 0,
          marked_count: 0,
          unmarked_count: 0,
        },
        {
          daily_session_id: "session-b",
          class_facing_session_key: "parallel-1",
          school_date: "2026-09-15",
          class_id: "class-1",
          subject_id: "sub-1",
          class_code: "G5A",
          grade_level: "Grade 5",
          section: "A",
          class_display_name: "Grade 5 A",
          subject_name: "Mathematics",
          teacher_id: "teacher-1",
          start_time: "08:00",
          end_time: "09:30",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: null,
          attendance_status: "not_started",
          expected_count: 0,
          marked_count: 0,
          unmarked_count: 0,
        },
      ],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getAllByRole("heading", { name: "Grade 5 A" })).toHaveLength(1);
    });
  });

  it("calls ensure register only when the user clicks Take Attendance", async () => {
    ensureTeacherAttendanceRegister.mockResolvedValue({ register_id: "reg-ensure", register_status: "open" });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Today's Classes")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /take attendance/i }));

    await waitFor(() => {
      expect(ensureTeacherAttendanceRegister).toHaveBeenCalledTimes(1);
    });
  });

  it("never creates a register while viewing the page", async () => {
    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Today's Classes")).toBeInTheDocument();
    });
    expect(ensureTeacherAttendanceRegister).not.toHaveBeenCalled();
  });

  it("renders a roster and controls local edits until save", async () => {
    bulkMarkTeacherAttendance.mockResolvedValue({ register_id: "reg-3", register_status: "open" });
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-3",
          class_facing_session_key: "class-3-session",
          school_date: "2026-09-15",
          class_id: "class-3",
          subject_id: "sub-3",
          class_code: "G7C",
          grade_level: "Grade 7",
          section: "C",
          class_display_name: "Grade 7 C",
          subject_name: "English",
          teacher_id: "teacher-1",
          start_time: "09:00",
          end_time: "09:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: "reg-3",
          attendance_status: "open",
          expected_count: 1,
          marked_count: 1,
          unmarked_count: 0,
        },
      ],
    });
    getTeacherAttendanceRegister.mockResolvedValue({
      register_id: "reg-3",
      class_facing_session_key: "class-3-session",
      school_date: "2026-09-15",
      register_status: "open",
      roster_resolution_status: "resolved",
      expected_count: 1,
      records: [{ student_id: "student-1", student_name: "Ada Student", student_identifier: "ST-001", attendance_status: "unmarked", minutes_late: null, marked_at: null }],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /open register/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /open register/i }));
    await waitFor(() => {
      expect(screen.getByText("Ada Student")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText(/present/i));
    fireEvent.click(screen.getByRole("button", { name: /save attendance/i }));

    await waitFor(() => {
      expect(bulkMarkTeacherAttendance).toHaveBeenCalledTimes(1);
    });
  });

  it("exposes a late minutes input and delegates bulk save", async () => {
    bulkMarkTeacherAttendance.mockResolvedValue({ register_status: "open" });
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-4",
          class_facing_session_key: "class-4-session",
          school_date: "2026-09-15",
          class_id: "class-4",
          subject_id: "sub-4",
          class_code: "G8D",
          grade_level: "Grade 8",
          section: "D",
          class_display_name: "Grade 8 D",
          subject_name: "History",
          teacher_id: "teacher-1",
          start_time: "11:00",
          end_time: "11:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: "reg-4",
          attendance_status: "open",
          expected_count: 1,
          marked_count: 1,
          unmarked_count: 0,
        },
      ],
    });
    getTeacherAttendanceRegister.mockResolvedValue({
      register_id: "reg-4",
      class_facing_session_key: "class-4-session",
      school_date: "2026-09-15",
      register_status: "open",
      roster_resolution_status: "resolved",
      expected_count: 1,
      records: [{ student_id: "student-1", student_name: "Late Student", student_identifier: "ST-002", attendance_status: "late", minutes_late: 12, marked_at: null }],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /open register/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /open register/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/minutes late/i)).toBeInTheDocument();
    });
  });

  it("delegates mark all present and submit", async () => {
    markAllPresentTeacherAttendance.mockResolvedValue({ register_id: "reg-d", register_status: "open" });
    submitTeacherAttendanceRegister.mockResolvedValue({ register_id: "reg-d", register_status: "submitted" });
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-open",
          class_facing_session_key: "class-open-session",
          school_date: "2026-09-15",
          class_id: "class-open",
          subject_id: "sub-open",
          class_code: "G9E",
          grade_level: "Grade 9",
          section: "E",
          class_display_name: "Grade 9 E",
          subject_name: "Biology",
          teacher_id: "teacher-1",
          start_time: "14:00",
          end_time: "14:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: "reg-d",
          attendance_status: "open",
          expected_count: 1,
          marked_count: 0,
          unmarked_count: 1,
        },
      ],
    });
    getTeacherAttendanceRegister.mockResolvedValue({
      register_id: "reg-d",
      class_facing_session_key: "class-open-session",
      school_date: "2026-09-15",
      register_status: "open",
      roster_resolution_status: "resolved",
      expected_count: 1,
      marked_count: 0,
      unmarked_count: 1,
      records: [{ student_id: "student-d", student_name: "Delta Student", student_identifier: "ST-999", attendance_status: "unmarked", minutes_late: null, marked_at: null }],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Today's Classes")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /open register/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /mark all present/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /mark all present/i }));
    expect(markAllPresentTeacherAttendance).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /submit attendance/i }));
    await waitFor(() => {
      expect(submitTeacherAttendanceRegister).toHaveBeenCalledTimes(1);
    });
  });

  it("shows a friendly incomplete submission error", async () => {
    submitTeacherAttendanceRegister.mockRejectedValue(new TeacherApiError(409, "Complete attendance for all students before submitting.", { detail: { code: "attendance_incomplete" } }));
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-open-2",
          class_facing_session_key: "class-open-session-2",
          school_date: "2026-09-15",
          class_id: "class-open-2",
          subject_id: "sub-open-2",
          class_code: "G9F",
          grade_level: "Grade 9",
          section: "F",
          class_display_name: "Grade 9 F",
          subject_name: "Chemistry",
          teacher_id: "teacher-1",
          start_time: "14:00",
          end_time: "14:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: "reg-h",
          attendance_status: "open",
          expected_count: 1,
          marked_count: 0,
          unmarked_count: 1,
        },
      ],
    });
    getTeacherAttendanceRegister.mockResolvedValue({
      register_id: "reg-h",
      class_facing_session_key: "class-open-session-2",
      school_date: "2026-09-15",
      register_status: "open",
      roster_resolution_status: "resolved",
      expected_count: 1,
      marked_count: 0,
      unmarked_count: 1,
      records: [{ student_id: "student-h", student_name: "Helen Student", student_identifier: "ST-888", attendance_status: "unmarked", minutes_late: null, marked_at: null }],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Today's Classes")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /open register/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /submit attendance/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /submit attendance/i }));
    await waitFor(() => {
      expect(screen.getByText(/complete attendance/i)).toBeInTheDocument();
    });
  });

  it("makes submitted and finalized registers read-only", async () => {
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "session-readonly",
          class_facing_session_key: "class-readonly-session",
          school_date: "2026-09-15",
          class_id: "class-readonly",
          subject_id: "sub-readonly",
          class_code: "G10A",
          grade_level: "Grade 10",
          section: "A",
          class_display_name: "Grade 10 A",
          subject_name: "Physics",
          teacher_id: "teacher-1",
          start_time: "12:00",
          end_time: "12:45",
          session_status: "scheduled",
          attendance_eligible: true,
          attendance_register_id: "reg-readonly",
          attendance_status: "submitted",
          expected_count: 1,
          marked_count: 1,
          unmarked_count: 0,
        },
      ],
    });

    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getByText("Submitted")).toBeInTheDocument();
    });
  });

  it("renders unavailable and parallel-unresolved states", async () => {
    getTeacherAttendanceToday.mockResolvedValue({
      school_date: "2026-09-15",
      items: [
        {
          daily_session_id: "unavailable-session",
          class_facing_session_key: "unavailable-1",
          school_date: "2026-09-15",
          class_id: "class-unavailable",
          subject_id: "sub-unavailable",
          class_code: "G10B",
          grade_level: "Grade 10",
          section: "B",
          class_display_name: "Grade 10 B",
          subject_name: "Art",
          teacher_id: "teacher-1",
          start_time: "13:00",
          end_time: "13:45",
          session_status: "scheduled",
          attendance_eligible: false,
          attendance_register_id: null,
          attendance_status: "unavailable",
          expected_count: 0,
          marked_count: 0,
          unmarked_count: 0,
        },
      ],
    });
    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getAllByText(/unavailable/i).length).toBeGreaterThan(0);
    });
  });

  it("renders API failure details", async () => {
    getTeacherAttendanceToday.mockRejectedValue(new TeacherApiError(500, "Unable to load attendance.", null));
    render(<TeacherAttendancePage />);
    await waitFor(() => {
      expect(screen.getAllByText(/unable to load attendance/i).length).toBeGreaterThan(0);
    });
  });
});
