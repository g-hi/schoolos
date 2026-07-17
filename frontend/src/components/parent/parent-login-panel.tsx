"use client";

import { FormEvent, useState } from "react";
import { ParentApiError } from "@/lib/parent-api";

interface ParentLoginPanelProps {
  onLogin: (email: string, password: string) => Promise<void>;
}

export default function ParentLoginPanel({ onLogin }: ParentLoginPanelProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);

    try {
      await onLogin(email.trim(), password);
    } catch (error) {
      if (error instanceof ParentApiError) {
        if (error.status === 401) {
          setErrorMessage("Invalid email or password.");
        } else if (error.status === 403) {
          setErrorMessage("This account does not have parent access.");
        } else {
          setErrorMessage(error.message || "Unable to sign in right now.");
        }
      } else {
        setErrorMessage("Unable to sign in right now. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mx-auto w-full max-w-lg rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
      <h1 className="text-2xl font-semibold text-gray-900">Parent Sign In</h1>
      <p className="mt-2 text-sm text-gray-600">
        Sign in with your parent account to access your family hub and child updates.
      </p>

      <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
        <div>
          <label htmlFor="parent-email" className="mb-1 block text-sm font-medium text-gray-700">
            Email
          </label>
          <input
            id="parent-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>

        <div>
          <label htmlFor="parent-password" className="mb-1 block text-sm font-medium text-gray-700">
            Password
          </label>
          <input
            id="parent-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>

        {errorMessage && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">
            {errorMessage}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          aria-label="Sign in to parent portal"
          className="inline-flex w-full items-center justify-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-indigo-300"
        >
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </section>
  );
}
