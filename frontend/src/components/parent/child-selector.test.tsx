import { fireEvent, render, screen } from "@testing-library/react";
import ChildSelector from "@/components/parent/child-selector";

describe("child-selector", () => {
  it("changes active student selection", () => {
    const onChange = vi.fn();
    render(
      <ChildSelector
        students={[
          {
            student_id: "s1",
            name: "Aisha",
            student_code: "S1",
            grade: "5",
            section: "A",
            class_name: "5-A",
            homeroom_teacher: null,
            is_primary_guardian: true,
            can_pickup: true,
            can_view_academics: true,
            can_view_behaviour: true,
          },
          {
            student_id: "s2",
            name: "Omar",
            student_code: "S2",
            grade: "3",
            section: "B",
            class_name: "3-B",
            homeroom_teacher: null,
            is_primary_guardian: false,
            can_pickup: true,
            can_view_academics: false,
            can_view_behaviour: false,
          },
        ]}
        activeStudentId="s1"
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Select child/i), { target: { value: "s2" } });
    expect(onChange).toHaveBeenCalledWith("s2");
  });
});
