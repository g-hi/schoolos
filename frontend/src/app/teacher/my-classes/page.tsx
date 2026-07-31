"use client";

import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  type TeacherMyClassItem,
  type TeacherMyClassesResponse,
  getTeacherMyClasses,
} from "@/lib/teacher-api";

function mapError(error: unknown): { title: string; detail: string; profileMissing: boolean } {
  if (error instanceof TeacherApiError) {
    const detail = error.message || "Request failed.";
    if (error.status === 401) {
      return {
        title: "Authenticated Access Error",
        detail: "Your session has expired. Please sign in again.",
        profileMissing: false,
      };
    }
    if (error.status === 403) {
      if (detail.toLowerCase().includes("teacher profile")) {
        return {
          title: "Teacher Profile Missing",
          detail: "A teacher profile has not been configured for this account yet.",
          profileMissing: true,
        };
      }
      return {
        title: "Authenticated Access Error",
        detail: "You do not have access to this page.",
        profileMissing: false,
      };
    }
    return {
      title: "API Failure",
      detail,
      profileMissing: false,
    };
  }

  return {
    title: "API Failure",
    detail: error instanceof Error ? error.message : "Failed to load classes.",
    profileMissing: false,
  };
}

function sourceBadgeClass(source: TeacherMyClassItem["assignment_source"]): string {
  return source === "canonical"
    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
    : "bg-amber-50 text-amber-700 border-amber-200";
}

function assignmentBadgeClass(type: "homeroom" | "subject_teacher"): string {
  return type === "homeroom"
    ? "bg-sky-50 text-sky-700 border-sky-200"
    : "bg-indigo-50 text-indigo-700 border-indigo-200";
}

function dateRange(startDate: string | null, endDate: string | null): string {
  if (!startDate && !endDate) {
    return "Compatibility source";
  }
  return `${startDate || "—"} to ${endDate || "ongoing"}`;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4" aria-label="loading">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="h-4 w-1/3 animate-pulse rounded bg-gray-100" />
          <div className="mt-3 h-3 w-1/2 animate-pulse rounded bg-gray-100" />
          <div className="mt-4 h-20 animate-pulse rounded bg-gray-50" />
        </div>
      ))}
    </div>
  );
}

export default function MyClassesPage() {
  const auth = useAuth();
  const [data, setData] = useState<TeacherMyClassesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ title: string; detail: string; profileMissing: boolean } | null>(null);

  const classes = useMemo(() => data?.classes ?? [], [data]);

  async function loadClasses() {
    if (!auth.isAuthenticated || !auth.token) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await getTeacherMyClasses(undefined, auth.token);
      setData(response);
    } catch (err) {
      setError(mapError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadClasses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, auth.token]);

  if (!auth.isAuthenticated) {
    return (
      <div className="max-w-7xl mx-auto">
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6">
          <h1 className="text-xl font-semibold text-amber-900">Authenticated Access Error</h1>
          <p className="mt-2 text-sm text-amber-800">Please sign in with a teacher account to view assigned classes.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="rounded-lg border border-gray-200 bg-white p-6">
        <h1 className="text-2xl font-bold text-gray-900">My Classes</h1>
        <p className="mt-2 text-sm text-gray-600">
          Review class assignments, compatibility coverage, and timetable activity for your teaching scope.
        </p>
      </header>

      {loading ? <LoadingSkeleton /> : null}

      {!loading && error ? (
        <div className={`rounded-lg border p-6 ${error.profileMissing ? "border-amber-200 bg-amber-50" : "border-red-200 bg-red-50"}`} role="alert">
          <h2 className={`font-semibold ${error.profileMissing ? "text-amber-900" : "text-red-900"}`}>{error.title}</h2>
          <p className={`mt-2 text-sm ${error.profileMissing ? "text-amber-800" : "text-red-800"}`}>{error.detail}</p>
          <button
            type="button"
            onClick={() => void loadClasses()}
            className="mt-4 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            Retry
          </button>
        </div>
      ) : null}

      {!loading && !error && data ? (
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">Total Classes</p>
            <p className="mt-2 text-2xl font-semibold text-gray-900">{data.summary.total_classes}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">Homeroom</p>
            <p className="mt-2 text-2xl font-semibold text-gray-900">{data.summary.homeroom_classes}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">Subject Classes</p>
            <p className="mt-2 text-2xl font-semibold text-gray-900">{data.summary.subject_classes}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">Canonical</p>
            <p className="mt-2 text-2xl font-semibold text-gray-900">{data.summary.canonical_classes}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">Legacy Compatibility</p>
            <p className="mt-2 text-2xl font-semibold text-gray-900">{data.summary.legacy_classes}</p>
          </div>
        </section>
      ) : null}

      {!loading && !error && data && classes.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
          <h2 className="text-lg font-semibold text-gray-900">No Assigned Classes</h2>
          <p className="mt-2 text-sm text-gray-600">No current class assignment is available for the selected date.</p>
        </div>
      ) : null}

      {!loading && !error && classes.length > 0 ? (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {classes.map((item) => (
            <article key={item.class_id} className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{item.code || `${item.grade_level} ${item.section}`}</h3>
                  <p className="text-sm text-gray-600">{item.grade_level} • Section {item.section}</p>
                </div>
                <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${sourceBadgeClass(item.assignment_source)}`}>
                  {item.assignment_source === "canonical" ? "Canonical" : "Legacy compatibility"}
                </span>
              </div>

              <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-gray-700">
                <div>
                  <dt className="font-medium text-gray-500">Campus</dt>
                  <dd>{item.campus || "—"}</dd>
                </div>
                <div>
                  <dt className="font-medium text-gray-500">Academic Year</dt>
                  <dd>{item.academic_year}</dd>
                </div>
                <div>
                  <dt className="font-medium text-gray-500">Students</dt>
                  <dd>{item.student_count}</dd>
                </div>
                <div>
                  <dt className="font-medium text-gray-500">Weekly Periods</dt>
                  <dd>{item.schedule.weekly_periods}</dd>
                </div>
              </dl>

              <div className="mt-4 space-y-2">
                {item.assignments.map((assignment, index) => (
                  <div key={`${assignment.assignment_type}-${assignment.subject_id || "none"}-${index}`} className="rounded-md border border-gray-100 bg-gray-50 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${assignmentBadgeClass(assignment.assignment_type)}`}>
                        {assignment.assignment_type === "homeroom" ? "Homeroom" : "Subject Teacher"}
                      </span>
                      <span className="text-xs text-gray-500">{dateRange(assignment.start_date, assignment.end_date)}</span>
                    </div>
                    {assignment.assignment_type === "subject_teacher" ? (
                      <p className="mt-2 text-sm text-gray-700">{assignment.subject_name || assignment.subject_code || "Subject"}</p>
                    ) : null}
                  </div>
                ))}
              </div>

              {item.assignment_source === "legacy" ? (
                <p className="mt-4 text-xs text-amber-700">
                  Legacy compatibility data is temporary until canonical assignments are fully available.
                </p>
              ) : null}
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
