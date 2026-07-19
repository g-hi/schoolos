"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  initializeWeeklyReport,
  listWeeklyReportStudents,
  listWeeklyReports,
  type InitializeWeeklyReportPayload,
  type StaffEvidenceInput,
  type WeeklyReportListItem,
  type WeeklyReportStudentOption,
  StaffApiError,
} from "@/lib/weekly-reports-api";
import { ReportEmptyState, ReportErrorState, ReportPageSkeleton, ReportStatusBadge } from "@/components/reports/report-page-states";

interface State {
  students: WeeklyReportStudentOption[];
  reports: WeeklyReportListItem[];
  loading: boolean;
  error: string | null;
  statusCode: number | null;
}

const INITIAL_EVIDENCE: StaffEvidenceInput = {
  weekly_teacher_summary: "",
  strengths_observed: "",
  achievements: "",
  areas_needing_support: "",
  suggested_parent_support: "",
  additional_factual_note: "",
};

export default function TeacherReportsPage() {
  const router = useRouter();
  const [state, setState] = useState<State>({
    students: [],
    reports: [],
    loading: true,
    error: null,
    statusCode: null,
  });
  const [selectedStudentId, setSelectedStudentId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [weekStart, setWeekStart] = useState("");
  const [initializing, setInitializing] = useState(false);
  const [evidence, setEvidence] = useState<StaffEvidenceInput>(INITIAL_EVIDENCE);

  async function load() {
    setState((prev) => ({ ...prev, loading: true, error: null, statusCode: null }));
    try {
      const [students, reports] = await Promise.all([
        listWeeklyReportStudents(),
        listWeeklyReports({ studentId: selectedStudentId || undefined, statusFilter: statusFilter || undefined }),
      ]);
      setState({ students, reports, loading: false, error: null, statusCode: null });
      if (!selectedStudentId && students.length > 0) {
        setSelectedStudentId(students[0].student_id);
      }
    } catch (error) {
      if (error instanceof StaffApiError) {
        setState({ students: [], reports: [], loading: false, error: error.message, statusCode: error.status });
        return;
      }
      setState({ students: [], reports: [], loading: false, error: "Unable to load weekly reports.", statusCode: null });
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const selectedStudent = useMemo(
    () => state.students.find((student) => student.student_id === selectedStudentId) ?? null,
    [state.students, selectedStudentId],
  );

  async function handleInitialize() {
    if (!selectedStudentId || !weekStart || initializing) return;
    setInitializing(true);
    try {
      const payload: InitializeWeeklyReportPayload = {
        student_id: selectedStudentId,
        week_start: weekStart,
        staff_evidence: evidence,
      };
      const result = await initializeWeeklyReport(payload);
      router.push(`/teacher/reports/${result.report_id}`);
    } catch (error) {
      if (error instanceof StaffApiError) {
        setState((prev) => ({ ...prev, error: error.message, statusCode: error.status }));
      } else {
        setState((prev) => ({ ...prev, error: "Unable to initialize the report.", statusCode: null }));
      }
    } finally {
      setInitializing(false);
    }
  }

  if (state.loading) {
    return <ReportPageSkeleton title="Loading weekly reports" />;
  }

  if (state.statusCode === 401) {
    return <ReportErrorState title="Staff authentication required" description="Add a valid staff JWT to continue using weekly reports." />;
  }

  if (state.statusCode === 403) {
    return <ReportErrorState title="Permission denied" description="This account cannot access the weekly reports workspace." />;
  }

  if (state.statusCode === 404) {
    return <ReportEmptyState title="No authorized students found" description="This staff account does not currently have any linked students for weekly report authoring." />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-indigo-600">Teacher authoring</p>
            <h1 className="mt-2 text-2xl font-semibold text-gray-900">Weekly student reports</h1>
            <p className="mt-2 text-sm text-gray-600">Initialize one report per student and week, capture structured evidence, and move drafts into leadership review.</p>
          </div>
          <div className="rounded-2xl bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
            <p className="font-medium">Unavailable-data notices are preserved</p>
            <p className="mt-1">Manual editing remains available even when AI is not used.</p>
          </div>
        </div>
      </header>

      <section className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <article className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Initialize report</h2>
          <div className="mt-4 space-y-4">
            <div>
              <label htmlFor="student-select" className="mb-1 block text-sm font-medium text-gray-700">Student</label>
              <select
                id="student-select"
                value={selectedStudentId}
                onChange={(event) => setSelectedStudentId(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select a student</option>
                {state.students.map((student) => (
                  <option key={student.student_id} value={student.student_id}>
                    {student.student_display_name} · {student.class_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="week-start" className="mb-1 block text-sm font-medium text-gray-700">Reporting week</label>
              <input
                id="week-start"
                type="date"
                value={weekStart}
                onChange={(event) => setWeekStart(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label htmlFor="weekly-teacher-summary" className="mb-1 block text-sm font-medium text-gray-700">Weekly teacher summary</label>
              <textarea
                id="weekly-teacher-summary"
                value={evidence.weekly_teacher_summary || ""}
                onChange={(event) => setEvidence((prev) => ({ ...prev, weekly_teacher_summary: event.target.value }))}
                rows={3}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label htmlFor="strengths-observed" className="mb-1 block text-sm font-medium text-gray-700">Strengths observed</label>
              <textarea
                id="strengths-observed"
                value={evidence.strengths_observed || ""}
                onChange={(event) => setEvidence((prev) => ({ ...prev, strengths_observed: event.target.value }))}
                rows={2}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <button
              type="button"
              onClick={() => void handleInitialize()}
              disabled={!selectedStudentId || !weekStart || initializing}
              className="inline-flex w-full items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-indigo-300"
            >
              {initializing ? "Initializing..." : "Initialize report"}
            </button>

            {selectedStudent ? (
              <p className="text-xs text-gray-500">Selected: {selectedStudent.student_display_name} in {selectedStudent.class_name}</p>
            ) : null}
          </div>
        </article>

        <article className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Authorized reports</h2>
              <p className="mt-1 text-sm text-gray-600">Drafts, review states, and publication state are shown here for your authorized students only.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <select
                aria-label="Filter reports by student"
                value={selectedStudentId}
                onChange={(event) => setSelectedStudentId(event.target.value)}
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">All students</option>
                {state.students.map((student) => (
                  <option key={student.student_id} value={student.student_id}>
                    {student.student_display_name}
                  </option>
                ))}
              </select>
              <select
                aria-label="Filter reports by status"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">All statuses</option>
                <option value="draft">Draft</option>
                <option value="pending_review">Pending review</option>
                <option value="changes_requested">Changes requested</option>
                <option value="approved">Approved</option>
                <option value="published">Published</option>
              </select>
              <button
                type="button"
                onClick={() => void load()}
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700"
              >
                Refresh
              </button>
            </div>
          </div>

          {state.error ? (
            <div className="mt-4">
              <ReportErrorState title="Weekly reports issue" description={state.error} />
            </div>
          ) : null}

          {state.reports.length === 0 ? (
            <div className="mt-6">
              <ReportEmptyState title="No reports yet" description="Initialize a weekly report to begin drafting and review." />
            </div>
          ) : (
            <div className="mt-6 grid gap-4 md:grid-cols-2">
              {state.reports.map((report) => (
                <Link
                  key={report.report_id}
                  href={`/teacher/reports/${report.report_id}`}
                  className="rounded-2xl border border-gray-200 p-4 transition hover:border-indigo-300 hover:bg-indigo-50/40"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-base font-semibold text-gray-900">{report.student_display_name}</h3>
                      <p className="mt-1 text-sm text-gray-600">{report.class_name}</p>
                    </div>
                    <ReportStatusBadge status={report.status} />
                  </div>
                  <dl className="mt-4 space-y-1 text-sm text-gray-600">
                    <div className="flex justify-between gap-4">
                      <dt>Week</dt>
                      <dd>{report.week_start}</dd>
                    </div>
                    <div className="flex justify-between gap-4">
                      <dt>Version</dt>
                      <dd>{report.current_version_number}</dd>
                    </div>
                    <div className="flex justify-between gap-4">
                      <dt>Row version</dt>
                      <dd>{report.row_version}</dd>
                    </div>
                  </dl>
                </Link>
              ))}
            </div>
          )}
        </article>
      </section>
    </div>
  );
}
