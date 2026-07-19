"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import { ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";
import { getParentPublishedReport, ParentApiError, type ParentPublishedReportDetail } from "@/lib/parent-api";

export default function ParentReportDetailPage({ reportId }: { reportId: string }) {
  const auth = useParentAuth();
  const [report, setReport] = useState<ParentPublishedReportDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);

  async function load(token: string) {
    setLoading(true);
    setError(null);
    setStatusCode(null);
    try {
      const detail = await getParentPublishedReport(token, reportId);
      setReport(detail);
    } catch (apiError) {
      if (apiError instanceof ParentApiError) {
        setError(apiError.message);
        setStatusCode(apiError.status);
      } else {
        setError("Unable to load the published report.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated || !auth.token) return;
    void load(auth.token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, auth.token, reportId]);

  if (auth.isHydrating || loading) {
    return <ParentPageSkeleton title="Loading published report" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (statusCode === 403) {
    return <ParentErrorState title="Access denied" description="This account cannot open the requested report." />;
  }

  if (statusCode === 404) {
    return <ParentErrorState title="Report not found" description="Only published reports linked to your family are available here." />;
  }

  if (!report) {
    return <ParentErrorState title="Published report unavailable" description={error || "Please retry."} actionLabel="Retry" onAction={() => auth.token ? void load(auth.token) : undefined} />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{report.title}</h1>
            <p className="mt-1 text-sm text-gray-600">{report.student_display_name} · {report.class_name}</p>
            <p className="mt-1 text-sm text-gray-500">{report.week_start} to {report.week_end}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/parent/reports" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700">Back to reports</Link>
            <Link href={`/parent/student/${report.student_id}`} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700">Back to child overview</Link>
          </div>
        </div>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="space-y-4">
          {report.sections.map((section, index) => (
            <article key={`${section.section_type}-${index}`} className="rounded-xl border border-gray-200 p-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{section.section_type.replaceAll("_", " ")}</h2>
              <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{section.content}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
