import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import PeoplePage from "@/app/people/page";
import { useAuth } from "@/components/auth/auth-provider";
import {
  getPeopleSummary,
  issueInvitation,
  listInvitations,
  listPeople,
  provisionParent,
  provisionStudent,
  provisionTeacher,
  revokeInvitation,
  updateUserStatus,
} from "@/lib/people-api";
import {
  createFamilyRelationship,
  getFamilySummary,
  listFamilyRelationships,
  updateFamilyRelationship,
} from "@/lib/families-api";
import { listClasses } from "@/lib/academic-structure-api";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/people",
}));

vi.mock("@/components/auth/auth-provider", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/people-api", () => ({
  PeopleApiError: class PeopleApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
  listPeople: vi.fn(),
  getPeopleSummary: vi.fn(),
  provisionTeacher: vi.fn(),
  provisionParent: vi.fn(),
  provisionStudent: vi.fn(),
  updateUserStatus: vi.fn(),
  issueInvitation: vi.fn(),
  listInvitations: vi.fn(),
  revokeInvitation: vi.fn(),
}));
vi.mock("@/lib/families-api", () => ({
  FamiliesApiError: class FamiliesApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
  listFamilyRelationships: vi.fn(),
  getFamilySummary: vi.fn(),
  createFamilyRelationship: vi.fn(),
  updateFamilyRelationship: vi.fn(),
}));
vi.mock("@/lib/academic-structure-api", () => ({
  listClasses: vi.fn(),
}));

const authMock = {
  isHydrating: false,
  isAuthenticated: true,
  user: { id: "u-1", role: "principal", is_active: true },
};

function seedHappyMocks() {
  (getPeopleSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    total_active_users: 10,
    active_teachers: 3,
    active_parents: 4,
    active_students: 20,
    teachers_without_user_accounts: 1,
    parents_without_user_accounts: 0,
    users_without_matching_role_profiles: 1,
    inactive_users_with_active_profiles: 1,
    pending_invitations: 2,
    expired_invitations: 1,
    accepted_invitations: 7,
    revoked_invitations: 1,
  });

  (getFamilySummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    total_active_relationships: 8,
    students_with_no_active_parent_guardian_relationship: 1,
    students_with_multiple_active_relationships: 2,
    primary_relationships: 6,
    inactive_historical_relationships: 1,
    cross_tenant_inconsistencies: 0,
  });

  (listPeople as ReturnType<typeof vi.fn>).mockImplementation((filters?: { role?: string }) => {
    if (filters?.role === "student") {
      return Promise.resolve({
        total: 1,
        limit: 200,
        offset: 0,
        items: [
          {
            person_id: "student-1",
            user_id: null,
            display_name: "Student One",
            email: null,
            role: "student",
            profile_type: "student",
            is_active: true,
            invitation_status: null,
            profile_consistency_status: "ok",
            created_at: "2026-08-01T00:00:00Z",
            has_account: false,
          },
        ],
      });
    }
    if (filters?.role === "parent") {
      return Promise.resolve({
        total: 1,
        limit: 200,
        offset: 0,
        items: [
          {
            person_id: "person-parent-1",
            user_id: "parent-1",
            display_name: "Parent One",
            email: "parent@example.test",
            role: "parent",
            profile_type: "parent",
            is_active: true,
            invitation_status: "pending",
            profile_consistency_status: "ok",
            created_at: "2026-08-01T00:00:00Z",
            has_account: true,
          },
        ],
      });
    }

    return Promise.resolve({
      total: 1,
      limit: 20,
      offset: 0,
      items: [
        {
          person_id: "person-teacher-1",
          user_id: "teacher-1",
          display_name: "Teacher One",
          email: "teacher@example.test",
          role: "teacher",
          profile_type: "teacher",
          is_active: true,
          invitation_status: "pending",
          profile_consistency_status: "ok",
          created_at: "2026-08-01T00:00:00Z",
          has_account: true,
        },
      ],
    });
  });

  (listInvitations as ReturnType<typeof vi.fn>).mockResolvedValue({
    total: 1,
    limit: 20,
    offset: 0,
    items: [
      {
        id: "inv-1",
        user_id: "teacher-1",
        invited_email: "teacher@example.test",
        role: "teacher",
        status: "pending",
        created_at: "2026-08-01T00:00:00Z",
        expires_at: "2026-08-08T00:00:00Z",
        accepted_at: null,
        revoked_at: null,
        is_expired: false,
      },
    ],
  });

  (listFamilyRelationships as ReturnType<typeof vi.fn>).mockResolvedValue([
    {
      relationship_id: "student-1:parent-1",
      parent_id: "parent-1",
      parent_name: "Parent One",
      student_id: "student-1",
      student_name: "Student One",
      relationship_type: "guardian",
      is_primary: true,
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    },
  ]);

  (listClasses as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: "class-1", code: "5A", section: "A" },
  ]);

  (provisionTeacher as ReturnType<typeof vi.fn>).mockResolvedValue({
    teacher_id: "teacher-profile-1",
    user_id: "teacher-1",
    email: "teacher@example.test",
    invitation_id: "inv-1",
    activation_token: "one-time-teacher-token",
    activation_token_one_time: true,
  });

  (provisionParent as ReturnType<typeof vi.fn>).mockResolvedValue({
    parent_user_id: "parent-1",
    email: "parent@example.test",
    invitation_id: "inv-2",
    activation_token: "one-time-parent-token",
    activation_token_one_time: true,
  });

  (provisionStudent as ReturnType<typeof vi.fn>).mockResolvedValue({
    student_id: "student-2",
    class_id: "class-1",
    enrollment_id: null,
  });

  (issueInvitation as ReturnType<typeof vi.fn>).mockResolvedValue({
    invitation_id: "inv-3",
    user_id: "teacher-1",
    role: "teacher",
    expires_at: "2026-08-08T00:00:00Z",
    activation_token: "new-one-time-token",
    activation_token_one_time: true,
  });

  (updateUserStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ user_id: "teacher-1", is_active: false });
  (revokeInvitation as ReturnType<typeof vi.fn>).mockResolvedValue({ invitation_id: "inv-1", status: "revoked" });
  (createFamilyRelationship as ReturnType<typeof vi.fn>).mockResolvedValue({});
  (updateFamilyRelationship as ReturnType<typeof vi.fn>).mockResolvedValue({});
}

describe("people workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue(authMock);
    seedHappyMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "prompt").mockReturnValue("policy reason");
  });

  it("allows principal access", async () => {
    render(<PeoplePage />);
    expect(await screen.findByText("People & Families")).toBeInTheDocument();
  });

  it("allows school_admin access", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      ...authMock,
      user: { id: "u-2", role: "school_admin", is_active: true },
    });
    render(<PeoplePage />);
    expect(await screen.findByText("People & Families")).toBeInTheDocument();
  });

  it("denies teacher and parent access", async () => {
    const denialText = "Only school leadership can access the People & Families workspace.";

    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      ...authMock,
      user: { id: "u-3", role: "teacher", is_active: true },
    });
    const teacherView = render(<PeoplePage />);
    expect(await screen.findByText(denialText)).toBeInTheDocument();
    teacherView.unmount();

    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      ...authMock,
      user: { id: "u-4", role: "parent", is_active: true },
    });
    render(<PeoplePage />);
    expect(await screen.findByText(denialText)).toBeInTheDocument();
  });

  it("shows loading state then overview counts", async () => {
    render(<PeoplePage />);
    expect(screen.getByText(/loading people/i)).toBeInTheDocument();
    expect(await screen.findByText("Total active users")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("shows API error and supports refresh retry", async () => {
    (getPeopleSummary as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValue({
        total_active_users: 10,
        active_teachers: 3,
        active_parents: 4,
        active_students: 20,
        teachers_without_user_accounts: 1,
        parents_without_user_accounts: 0,
        users_without_matching_role_profiles: 1,
        inactive_users_with_active_profiles: 1,
        pending_invitations: 2,
        expired_invitations: 1,
        accepted_invitations: 7,
        revoked_invitations: 1,
      });

    render(<PeoplePage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("temporary");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(getPeopleSummary).toHaveBeenCalledTimes(2);
    });
  });

  it("supports directory filters", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");
    fireEvent.click(screen.getByRole("button", { name: "People" }));

    fireEvent.change(screen.getByLabelText("Role filter"), { target: { value: "teacher" } });
    await waitFor(() => {
      expect(listPeople).toHaveBeenCalledWith(expect.objectContaining({ role: "teacher" }));
    });
  });

  it("submits teacher, parent and student provisioning", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");

    fireEvent.click(screen.getByRole("button", { name: "Add Teacher" }));
    fireEvent.change(screen.getByLabelText("Teacher name"), { target: { value: "Teacher Alpha" } });
    fireEvent.change(screen.getByLabelText("Teacher email"), { target: { value: "ta@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create teacher" }));
    await waitFor(() => {
      expect(provisionTeacher).toHaveBeenCalled();
      expect(screen.getByText(/one-time activation material/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Parent" }));
    fireEvent.change(screen.getByLabelText("Parent name"), { target: { value: "Parent Alpha" } });
    fireEvent.change(screen.getByLabelText("Parent email"), { target: { value: "pa@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create parent" }));
    await waitFor(() => {
      expect(provisionParent).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Student" }));
    fireEvent.change(screen.getByLabelText("Student name"), { target: { value: "Student Z" } });
    fireEvent.change(screen.getByLabelText("Class"), { target: { value: "class-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create student" }));
    await waitFor(() => {
      expect(provisionStudent).toHaveBeenCalledWith(expect.objectContaining({
        class_id: "class-1",
        initial_enrollment: null,
      }));
    });
  });

  it("shows duplicate conflict display", async () => {
    (provisionTeacher as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("Email already belongs to another role."));
    render(<PeoplePage />);
    await screen.findByText("People & Families");

    fireEvent.click(screen.getByRole("button", { name: "Add Teacher" }));
    fireEvent.change(screen.getByLabelText("Teacher name"), { target: { value: "Teacher Alpha" } });
    fireEvent.change(screen.getByLabelText("Teacher email"), { target: { value: "dup@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create teacher" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Email already belongs to another role.");
  });

  it("shows one-time invitation after issue and does not persist it", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");

    fireEvent.click(screen.getByRole("button", { name: "People" }));
    fireEvent.click(await screen.findByRole("button", { name: "Issue invitation" }));

    await waitFor(() => {
      expect(issueInvitation).toHaveBeenCalled();
      expect(screen.getByText("new-one-time-token")).toBeInTheDocument();
    });

    expect(window.localStorage.getItem("activation_token")).toBeNull();
    expect(window.sessionStorage.getItem("activation_token")).toBeNull();
  });

  it("supports invitation list filters and revoke confirmation", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");
    fireEvent.click(screen.getByRole("button", { name: "Invitations" }));

    fireEvent.change(screen.getByLabelText("Invitation status"), { target: { value: "pending" } });
    await waitFor(() => {
      expect(listInvitations).toHaveBeenCalledWith(expect.objectContaining({ status: "pending" }));
    });

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => {
      expect(revokeInvitation).toHaveBeenCalledWith("inv-1");
    });
  });

  it("supports account activate/deactivate confirmation", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");

    fireEvent.click(screen.getByRole("button", { name: "People" }));
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    await waitFor(() => {
      expect(updateUserStatus).toHaveBeenCalledWith("teacher-1", { is_active: false, reason: "policy reason" });
    });
  });

  it("supports families create, update and deactivate without delete action", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");
    fireEvent.click(screen.getByRole("button", { name: "Families" }));

    fireEvent.change(screen.getByLabelText("Family create parent"), { target: { value: "parent-1" } });
    fireEvent.change(screen.getByLabelText("Family create student"), { target: { value: "student-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createFamilyRelationship).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => {
      expect(updateFamilyRelationship).toHaveBeenCalledWith("student-1:parent-1", { is_active: false });
    });

    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  });

  it("shows reconciliation counts and never exposes token_hash", async () => {
    render(<PeoplePage />);
    await screen.findByText("People & Families");
    fireEvent.click(screen.getByRole("button", { name: "Reconciliation" }));

    expect(await screen.findByText(/teachers without user/i)).toBeInTheDocument();
    expect(screen.queryByText(/token_hash/i)).not.toBeInTheDocument();
  });
});
