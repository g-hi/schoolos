"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getSession,
  listSubmissions,
  uploadPage,
  markStudentComplete,
  type MarkingSession,
  type SubmissionSummary,
  type PageUploadResponse,
  paperTypeLabel,
  statusColor,
  statusLabel,
} from "@/lib/exam-marking-api";
import StudentQueue from "@/components/exam-marking/student-queue";
import SmartScanCapture from "@/components/exam-marking/smart-scan-capture";

export default function SessionDetailPage() {
  const params = useParams<{ sessionId: string }>();
  const router = useRouter();
  const sessionId = params.sessionId;

  const [session, setSession] = useState<MarkingSession | null>(null);
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSubmissionId, setActiveSubmissionId] = useState<string | undefined>();
  const [activeStudentName, setActiveStudentName] = useState("");
  const [inputTab, setInputTab] = useState<"smart_scan" | "upload">("upload");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [newStudentName, setNewStudentName] = useState("");
  const [newStudentCode, setNewStudentCode] = useState("");

  const refresh = async () => {
    try {
      const [sess, subs] = await Promise.all([getSession(sessionId), listSubmissions(sessionId)]);
      setSession(sess);
      setSubmissions(subs);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [sessionId]);

  const handleSelectStudent = (submissionId: string | undefined, name: string) => {
    setActiveSubmissionId(submissionId);
    setActiveStudentName(name);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setUploading(true);
    setUploadError(null);
    try {
      let currentSubmissionId = activeSubmissionId;
      for (let i = 0; i < files.length; i++) {
        const result = await uploadPage(
          sessionId,
          files[i],
          i + 1,
          currentSubmissionId,
          newStudentName || activeStudentName,
          newStudentCode,
        );
        if (!currentSubmissionId) currentSubmissionId = result.submission_id;
      }
      await refresh();
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handlePageUploaded = async (_resp: PageUploadResponse, _pageNum: number) => {
    await refresh();
  };

  const handleStudentComplete = async () => {
    if (!activeSubmissionId) return;
    try {
      await markStudentComplete(sessionId, activeSubmissionId);
      setActiveSubmissionId(undefined);
      setActiveStudentName("");
      setNewStudentName("");
      setNewStudentCode("");
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to complete student");
    }
  };

  if (loading) {
    return <div className="animate-pulse h-8 bg-gray-100 rounded w-48" />;
  }
  if (error || !session) {
    return <div className="text-red-600 bg-red-50 px-4 py-3 rounded-xl text-sm">{error ?? "Session not found"}</div>;
  }

  const captured = submissions.length;
  const progress = session.total_students > 0 ? Math.round((captured / session.total_students) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Session header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link href="/teacher/exam-marking" className="text-sm text-gray-400 hover:text-gray-600">
              ← Marking Studio
            </Link>
          </div>
          <h1 className="text-xl font-bold text-gray-900">{session.exam_title}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {session.subject} · {session.grade} {session.class_name} · {paperTypeLabel(session.paper_type)}
          </p>
        </div>
        <span className={`shrink-0 inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${statusColor(session.status)}`}>
          {statusLabel(session.status)}
        </span>
      </div>

      {/* Progress bar */}
      {session.total_students > 0 && (
        <div>
          <div className="flex justify-between text-xs text-gray-600 mb-1">
            <span>{captured} / {session.total_students} students captured</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div className="bg-indigo-500 h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Student Queue */}
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-3">Student Queue</h2>
          <StudentQueue
            submissions={submissions}
            activeSubmissionId={activeSubmissionId}
            onSelect={handleSelectStudent}
          />
          <button
            type="button"
            onClick={() => {
              setActiveSubmissionId(undefined);
              setActiveStudentName("");
            }}
            className="mt-3 w-full text-xs py-2 bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100 transition-colors font-medium"
          >
            + Add New Student
          </button>
        </div>

        {/* Upload / Scan area */}
        <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          {/* Student selector for new student */}
          {!activeSubmissionId && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Student Name</label>
                <input
                  type="text"
                  value={newStudentName}
                  onChange={(e) => setNewStudentName(e.target.value)}
                  placeholder="e.g. John Smith"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Student Code</label>
                <input
                  type="text"
                  value={newStudentCode}
                  onChange={(e) => setNewStudentCode(e.target.value)}
                  placeholder="e.g. STU-001"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>
            </div>
          )}

          {activeSubmissionId && (
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-gray-800">
                Scanning: <span className="text-indigo-600">{activeStudentName}</span>
              </span>
              <button type="button" onClick={() => setActiveSubmissionId(undefined)} className="text-xs text-gray-400 hover:text-gray-600">
                Change student
              </button>
            </div>
          )}

          {/* Input method tabs */}
          <div className="flex gap-1 p-1 bg-gray-100 rounded-lg w-fit">
            {(["smart_scan", "upload"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setInputTab(tab)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  inputTab === tab ? "bg-white shadow-sm text-indigo-700" : "text-gray-500 hover:text-gray-700"
                }`}
              >
                {tab === "smart_scan" ? "📷 Smart Scan" : "📤 Upload Files"}
              </button>
            ))}
          </div>

          {inputTab === "smart_scan" ? (
            <SmartScanCapture
              sessionId={sessionId}
              submissionId={activeSubmissionId}
              studentName={newStudentName || activeStudentName}
              studentCode={newStudentCode}
              onPageUploaded={handlePageUploaded}
              onStudentComplete={async () => {
                if (activeSubmissionId) await handleStudentComplete();
                else await refresh();
              }}
            />
          ) : (
            <div className="space-y-3">
              <label className="flex flex-col items-center justify-center gap-3 border-2 border-dashed border-gray-300 rounded-xl p-8 cursor-pointer hover:border-indigo-400 hover:bg-indigo-50/30 transition-colors">
                <span className="text-3xl">📤</span>
                <div className="text-center">
                  <p className="font-medium text-gray-700">Drop files here or click to upload</p>
                  <p className="text-xs text-gray-400 mt-0.5">PDF, PNG, JPG, JPEG, DOCX, TXT · max 20 MB</p>
                </div>
                <input
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.docx,.txt"
                  multiple
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={uploading}
                />
              </label>
              {uploading && (
                <div className="flex items-center gap-2 text-sm text-blue-600">
                  <span className="animate-spin">⏳</span> Uploading…
                </div>
              )}
              {uploadError && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{uploadError}</div>
              )}
            </div>
          )}

          {/* Process button */}
          {submissions.some((s) => s.status === "pending") && (
            <div className="pt-3 border-t border-gray-100">
              <Link
                href={`/teacher/exam-marking/${sessionId}/review`}
                className="w-full block text-center py-3 bg-green-600 text-white rounded-xl font-semibold hover:bg-green-700 transition-colors text-sm"
              >
                Process & Review Papers →
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
