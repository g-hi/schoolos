"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthApiError, routeForRole, readTenantSlug } from "@/lib/auth";
import { useAuth } from "@/components/auth/auth-provider";

export default function LoginPanel() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantSlug, setTenantSlug] = useState(readTenantSlug());
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const normalizedTenant = useMemo(() => tenantSlug.trim().toLowerCase(), [tenantSlug]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);

    try {
      const profile = await login(email.trim(), password, normalizedTenant);
      const destination = routeForRole(profile.role);
      if (!destination) {
        setErrorMessage("This account role is not supported in SchoolOS.");
        return;
      }
      router.replace(destination);
    } catch (error) {
      if (error instanceof AuthApiError) {
        if (error.status === 401) {
          setErrorMessage("Invalid email or password.");
        } else if (error.status === 403) {
          setErrorMessage("This account does not have access to SchoolOS.");
        } else if (error.status === 0) {
          setErrorMessage("Network error. Please check your connection and try again.");
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
    <section className="mx-auto mt-8 w-full max-w-lg rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
      <h1 className="text-2xl font-semibold text-gray-900">SchoolOS Sign In</h1>
      <p className="mt-2 text-sm text-gray-600">
        Sign in with your school account to open the correct portal for your role.
      </p>

      <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
        <div>
          <label htmlFor="auth-email" className="mb-1 block text-sm font-medium text-gray-700">
            Email
          </label>
          <input
            id="auth-email"
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
          <label htmlFor="auth-password" className="mb-1 block text-sm font-medium text-gray-700">
            Password
          </label>
          <input
            id="auth-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>

        <div>
          <label htmlFor="auth-tenant" className="mb-1 block text-sm font-medium text-gray-700">
            Tenant Slug
          </label>
          <input
            id="auth-tenant"
            name="tenantSlug"
            type="text"
            autoCapitalize="none"
            autoComplete="off"
            required
            value={tenantSlug}
            onChange={(event) => setTenantSlug(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>

        {errorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {errorMessage}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Signing in..." : "Sign In"}
        </button>

        <div className="text-center">
          <a href="/activate-account" className="text-sm text-indigo-700 underline">
            Activate invited account
          </a>
        </div>
      </form>
    </section>
  );
}
