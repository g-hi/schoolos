"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { AccountActivationApiError, acceptInvitation } from "@/lib/account-activation-api";

function passwordPolicy(password: string): string | null {
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (!/[A-Z]/.test(password)) return "Password must include an uppercase letter.";
  if (!/[a-z]/.test(password)) return "Password must include a lowercase letter.";
  if (!/[0-9]/.test(password)) return "Password must include a number.";
  return null;
}

function sanitizeLocationAfterTokenRead(removeHash: boolean): void {
  if (typeof window === "undefined") return;
  const current = new URL(window.location.href);
  current.searchParams.delete("token");
  if (removeHash) {
    current.hash = "";
  }
  const next = `${current.pathname}${current.search}${current.hash}`;
  window.history.replaceState({}, "", next);
}

function extractFragmentToken(hash: string): string | null {
  if (!hash) return null;
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!raw) return null;

  if (raw.includes("=")) {
    const params = new URLSearchParams(raw);
    return params.get("token")?.trim() || null;
  }

  return raw.trim();
}

export default function ActivateAccountPage() {
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const queryToken = new URL(window.location.href).searchParams.get("token")?.trim() || null;
    const fragmentToken = extractFragmentToken(window.location.hash);
    const resolved = fragmentToken || queryToken;

    if (resolved) {
      setToken(resolved);
    }

    sanitizeLocationAfterTokenRead(Boolean(fragmentToken));
  }, []);

  const policyMessage = useMemo(() => passwordPolicy(newPassword), [newPassword]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);

    const trimmedToken = token.trim();
    if (!trimmedToken) {
      setErrorMessage("Activation token is required.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setErrorMessage("Passwords do not match.");
      return;
    }

    const policyError = passwordPolicy(newPassword);
    if (policyError) {
      setErrorMessage(policyError);
      return;
    }

    setSubmitting(true);
    try {
      await acceptInvitation(trimmedToken, newPassword);
      setSuccess(true);
      setToken("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (error) {
      if (error instanceof AccountActivationApiError) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("Activation failed. Please request a new invitation.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto mt-8 w-full max-w-lg rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
      <h1 className="text-2xl font-semibold text-gray-900">Activate invited account</h1>
      <p className="mt-2 text-sm text-gray-600">
        Paste your one-time activation token and set a new password.
      </p>

      {success ? (
        <section className="mt-6 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">
          <p>Your account is now active.</p>
          <Link href="/login" className="mt-2 inline-block font-medium underline">
            Continue to login
          </Link>
        </section>
      ) : (
        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="activation-token" className="mb-1 block text-sm font-medium text-gray-700">
              Invitation token
            </label>
            <input
              id="activation-token"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
              autoComplete="off"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="new-password" className="mb-1 block text-sm font-medium text-gray-700">
              New password
            </label>
            <input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">
              Minimum 8 characters, with uppercase, lowercase and a number.
            </p>
            {policyMessage ? <p className="mt-1 text-xs text-amber-700">{policyMessage}</p> : null}
          </div>

          <div>
            <label htmlFor="confirm-password" className="mb-1 block text-sm font-medium text-gray-700">
              Confirm password
            </label>
            <input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          {errorMessage ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {errorMessage}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {submitting ? "Activating..." : "Activate account"}
          </button>
        </form>
      )}
    </main>
  );
}
