"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import {
  ParentApiError,
  ParentStudentOverviewResponse,
  ParentStudentSummary,
  getParentStudentOverview,
  getParentStudents,
} from "@/lib/parent-api";
import {
  ParentEmptyState,
  ParentErrorState,
  ParentPageSkeleton,
} from "@/components/parent/parent-page-states";
import ChildSelector from "@/components/parent/child-selector";
import UnavailableModuleCard from "@/components/parent/unavailable-module-card";

interface OverviewState {
  overview: ParentStudentOverviewResponse | null;
  students: ParentStudentSummary[];
  loading: boolean;
  error: string | null;
  statusCode: number | null;
}

export default function ParentStudentOverviewPage() {
  const auth = useParentAuth();
  const params = useParams<{ studentId: string }>();
  const router = useRouter();
  const studentId = params.studentId;

  const [state, setState] = useState<OverviewState>({
    overview: null,
    students: [],
    loading: false,
    error: null,
    statusCode: null,
  });

  async function loadData(token: string, selectedStudentId: string) {
    setState((prev) => ({ ...prev, loading: true, error: null, statusCode: null }));
    try {
      const [overview, studentsResponse] = await Promise.all([
        getParentStudentOverview(token, selectedStudentId),
        getParentStudents(token),
      ]);

      setState({
        overview,
        students: studentsResponse.students,
        loading: false,
        error: null,
        statusCode: null,
      });
    } catch (error) {
      if (error instanceof ParentApiError) {
        setState({
          overview: null,
          students: [],
          loading: false,
          error: error.message,
          statusCode: error.status,
        });
        return;
      }

      setState({
        overview: null,
        students: [],
        loading: false,
        error: "Unable to load child overview.",
        statusCode: null,
      });
    }
  }

  useEffect(() => {
    if (!auth.token || !auth.isAuthenticated) return;

    if (!studentId) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadData(auth.token, studentId);
  }, [auth.token, auth.isAuthenticated, studentId]);

  const activeStudentId = useMemo(() => state.overview?.student_id ?? studentId, [state.overview, studentId]);

  if (auth.isHydrating) {
    return <ParentPageSkeleton title="Loading child overview" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (state.loading) {
    return <ParentPageSkeleton title="Loading child overview" />;
  }

  if (state.statusCode === 404) {
    return (
      <ParentEmptyState
        title="Child overview is not available"
        description={state.error || "This child cannot be accessed from your account."}
      />
    );
  }

  if (state.statusCode === 403) {
    return (
      <ParentErrorState
        title="Access denied"
        description="This account does not have access to this student overview."
      />
    );
  }

  if (!state.overview || state.error) {
    return (
      <ParentErrorState
        title="Unable to load child overview"
        description={state.error || "Please try again."}
        actionLabel="Retry"
        onAction={() => {
          if (auth.token && studentId) {
            void loadData(auth.token, studentId);
          }
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{state.overview.name}</h1>
            <p className="mt-1 text-sm text-gray-600">
              {state.overview.class_name}
              {state.overview.homeroom_teacher ? ` • ${state.overview.homeroom_teacher}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/parent"
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
            >
              Back to Family Hub
            </Link>
            <button
              type="button"
              onClick={auth.logout}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-lg font-semibold text-gray-900">Child selection</h2>
        <div className="mt-4">
          <ChildSelector
            students={state.students}
            activeStudentId={activeStudentId}
            onChange={(nextId) => {
              if (nextId === studentId || !auth.token) return;
                router.push(`/parent/student/${nextId}`);
            }}
          />
        </div>
      </section>

      <section className="space-y-3" aria-label="Student module overview">
        <h2 className="text-lg font-semibold text-gray-900">Overview</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <UnavailableModuleCard label="Academics" state={state.overview.academics} />
          <UnavailableModuleCard label="Attendance" state={state.overview.attendance} />
          <UnavailableModuleCard label="Homework" state={state.overview.homework} />
          <UnavailableModuleCard label="Behaviour" state={state.overview.behaviour} />
          <UnavailableModuleCard label="Assessment results" state={state.overview.assessment_results} />
        </div>
      </section>
    </div>
  );
}
