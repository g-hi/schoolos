import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ActivateAccountPage from "@/app/activate-account/page";
import { AccountActivationApiError, acceptInvitation } from "@/lib/account-activation-api";

vi.mock("@/lib/account-activation-api", () => ({
  AccountActivationApiError: class AccountActivationApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  acceptInvitation: vi.fn(),
}));

describe("activate-account page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.history.replaceState({}, "", "/activate-account");
  });

  it("renders publicly without authenticated user context", () => {
    render(<ActivateAccountPage />);
    expect(screen.getByText("Activate invited account")).toBeInTheDocument();
  });

  it("accepts pasted token", () => {
    render(<ActivateAccountPage />);
    const tokenInput = screen.getByLabelText("Invitation token");
    fireEvent.change(tokenInput, { target: { value: "manual-token" } });
    expect(tokenInput).toHaveValue("manual-token");
  });

  it("loads query token and sanitizes url", async () => {
    window.history.replaceState({}, "", "/activate-account?token=query-secret");
    render(<ActivateAccountPage />);

    const tokenInput = await screen.findByLabelText("Invitation token");
    expect(tokenInput).toHaveValue("query-secret");
    expect(window.location.search).toBe("");
  });

  it("loads fragment token", async () => {
    window.history.replaceState({}, "", "/activate-account#token=frag-secret");
    render(<ActivateAccountPage />);
    expect(await screen.findByDisplayValue("frag-secret")).toBeInTheDocument();
  });

  it("validates password confirmation", async () => {
    render(<ActivateAccountPage />);
    fireEvent.change(screen.getByLabelText("Invitation token"), { target: { value: "abc" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "StrongPass1" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "StrongPass2" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords do not match.");
  });

  it("shows password policy error", async () => {
    render(<ActivateAccountPage />);
    fireEvent.change(screen.getByLabelText("Invitation token"), { target: { value: "abc" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "weak" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "weak" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/at least 8 characters/i);
  });

  it("activates successfully and links to login", async () => {
    (acceptInvitation as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "accepted" });

    render(<ActivateAccountPage />);
    fireEvent.change(screen.getByLabelText("Invitation token"), { target: { value: "valid-token" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "StrongPass1" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "StrongPass1" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));

    await waitFor(() => {
      expect(acceptInvitation).toHaveBeenCalledWith("valid-token", "StrongPass1");
      expect(screen.getByText(/account is now active/i)).toBeInTheDocument();
      expect(screen.getByText("Continue to login")).toHaveAttribute("href", "/login");
    });
  });

  it("maps invalid, expired, revoked and reused token states to controlled errors", async () => {
    (acceptInvitation as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new AccountActivationApiError(400, "The activation link is invalid."))
      .mockRejectedValueOnce(new AccountActivationApiError(410, "This activation link has expired."))
      .mockRejectedValueOnce(new AccountActivationApiError(409, "This activation link is no longer valid."))
      .mockRejectedValueOnce(new AccountActivationApiError(409, "This activation link is no longer valid."));

    render(<ActivateAccountPage />);

    const submit = async () => {
      fireEvent.change(screen.getByLabelText("Invitation token"), { target: { value: "bad-token" } });
      fireEvent.change(screen.getByLabelText("New password"), { target: { value: "StrongPass1" } });
      fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "StrongPass1" } });
      fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
      await screen.findByRole("alert");
    };

    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent("invalid");

    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent("expired");

    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent("no longer valid");

    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent("no longer valid");
  });

  it("does not write token to storage and has no role/tenant selector", async () => {
    render(<ActivateAccountPage />);
    fireEvent.change(screen.getByLabelText("Invitation token"), { target: { value: "secret-token" } });

    expect(window.localStorage.getItem("token")).toBeNull();
    expect(window.sessionStorage.getItem("token")).toBeNull();
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
  });
});
