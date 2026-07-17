import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ParentAssistant from "@/components/parent/parent-assistant";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import {
  continueParentAssistant,
  getParentStudents,
  runParentAssistant,
} from "@/lib/parent-api";

vi.mock("@/components/parent/parent-auth-provider", () => ({
  useParentAuth: vi.fn(),
}));

vi.mock("@/lib/parent-api", () => ({
  getParentStudents: vi.fn(),
  runParentAssistant: vi.fn(),
  continueParentAssistant: vi.fn(),
}));

describe("parent-assistant component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    (useParentAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      token: "token-parent",
      login: vi.fn(),
      logout: vi.fn(),
      status: "authenticated",
    });
    (getParentStudents as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      students: [
        {
          student_id: "student-1",
          name: "Ahmed Hassan",
          student_code: "S001",
          grade: "7",
          section: "A",
          class_name: "Grade 7-A",
          homeroom_teacher: "Mr. Ali",
          is_primary_guardian: true,
          can_pickup: true,
          can_view_academics: true,
          can_view_behaviour: true,
        },
      ],
    });
    (continueParentAssistant as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
      request_id: "req-default",
      conversation_id: "conv-default",
      message: "Follow-up received.",
      sources: [],
      suggested_questions: [],
      execution: {
        workflow: "parent_assistant",
        current_step: "parent_response",
        validation_passed: true,
        retry_count: 0,
      },
    });
  });

  it("submits message and renders assistant response with suggestions", async () => {
    (runParentAssistant as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
      request_id: "req-1",
      conversation_id: "conv-1",
      message: "You have 1 linked child: Ahmed Hassan.",
      sources: [{ type: "student_profile", label: "Student Profile" }],
      suggested_questions: ["Show recent family updates"],
      execution: {
        workflow: "parent_assistant",
        current_step: "parent_response",
        validation_passed: true,
        retry_count: 0,
      },
    });

    render(<ParentAssistant />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Select child/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Ask a question/i), {
      target: { value: "Summarize my family" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send/i }));

    await waitFor(() => {
      expect(screen.getByText(/You have 1 linked child/i)).toBeInTheDocument();
    });

    expect(runParentAssistant).toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: /Show recent family updates/i }).length).toBeGreaterThan(0);
  });

  it("prevents duplicate submission while request is active", async () => {
    let resolveRequest: (value: unknown) => void = () => {};
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    (runParentAssistant as unknown as ReturnType<typeof vi.fn>).mockReturnValue(pending);

    render(<ParentAssistant />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Ask a question/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Ask a question/i), {
      target: { value: "Summarize my family" },
    });

    const send = screen.getByRole("button", { name: /Send/i });
    fireEvent.click(send);
    fireEvent.click(send);

    expect(runParentAssistant).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRequest({
        status: "completed",
        request_id: "req-1",
        conversation_id: "conv-1",
        message: "Done",
        sources: [],
        suggested_questions: [],
        execution: {
          workflow: "parent_assistant",
          current_step: "parent_response",
          validation_passed: true,
          retry_count: 0,
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Done")).toBeInTheDocument();
    });
  });

  it("renders response text safely and does not inject html", async () => {
    (runParentAssistant as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
      request_id: "req-2",
      conversation_id: "conv-2",
      message: "<script>alert('x')</script>",
      sources: [],
      suggested_questions: [],
      execution: {
        workflow: "parent_assistant",
        current_step: "parent_response",
        validation_passed: true,
        retry_count: 0,
      },
    });

    render(<ParentAssistant />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Ask a question/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Ask a question/i), {
      target: { value: "Show me updates" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send/i }));

    await waitFor(() => {
      expect(screen.getByText("<script>alert('x')</script>")).toBeInTheDocument();
    });
  });

  it("uses continue endpoint after request id is set", async () => {
    (runParentAssistant as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "needs_clarification",
      request_id: "req-3",
      conversation_id: "conv-3",
      message: "Which child do you mean?",
      clarification_question: "Which child do you mean?",
      suggested_questions: [],
      sources: [],
      execution: {
        workflow: "parent_assistant",
        current_step: "parent_student_resolution",
        validation_passed: true,
        retry_count: 0,
      },
    });

    (continueParentAssistant as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
      request_id: "req-3",
      conversation_id: "conv-3",
      message: "Ahmed Hassan is in Grade 7-A.",
      sources: [{ type: "student_profile", label: "Student Profile" }],
      suggested_questions: [],
      execution: {
        workflow: "parent_assistant",
        current_step: "parent_response",
        validation_passed: true,
        retry_count: 0,
      },
    });

    render(<ParentAssistant />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Ask a question/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Ask a question/i), {
      target: { value: "How is Ahmed doing?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send/i }));

    await waitFor(() => {
      expect(screen.getByText(/Which child do you mean/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Ask a question/i), {
      target: { value: "Ahmed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send/i }));

    await waitFor(() => {
      expect(continueParentAssistant).toHaveBeenCalled();
    });
  });
});