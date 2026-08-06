"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import RoleGuard from "@/components/auth/role-guard";
import {
  approveCalendarCandidate,
  approveManualEvent,
  approveNotificationPlan,
  archiveManualEvent,
  cancelCalendarPdfBatch,
  cancelManualEvent,
  cancelNotificationPlan,
  commitCalendarPdfBatch,
  createManualEvent,
  editCalendarCandidate,
  extractCalendarPdfCandidates,
  getCalendarPdfDiagnostics,
  getCalendarPdfImport,
  getCalendarPdfPages,
  getEventImpact,
  getManualEvent,
  getNotificationPlan,
  listCalendarPdfCandidates,
  listCalendarPdfImports,
  listEventVersions,
  listManualEvents,
  listNotificationPlans,
  patchManualEvent,
  publishManualEvent,
  rejectCalendarCandidate,
  rescheduleManualEvent,
  restoreManualEvent,
  submitManualEvent,
  TimetableCalendarApiError,
  type CalendarEventCandidate,
  type CalendarNotificationPlanDetail,
  type CalendarNotificationPlanSummary,
  type CalendarPdfDiagnostics,
  type CalendarPdfImportDetail,
  type CalendarPdfImportItem,
  type EventImpactResponse,
  type EventVersion,
  type ManualEvent,
  type PagedResponse,
} from "@/lib/timetable-calendar-api";
import { toFriendlyError } from "@/app/leadership/calendar/calendar-utils";
import OverviewPanel from "@/app/leadership/calendar/overview-panel";
import EventListPanel from "@/app/leadership/calendar/event-list-panel";
import ManualEventForm from "@/app/leadership/calendar/manual-event-form";
import PdfIntakePanel from "@/app/leadership/calendar/pdf-intake-panel";
import NotificationPlansPanel from "@/app/leadership/calendar/notification-plans-panel";
import EventDetailPanel from "@/app/leadership/calendar/event-detail-panel";

type TabKey = "overview" | "events" | "add" | "imports" | "candidates" | "notifications" | "history";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "events", label: "Calendar Events" },
  { key: "add", label: "Add Event" },
  { key: "imports", label: "PDF Imports" },
  { key: "candidates", label: "Review Candidates" },
  { key: "notifications", label: "Notification Plans" },
  { key: "history", label: "Change History" },
];

function handleApiError(error: unknown): string {
  if (error instanceof TimetableCalendarApiError) {
    return error.message;
  }
  return toFriendlyError(error);
}

export default function LeadershipCalendarPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ManualEvent[]>([]);
  const [imports, setImports] = useState<CalendarPdfImportItem[]>([]);
  const [plans, setPlans] = useState<CalendarNotificationPlanSummary[]>([]);

  const [selectedEvent, setSelectedEvent] = useState<ManualEvent | null>(null);
  const [eventVersions, setEventVersions] = useState<EventVersion[]>([]);
  const [eventImpact, setEventImpact] = useState<EventImpactResponse | null>(null);

  const [selectedImport, setSelectedImport] = useState<CalendarPdfImportDetail | null>(null);
  const [pages, setPages] = useState<PagedResponse<{ page_number: number; text_excerpt: string | null; extracted_char_count: number }> | null>(null);
  const [candidates, setCandidates] = useState<PagedResponse<CalendarEventCandidate> | null>(null);
  const [flatCandidates, setFlatCandidates] = useState<CalendarEventCandidate[]>([]);
  const [diagnostics, setDiagnostics] = useState<CalendarPdfDiagnostics | null>(null);
  const [validation, setValidation] = useState<{ blocker_count: number; warning_count: number; approved_candidates: number; status: string; batch_id: string; document_id: string } | null>(null);
  const [uploadState, setUploadState] = useState("idle");

  const [selectedPlan, setSelectedPlan] = useState<CalendarNotificationPlanDetail | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refreshWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [eventRows, importRows, planRows] = await Promise.all([
        listManualEvents(),
        listCalendarPdfImports(),
        listNotificationPlans(),
      ]);
      setEvents(eventRows);
      setImports(importRows);
      setPlans(planRows);
    } catch (loadError) {
      setError(handleApiError(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshWorkspace();
  }, [refreshWorkspace]);

  const handleSelectEvent = useCallback(async (eventId: string) => {
    try {
      const [eventDetail, versions, impact] = await Promise.all([
        getManualEvent(eventId),
        listEventVersions(eventId),
        getEventImpact(eventId),
      ]);
      setSelectedEvent(eventDetail);
      setEventVersions(versions);
      setEventImpact(impact);
      setActiveTab("history");
    } catch (selectError) {
      setError(handleApiError(selectError));
    }
  }, []);

  const runEventAction = useCallback(
    async (item: ManualEvent, action: string) => {
      try {
        if (action === "edit") {
          const newName = window.prompt("Edit event name", item.event_name);
          if (newName && newName.trim() && newName.trim() !== item.event_name) {
            await patchManualEvent(item.id, { event_name: newName.trim(), reason: "manual_edit_from_workspace" });
          }
        } else if (["submit", "approve", "publish", "cancel", "restore", "archive"].includes(action)) {
          const reason = window.prompt(`Reason for ${action}`) || "";
          if (!reason.trim()) return;
          if (action === "submit") await submitManualEvent(item.id, { reason: reason.trim() });
          if (action === "approve") await approveManualEvent(item.id, { reason: reason.trim() });
          if (action === "publish") await publishManualEvent(item.id, { reason: reason.trim() });
          if (action === "cancel") await cancelManualEvent(item.id, { reason: reason.trim() });
          if (action === "restore") await restoreManualEvent(item.id, { reason: reason.trim() });
          if (action === "archive") await archiveManualEvent(item.id, { reason: reason.trim() });
        } else if (action === "reschedule") {
          const newStart = window.prompt("New start date (YYYY-MM-DD)", item.start_date) || "";
          const newEnd = window.prompt("New end date (YYYY-MM-DD)", item.end_date) || "";
          const reason = window.prompt("Reschedule reason") || "";
          if (!newStart || !newEnd || !reason.trim()) return;
          await rescheduleManualEvent(item.id, { new_start_date: newStart, new_end_date: newEnd, reason: reason.trim() });
        }
        await refreshWorkspace();
        if (selectedEvent?.id === item.id) {
          await handleSelectEvent(item.id);
        }
      } catch (actionError) {
        setError(handleApiError(actionError));
      }
    },
    [handleSelectEvent, refreshWorkspace, selectedEvent?.id],
  );

  const handleCreateManualEvent = useCallback(
    async (payload: Parameters<typeof createManualEvent>[0]) => {
      const created = await createManualEvent(payload);
      setToast("Draft created. Manual approval is still required before publication.");
      await refreshWorkspace();
      return created;
    },
    [refreshWorkspace],
  );

  const handleSelectImport = useCallback(async (documentId: string) => {
    try {
      const [detail, pageResponse, candidateResponse, diag] = await Promise.all([
        getCalendarPdfImport(documentId),
        getCalendarPdfPages(documentId, 1, 5),
        listCalendarPdfCandidates(documentId, 1, 10),
        getCalendarPdfDiagnostics(documentId),
      ]);
      setSelectedImport(detail);
      setPages(pageResponse);
      setCandidates(candidateResponse);
      setFlatCandidates(candidateResponse.items);
      setDiagnostics(diag);
      setValidation(null);
    } catch (selectError) {
      setError(handleApiError(selectError));
    }
  }, []);

  const handleUpload = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("Only .pdf files are accepted.");
        return;
      }
      setUploadState("uploading");
      try {
        const response = await import("@/lib/timetable-calendar-api").then((mod) => mod.uploadCalendarPdf(file));
        setUploadState(response.status || "review_ready");
        await refreshWorkspace();
        await handleSelectImport(response.document_id);
      } catch (uploadError) {
        setUploadState("failed");
        setError(handleApiError(uploadError));
      }
    },
    [handleSelectImport, refreshWorkspace],
  );

  const handleExtract = useCallback(async () => {
    if (!selectedImport) return;
    setUploadState("extracting");
    try {
      await extractCalendarPdfCandidates(selectedImport.document_id);
      await handleSelectImport(selectedImport.document_id);
      setUploadState("review_ready");
    } catch (extractError) {
      setError(handleApiError(extractError));
    }
  }, [handleSelectImport, selectedImport]);

  const handleValidate = useCallback(async () => {
    if (!selectedImport) return;
    try {
      const result = await import("@/lib/timetable-calendar-api").then((mod) => mod.validateCalendarPdfBatch(selectedImport.document_id, true));
      setValidation(result);
      await handleSelectImport(selectedImport.document_id);
    } catch (validateError) {
      setError(handleApiError(validateError));
    }
  }, [handleSelectImport, selectedImport]);

  const handleCommit = useCallback(async () => {
    if (!selectedImport) return;
    if (validation && validation.blocker_count > 0) {
      setError("Commit is disabled because blockers remain.");
      return;
    }
    const proceed = window.confirm("Commit approved candidates to operational calendar? This does not auto-approve external delivery.");
    if (!proceed) return;

    try {
      await commitCalendarPdfBatch(selectedImport.document_id, {
        default_scope: {
          scope_type: "public_information",
          public_information: true,
        },
      });
      setToast("Committed approved candidates. Review created notification plans before approval.");
      await refreshWorkspace();
      await handleSelectImport(selectedImport.document_id);
    } catch (commitError) {
      setError(handleApiError(commitError));
    }
  }, [handleSelectImport, refreshWorkspace, selectedImport, validation]);

  const handleCancelImport = useCallback(async (reason: string) => {
    if (!selectedImport) return;
    try {
      await cancelCalendarPdfBatch(selectedImport.document_id, { reason });
      await refreshWorkspace();
      await handleSelectImport(selectedImport.document_id);
    } catch (cancelError) {
      setError(handleApiError(cancelError));
    }
  }, [handleSelectImport, refreshWorkspace, selectedImport]);

  const handleEditCandidate = useCallback(async (candidateId: string, patch: { proposed_event_name?: string }) => {
    try {
      await editCalendarCandidate(candidateId, patch);
      if (selectedImport) {
        await handleSelectImport(selectedImport.document_id);
      }
    } catch (editError) {
      setError(handleApiError(editError));
    }
  }, [handleSelectImport, selectedImport]);

  const handleApproveCandidate = useCallback(async (candidateId: string) => {
    try {
      await approveCalendarCandidate(candidateId);
      if (selectedImport) {
        await handleSelectImport(selectedImport.document_id);
      }
    } catch (approveError) {
      setError(handleApiError(approveError));
    }
  }, [handleSelectImport, selectedImport]);

  const handleRejectCandidate = useCallback(async (candidateId: string, reason: string) => {
    try {
      await rejectCalendarCandidate(candidateId, { reason });
      if (selectedImport) {
        await handleSelectImport(selectedImport.document_id);
      }
    } catch (rejectError) {
      setError(handleApiError(rejectError));
    }
  }, [handleSelectImport, selectedImport]);

  const handleLoadPages = useCallback(async (page: number) => {
    if (!selectedImport) return;
    try {
      const response = await getCalendarPdfPages(selectedImport.document_id, page, pages?.page_size || 5);
      setPages(response);
    } catch (pageError) {
      setError(handleApiError(pageError));
    }
  }, [pages?.page_size, selectedImport]);

  const handleLoadCandidates = useCallback(async (page: number) => {
    if (!selectedImport) return;
    try {
      const response = await listCalendarPdfCandidates(selectedImport.document_id, page, candidates?.page_size || 10);
      setCandidates(response);
      setFlatCandidates(response.items);
    } catch (candidatePageError) {
      setError(handleApiError(candidatePageError));
    }
  }, [candidates?.page_size, selectedImport]);

  const handleSelectPlan = useCallback(async (planId: string) => {
    try {
      const detail = await getNotificationPlan(planId);
      setSelectedPlan(detail);
    } catch (planError) {
      setError(handleApiError(planError));
    }
  }, []);

  const handleApprovePlan = useCallback(async (planId: string, reason: string) => {
    try {
      await approveNotificationPlan(planId, { reason });
      await refreshWorkspace();
      await handleSelectPlan(planId);
    } catch (approveError) {
      setError(handleApiError(approveError));
    }
  }, [handleSelectPlan, refreshWorkspace]);

  const handleCancelPlan = useCallback(async (planId: string, reason: string) => {
    try {
      await cancelNotificationPlan(planId, { reason });
      await refreshWorkspace();
      await handleSelectPlan(planId);
    } catch (cancelError) {
      setError(handleApiError(cancelError));
    }
  }, [handleSelectPlan, refreshWorkspace]);

  const tabContent = useMemo(() => {
    if (activeTab === "overview") {
      return <OverviewPanel events={events} imports={imports} plans={plans} candidates={flatCandidates} />;
    }
    if (activeTab === "events") {
      return <EventListPanel events={events} loading={loading} onSelect={handleSelectEvent} onAction={runEventAction} />;
    }
    if (activeTab === "add") {
      return <ManualEventForm onCreate={handleCreateManualEvent} />;
    }
    if (activeTab === "imports" || activeTab === "candidates") {
      return (
        <PdfIntakePanel
          imports={imports}
          selectedImport={selectedImport}
          pages={pages}
          candidates={candidates}
          diagnostics={diagnostics}
          validation={validation}
          loading={loading}
          uploadState={uploadState}
          onUpload={handleUpload}
          onSelectImport={handleSelectImport}
          onExtract={handleExtract}
          onValidate={handleValidate}
          onCommit={handleCommit}
          onCancelImport={handleCancelImport}
          onEditCandidate={handleEditCandidate}
          onApproveCandidate={handleApproveCandidate}
          onRejectCandidate={handleRejectCandidate}
          onLoadPageEvidence={handleLoadPages}
          onLoadCandidatesPage={handleLoadCandidates}
        />
      );
    }
    if (activeTab === "notifications") {
      return (
        <NotificationPlansPanel
          plans={plans}
          selectedPlan={selectedPlan}
          loading={loading}
          onSelectPlan={handleSelectPlan}
          onApprovePlan={handleApprovePlan}
          onCancelPlan={handleCancelPlan}
        />
      );
    }
    return <EventDetailPanel selectedEvent={selectedEvent} versions={eventVersions} impact={eventImpact} loading={loading} />;
  }, [
    activeTab,
    candidates,
    diagnostics,
    eventImpact,
    eventVersions,
    events,
    flatCandidates,
    handleApproveCandidate,
    handleApprovePlan,
    handleCancelImport,
    handleCancelPlan,
    handleCommit,
    handleCreateManualEvent,
    handleEditCandidate,
    handleExtract,
    handleLoadCandidates,
    handleLoadPages,
    handleRejectCandidate,
    handleSelectEvent,
    handleSelectImport,
    handleSelectPlan,
    handleUpload,
    handleValidate,
    imports,
    loading,
    pages,
    plans,
    runEventAction,
    selectedEvent,
    selectedImport,
    selectedPlan,
    uploadState,
    validation,
  ]);

  return (
    <RoleGuard
      allowedRoles={["principal", "school_admin"]}
      forbiddenMessage="Only authorised leadership can access the academic calendar workspace."
    >
      <div className="space-y-6">
        <header className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <p className="text-sm font-semibold uppercase tracking-[0.22em] text-indigo-700">Leadership living calendar workspace</p>
          <h1 className="mt-2 text-2xl font-semibold text-gray-900">Academic Calendar</h1>
          <p className="mt-2 text-sm text-gray-600">
            Review source evidence, agent suggestions, deterministic validation, human approvals, and operational lifecycle state.
          </p>
        </header>

        {error ? (
          <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
            <button type="button" onClick={() => void refreshWorkspace()} className="ml-3 rounded border border-rose-300 px-2 py-1 text-xs">
              Retry
            </button>
          </div>
        ) : null}

        {toast ? (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            {toast}
            <button type="button" onClick={() => setToast(null)} className="ml-3 rounded border border-emerald-300 px-2 py-1 text-xs">Dismiss</button>
          </div>
        ) : null}

        <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <div role="tablist" aria-label="Calendar workspace sections" className="flex flex-wrap gap-2">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={activeTab === tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`rounded-lg px-3 py-2 text-sm font-medium ${activeTab === tab.key ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </section>

        <section>{tabContent}</section>
      </div>
    </RoleGuard>
  );
}
