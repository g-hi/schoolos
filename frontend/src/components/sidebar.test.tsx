import { render, screen } from "@testing-library/react";
import Sidebar from "@/components/sidebar";

const mockedUsePathname = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockedUsePathname(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

describe("sidebar route mode", () => {
  it("shows parent links only on parent routes", () => {
    mockedUsePathname.mockReturnValue("/parent");
    const { rerender } = render(<Sidebar />);
    expect(screen.getByText("Family Hub")).toBeInTheDocument();

    mockedUsePathname.mockReturnValue("/teacher");
    rerender(<Sidebar />);
    expect(screen.queryByText("Family Hub")).not.toBeInTheDocument();
    expect(screen.getByText("My Classes")).toBeInTheDocument();

    mockedUsePathname.mockReturnValue("/");
    rerender(<Sidebar />);
    expect(screen.queryByText("Family Hub")).not.toBeInTheDocument();
    expect(screen.getByText("Timetable")).toBeInTheDocument();
  });
});
