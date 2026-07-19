"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  approveWeeklyReport,
  getWeeklyReport,
  getWeeklyReportReviewEvents,
  publishWeeklyReport,
  requestWeeklyReportChanges,
  type WeeklyReportDetailResponse,
  type WeeklyReportReviewEventResponse,
  StaffApiError,
} from "@/lib/weekly-reports-api";
import { ReportErrorState, ReportPageSkeleton, ReportStatusBadge } from "@/components/reports/report-page-states";

export default function ReviewDetailPage({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<WeeklyReportDetailResponse | null>(null);
  const [events, setEvents] = useState<WeeklyReportReviewEventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [pendingAction, setPendingAction] = useState<"changes" | "approve" | "publish" | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setStatusCode(null);
    try {
      const [detail, reviewEvents] = await Promise.all([
        getWeeklyReport(reportId),
        getWeeklyReportReviewEvents(reportId),
      ]);
      setReport(detail);
      setEvents(reviewEvents);
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to load the review detail.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  async function handleRequestChanges() {
    if (!report || pendingAction) return;
    setPendingAction("changes");
    try {
      await requestWeeklyReportChanges(reportId, {
        expected_row_version: report.row_version,
        comment,
      });
      await load();
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to request changes.");
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function handleApprove() {
    if (!report || pendingAction) return;
    setPendingAction("approve");
    try {
      await approveWeeklyReport(reportId, {
        expected_row_version: report.row_version,
        comment,
      });
      await load();
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to approve the report.");
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function handlePublish() {
    if (!report || pendingAction) return;
    if (typeof window !== "undefined" && !window.confirm("Publish this weekly report to the parent portal?")) {
      return;
    }
    setPendingAction("publish");
    try {
      await publishWeeklyReport(reportId, {
        expected_row_version: report.row_version,
        comment,
      });
      await load();
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to publish the report.");
      }
    } finally {
      setPendingAction(null);
    }
  }

  if (loading) {
    return <ReportPageSkeleton title="Loading review detail" />;
  }

  if (statusCode === 401) {
    return <ReportErrorState title="Leadership authentication required" description="Add a valid leadership JWT to review this report." />;
  }

  if (statusCode === 403) {
    return <ReportErrorState title="Permission denied" description="This report cannot be reviewed by the current account." />;
  }

  if (statusCode === 404) {
    return <ReportErrorState title="Report not found" description="The requested review record could not be located." />;
  }

  if (!report) {
    return <ReportErrorState title="Review detail unavailable" description={error || "Please retry."} actionLabel="Retry" onAction={() => void load()} />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-indigo-600">Leadership review</p>
            <h1 className="mt-2 text-2xl font-semibold text-gray-900">{report.student_display_name}</h1>
            <p className="mt-1 text-sm text-gray-600">{report.class_name} · {report.week_start} to {report.week_end}</p>
          </div>
          <div className="flex items-center gap-3">
            <ReportStatusBadge status={report.status} />
            <Link href="/reports/review" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700">Back to queue</Link>
          </div>
        </div>
      </header>

      {error ? <ReportErrorState title="Review action issue" description={error} /> : null}

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <article className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Current version</h2>
          <div className="mt-4 space-y-4">
            {(report.current_content.sections || []).map((section) => (
              <section key={`${section.section_type}-${section.content}`} className="rounded-xl border border-gray-200 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{section.section_type.replaceAll("_", " ")}</h3>
                <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{section.content}</p>
              </section>
            ))}
          </div>
        </article>

        <aside className="space-y-6">
          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Evidence availability</h2>
            <ul className="mt-3 space-y-2 text-sm text-gray-600">
              {(report.current_evidence_snapshot.evidence_items || []).map((item) => (
                <li key={item.evidence_id}>
                  <span className="font-medium text-gray-900">{item.source_type}</span>
                  {item.available ? " available" : ` unavailable: ${item.unavailable_reason || "No additional detail."}`}
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Review history</h2>
            <ul className="mt-3 space-y-3 text-sm text-gray-600">
              {events.map((event) => (
                <li key={event.event_id} className="rounded-xl border border-gray-200 p-3">
                  <p className="font-medium text-gray-900">{event.event_type.replaceAll("_", " ")}</p>
                  <p className="mt-1">{event.previous_status || "new"} to {event.new_status || "unknown"}</p>
                  {event.comment ? <p className="mt-1">{event.comment}</p> : null}
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <label htmlFor="review-comment" className="mb-2 block text-sm font-medium text-gray-700">Review comment</label>
            <textarea
              id="review-comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
            <div className="mt-4 grid gap-3">
              <button
                type="button"
                onClick={() => void handleRequestChanges()}
                disabled={pendingAction !== null}
                className="rounded-lg border border-orange-300 px-4 py-2 text-sm font-medium text-orange-700 disabled:cursor-not-allowed disabled:text-orange-300"
              >
                {pendingAction === "changes" ? "Requesting..." : "Request changes"}
              </button>
              <button
                type="button"
                onClick={() => void handleApprove()}
                disabled={pendingAction !== null}
                className="rounded-lg border border-blue-300 px-4 py-2 text-sm font-medium text-blue-700 disabled:cursor-not-allowed disabled:text-blue-300"
              >
                {pendingAction === "approve" ? "Approving..." : "Approve"}
              </button>
              <button
                type="button"
                onClick={() => void handlePublish()}
                disabled={pendingAction !== null}
                className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-green-300"
              >
                {pendingAction === "publish" ? "Publishing..." : "Publish"}
              </button>
            </div>
          </section>
        </aside>
      </section>
    </div>
  );
}
