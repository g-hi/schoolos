import { render, screen, waitFor } from "@testing-library/react";
import RoleGuard from "@/components/auth/role-guard";

const replaceMock = vi.fn();
const useAuthMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/protected",
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => useAuthMock(),
}));

function renderGuard(allowedRoles: string[], userRole: string | null, isAuthenticated = true) {
  useAuthMock.mockReturnValue({
    isHydrating: false,
    isAuthenticated,
    user: userRole
      ? { role: userRole, is_active: true }
      : null,
  });

  return render(
    <RoleGuard allowedRoles={allowedRoles} forbiddenMessage="Permission denied test message">
      <div>Protected content</div>
    </RoleGuard>,
  );
}

describe("role-guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects to /login when no token/session exists", async () => {
    renderGuard(["teacher"], null, false);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("blocks parent from teacher routes", () => {
    renderGuard(["teacher"], "parent");
    expect(screen.getByText(/permission denied test message/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("blocks teacher from parent routes", () => {
    renderGuard(["parent"], "teacher");
    expect(screen.getByText(/permission denied test message/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("blocks teacher from leadership review routes", () => {
    renderGuard(["principal", "school_admin"], "teacher");
    expect(screen.getByText(/permission denied test message/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("allows principal on leadership review routes", () => {
    renderGuard(["principal", "school_admin"], "principal");
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("shows 403 UI without forcing logout for wrong role", () => {
    renderGuard(["teacher"], "parent");
    expect(screen.getByText(/permission denied test message/i)).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalledWith("/login");
  });
});
