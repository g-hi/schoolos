import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MyClassesPage from "@/app/teacher/my-classes/page";
import { useAuth } from "@/components/auth/auth-provider";
import { TeacherApiError, getTeacherMyClasses } from "@/lib/teacher-api";

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
  getTeacherMyClasses: vi.fn(),
}));

const mockAuth = {
  isAuthenticated: true,
  isHydrating: false,
  token: "teacher-token",
  user: {
    id: "teacher-user",
    role: "teacher",
    name: "Teacher User",
  },
};

const canonicalResponse = {
  effective_date: "2026-07-31",
  teacher: { id: "teacher-profile", display_name: "Teacher User" },
  summary: {
    total_classes: 1,
    homeroom_classes: 1,
    subject_classes: 1,
    canonical_classes: 1,
    legacy_classes: 0,
  },
  classes: [
    {
      class_id: "class-1",
      code: "5A",
      grade_level: "Grade 5",
      section: "A",
      academic_year_id: "year-1",
      academic_year: "2026-2027",
      campus_id: "campus-1",
      campus: "Main",
      is_active: true,
      student_count: 25,
      assignment_source: "canonical",
      assignments: [
        {
          assignment_type: "homeroom",
          subject_id: null,
          subject_code: null,
          subject_name: null,
          start_date: "2026-01-01",
          end_date: null,
        },
        {
          assignment_type: "subject_teacher",
          subject_id: "subject-1",
          subject_code: "MATH",
          subject_name: "Mathematics",
          start_date: "2026-01-01",
          end_date: null,
        },
      ],
      schedule: {
        weekly_periods: 6,
        next_period: null,
      },
    },
  ],
};

describe("teacher my classes page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue(mockAuth);
    (getTeacherMyClasses as ReturnType<typeof vi.fn>).mockResolvedValue(canonicalResponse);
  });

  it("shows loading then populated canonical class", async () => {
    render(<MyClassesPage />);

    expect(screen.getByLabelText("loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("My Classes")).toBeInTheDocument();
      expect(screen.getByText("5A")).toBeInTheDocument();
      expect(screen.getAllByText("Canonical").length).toBeGreaterThan(0);
      expect(screen.getByText("Mathematics")).toBeInTheDocument();
      expect(screen.getByText("25")).toBeInTheDocument();
      expect(screen.getByText("6")).toBeInTheDocument();
    });
  });

  it("renders multiple subject assignments for one class", async () => {
    const multiSubject = {
      ...canonicalResponse,
      classes: [
        {
          ...canonicalResponse.classes[0],
          assignments: [
            {
              assignment_type: "subject_teacher",
              subject_id: "subject-1",
              subject_code: "MATH",
              subject_name: "Mathematics",
              start_date: "2026-01-01",
              end_date: null,
            },
            {
              assignment_type: "subject_teacher",
              subject_id: "subject-2",
              subject_code: "SCI",
              subject_name: "Science",
              start_date: "2026-01-01",
              end_date: null,
            },
          ],
        },
      ],
    };
    (getTeacherMyClasses as ReturnType<typeof vi.fn>).mockResolvedValue(multiSubject);

    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("Mathematics")).toBeInTheDocument();
      expect(screen.getByText("Science")).toBeInTheDocument();
    });
  });

  it("shows legacy compatibility label", async () => {
    (getTeacherMyClasses as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...canonicalResponse,
      summary: {
        ...canonicalResponse.summary,
        canonical_classes: 0,
        legacy_classes: 1,
      },
      classes: [
        {
          ...canonicalResponse.classes[0],
          assignment_source: "legacy",
          assignments: [
            {
              assignment_type: "homeroom",
              subject_id: null,
              subject_code: null,
              subject_name: null,
              start_date: null,
              end_date: null,
            },
          ],
        },
      ],
    });

    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("Legacy compatibility")).toBeInTheDocument();
      expect(
        screen.getByText("Legacy compatibility data is temporary until canonical assignments are fully available."),
      ).toBeInTheDocument();
    });
  });

  it("shows empty state", async () => {
    (getTeacherMyClasses as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...canonicalResponse,
      summary: {
        total_classes: 0,
        homeroom_classes: 0,
        subject_classes: 0,
        canonical_classes: 0,
        legacy_classes: 0,
      },
      classes: [],
    });

    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("No Assigned Classes")).toBeInTheDocument();
    });
  });

  it("shows API error and supports retry", async () => {
    (getTeacherMyClasses as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new TeacherApiError(500, "Server error", null))
      .mockResolvedValueOnce(canonicalResponse);

    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("API Failure")).toBeInTheDocument();
      expect(screen.getByText("Server error")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Retry"));

    await waitFor(() => {
      expect(screen.getByText("5A")).toBeInTheDocument();
      expect(getTeacherMyClasses).toHaveBeenCalledTimes(2);
    });
  });

  it("does not render mock class fallback when API fails", async () => {
    (getTeacherMyClasses as ReturnType<typeof vi.fn>).mockRejectedValue(new TeacherApiError(500, "Server error", null));

    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("API Failure")).toBeInTheDocument();
      expect(screen.queryByText("5A")).toBeNull();
    });
  });

  it("shows authenticated access error for unauthenticated users", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      ...mockAuth,
      isAuthenticated: false,
      token: null,
      user: null,
    });

    render(<MyClassesPage />);

    expect(screen.getByText("Authenticated Access Error")).toBeInTheDocument();
  });

  it("shows teacher profile missing state", async () => {
    (getTeacherMyClasses as ReturnType<typeof vi.fn>).mockRejectedValue(
      new TeacherApiError(403, "Teacher profile not found.", null),
    );

    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("Teacher Profile Missing")).toBeInTheDocument();
    });
  });

  it("does not display IDs as primary content", async () => {
    render(<MyClassesPage />);

    await waitFor(() => {
      expect(screen.getByText("5A")).toBeInTheDocument();
    });

    expect(screen.queryByText("teacher-profile")).toBeNull();
    expect(screen.queryByText("class-1")).toBeNull();
  });
});
