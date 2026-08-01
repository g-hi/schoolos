"use client";

import { useEffect, useMemo, useState } from "react";
import RoleGuard from "@/components/auth/role-guard";
import { apiUpload } from "@/lib/api";
import {
  ImportsApiError,
  ImportBatch,
  ImportBatchStatus,
  ImportEntityType,
  ImportRowAction,
  ImportRowDiagnostic,
  ImportRowStatus,
  PagedBatches,
  PagedRows,
  cancelImport,
  commitImport,
  downloadImportErrors,
  getImportBatch,
  getImportSummary,
  listImportBatches,
  listImportRows,
  previewImport,
} from "@/lib/imports-api";

const IMPORT_TABS = ["New Import", "Preview", "Import History", "Batch Detail", "Error Review"] as const;
type ImportTab = (typeof IMPORT_TABS)[number];
type ImportModeFilter = "all" | "preview" | "commit";
type StatusFilter = "all" | ImportBatchStatus;
type RowStatusFilter = "all" | ImportRowStatus;
type RowActionFilter = "all" | ImportRowAction;

const importEntityOptions: Array<{ value: ImportEntityType; label: string }> = [
  { value: "subjects", label: "Subjects" },
  { value: "classes", label: "Classes" },
  { value: "teachers", label: "Teachers" },
  { value: "students", label: "Students" },
  { value: "parents", label: "Parents" },
];

const batchStatuses: StatusFilter[] = [
  "all",
  "uploaded",
  "validating",
  "preview_ready",
  "invalid",
  "committing",
  "completed",
  "completed_with_errors",
  "failed",
  "cancelled",
];

const rowStatuses: RowStatusFilter[] = ["all", "valid", "invalid", "conflict", "created", "updated", "skipped", "failed"];
const rowActions: RowActionFilter[] = ["all", "create", "update", "skip", "none"];

const endpoints = [
  { label: "Subjects", path: "/ingest/subjects" },
  { label: "Classes", path: "/ingest/classes" },
  { label: "Teachers", path: "/ingest/teachers" },
  { label: "Students", path: "/ingest/students" },
  { label: "Parents", path: "/ingest/parents" },
  { label: "Periods", path: "/timetable/periods" },
  { label: "Timetable", path: "/timetable/upload" },
];

interface UploadResult {
  inserted: number;
  skipped: number;
  errors: { row: number; error: string }[];
}

function statusTone(status: ImportBatchStatus): string {
  if (status === "completed") return "bg-green-100 text-green-800";
  if (status === "completed_with_errors" || status === "failed" || status === "invalid") return "bg-red-100 text-red-700";
  if (status === "preview_ready") return "bg-amber-100 text-amber-800";
  if (status === "cancelled") return "bg-slate-200 text-slate-700";
  return "bg-blue-100 text-blue-800";
}

function toMessage(error: unknown): string {
  if (error instanceof ImportsApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Request failed.";
}

function canCommit(batch: ImportBatch | null): boolean {
  if (!batch) return false;
  if (Array.isArray(batch.available_actions) && !batch.available_actions.includes("commit")) return false;
  if (batch.status !== "preview_ready") return false;
  if ((batch.valid_rows ?? 0) + (batch.skipped_rows ?? 0) <= 0) return false;
  if (batch.invalid_rows >= batch.total_rows) return false;
  if (batch.conflict_rows >= batch.total_rows) return false;
  return true;
}

function canCancel(batch: ImportBatch | null): boolean {
  if (!batch) return false;
  if (Array.isArray(batch.available_actions) && !batch.available_actions.includes("cancel")) return false;
  return !["cancelled", "completed", "completed_with_errors", "failed", "committing"].includes(batch.status);
}

function showErrorCsv(batch: ImportBatch | null): boolean {
  if (!batch) return false;
  return batch.invalid_rows > 0 || batch.conflict_rows > 0;
}

function DataImportsWorkspace() {
  const [activeTab, setActiveTab] = useState<ImportTab>("New Import");
  const [entityType, setEntityType] = useState<ImportEntityType>("subjects");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [previewRows, setPreviewRows] = useState<ImportRowDiagnostic[]>([]);
  const [previewBatch, setPreviewBatch] = useState<ImportBatch | null>(null);
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const [batchSummary, setBatchSummary] = useState<Record<string, number> | null>(null);
  const [history, setHistory] = useState<PagedBatches>({ items: [], total: 0, page: 1, pageSize: 10 });
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize] = useState(10);
  const [historyEntity, setHistoryEntity] = useState<ImportEntityType | "all">("all");
  const [historyStatus, setHistoryStatus] = useState<StatusFilter>("all");
  const [historyMode, setHistoryMode] = useState<ImportModeFilter>("all");
  const [historyDateFrom, setHistoryDateFrom] = useState("");
  const [historyDateTo, setHistoryDateTo] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [batchDetail, setBatchDetail] = useState<ImportBatch | null>(null);
  const [rows, setRows] = useState<PagedRows>({ items: [], total: 0, page: 1, pageSize: 20 });
  const [rowsPage, setRowsPage] = useState(1);
  const [rowsPageSize] = useState(20);
  const [rowStatusFilter, setRowStatusFilter] = useState<RowStatusFilter>("all");
  const [rowActionFilter, setRowActionFilter] = useState<RowActionFilter>("all");
  const [rowErrorCode, setRowErrorCode] = useState("");
  const [importsError, setImportsError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, UploadResult | string>>({});
  const [uploading, setUploading] = useState<string | null>(null);

  const previewTopRows = useMemo(() => previewRows.slice(0, 20), [previewRows]);

  async function refreshSummary() {
    const data = await getImportSummary();
    setSummary(data.by_status || {});
    setBatchSummary(data.by_entity_type || {});
  }

  async function refreshHistory() {
    const response = await listImportBatches({
      entity_type: historyEntity === "all" ? undefined : historyEntity,
      status: historyStatus === "all" ? undefined : historyStatus,
      mode: historyMode === "all" ? undefined : historyMode,
      created_from: historyDateFrom || undefined,
      created_to: historyDateTo || undefined,
      page: historyPage,
      page_size: historyPageSize,
    });
    setHistory(response);
  }

  async function refreshBatchDetail(batchId: string) {
    const detail = await getImportBatch(batchId);
    setBatchDetail(detail);
    const rowsResult = await listImportRows(batchId, {
      status: rowStatusFilter === "all" ? undefined : rowStatusFilter,
      action: rowActionFilter === "all" ? undefined : rowActionFilter,
      error_code: rowErrorCode || undefined,
      page: rowsPage,
      page_size: rowsPageSize,
    });
    setRows(rowsResult);
  }

  useEffect(() => {
    void refreshSummary().catch((err) => setImportsError(toMessage(err)));
  }, []);

  useEffect(() => {
    void refreshHistory().catch((err) => setImportsError(toMessage(err)));
  }, [historyEntity, historyStatus, historyMode, historyDateFrom, historyDateTo, historyPage]);

  useEffect(() => {
    if (!selectedBatchId) return;
    void refreshBatchDetail(selectedBatchId).catch((err) => setImportsError(toMessage(err)));
  }, [selectedBatchId, rowStatusFilter, rowActionFilter, rowErrorCode, rowsPage]);

  async function handlePreview() {
    if (!selectedFile) {
      setImportsError("Choose a CSV file first.");
      return;
    }
    if (!selectedFile.name.toLowerCase().endsWith(".csv")) {
      setImportsError("Only CSV files are accepted.");
      return;
    }
    if (selectedFile.size <= 0) {
      setImportsError("Selected file is empty.");
      return;
    }

    setImportsError(null);
    setIsPreviewing(true);
    try {
      const response = await previewImport(entityType, selectedFile);
      setPreviewBatch(response.batch);
      setPreviewRows(response.rows);
      setSelectedBatchId(response.batch.id);
      setActiveTab("Preview");
      await Promise.all([refreshSummary(), refreshHistory()]);
    } catch (err) {
      setImportsError(toMessage(err));
    } finally {
      setIsPreviewing(false);
    }
  }

  async function handleCommit() {
    if (!previewBatch) return;
    const shouldCommit = window.confirm(
      `Confirm import commit?\n\nValid rows: ${previewBatch.valid_rows}\nSkipped rows: ${previewBatch.skipped_rows}\nInvalid rows: ${previewBatch.invalid_rows}\nConflict rows: ${previewBatch.conflict_rows}\n\nOnly valid and skipped rows will be processed. Invalid and conflict rows will not be applied.`
    );
    if (!shouldCommit) return;

    setImportsError(null);
    setIsCommitting(true);
    try {
      const response = await commitImport(previewBatch.id);
      setPreviewBatch(response.batch);
      setPreviewRows(response.rows);
      setSelectedBatchId(response.batch.id);
      setActiveTab("Batch Detail");
      await Promise.all([refreshSummary(), refreshHistory(), refreshBatchDetail(response.batch.id)]);
    } catch (err) {
      setImportsError(toMessage(err));
    } finally {
      setIsCommitting(false);
    }
  }

  async function handleCancel() {
    if (!previewBatch) return;
    const shouldCancel = window.confirm(
      "Cancel this preview batch? Cancellation preserves history, imported records are not deleted, and committed batches cannot be cancelled."
    );
    if (!shouldCancel) return;

    setImportsError(null);
    setIsCancelling(true);
    try {
      const batch = await cancelImport(previewBatch.id);
      setPreviewBatch(batch);
      setSelectedBatchId(batch.id);
      await Promise.all([refreshSummary(), refreshHistory(), refreshBatchDetail(batch.id)]);
    } catch (err) {
      setImportsError(toMessage(err));
    } finally {
      setIsCancelling(false);
    }
  }

  async function handleDownloadErrors(batch: ImportBatch | null) {
    if (!batch) return;
    try {
      await downloadImportErrors(batch.id);
    } catch (err) {
      setImportsError(toMessage(err));
    }
  }

  async function handleLegacyUpload(label: string, path: string, file: File) {
    setUploading(label);
    try {
      const res = await apiUpload<UploadResult>(path, file);
      setResults((prev) => ({ ...prev, [label]: res }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [label]: String(err) }));
    } finally {
      setUploading(null);
    }
  }

  const currentBatch = batchDetail ?? previewBatch;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">Data Imports</h1>
          <p className="text-sm text-gray-500 mt-1">
            Leadership preview-and-commit workflow with import history, diagnostics, and audit-safe lifecycle controls.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2">
            <p className="text-green-800 font-medium">Completed</p>
            <p className="text-lg font-semibold text-green-900">{summary?.completed ?? 0}</p>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="text-amber-800 font-medium">Needs Review</p>
            <p className="text-lg font-semibold text-amber-900">{(summary?.preview_ready ?? 0) + (summary?.completed_with_errors ?? 0)}</p>
          </div>
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
            <p className="text-red-800 font-medium">Failed</p>
            <p className="text-lg font-semibold text-red-900">{summary?.failed ?? 0}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <p className="text-slate-700 font-medium">Total Batches</p>
            <p className="text-lg font-semibold text-slate-900">{Object.values(summary ?? {}).reduce((a, b) => a + b, 0)}</p>
          </div>
        </div>
      </div>

      {importsError ? (
        <section className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700" role="alert">
          {importsError}
          <button
            type="button"
            className="ml-3 underline text-sm"
            onClick={() => {
              setImportsError(null);
              void Promise.all([refreshSummary(), refreshHistory()]).catch((err) => setImportsError(toMessage(err)));
            }}
          >
            Retry
          </button>
        </section>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {IMPORT_TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`rounded-lg border px-3 py-2 text-sm font-medium ${
              activeTab === tab
                ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "New Import" ? (
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <article className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-semibold">New Import</h2>
            <p className="text-sm text-gray-600">
              Supported entity types: subjects, classes, teachers, students, parents.
            </p>

            <label className="block text-sm font-medium text-gray-700">
              Entity type
              <select
                value={entityType}
                onChange={(e) => setEntityType(e.target.value as ImportEntityType)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                {importEntityOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-sm font-medium text-gray-700">
              CSV file
              <input
                type="file"
                accept=".csv,text/csv"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
              />
            </label>

            {selectedFile ? (
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 space-y-1">
                <p><span className="font-medium">Filename:</span> {selectedFile.name}</p>
                <p><span className="font-medium">Size:</span> {selectedFile.size} bytes</p>
                <p><span className="font-medium">Entity:</span> {entityType}</p>
                <p><span className="font-medium">Accepted type:</span> .csv</p>
              </div>
            ) : null}

            <button
              type="button"
              onClick={handlePreview}
              disabled={!selectedFile || isPreviewing}
              className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                !selectedFile || isPreviewing ? "bg-gray-300 text-gray-600" : "bg-indigo-600 text-white hover:bg-indigo-700"
              }`}
            >
              {isPreviewing ? "Previewing..." : "Preview Import"}
            </button>
          </article>

          <article className="rounded-xl border border-indigo-200 bg-indigo-50 p-5 space-y-3 text-sm text-indigo-900">
            <h3 className="font-semibold">Recommended workflow</h3>
            <ol className="list-decimal pl-5 space-y-1">
              <li>Choose entity type.</li>
              <li>Select CSV.</li>
              <li>Run preview.</li>
              <li>Review invalid/conflict rows.</li>
              <li>Download error report when needed.</li>
              <li>Correct source file outside SchoolOS and preview again.</li>
              <li>Confirm commit.</li>
              <li>Review batch completion details.</li>
            </ol>
          </article>
        </section>
      ) : null}

      {activeTab === "Preview" ? (
        <section className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
          <h2 className="text-lg font-semibold">Preview</h2>
          {previewBatch ? (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div className="rounded-lg border border-gray-200 p-3"><p className="text-gray-500">Total</p><p className="text-xl font-semibold">{previewBatch.total_rows}</p></div>
                <div className="rounded-lg border border-green-200 bg-green-50 p-3"><p className="text-green-700">Valid</p><p className="text-xl font-semibold text-green-900">{previewBatch.valid_rows}</p></div>
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3"><p className="text-amber-700">Conflict</p><p className="text-xl font-semibold text-amber-900">{previewBatch.conflict_rows}</p></div>
                <div className="rounded-lg border border-red-200 bg-red-50 p-3"><p className="text-red-700">Invalid</p><p className="text-xl font-semibold text-red-900">{previewBatch.invalid_rows}</p></div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusTone(previewBatch.status)}`}>{previewBatch.status}</span>
                {previewBatch.duplicate_file_diagnostic?.message ? (
                  <span className="text-xs text-amber-700">Duplicate-file diagnostic: {previewBatch.duplicate_file_diagnostic.message}</span>
                ) : null}
              </div>
              <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                Only valid and skipped rows will be processed. Invalid and conflict rows will not be applied.
              </p>

              <div className="overflow-auto rounded-lg border border-gray-200">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left">Row</th>
                      <th className="px-3 py-2 text-left">Status</th>
                      <th className="px-3 py-2 text-left">Action</th>
                      <th className="px-3 py-2 text-left">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewTopRows.map((row) => (
                      <tr key={`${row.row_number}-${row.error_code || "ok"}`} className="border-t border-gray-100">
                        <td className="px-3 py-2">{row.row_number}</td>
                        <td className="px-3 py-2">{row.status}</td>
                        <td className="px-3 py-2">{row.action}</td>
                        <td className="px-3 py-2 text-red-700">{row.error_message || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleCommit}
                  disabled={!canCommit(previewBatch) || isCommitting}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                    !canCommit(previewBatch) || isCommitting ? "bg-gray-300 text-gray-600" : "bg-green-600 text-white hover:bg-green-700"
                  }`}
                >
                  {isCommitting ? "Committing..." : "Commit Batch"}
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={!canCancel(previewBatch) || isCancelling}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                    !canCancel(previewBatch) || isCancelling ? "bg-gray-300 text-gray-600" : "bg-red-600 text-white hover:bg-red-700"
                  }`}
                >
                  {isCancelling ? "Cancelling..." : "Cancel Preview"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (previewBatch) {
                      setSelectedBatchId(previewBatch.id);
                      setActiveTab("Batch Detail");
                    }
                  }}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                >
                  View Batch Detail
                </button>
                {showErrorCsv(previewBatch) ? (
                  <button
                    type="button"
                    onClick={() => void handleDownloadErrors(previewBatch)}
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                  >
                    Download Error CSV
                  </button>
                ) : null}
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">No preview yet. Start from New Import.</p>
          )}
        </section>
      ) : null}

      {activeTab === "Import History" ? (
        <section className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
          <h2 className="text-lg font-semibold">Import History</h2>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            <select className="rounded-lg border border-gray-300 px-3 py-2 text-sm" value={historyEntity} onChange={(e) => { setHistoryPage(1); setHistoryEntity(e.target.value as ImportEntityType | "all"); }}>
              <option value="all">All entities</option>
              {importEntityOptions.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
            <select className="rounded-lg border border-gray-300 px-3 py-2 text-sm" value={historyStatus} onChange={(e) => { setHistoryPage(1); setHistoryStatus(e.target.value as StatusFilter); }}>
              {batchStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <select className="rounded-lg border border-gray-300 px-3 py-2 text-sm" value={historyMode} onChange={(e) => { setHistoryPage(1); setHistoryMode(e.target.value as ImportModeFilter); }}>
              <option value="all">All modes</option>
              <option value="preview">preview</option>
              <option value="commit">commit</option>
            </select>
            <input type="date" value={historyDateFrom} onChange={(e) => { setHistoryPage(1); setHistoryDateFrom(e.target.value); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            <input type="date" value={historyDateTo} onChange={(e) => { setHistoryPage(1); setHistoryDateTo(e.target.value); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </div>

          <div className="overflow-auto rounded-lg border border-gray-200">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">Filename</th>
                  <th className="px-3 py-2 text-left">Entity</th>
                  <th className="px-3 py-2 text-left">Status</th>
                  <th className="px-3 py-2 text-left">Mode</th>
                  <th className="px-3 py-2 text-left">Counts</th>
                  <th className="px-3 py-2 text-left">Created</th>
                  <th className="px-3 py-2 text-left">Completed</th>
                  <th className="px-3 py-2 text-left">Committed</th>
                  <th className="px-3 py-2 text-left">Action</th>
                </tr>
              </thead>
              <tbody>
                {history.items.map((batch) => (
                  <tr key={batch.id} className="border-t border-gray-100">
                    <td className="px-3 py-2">{batch.original_filename || "-"}</td>
                    <td className="px-3 py-2">{batch.entity_type}</td>
                    <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-xs ${statusTone(batch.status)}`}>{batch.status}</span></td>
                    <td className="px-3 py-2">{batch.mode}</td>
                    <td className="px-3 py-2">T:{batch.total_rows} V:{batch.valid_rows} I:{batch.invalid_rows} C:{batch.conflict_rows} Cr:{batch.created_rows} Up:{batch.updated_rows} Sk:{batch.skipped_rows}</td>
                    <td className="px-3 py-2">{batch.created_at ? new Date(batch.created_at).toLocaleString() : "-"}</td>
                    <td className="px-3 py-2">{batch.completed_at ? new Date(batch.completed_at).toLocaleString() : "-"}</td>
                    <td className="px-3 py-2">{batch.committed_at ? new Date(batch.committed_at).toLocaleString() : "-"}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedBatchId(batch.id);
                          setActiveTab("Batch Detail");
                        }}
                        className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm">
            <p>Showing {history.items.length} of {history.total} batches.</p>
            <div className="flex gap-2">
              <button type="button" disabled={history.page <= 1} onClick={() => setHistoryPage((p) => Math.max(1, p - 1))} className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50">Prev</button>
              <span>Page {history.page}</span>
              <button
                type="button"
                disabled={history.page * history.pageSize >= history.total}
                onClick={() => setHistoryPage((p) => p + 1)}
                className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "Batch Detail" ? (
        <section className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
          <h2 className="text-lg font-semibold">Batch Detail</h2>
          {currentBatch ? (
            <>
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusTone(currentBatch.status)}`}>{currentBatch.status}</span>
                <span className="text-xs text-gray-500">{currentBatch.id}</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg border border-gray-200 p-3">
                  <p><span className="font-medium">Filename:</span> {currentBatch.original_filename || "-"}</p>
                  <p><span className="font-medium">Entity:</span> {currentBatch.entity_type}</p>
                  <p><span className="font-medium">Mode:</span> {currentBatch.mode}</p>
                  <p><span className="font-medium">SHA-256:</span> {currentBatch.file_sha256}</p>
                </div>
                <div className="rounded-lg border border-gray-200 p-3">
                  <p><span className="font-medium">Rows:</span> total {currentBatch.total_rows}, valid {currentBatch.valid_rows}, invalid {currentBatch.invalid_rows}, conflict {currentBatch.conflict_rows}</p>
                  <p><span className="font-medium">Processed:</span> created {currentBatch.created_rows}, updated {currentBatch.updated_rows}, skipped {currentBatch.skipped_rows}</p>
                  <p><span className="font-medium">Started:</span> {currentBatch.started_at ? new Date(currentBatch.started_at).toLocaleString() : "-"}</p>
                  <p><span className="font-medium">Completed:</span> {currentBatch.completed_at ? new Date(currentBatch.completed_at).toLocaleString() : "-"}</p>
                </div>
              </div>
              {currentBatch.duplicate_file_diagnostic?.message ? (
                <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  Duplicate-file diagnostic: {currentBatch.duplicate_file_diagnostic.message}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {canCommit(currentBatch) ? (
                  <button type="button" onClick={handleCommit} disabled={isCommitting} className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-gray-400">
                    {isCommitting ? "Committing..." : "Commit"}
                  </button>
                ) : null}
                {canCancel(currentBatch) ? (
                  <button type="button" onClick={handleCancel} disabled={isCancelling} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-gray-400">
                    {isCancelling ? "Cancelling..." : "Cancel"}
                  </button>
                ) : null}
                {showErrorCsv(currentBatch) ? (
                  <button type="button" onClick={() => void handleDownloadErrors(currentBatch)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">
                    Download errors.csv
                  </button>
                ) : null}
                <button type="button" onClick={() => setActiveTab("Error Review")} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">
                  Review Row Diagnostics
                </button>
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">Select a batch from Import History or run a new preview.</p>
          )}
        </section>
      ) : null}

      {activeTab === "Error Review" ? (
        <section className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
          <h2 className="text-lg font-semibold">Row Diagnostics</h2>
          {!selectedBatchId ? (
            <p className="text-sm text-gray-500">Select a batch first.</p>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <select value={rowStatusFilter} onChange={(e) => { setRowsPage(1); setRowStatusFilter(e.target.value as RowStatusFilter); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
                  {rowStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
                <select value={rowActionFilter} onChange={(e) => { setRowsPage(1); setRowActionFilter(e.target.value as RowActionFilter); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
                  {rowActions.map((action) => <option key={action} value={action}>{action}</option>)}
                </select>
                <input value={rowErrorCode} onChange={(e) => { setRowsPage(1); setRowErrorCode(e.target.value); }} placeholder="error_code" className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                <button type="button" onClick={() => selectedBatchId && void refreshBatchDetail(selectedBatchId).catch((err) => setImportsError(toMessage(err)))} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-50">Apply</button>
              </div>

              <div className="overflow-auto rounded-lg border border-gray-200">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left">Row</th>
                      <th className="px-3 py-2 text-left">Status</th>
                      <th className="px-3 py-2 text-left">Action</th>
                      <th className="px-3 py-2 text-left">Entity Ref</th>
                      <th className="px-3 py-2 text-left">Error Code</th>
                      <th className="px-3 py-2 text-left">Error Message</th>
                      <th className="px-3 py-2 text-left">Field Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.items.map((row) => (
                      <tr key={`${row.row_number}-${row.id || row.error_code || "row"}`} className="border-t border-gray-100">
                        <td className="px-3 py-2">{row.row_number}</td>
                        <td className="px-3 py-2">{row.status}</td>
                        <td className="px-3 py-2">{row.action}</td>
                        <td className="px-3 py-2">{row.entity_reference_id || "-"}</td>
                        <td className="px-3 py-2">{row.error_code || "-"}</td>
                        <td className="px-3 py-2">{row.error_message || "-"}</td>
                        <td className="px-3 py-2">{row.field_errors ? JSON.stringify(row.field_errors) : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between text-sm">
                <p>Showing {rows.items.length} of {rows.total} rows.</p>
                <div className="flex gap-2">
                  <button type="button" disabled={rows.page <= 1} onClick={() => setRowsPage((p) => Math.max(1, p - 1))} className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50">Prev</button>
                  <span>Page {rows.page}</span>
                  <button
                    type="button"
                    disabled={rows.page * rows.pageSize >= rows.total}
                    onClick={() => setRowsPage((p) => p + 1)}
                    className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      ) : null}

      <details className="rounded-xl border border-gray-200 bg-white p-4">
        <summary className="cursor-pointer font-semibold text-sm">Legacy direct upload (compatibility)</summary>
        <p className="text-sm text-gray-600 mt-2">
          This compatibility workflow preserves existing direct upload contracts. Preview + history workflow is recommended for safer operations.
        </p>
        <div className="space-y-4 mt-4">
          {endpoints.map((ep) => {
            const res = results[ep.label];
            const isError = typeof res === "string";
            const data = !isError ? (res as UploadResult | undefined) : undefined;
            return (
              <div key={ep.label} className="rounded-lg border border-gray-200 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h4 className="font-medium">{ep.label}</h4>
                    {isError ? <p className="text-sm text-red-600">{res as string}</p> : null}
                    {data ? (
                      <p className="text-sm text-green-700">
                        {data.inserted} inserted, {data.skipped} skipped, {data.errors.length} errors
                      </p>
                    ) : null}
                  </div>
                  <label className={`rounded-lg px-3 py-2 text-sm font-medium ${uploading === ep.label ? "bg-gray-300 text-gray-600" : "bg-indigo-600 text-white hover:bg-indigo-700"}`}>
                    {uploading === ep.label ? "Uploading..." : "Choose CSV"}
                    <input
                      type="file"
                      accept=".csv"
                      className="hidden"
                      disabled={uploading === ep.label}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) {
                          void handleLegacyUpload(ep.label, ep.path, file);
                        }
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
              </div>
            );
          })}
        </div>
      </details>

      <section className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-700">
        <h3 className="font-semibold mb-2">Entity totals from import summary</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {importEntityOptions.map((entity) => (
            <div key={entity.value} className="rounded border border-gray-200 bg-gray-50 p-2">
              <p className="text-xs uppercase text-gray-500">{entity.label}</p>
              <p className="text-lg font-semibold">{batchSummary?.[entity.value] ?? 0}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function DataPage() {
  return (
    <RoleGuard
      allowedRoles={["principal", "school_admin"]}
      forbiddenMessage="Only school leadership can access Data Imports."
    >
      <DataImportsWorkspace />
    </RoleGuard>
  );
}
