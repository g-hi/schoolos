"use client";

import { useMemo, useState } from "react";
import type {
  CalendarEventCandidate,
  CalendarPdfDiagnostics,
  CalendarPdfImportDetail,
  CalendarPdfImportItem,
  CalendarPdfPageEvidence,
  PagedResponse,
  ValidatePdfBatchResponse,
} from "@/lib/timetable-calendar-api";

interface PdfIntakePanelProps {
  imports: CalendarPdfImportItem[];
  selectedImport: CalendarPdfImportDetail | null;
  pages: PagedResponse<CalendarPdfPageEvidence> | null;
  candidates: PagedResponse<CalendarEventCandidate> | null;
  diagnostics: CalendarPdfDiagnostics | null;
  validation: ValidatePdfBatchResponse | null;
  loading: boolean;
  uploadState: string;
  onUpload: (file: File) => Promise<void>;
  onSelectImport: (documentId: string) => Promise<void>;
  onExtract: () => Promise<void>;
  onValidate: () => Promise<void>;
  onCommit: () => Promise<void>;
  onCancelImport: (reason: string) => Promise<void>;
  onEditCandidate: (candidateId: string, patch: { proposed_event_name?: string }) => Promise<void>;
  onApproveCandidate: (candidateId: string) => Promise<void>;
  onRejectCandidate: (candidateId: string, reason: string) => Promise<void>;
  onLoadPageEvidence: (page: number) => Promise<void>;
  onLoadCandidatesPage: (page: number) => Promise<void>;
}

function confidenceTone(value: number | null): string {
  if (value === null) return "text-gray-700";
  if (value < 60) return "text-red-700";
  if (value < 80) return "text-amber-700";
  return "text-emerald-700";
}

export default function PdfIntakePanel({
  imports,
  selectedImport,
  pages,
  candidates,
  diagnostics,
  validation,
  loading,
  uploadState,
  onUpload,
  onSelectImport,
  onExtract,
  onValidate,
  onCommit,
  onCancelImport,
  onEditCandidate,
  onApproveCandidate,
  onRejectCandidate,
  onLoadPageEvidence,
  onLoadCandidatesPage,
}: PdfIntakePanelProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const canCommit = useMemo(() => {
    if (!validation) return false;
    return validation.blocker_count === 0;
  }, [validation]);

  async function withBusy(key: string, work: () => Promise<void>) {
    setBusy(key);
    try {
      await work();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-lg font-semibold text-gray-900">PDF intake</h3>
        <p className="mt-1 text-sm text-gray-600">Accepted format: text-based PDF. Max size and limits are enforced by backend configuration.</p>
        <p className="mt-1 text-xs text-gray-500">Status: {uploadState}</p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            aria-label="Choose calendar PDF"
            type="file"
            accept=".pdf,application/pdf"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <button
            type="button"
            disabled={!selectedFile || loading}
            onClick={() => selectedFile && withBusy("upload", () => onUpload(selectedFile))}
            className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {busy === "upload" ? "Uploading..." : "Upload PDF"}
          </button>
        </div>
        {selectedImport?.status === "ocr_required" ? (
          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            This PDF appears to be scanned and has no usable text layer. Automatic OCR is not enabled in this phase. Add events manually or use a text-based PDF.
          </p>
        ) : null}
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h4 className="text-sm font-semibold text-gray-900">Imports</h4>
        {imports.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">No calendar PDFs have been uploaded.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {imports.map((item) => (
              <button
                key={item.document_id}
                type="button"
                onClick={() => void onSelectImport(item.document_id)}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-left text-sm hover:bg-gray-50"
              >
                <p className="font-medium text-gray-900">{item.filename || "Unnamed PDF"}</p>
                <p className="text-xs text-gray-600">status: {item.status} · pages: {item.page_count}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      {selectedImport ? (
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-gray-900">Selected import details</h4>
          <p className="mt-1 text-xs text-gray-600">Document id: {selectedImport.document_id}</p>
          <p className="text-xs text-gray-600">Status: {selectedImport.status} · Pages: {selectedImport.page_count} · Characters: {selectedImport.extracted_char_count}</p>
          {selectedImport.error ? <p className="mt-2 text-sm text-red-700">{selectedImport.error}</p> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => void withBusy("extract", onExtract)} disabled={busy !== null} className="rounded border border-gray-300 px-3 py-1.5 text-sm">{busy === "extract" ? "Extracting..." : "Extract"}</button>
            <button type="button" onClick={() => void withBusy("validate", onValidate)} disabled={busy !== null} className="rounded border border-gray-300 px-3 py-1.5 text-sm">{busy === "validate" ? "Validating..." : "Validate"}</button>
            <button type="button" onClick={() => void withBusy("commit", onCommit)} disabled={!canCommit || busy !== null} className="rounded border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-60">Commit approved candidates</button>
            <button
              type="button"
              onClick={() => {
                const reason = window.prompt("Provide cancellation reason") || "";
                if (reason.trim()) {
                  void withBusy("cancel", () => onCancelImport(reason.trim()));
                }
              }}
              disabled={busy !== null}
              className="rounded border border-rose-300 px-3 py-1.5 text-sm text-rose-700"
            >
              Cancel intake
            </button>
          </div>

          {validation ? (
            <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
              <p className="font-medium text-gray-900">Validation summary</p>
              <p className="text-gray-700">blockers: {validation.blocker_count} · warnings: {validation.warning_count} · approved: {validation.approved_candidates}</p>
              <p className="text-gray-700">status: {validation.status}</p>
              {!canCommit ? <p className="mt-1 text-rose-700">Commit is disabled while blockers remain.</p> : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {pages ? (
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-gray-900">Page evidence</h4>
          <p className="text-xs text-gray-600">Page {pages.page} of {Math.max(1, Math.ceil(pages.total / pages.page_size))}</p>
          <div className="mt-3 space-y-2">
            {pages.items.map((item) => (
              <article key={`${item.page_number}-${item.extracted_char_count}`} className="rounded-lg border border-gray-100 p-3">
                <p className="text-sm font-medium text-gray-900">Page {item.page_number}</p>
                <p className="text-xs text-gray-600">Characters: {item.extracted_char_count} · Usable text: {item.extracted_char_count > 0 ? "yes" : "no"}</p>
                <p className="mt-2 max-h-24 overflow-y-auto rounded bg-gray-50 p-2 text-xs text-gray-700">{item.text_excerpt || "(No extracted text)"}</p>
              </article>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <button type="button" disabled={pages.page <= 1} onClick={() => void onLoadPageEvidence(pages.page - 1)} className="rounded border border-gray-300 px-2 py-1 text-xs disabled:opacity-60">Prev</button>
            <button
              type="button"
              disabled={pages.page * pages.page_size >= pages.total}
              onClick={() => void onLoadPageEvidence(pages.page + 1)}
              className="rounded border border-gray-300 px-2 py-1 text-xs disabled:opacity-60"
            >
              Next
            </button>
          </div>
        </section>
      ) : null}

      {candidates ? (
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-gray-900">Review candidates</h4>
          {candidates.items.length === 0 ? (
            <p className="mt-2 text-sm text-gray-600">No candidates are waiting for review.</p>
          ) : (
            <div className="mt-3 space-y-3">
              {candidates.items.map((item) => (
                <article key={item.id} className="rounded-lg border border-gray-100 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">{item.proposed_event_name}</p>
                    <p className={`text-xs font-semibold ${confidenceTone(item.confidence_score)}`}>Confidence: {item.confidence_score ?? "n/a"}</p>
                  </div>
                  <p className="text-xs text-gray-600">Type: {item.proposed_event_type} · Dates: {item.proposed_start_date || "?"} to {item.proposed_end_date || "?"}</p>
                  <p className="text-xs text-gray-600">Status: {item.candidate_status} · Parse: {item.date_parse_status}</p>
                  <p className="mt-1 text-xs text-gray-600">Source page: {String(item.source_payload?.page_number ?? "n/a")} · Excerpt: {String(item.source_payload?.line ?? "-")}</p>
                  <p className="mt-1 text-xs text-gray-600">Proposed interpretation: {String(item.classification_json?.explanation || "No explanation provided.")}</p>
                  <p className="mt-1 text-xs text-gray-600">Warnings: {(item.validation_issues_json?.warnings || []).join(", ") || "none"}</p>
                  <p className="mt-1 text-xs text-gray-600">Blockers: {(item.validation_issues_json?.blockers || []).join(", ") || "none"}</p>
                  {item.date_parse_status !== "parsed" || (item.confidence_score ?? 0) < 70 ? (
                    <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">Requires human review due to low confidence or ambiguity.</p>
                  ) : null}

                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        const value = window.prompt("Edit proposed event name", item.proposed_event_name);
                        if (value && value.trim() && value.trim() !== item.proposed_event_name) {
                          void onEditCandidate(item.id, { proposed_event_name: value.trim() });
                        }
                      }}
                      className="rounded border border-gray-300 px-2 py-1 text-xs"
                    >
                      Edit proposed fields
                    </button>
                    <button type="button" onClick={() => void onApproveCandidate(item.id)} className="rounded border border-emerald-300 px-2 py-1 text-xs text-emerald-800">Approve</button>
                    <button
                      type="button"
                      onClick={() => {
                        const reason = window.prompt("Reject reason") || "";
                        if (reason.trim()) {
                          void onRejectCandidate(item.id, reason.trim());
                        }
                      }}
                      className="rounded border border-rose-300 px-2 py-1 text-xs text-rose-800"
                    >
                      Reject with reason
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}

          <div className="mt-3 flex gap-2">
            <button type="button" disabled={candidates.page <= 1} onClick={() => void onLoadCandidatesPage(candidates.page - 1)} className="rounded border border-gray-300 px-2 py-1 text-xs disabled:opacity-60">Prev</button>
            <button
              type="button"
              disabled={candidates.page * candidates.page_size >= candidates.total}
              onClick={() => void onLoadCandidatesPage(candidates.page + 1)}
              className="rounded border border-gray-300 px-2 py-1 text-xs disabled:opacity-60"
            >
              Next
            </button>
          </div>
        </section>
      ) : null}

      {diagnostics ? (
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-gray-900">Diagnostics</h4>
          <p className="text-xs text-gray-600">Blockers: {diagnostics.blocker_count} · Warnings: {diagnostics.warning_count}</p>
        </section>
      ) : null}
    </div>
  );
}
