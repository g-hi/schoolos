"use client";

import { type SubmissionSummary } from "@/lib/exam-marking-api";

interface QueueEntry {
  submission_id?: string;
  name: string;
  code?: string;
  status: "pending" | "scanning" | "captured" | "complete" | "skipped" | "flagged" | "approved" | "rejected";
}

interface Props {
  submissions: SubmissionSummary[];
  activeSubmissionId?: string;
  onSelect: (submissionId: string | undefined, studentName: string) => void;
  onSkip?: (submissionId: string) => void;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-600",
  scanning: "bg-blue-100 text-blue-700",
  captured: "bg-indigo-100 text-indigo-700",
  complete: "bg-green-100 text-green-700",
  skipped: "bg-gray-100 text-gray-400",
  flagged: "bg-orange-100 text-orange-700",
  approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
};

const STATUS_ICON: Record<string, string> = {
  pending: "○",
  scanning: "📷",
  captured: "✓",
  complete: "✓",
  skipped: "–",
  flagged: "⚠",
  approved: "✅",
  rejected: "✗",
};

export default function StudentQueue({ submissions, activeSubmissionId, onSelect, onSkip }: Props) {
  if (submissions.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        No students in queue yet.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {submissions.map((sub) => {
        const isActive = sub.submission_id === activeSubmissionId;
        const statusKey = sub.status in STATUS_COLORS ? sub.status : "pending";

        return (
          <div
            key={sub.submission_id}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors cursor-pointer ${
              isActive ? "bg-indigo-50 border border-indigo-200" : "hover:bg-gray-50"
            }`}
            onClick={() => onSelect(sub.submission_id, sub.student_name)}
          >
            <span
              className={`shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-xs font-medium ${STATUS_COLORS[statusKey]}`}
            >
              {STATUS_ICON[statusKey]}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">
                {sub.student_name || "—"}
              </p>
              {sub.student_code && (
                <p className="text-xs text-gray-400 truncate">{sub.student_code}</p>
              )}
            </div>
            {sub.confidence_score !== null && sub.confidence_score !== undefined && (
              <span
                className={`text-xs font-medium shrink-0 ${
                  sub.confidence_score >= 0.9
                    ? "text-green-600"
                    : sub.confidence_score >= 0.7
                      ? "text-yellow-600"
                      : "text-red-600"
                }`}
              >
                {Math.round(sub.confidence_score * 100)}%
              </span>
            )}
            {onSkip && sub.status === "pending" && !isActive && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (sub.submission_id) onSkip(sub.submission_id);
                }}
                className="shrink-0 text-xs text-gray-400 hover:text-gray-600 px-1"
                title="Skip student"
              >
                Skip
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
