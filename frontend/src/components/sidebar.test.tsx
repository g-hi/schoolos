import { render, screen } from "@testing-library/react";
import Sidebar from "@/components/sidebar";

const mockedUsePathname = vi.fn();
const mockedUseAuth = vi.fn();
const mockedGetParentUnreadNotificationCount = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockedUsePathname(),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => mockedUseAuth(),
}));

vi.mock("@/lib/announcements-api", () => ({
  getParentUnreadNotificationCount: () => mockedGetParentUnreadNotificationCount(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

describe("sidebar route mode", () => {
  it("shows parent links only on parent routes", async () => {
    mockedGetParentUnreadNotificationCount.mockResolvedValue({ unread_count: 3 });
    mockedUsePathname.mockReturnValue("/parent");
    mockedUseAuth.mockReturnValue({ user: { role: "parent" }, logout: vi.fn() });
    const { rerender } = render(<Sidebar />);
    expect(screen.getByText("Family Hub")).toBeInTheDocument();
    expect(screen.getByText("Appointments").closest("a")).toHaveAttribute("href", "/parent/appointments");
    expect(await screen.findByLabelText("Unread notifications: 3")).toBeInTheDocument();
    expect(screen.getByText("Notifications").closest("a")).toHaveAttribute("href", "/parent/notifications");
    expect(screen.getByText("Announcements").closest("a")).toHaveAttribute("href", "/parent/announcements");
    expect(screen.getByText("Pickup").closest("a")).toHaveAttribute("href", "/parent/pickup");
    expect(screen.getByText("Weekly Reports").closest("a")).toHaveAttribute("href", "/parent/reports");

    mockedUsePathname.mockReturnValue("/teacher");
    mockedUseAuth.mockReturnValue({ user: { role: "teacher" }, logout: vi.fn() });
    rerender(<Sidebar />);
    expect(screen.queryByText("Family Hub")).not.toBeInTheDocument();
    expect(screen.queryByText("People & Families")).not.toBeInTheDocument();
    expect(screen.getByText("My Classes")).toBeInTheDocument();
    expect(screen.getByText("Appointments").closest("a")).toHaveAttribute("href", "/teacher/appointments");
    expect(screen.getByText("Weekly Reports").closest("a")).toHaveAttribute("href", "/teacher/reports");

    mockedUsePathname.mockReturnValue("/");
    mockedUseAuth.mockReturnValue({ user: { role: "principal" }, logout: vi.fn() });
    rerender(<Sidebar />);
    expect(screen.queryByText("Family Hub")).not.toBeInTheDocument();
    expect(screen.getByText("People & Families").closest("a")).toHaveAttribute("href", "/people");
    expect(screen.getByText("Appointments").closest("a")).toHaveAttribute("href", "/appointments");
    expect(screen.getByText("Announcements").closest("a")).toHaveAttribute("href", "/announcements");
    expect(screen.getByText("Data Imports").closest("a")).toHaveAttribute("href", "/data");
    expect(screen.getByText("Timetable")).toBeInTheDocument();
    expect(screen.getByText("Weekly Reports").closest("a")).toHaveAttribute("href", "/reports/review");
  });
});
