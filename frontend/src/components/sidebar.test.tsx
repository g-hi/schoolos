import { render, screen } from "@testing-library/react";
import Sidebar from "@/components/sidebar";

const mockedUsePathname = vi.fn();
const mockedUseAuth = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockedUsePathname(),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => mockedUseAuth(),
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
    mockedUseAuth.mockReturnValue({ user: { role: "parent" }, logout: vi.fn() });
    const { rerender } = render(<Sidebar />);
    expect(screen.getByText("Family Hub")).toBeInTheDocument();
    expect(screen.getByText("Weekly Reports")).toHaveAttribute("href", "/parent/reports");

    mockedUsePathname.mockReturnValue("/teacher");
    mockedUseAuth.mockReturnValue({ user: { role: "teacher" }, logout: vi.fn() });
    rerender(<Sidebar />);
    expect(screen.queryByText("Family Hub")).not.toBeInTheDocument();
    expect(screen.getByText("My Classes")).toBeInTheDocument();
    expect(screen.getByText("Weekly Reports")).toHaveAttribute("href", "/teacher/reports");

    mockedUsePathname.mockReturnValue("/");
    mockedUseAuth.mockReturnValue({ user: { role: "principal" }, logout: vi.fn() });
    rerender(<Sidebar />);
    expect(screen.queryByText("Family Hub")).not.toBeInTheDocument();
    expect(screen.getByText("Timetable")).toBeInTheDocument();
    expect(screen.getByText("Weekly Reports")).toHaveAttribute("href", "/reports/review");
  });
});
