import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ManualEventForm from "@/app/leadership/calendar/manual-event-form";

describe("manual event form", () => {
  it("renders required fields and blocks invalid date ranges", async () => {
    const onCreate = vi.fn();
    render(<ManualEventForm onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText(/event name/i), { target: { value: "Term Opening" } });
    fireEvent.change(screen.getByLabelText(/start date/i), { target: { value: "2026-09-20" } });
    fireEvent.change(screen.getByLabelText(/end date/i), { target: { value: "2026-09-10" } });

    fireEvent.click(screen.getByRole("button", { name: /save draft event/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/end date cannot be before start date/i);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("submits structured scope to create draft endpoint and does not imply publication", async () => {
    const onCreate = vi.fn().mockResolvedValue({ id: "evt-1" });
    render(<ManualEventForm onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText(/event name/i), { target: { value: "Founders Day" } });
    fireEvent.change(screen.getByLabelText(/^event type/i), { target: { value: "school_event" } });
    fireEvent.change(screen.getByLabelText(/start date/i), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText(/end date/i), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText(/scope type/i), { target: { value: "grade_levels" } });
    fireEvent.change(screen.getByLabelText(/grade levels/i), { target: { value: "Grade 9, Grade 10" } });

    fireEvent.click(screen.getByRole("button", { name: /save draft event/i }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate.mock.calls[0][0].scope.scope_type).toBe("grade_levels");
    expect(onCreate.mock.calls[0][0].scope.grade_levels).toEqual(["Grade 9", "Grade 10"]);
    expect(await screen.findByText(/not published and still requires review and approval/i)).toBeInTheDocument();
  });
});
