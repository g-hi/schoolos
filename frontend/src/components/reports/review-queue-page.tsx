"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listWeeklyReports, type WeeklyReportListItem, StaffApiError } from "@/lib/weekly-reports-api";
import { ReportEmptyState, ReportErrorState, ReportPageSkeleton, ReportStatusBadge } from "@/components/reports/report-page-states";

export default function ReviewQueuePage() {
  const [reports, setReports] = useState<WeeklyReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setStatusCode(null);
    try {
      const data = await listWeeklyReports({ statusFilter: "pending_review" });
      setReports(data);
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to load the review queue.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (loading) {
    return <ReportPageSkeleton title="Loading review queue" />;
  }

  if (statusCode === 401) {
    return <ReportErrorState title="Leadership authentication required" description="Add a valid leadership JWT to review weekly reports." />;
  }

  if (statusCode === 403) {
    return <ReportErrorState title="Permission denied" description="This account cannot open the weekly report review queue." />;
  }

  if (error) {
    return <ReportErrorState title="Review queue unavailable" description={error} actionLabel="Retry" onAction={() => void load()} />;
  }

  if (reports.length === 0) {
    return <ReportEmptyState title="Review queue is clear" description="No weekly reports are currently awaiting leadership review." />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-[0.3em] text-indigo-600">Leadership review</p>
        <h1 className="mt-2 text-2xl font-semibold text-gray-900">Weekly reports review queue</h1>
        <p className="mt-2 text-sm text-gray-600">Open a report to inspect evidence availability, review history, and approve or publish safely.</p>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {reports.map((report) => (
          <Link
            key={report.report_id}
            href={`/reports/${report.report_id}/review`}
            className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-50/40"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">{report.student_display_name}</h2>
                <p className="mt-1 text-sm text-gray-600">{report.class_name}</p>
              </div>
              <ReportStatusBadge status={report.status} />
            </div>
            <dl className="mt-4 space-y-1 text-sm text-gray-600">
              <div className="flex justify-between gap-3">
                <dt>Week</dt>
                <dd>{report.week_start}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Version</dt>
                <dd>{report.current_version_number}</dd>
              </div>
            </dl>
          </Link>
        ))}
      </section>
    </div>
  );
}
