"use client";

import { useEffect, useState } from "react";
import ChildCard from "@/components/parent/child-card";
import ChildSelector from "@/components/parent/child-selector";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import ParentWidgets from "@/components/parent/parent-widgets";
import {
  ParentApiError,
  ParentDashboardResponse,
  ParentProfileResponse,
  getParentDashboard,
  getParentMe,
} from "@/lib/parent-api";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import {
  ParentEmptyState,
  ParentErrorState,
  ParentPageSkeleton,
} from "@/components/parent/parent-page-states";

interface LoadState {
  profile: ParentProfileResponse | null;
  dashboard: ParentDashboardResponse | null;
  loading: boolean;
  error: string | null;
  statusCode: number | null;
}

export default function FamilyHub() {
  const auth = useParentAuth();
  const [state, setState] = useState<LoadState>({
    profile: null,
    dashboard: null,
    loading: false,
    error: null,
    statusCode: null,
  });
  const [activeStudentId, setActiveStudentId] = useState<string | null>(null);

  async function loadData(token: string) {
    setState((prev) => ({ ...prev, loading: true, error: null, statusCode: null }));

    try {
      const [profile, dashboard] = await Promise.all([
        getParentMe(token),
        getParentDashboard(token),
      ]);

      setState({
        profile,
        dashboard,
        loading: false,
        error: null,
        statusCode: null,
      });

      if (dashboard.students.length > 0) {
        setActiveStudentId((prev) => prev ?? dashboard.students[0].student_id);
      }
    } catch (error) {
      if (error instanceof ParentApiError) {
        setState({
          profile: null,
          dashboard: null,
          loading: false,
          error: error.message,
          statusCode: error.status,
        });
        return;
      }

      setState({
        profile: null,
        dashboard: null,
        loading: false,
        error: "Unable to load family hub.",
        statusCode: null,
      });
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated || !auth.token) return;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadData(auth.token);
  }, [auth.isAuthenticated, auth.token]);

  const students = state.dashboard?.students ?? [];
  const activeStudent = students.find((student) => student.student_id === activeStudentId) ?? students[0] ?? null;

  if (auth.isHydrating) {
    return <ParentPageSkeleton title="Loading family hub" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (state.loading) {
    return <ParentPageSkeleton title="Loading family hub" />;
  }

  if (state.statusCode === 404) {
    return (
      <ParentEmptyState
        title="Family profile is not available yet"
        description={state.error || "No active family was found for this account."}
      />
    );
  }

  if (state.statusCode === 403) {
    return (
      <ParentErrorState
        title="Access denied"
        description="This account does not have parent portal permissions."
        actionLabel="Sign out"
        onAction={auth.logout}
      />
    );
  }

  if (state.error || !state.dashboard || !state.profile) {
    return (
      <ParentErrorState
        title="Unable to open Family Hub"
        description={state.error || "Please try again."}
        actionLabel="Retry"
        onAction={() => {
          if (auth.token) {
            void loadData(auth.token);
          }
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <h1 className="text-2xl font-semibold text-gray-900">Family Hub</h1>
        <p className="mt-2 text-sm text-gray-600">
          {state.dashboard.family_name || state.profile.family_name || "Your family"}
        </p>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-label="Children">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Children</h2>
          <button
            type="button"
            onClick={auth.logout}
            className="inline-flex w-fit rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
          >
            Sign out
          </button>
        </div>

        {students.length === 0 ? (
          <ParentEmptyState
            title="No linked students"
            description="No students are currently linked to this parent account."
          />
        ) : (
          <div className="mt-4 space-y-4">
            <ChildSelector
              students={students}
              activeStudentId={activeStudent?.student_id ?? null}
              onChange={setActiveStudentId}
            />

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {students.map((student) => (
                <ChildCard
                  key={student.student_id}
                  student={student}
                  isActive={student.student_id === activeStudent?.student_id}
                  onActivate={setActiveStudentId}
                />
              ))}
            </div>
          </div>
        )}
      </section>

      <ParentWidgets dashboard={state.dashboard} />
    </div>
  );
}
