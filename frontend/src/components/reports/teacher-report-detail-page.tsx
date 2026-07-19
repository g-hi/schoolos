"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  editWeeklyReportDraft,
  generateWeeklyReportDraft,
  getWeeklyReport,
  getWeeklyReportReviewEvents,
  getWeeklyReportVersions,
  submitWeeklyReportForReview,
  type EditWeeklyReportPayload,
  type WeeklyReportDetailResponse,
  type WeeklyReportReviewEventResponse,
  type WeeklyReportVersionResponse,
  StaffApiError,
} from "@/lib/weekly-reports-api";
import { ReportErrorState, ReportPageSkeleton, ReportStatusBadge } from "@/components/reports/report-page-states";

const EDITABLE_SECTION_TYPES = [
  "weekly_overview",
  "teacher_comment",
  "achievements_and_strengths",
  "areas_needing_support",
  "suggested_parent_support",
] as const;

interface Props {
  reportId: string;
}

export default function TeacherReportDetailPage({ reportId }: Props) {
  const [report, setReport] = useState<WeeklyReportDetailResponse | null>(null);
  const [versions, setVersions] = useState<WeeklyReportVersionResponse[]>([]);
  const [reviewEvents, setReviewEvents] = useState<WeeklyReportReviewEventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [sections, setSections] = useState<Record<string, string>>({});
  const [reviewComment, setReviewComment] = useState("");
  const [pendingAction, setPendingAction] = useState<"save" | "generate-ai" | "generate-manual" | "submit" | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setStatusCode(null);
    try {
      const [detail, versionRows, reviewRows] = await Promise.all([
        getWeeklyReport(reportId),
        getWeeklyReportVersions(reportId),
        getWeeklyReportReviewEvents(reportId),
      ]);
      setReport(detail);
      setVersions(versionRows);
      setReviewEvents(reviewRows);
      setTitle(detail.current_content.title || "");

      const nextSections: Record<string, string> = {};
      for (const section of detail.current_content.sections || []) {
        nextSections[section.section_type] = section.content;
      }
      setSections(nextSections);
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to load the report.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  async function handleSave() {
    if (!report || pendingAction) return;
    setPendingAction("save");
    try {
      const payload: EditWeeklyReportPayload = {
        expected_row_version: report.row_version,
        title,
        sections: EDITABLE_SECTION_TYPES.map((sectionType) => ({
          section_type: sectionType,
          content: sections[sectionType] || "",
        })).filter((section) => section.content.trim().length > 0),
      };
      await editWeeklyReportDraft(reportId, payload);
      await load();
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to save the draft.");
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function handleGenerate(useAi: boolean) {
    if (!report || pendingAction) return;
    setPendingAction(useAi ? "generate-ai" : "generate-manual");
    try {
      await generateWeeklyReportDraft(reportId, {
        expected_row_version: report.row_version,
        use_ai: useAi,
      });
      await load();
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to generate the draft.");
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function handleSubmitForReview() {
    if (!report || pendingAction) return;
    setPendingAction("submit");
    try {
      await submitWeeklyReportForReview(reportId, {
        expected_row_version: report.row_version,
        comment: reviewComment || undefined,
      });
      await load();
    } catch (apiError) {
      if (apiError instanceof StaffApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to submit the report for review.");
      }
    } finally {
      setPendingAction(null);
    }
  }

  if (loading) {
    return <ReportPageSkeleton title="Loading report workspace" />;
  }

  if (statusCode === 401) {
    return <ReportErrorState title="Staff authentication required" description="Add a valid staff JWT to continue editing this report." />;
  }

  if (statusCode === 403) {
    return <ReportErrorState title="Permission denied" description="This report is outside your current permissions." />;
  }

  if (statusCode === 404) {
    return <ReportErrorState title="Report not found" description="The requested report could not be located for this staff account." />;
  }

  if (!report) {
    return <ReportErrorState title="Report unavailable" description={error || "Please retry."} actionLabel="Retry" onAction={() => void load()} />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-indigo-600">Teacher authoring</p>
            <h1 className="mt-2 text-2xl font-semibold text-gray-900">{report.student_display_name}</h1>
            <p className="mt-1 text-sm text-gray-600">{report.class_name} · {report.week_start} to {report.week_end}</p>
          </div>
          <div className="flex items-center gap-3">
            <ReportStatusBadge status={report.status} />
            <Link href="/teacher/reports" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700">Back to reports</Link>
          </div>
        </div>
      </header>

      {error ? <ReportErrorState title="Report action issue" description={error} /> : null}

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <article className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="space-y-4">
            <div>
              <label htmlFor="report-title" className="mb-1 block text-sm font-medium text-gray-700">Title</label>
              <input
                id="report-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            {EDITABLE_SECTION_TYPES.map((sectionType) => (
              <div key={sectionType}>
                <label htmlFor={sectionType} className="mb-1 block text-sm font-medium capitalize text-gray-700">
                  {sectionType.replaceAll("_", " ")}
                </label>
                <textarea
                  id={sectionType}
                  value={sections[sectionType] || ""}
                  onChange={(event) => setSections((prev) => ({ ...prev, [sectionType]: event.target.value }))}
                  rows={4}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            ))}

            <div className="rounded-xl border border-sky-200 bg-sky-50 p-4">
              <h2 className="text-sm font-semibold text-sky-800">Unavailable-data notices</h2>
              <ul className="mt-2 space-y-2 text-sm text-sky-700">
                {(report.current_evidence_snapshot.evidence_items || [])
                  .filter((item) => item.available === false)
                  .map((item) => (
                    <li key={item.evidence_id}>{item.unavailable_reason || `${item.source_type} is unavailable.`}</li>
                  ))}
              </ul>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={pendingAction !== null}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-indigo-300"
              >
                {pendingAction === "save" ? "Saving..." : "Save draft"}
              </button>
              <button
                type="button"
                onClick={() => void handleGenerate(true)}
                disabled={pendingAction !== null}
                className="rounded-lg border border-indigo-300 px-4 py-2 text-sm font-medium text-indigo-700 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
              >
                {pendingAction === "generate-ai" ? "Generating..." : "Generate AI-assisted draft"}
              </button>
              <button
                type="button"
                onClick={() => void handleGenerate(false)}
                disabled={pendingAction !== null}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:text-gray-400"
              >
                {pendingAction === "generate-manual" ? "Generating..." : "Refresh deterministic draft"}
              </button>
            </div>

            <div>
              <label htmlFor="submit-comment" className="mb-1 block text-sm font-medium text-gray-700">Review note</label>
              <textarea
                id="submit-comment"
                value={reviewComment}
                onChange={(event) => setReviewComment(event.target.value)}
                rows={2}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <button
              type="button"
              onClick={() => void handleSubmitForReview()}
              disabled={pendingAction !== null}
              className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-amber-300"
            >
              {pendingAction === "submit" ? "Submitting..." : "Submit for review"}
            </button>
          </div>
        </article>

        <aside className="space-y-6">
          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Validation</h2>
            {report.current_validation_errors.length === 0 ? (
              <p className="mt-2 text-sm text-gray-600">No validation warnings for the current version.</p>
            ) : (
              <ul className="mt-3 space-y-2 text-sm text-red-700">
                {report.current_validation_errors.map((errorItem) => (
                  <li key={`${errorItem.code}-${errorItem.message}`}>{errorItem.message}</li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Version history</h2>
            <ul className="mt-3 space-y-3 text-sm text-gray-600">
              {versions.map((version) => (
                <li key={version.version_id} className="rounded-xl border border-gray-200 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-gray-900">Version {version.version_number}</span>
                    <span>{version.source_type}</span>
                  </div>
                  <p className="mt-1">Validation: {version.validation_status}</p>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Review history</h2>
            <ul className="mt-3 space-y-3 text-sm text-gray-600">
              {reviewEvents.map((event) => (
                <li key={event.event_id} className="rounded-xl border border-gray-200 p-3">
                  <p className="font-medium text-gray-900">{event.event_type.replaceAll("_", " ")}</p>
                  <p className="mt-1">{event.previous_status || "new"} to {event.new_status || "unknown"}</p>
                  {event.comment ? <p className="mt-1">{event.comment}</p> : null}
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </section>
    </div>
  );
}
