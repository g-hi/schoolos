"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import { ParentEmptyState, ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";
import {
  getParentPublishedReportList,
  getParentStudents,
  ParentApiError,
  type ParentPublishedReportListItem,
  type ParentStudentsResponse,
} from "@/lib/parent-api";

interface State {
  students: ParentStudentsResponse["students"];
  reports: ParentPublishedReportListItem[];
  loading: boolean;
  error: string | null;
  statusCode: number | null;
}

export default function ParentReportsPage() {
  const auth = useParentAuth();
  const [state, setState] = useState<State>({
    students: [],
    reports: [],
    loading: false,
    error: null,
    statusCode: null,
  });
  const [studentFilter, setStudentFilter] = useState("");
  const [periodFilter, setPeriodFilter] = useState("");

  async function load(token: string) {
    setState((prev) => ({ ...prev, loading: true, error: null, statusCode: null }));
    try {
      const [studentsResponse, reports] = await Promise.all([
        getParentStudents(token),
        getParentPublishedReportList(token, { studentId: studentFilter || undefined }),
      ]);
      setState({
        students: studentsResponse.students,
        reports,
        loading: false,
        error: null,
        statusCode: null,
      });
    } catch (apiError) {
      if (apiError instanceof ParentApiError) {
        setState({ students: [], reports: [], loading: false, error: apiError.message, statusCode: apiError.status });
        return;
      }
      setState({ students: [], reports: [], loading: false, error: "Unable to load weekly reports.", statusCode: null });
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated || !auth.token) return;
    void load(auth.token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, auth.token, studentFilter]);

  const periodOptions = useMemo(() => Array.from(new Set(state.reports.map((report) => report.week_start))).sort().reverse(), [state.reports]);
  const visibleReports = useMemo(
    () => state.reports.filter((report) => (periodFilter ? report.week_start === periodFilter : true)),
    [state.reports, periodFilter],
  );

  if (auth.isHydrating) {
    return <ParentPageSkeleton title="Loading weekly reports" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (state.loading) {
    return <ParentPageSkeleton title="Loading weekly reports" />;
  }

  if (state.statusCode === 403) {
    return <ParentErrorState title="Access denied" description="This account cannot access weekly student reports." />;
  }

  if (state.error && !state.reports.length) {
    return <ParentErrorState title="Unable to load weekly reports" description={state.error} actionLabel="Retry" onAction={() => auth.token ? void load(auth.token) : undefined} />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Weekly reports</h1>
            <p className="mt-1 text-sm text-gray-600">Published weekly reports only. Drafts, evidence, and review history are never shown in the parent portal.</p>
          </div>
          <Link href="/parent" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700">Back to Family Hub</Link>
        </div>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-lg font-semibold text-gray-900">Filters</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="parent-report-student-filter" className="mb-1 block text-sm font-medium text-gray-700">Child</label>
            <select
              id="parent-report-student-filter"
              value={studentFilter}
              onChange={(event) => setStudentFilter(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">All linked children</option>
              {state.students.map((student) => (
                <option key={student.student_id} value={student.student_id}>{student.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="parent-report-period-filter" className="mb-1 block text-sm font-medium text-gray-700">Reporting period</label>
            <select
              id="parent-report-period-filter"
              value={periodFilter}
              onChange={(event) => setPeriodFilter(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">All reporting weeks</option>
              {periodOptions.map((period) => (
                <option key={period} value={period}>{period}</option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {visibleReports.length === 0 ? (
        <ParentEmptyState title="No published reports yet" description="Published weekly reports will appear here once leadership completes the review and publication process." />
      ) : (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleReports.map((report) => (
            <Link key={report.report_id} href={`/parent/reports/${report.report_id}`} className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-50/30">
              <h2 className="text-lg font-semibold text-gray-900">{report.student_display_name}</h2>
              <p className="mt-1 text-sm text-gray-600">{report.class_name}</p>
              <p className="mt-4 text-sm font-medium text-gray-900">{report.title}</p>
              <dl className="mt-3 space-y-1 text-sm text-gray-600">
                <div className="flex justify-between gap-3">
                  <dt>Week</dt>
                  <dd>{report.week_start}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt>Published</dt>
                  <dd>{new Date(report.published_at).toLocaleDateString()}</dd>
                </div>
              </dl>
            </Link>
          ))}
        </section>
      )}
    </div>
  );
}
