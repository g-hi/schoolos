"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getSession,
  listSubmissions,
  processSession,
  submitReview,
  approveSubmissions,
  type MarkingSession,
  type SubmissionSummary,
  type QuestionOverride,
  type AnswerKeyItem,
  paperTypeLabel,
  statusColor,
  statusLabel,
  confidenceColor,
} from "@/lib/exam-marking-api";
import { copilotStatus, type CopilotResponse } from "@/lib/api";
import QuestionReviewRow from "@/components/exam-marking/question-review-row";
import MarkSummary from "@/components/exam-marking/mark-summary";
import StudentQueue from "@/components/exam-marking/student-queue";

interface QuestionResponse {
  question_number: number;
  question_type: string;
  extracted_answer: string;
  extraction_confidence: number;
  correct_answer: string;
  proposed_marks: number;
  max_marks: number;
  teacher_final_marks?: number;
  grading_method: string;
  confidence: number;
  confidence_band?: string;
  ambiguous_mark: boolean;
  requires_teacher_review: boolean;
  teacher_overridden?: boolean;
  teacher_comment?: string;
  evidence: Record<string, unknown>;
  rubric_result?: {
    criteria?: { criterion: string; awarded: number; max: number; evidence: string }[];
    feedback?: string;
  };
  status: string;
}

interface ProcessingResult {
  question_responses: QuestionResponse[];
  proposed_total: number;
  max_marks: number;
  percentage: number;
  processing_pipeline: string;
  requires_review: boolean;
  unresolved_count: number;
  low_confidence_count: number;
  ai_graded_count: number;
  deterministic_count: number;
  estimated_cost_usd?: number;
}

export default function ReviewPage() {
  const params = useParams<{ sessionId: string }>();
  const router = useRouter();
  const sessionId = params.sessionId;

  const [session, setSession] = useState<MarkingSession | null>(null);
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([]);
  const [selectedSubId, setSelectedSubId] = useState<string | undefined>();
  const [processing, setProcessing] = useState(false);
  const [processingResult, setProcessingResult] = useState<ProcessingResult | null>(null);
  const [copilotRequestId, setCopilotRequestId] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<QuestionOverride[]>([]);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Simple answer key for demo — in production loaded from session or DB
  const [answerKey] = useState<AnswerKeyItem[]>([
    { question_number: 1, question_type: "mcq", question_text: "Q1", correct_answer: "B", max_marks: 2, accepted_alternatives: [] },
    { question_number: 2, question_type: "true_false", question_text: "Q2", correct_answer: "True", max_marks: 1 },
    { question_number: 3, question_type: "short_answer", question_text: "Q3", correct_answer: "", max_marks: 5, rubric_criteria: [{ criterion: "Content", max_marks: 3, description: "Core concept" }, { criterion: "Clarity", max_marks: 2, description: "Clear explanation" }] },
  ]);

  useEffect(() => {
    const load = async () => {
      try {
        const [sess, subs] = await Promise.all([getSession(sessionId), listSubmissions(sessionId)]);
        setSession(sess);
        setSubmissions(subs);
        if (subs.length > 0 && !selectedSubId) setSelectedSubId(subs[0].submission_id);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load session");
      }
    };
    load();
  }, [sessionId]);

  const handleProcess = async () => {
    if (!selectedSubId) return;
    setProcessing(true);
    setError(null);
    setProcessingResult(null);
    setOverrides([]);
    try {
      const result = await processSession(sessionId, {
        submission_ids: [selectedSubId],
        answer_key: answerKey,
        teacher_guidance: session?.teacher_notes || "",
      });
      setCopilotRequestId(result.copilot_request_id);

      // Poll for result
      let attempts = 0;
      const poll = async () => {
        attempts++;
        try {
          const status = await copilotStatus(result.copilot_request_id);
          if (status.status === "pending_review" && status.result) {
            setProcessingResult(status.result as unknown as ProcessingResult);
            setProcessing(false);
          } else if (status.status === "error" || attempts > 20) {
            setError(status.message || "Processing failed");
            setProcessing(false);
          } else {
            setTimeout(poll, 1500);
          }
        } catch {
          if (attempts < 5) setTimeout(poll, 2000);
          else {
            setError("Could not retrieve processing result");
            setProcessing(false);
          }
        }
      };
      poll();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Processing failed");
      setProcessing(false);
    }
  };

  const handleOverride = (questionNumber: number, marks: number, comment: string) => {
    setOverrides((prev) => {
      const existing = prev.findIndex((o) => o.question_number === questionNumber);
      const updated = [...prev];
      if (existing >= 0) updated[existing] = { question_number: questionNumber, teacher_final_marks: marks, teacher_comment: comment };
      else updated.push({ question_number: questionNumber, teacher_final_marks: marks, teacher_comment: comment });
      return updated;
    });

    // Update local display
    if (processingResult) {
      setProcessingResult((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          question_responses: prev.question_responses.map((r) =>
            r.question_number === questionNumber ? { ...r, teacher_final_marks: marks, teacher_overridden: true, teacher_comment: comment } : r,
          ),
        };
      });
    }
  };

  const handleSaveOverrides = async () => {
    if (!selectedSubId || overrides.length === 0) return;
    setSaving(true);
    try {
      await submitReview(sessionId, { submission_id: selectedSubId, overrides });
      setSuccessMsg(`${overrides.length} override(s) saved.`);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save overrides");
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async (approved: boolean) => {
    if (!selectedSubId) return;
    setApproving(true);
    try {
      await approveSubmissions(sessionId, { submission_ids: [selectedSubId], approved, notes: "" });
      setSuccessMsg(approved ? "Paper approved." : "Paper rejected.");
      const [_sess, subs] = await Promise.all([getSession(sessionId).then(setSession), listSubmissions(sessionId)]);
      setSubmissions(subs);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : approved ? "Approval failed" : "Rejection failed");
    } finally {
      setApproving(false);
    }
  };

  const selectedSub = submissions.find((s) => s.submission_id === selectedSubId);

  const teacherTotal = processingResult
    ? overrides.reduce(
        (sum, o) => {
          const q = processingResult.question_responses.find((r) => r.question_number === o.question_number);
          return sum + o.teacher_final_marks - (q?.proposed_marks ?? 0);
        },
        processingResult.proposed_total,
      )
    : null;

  if (!session) {
    return <div className="text-sm text-gray-500">Loading…</div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Link href={`/teacher/exam-marking/${sessionId}`} className="text-sm text-gray-400 hover:text-gray-600">
            ← Session
          </Link>
          <span className="text-gray-300">/</span>
          <span className="text-sm font-semibold text-gray-700">Teacher Review</span>
        </div>
        <span className={`shrink-0 inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${statusColor(session.status)}`}>
          {statusLabel(session.status)}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar: student queue */}
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-3">Students</h2>
          <StudentQueue
            submissions={submissions}
            activeSubmissionId={selectedSubId}
            onSelect={(id) => { setSelectedSubId(id); setProcessingResult(null); setOverrides([]); }}
          />
        </div>

        {/* Main review panel */}
        <div className="lg:col-span-3 space-y-5">
          {/* Student + exam info */}
          {selectedSub && (
            <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between gap-4">
              <div>
                <p className="font-semibold text-gray-900">{selectedSub.student_name || "Unknown Student"}</p>
                <p className="text-xs text-gray-500">{selectedSub.student_code}</p>
              </div>
              <div className="text-right text-sm">
                <p className="text-gray-600">{session.exam_title}</p>
                <p className="text-xs text-gray-400">{paperTypeLabel(session.paper_type)} · {session.total_marks} marks</p>
              </div>
            </div>
          )}

          {/* Errors / Success */}
          {error && (
            <div className="text-sm text-red-600 bg-red-50 px-4 py-3 rounded-xl">{error}
              <button onClick={() => setError(null)} className="ml-3 text-red-400 hover:text-red-600">✕</button>
            </div>
          )}
          {successMsg && (
            <div className="text-sm text-green-700 bg-green-50 px-4 py-3 rounded-xl">{successMsg}</div>
          )}

          {/* Process button */}
          {!processingResult && (
            <div className="bg-white border border-gray-200 rounded-xl p-5 text-center space-y-3">
              <p className="text-gray-600 text-sm">
                Click <strong>Process Paper</strong> to run the AI marking pipeline.
                All results require your approval before they are finalised.
              </p>
              <button
                type="button"
                onClick={handleProcess}
                disabled={processing || !selectedSubId}
                className="px-6 py-3 bg-indigo-600 text-white rounded-xl font-semibold hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {processing ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">⏳</span> Processing…
                  </span>
                ) : "Process Paper"}
              </button>
              <p className="text-xs text-gray-400">
                Pipeline: {paperTypeLabel(session.paper_type)} · AI assists, teacher decides
              </p>
            </div>
          )}

          {/* Results */}
          {processingResult && (
            <div className="space-y-4">
              {/* Mark summary */}
              <MarkSummary
                proposedTotal={processingResult.proposed_total}
                teacherFinalTotal={overrides.length > 0 ? teacherTotal : undefined}
                maxMarks={processingResult.max_marks}
                percentage={processingResult.percentage}
                objectiveCount={processingResult.deterministic_count}
                aiGradedCount={processingResult.ai_graded_count}
                deterministicCount={processingResult.deterministic_count}
                unresolvedCount={processingResult.unresolved_count}
                lowConfidenceCount={processingResult.low_confidence_count}
                estimatedCostUsd={processingResult.estimated_cost_usd}
              />

              {/* Pipeline info */}
              <div className="text-xs text-gray-400 flex items-center gap-2">
                <span>Pipeline: <strong className="text-gray-600">{processingResult.processing_pipeline}</strong></span>
                <span>·</span>
                <span>AI proposed marks are <strong className="text-purple-600">pending review</strong> until you approve</span>
              </div>

              {/* Question responses */}
              <div className="space-y-3">
                <h3 className="font-semibold text-gray-700 text-sm">
                  Question-by-Question Review
                  {processingResult.unresolved_count > 0 && (
                    <span className="ml-2 text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">
                      {processingResult.unresolved_count} unresolved
                    </span>
                  )}
                </h3>
                {processingResult.question_responses.map((qr) => (
                  <QuestionReviewRow
                    key={qr.question_number}
                    response={qr}
                    onOverride={handleOverride}
                  />
                ))}
              </div>

              {/* Save overrides */}
              {overrides.length > 0 && (
                <button
                  type="button"
                  onClick={handleSaveOverrides}
                  disabled={saving}
                  className="w-full py-2.5 bg-indigo-100 text-indigo-700 rounded-xl font-medium hover:bg-indigo-200 text-sm transition-colors"
                >
                  {saving ? "Saving…" : `Save ${overrides.length} Override${overrides.length !== 1 ? "s" : ""}`}
                </button>
              )}

              {/* Approval row */}
              <div className="flex gap-3 pt-2 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => handleApprove(true)}
                  disabled={approving || processingResult.unresolved_count > 0}
                  className="flex-1 py-3 bg-green-600 text-white rounded-xl font-semibold hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {approving ? "Approving…" : "✓ Approve Paper"}
                </button>
                <button
                  type="button"
                  onClick={() => handleApprove(false)}
                  disabled={approving}
                  className="px-6 py-3 bg-red-50 text-red-600 rounded-xl font-medium hover:bg-red-100 transition-colors"
                >
                  Reject
                </button>
              </div>
              {processingResult.unresolved_count > 0 && (
                <p className="text-xs text-red-500 text-center">
                  Resolve {processingResult.unresolved_count} unresolved question(s) before approving.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
