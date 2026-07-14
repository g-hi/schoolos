"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listSessions,
  type MarkingSession,
} from "@/lib/exam-marking-api";
import SessionCard from "@/components/exam-marking/session-card";

interface MetricCardProps {
  label: string;
  value: string | number;
  icon: string;
  color?: string;
}

function MetricCard({ label, value, icon, color = "text-gray-900" }: MetricCardProps) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <div className="flex items-center gap-3">
        <span className="text-2xl">{icon}</span>
        <div>
          <p className={`text-xl font-bold ${color}`}>{value}</p>
          <p className="text-xs text-gray-500 mt-0.5">{label}</p>
        </div>
      </div>
    </div>
  );
}

export default function ExamMarkingHome() {
  const [sessions, setSessions] = useState<MarkingSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSessions()
      .then(setSessions)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load sessions"))
      .finally(() => setLoading(false));
  }, []);

  const activeSessions = sessions.filter((s) =>
    ["scanning", "uploading", "processing", "pending_review", "partially_approved"].includes(s.status),
  ).length;
  const totalPapers = sessions.reduce((sum, s) => sum + (s.processed_students || 0), 0);
  const pendingReview = sessions.reduce(
    (sum, s) =>
      sum +
      (["pending_review", "partially_approved"].includes(s.status)
        ? s.total_students - s.approved_students
        : 0),
    0,
  );
  const flaggedPapers = sessions.reduce((sum, s) => sum + (s.flagged_students || 0), 0);
  const confSessions = sessions.filter((s) => s.average_confidence !== null);
  const avgConfidence =
    confSessions.length > 0
      ? Math.round(
          (confSessions.reduce((sum, s) => sum + (s.average_confidence ?? 0), 0) / confSessions.length) * 100,
        )
      : null;

  const recentSessions = sessions.slice(0, 6);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Assessment Review & Marking Studio</h1>
          <p className="text-sm text-gray-500 mt-1">
            AI assists. Teachers decide. Every mark requires approval.
          </p>
        </div>
        <Link
          href="/teacher/exam-marking/new-session"
          className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 transition-colors shadow-sm text-sm"
        >
          <span>＋</span> New Session
        </Link>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <MetricCard label="Active Sessions" value={activeSessions} icon="📋" />
        <MetricCard label="Papers Processed" value={totalPapers} icon="📄" />
        <MetricCard
          label="Pending Review"
          value={pendingReview}
          icon="⏳"
          color={pendingReview > 0 ? "text-orange-600" : "text-gray-900"}
        />
        <MetricCard
          label="Low-Confidence"
          value={flaggedPapers}
          icon="⚠️"
          color={flaggedPapers > 0 ? "text-red-600" : "text-gray-900"}
        />
        <MetricCard
          label="Avg Confidence"
          value={avgConfidence !== null ? `${avgConfidence}%` : "—"}
          icon="📊"
          color={
            avgConfidence === null
              ? "text-gray-400"
              : avgConfidence >= 90
                ? "text-green-600"
                : avgConfidence >= 70
                  ? "text-yellow-600"
                  : "text-red-600"
          }
        />
        <MetricCard label="Est. Time Saved" value={`${Math.round(totalPapers * 0.5)} min`} icon="⏱️" />
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">Quick Actions</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
          {[
            { href: "/teacher/exam-marking/new-session?method=smart_scan", label: "Start Smart Scan", icon: "📷", color: "bg-indigo-50 text-indigo-700 hover:bg-indigo-100" },
            { href: "/teacher/exam-marking/new-session?method=upload", label: "Upload Papers", icon: "📤", color: "bg-blue-50 text-blue-700 hover:bg-blue-100" },
            {
              href: sessions.find((s) => ["scanning", "uploading", "processing"].includes(s.status))
                ? `/teacher/exam-marking/${sessions.find((s) => ["scanning", "uploading", "processing"].includes(s.status))?.session_id}`
                : "/teacher/exam-marking/new-session",
              label: "Continue Session",
              icon: "▶️",
              color: "bg-green-50 text-green-700 hover:bg-green-100",
            },
            {
              href: sessions.find((s) => s.flagged_students > 0)
                ? `/teacher/exam-marking/${sessions.find((s) => s.flagged_students > 0)?.session_id}/review`
                : "#",
              label: "Review Flagged",
              icon: "🚩",
              color: "bg-orange-50 text-orange-700 hover:bg-orange-100",
            },
            { href: "#", label: "View Completed", icon: "✅", color: "bg-gray-50 text-gray-700 hover:bg-gray-100" },
          ].map((action) => (
            <Link
              key={action.label}
              href={action.href}
              className={`flex flex-col items-center gap-2 p-4 rounded-xl font-medium text-sm transition-colors ${action.color}`}
            >
              <span className="text-2xl">{action.icon}</span>
              <span className="text-center leading-tight">{action.label}</span>
            </Link>
          ))}
        </div>
      </div>

      {/* Recent Sessions */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">
            Recent Marking Sessions
          </h2>
        </div>
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-44 bg-gray-100 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="text-sm text-red-600 bg-red-50 px-4 py-3 rounded-xl">{error}</div>
        ) : recentSessions.length === 0 ? (
          <div className="text-center py-12 bg-gray-50 rounded-xl border border-dashed border-gray-200">
            <p className="text-3xl mb-2">📝</p>
            <p className="text-gray-600 font-medium">No marking sessions yet</p>
            <p className="text-sm text-gray-400 mt-1">Create your first session to get started.</p>
            <Link
              href="/teacher/exam-marking/new-session"
              className="mt-4 inline-flex items-center gap-1 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700"
            >
              ＋ New Session
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {recentSessions.map((session) => (
              <SessionCard key={session.session_id} session={session} />
            ))}
          </div>
        )}
      </div>

      {/* Office Scanner Placeholder */}
      <div className="bg-gray-50 border border-dashed border-gray-200 rounded-xl p-6 flex items-center gap-4">
        <span className="text-3xl">🖨️</span>
        <div>
          <p className="font-medium text-gray-700">Office Scanner Integration</p>
          <p className="text-sm text-gray-400">
            Connect portable scanners, sheet-fed scanners, and multifunction printers. Coming soon.
          </p>
        </div>
        <span className="ml-auto shrink-0 text-xs bg-gray-200 text-gray-500 px-2 py-1 rounded-full">
          Coming Soon
        </span>
      </div>
    </div>
  );
}
