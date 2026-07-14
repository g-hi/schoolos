"use client";

import Link from "next/link";
import { type MarkingSession, paperTypeLabel, statusColor, statusLabel } from "@/lib/exam-marking-api";

interface Props {
  session: MarkingSession;
}

export default function SessionCard({ session }: Props) {
  const progress =
    session.total_students > 0
      ? Math.round((session.captured_students / session.total_students) * 100)
      : 0;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 truncate">{session.exam_title}</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            {session.subject} · {session.grade} {session.class_name}
          </p>
        </div>
        <span
          className={`ml-3 shrink-0 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColor(session.status)}`}
        >
          {statusLabel(session.status)}
        </span>
      </div>

      <div className="text-xs text-gray-500 mb-3">
        {paperTypeLabel(session.paper_type)} · {session.total_marks} marks
      </div>

      {session.total_students > 0 && (
        <div className="mb-3">
          <div className="flex justify-between text-xs text-gray-600 mb-1">
            <span>
              {session.captured_students}/{session.total_students} students
            </span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-1.5">
            <div
              className="bg-indigo-500 h-1.5 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {session.average_confidence !== null && (
        <p className="text-xs text-gray-500 mb-3">
          Avg confidence:{" "}
          <span
            className={
              session.average_confidence >= 0.9
                ? "text-green-600 font-medium"
                : session.average_confidence >= 0.7
                  ? "text-yellow-600 font-medium"
                  : "text-red-600 font-medium"
            }
          >
            {Math.round(session.average_confidence * 100)}%
          </span>
        </p>
      )}

      <div className="flex gap-2 mt-3 pt-3 border-t border-gray-100">
        <Link
          href={`/teacher/exam-marking/${session.session_id}`}
          className="flex-1 text-center text-xs font-medium px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
        >
          {session.status === "pending_review" || session.status === "partially_approved"
            ? "Review"
            : session.status === "draft" || session.status === "scanning" || session.status === "uploading"
              ? "Continue"
              : "View"}
        </Link>
        {session.flagged_students > 0 && (
          <Link
            href={`/teacher/exam-marking/${session.session_id}/review`}
            className="text-xs font-medium px-3 py-1.5 rounded-lg bg-orange-50 text-orange-700 hover:bg-orange-100 transition-colors"
          >
            {session.flagged_students} flagged
          </Link>
        )}
      </div>
    </div>
  );
}
