"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import SmartScanCapture from "@/components/exam-marking/smart-scan-capture";
import { type PageUploadResponse } from "@/lib/exam-marking-api";
import { useState } from "react";

/**
 * Smart Scan page — dedicated full-screen scanning experience.
 *
 * The teacher starts scanning here after session creation with method=smart_scan.
 * The continuous scan architecture is abstracted via SmartScanCapture which
 * wraps the ManualScanProvider (V1).
 *
 * Architecture note:
 * V2 will implement AutoScanProvider using WebRTC getUserMedia + edge detection.
 * This page interface (onPageUploaded, onStudentComplete callbacks) stays unchanged.
 */
export default function ScanPage() {
  const params = useParams<{ sessionId: string }>();
  const router = useRouter();
  const sessionId = params.sessionId;

  const [currentStudent, setCurrentStudent] = useState({ name: "", code: "", submissionId: undefined as string | undefined });
  const [completedStudents, setCompletedStudents] = useState(0);
  const [studentNameInput, setStudentNameInput] = useState("");
  const [studentCodeInput, setStudentCodeInput] = useState("");
  const [editingStudent, setEditingStudent] = useState(true);

  const handlePageUploaded = (resp: PageUploadResponse, pageNum: number) => {
    if (!currentStudent.submissionId) {
      setCurrentStudent((prev) => ({ ...prev, submissionId: resp.submission_id }));
    }
    console.info(`Page ${pageNum} uploaded: ${resp.page_id}`);
  };

  const handleStudentComplete = () => {
    setCompletedStudents((n) => n + 1);
    setCurrentStudent({ name: "", code: "", submissionId: undefined });
    setStudentNameInput("");
    setStudentCodeInput("");
    setEditingStudent(true);
  };

  const startStudent = () => {
    setCurrentStudent({ name: studentNameInput, code: studentCodeInput, submissionId: undefined });
    setEditingStudent(false);
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link href={`/teacher/exam-marking/${sessionId}`} className="text-sm text-gray-400 hover:text-gray-600">
            ← Session
          </Link>
          <span className="text-gray-300">/</span>
          <span className="text-sm font-medium text-gray-700">Smart Scan</span>
        </div>
        {completedStudents > 0 && (
          <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full font-medium">
            {completedStudents} student{completedStudents !== 1 ? "s" : ""} complete
          </span>
        )}
      </div>

      {/* Student identification */}
      {editingStudent ? (
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h2 className="font-semibold text-gray-800">Identify Student</h2>
          <p className="text-sm text-gray-500">
            Enter the student&apos;s name before scanning their paper.
            Future: QR code or barcode identification.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Student Name</label>
              <input
                type="text"
                value={studentNameInput}
                onChange={(e) => setStudentNameInput(e.target.value)}
                placeholder="e.g. Amira Osei"
                autoFocus
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Student Code</label>
              <input
                type="text"
                value={studentCodeInput}
                onChange={(e) => setStudentCodeInput(e.target.value)}
                placeholder="e.g. STU-042"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={startStudent}
            disabled={!studentNameInput.trim()}
            className="w-full py-3 bg-indigo-600 text-white rounded-xl font-semibold hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Start Scanning {studentNameInput || "Student"}
          </button>
        </div>
      ) : (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl px-4 py-3 flex items-center justify-between">
          <div>
            <p className="font-semibold text-indigo-800">{currentStudent.name}</p>
            {currentStudent.code && <p className="text-xs text-indigo-600">{currentStudent.code}</p>}
          </div>
          <button
            type="button"
            onClick={() => setEditingStudent(true)}
            className="text-xs text-indigo-500 hover:text-indigo-700"
          >
            Change
          </button>
        </div>
      )}

      {/* Scan capture */}
      {!editingStudent && (
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Scan Pages</h2>
          <SmartScanCapture
            sessionId={sessionId}
            submissionId={currentStudent.submissionId}
            studentName={currentStudent.name}
            studentCode={currentStudent.code}
            onPageUploaded={handlePageUploaded}
            onStudentComplete={handleStudentComplete}
          />
        </div>
      )}

      {/* Done scanning */}
      {completedStudents > 0 && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 flex items-center justify-between">
          <p className="text-sm text-green-700 font-medium">
            {completedStudents} student{completedStudents !== 1 ? "s" : ""} scanned.
          </p>
          <Link
            href={`/teacher/exam-marking/${sessionId}`}
            className="text-xs px-3 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium"
          >
            View Session →
          </Link>
        </div>
      )}

      {/* QR/barcode placeholder */}
      <div className="bg-gray-50 border border-dashed border-gray-200 rounded-xl p-4 text-sm text-gray-400 text-center">
        Future: QR code and barcode student identification. Tap the QR icon to scan the student ID barcode automatically.
      </div>
    </div>
  );
}
