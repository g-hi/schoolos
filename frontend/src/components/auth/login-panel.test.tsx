import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LoginPanel from "@/components/auth/login-panel";
import { AuthApiError } from "@/lib/auth";

const replaceMock = vi.fn();
const loginMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ login: loginMock }),
}));

describe("login-panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
  });

  it("submits one shared login form with normalized tenant slug", async () => {
    loginMock.mockResolvedValue({ role: "teacher" });
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " teacher@example.com " } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pass123" } });
    fireEvent.change(screen.getByLabelText("Tenant Slug"), { target: { value: " GREENWOOD " } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith("teacher@example.com", "pass123", "greenwood");
    });
  });

  it("redirects parent login to /parent", async () => {
    loginMock.mockResolvedValue({ role: "parent" });
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "parent@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pass" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/parent");
    });
  });

  it("redirects teacher login to /teacher", async () => {
    loginMock.mockResolvedValue({ role: "teacher" });
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "teacher@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pass" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/teacher");
    });
  });

  it("redirects principal login to the principal dashboard route", async () => {
    loginMock.mockResolvedValue({ role: "principal" });
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "principal@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pass" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
  });

  it("shows access denied for unsupported role", async () => {
    loginMock.mockResolvedValue({ role: "staff" });
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "staff@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pass" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/role is not supported/i)).toBeInTheDocument();
    });
  });

  it("shows invalid credentials on 401", async () => {
    loginMock.mockRejectedValue(new AuthApiError(401, "Invalid credentials.", null));
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "teacher@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument();
    });
  });

  it("shows no access message on 403", async () => {
    loginMock.mockRejectedValue(new AuthApiError(403, "Forbidden", null));
    render(<LoginPanel />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "teacher@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/does not have access/i)).toBeInTheDocument();
    });
  });
});
