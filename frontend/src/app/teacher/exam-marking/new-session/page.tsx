"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { createSession, type CreateSessionRequest, type PaperType, type InputMethod } from "@/lib/exam-marking-api";

const PAPER_TYPES: { value: PaperType; label: string; description: string; icon: string }[] = [
  { value: "scantron", label: "Scantron / Bubble Sheet", description: "OMR only — zero AI tokens", icon: "⚫" },
  { value: "printed_mcq", label: "Printed MCQ Paper", description: "Computer vision + deterministic", icon: "☑️" },
  { value: "mixed", label: "Mixed Paper", description: "Objective + open-ended questions", icon: "📋" },
  { value: "open_ended", label: "Open-Ended Paper", description: "OCR + rubric AI grading", icon: "✍️" },
];

const INPUT_METHODS: { value: InputMethod; label: string; description: string; icon: string; available: boolean }[] = [
  { value: "smart_scan", label: "Smart Scan", description: "Use your phone's rear camera", icon: "📷", available: true },
  { value: "upload", label: "Upload Files", description: "PDF, PNG, JPG, DOCX, TXT", icon: "📤", available: true },
  { value: "office_scanner", label: "Office Scanner", description: "Sheet-fed and network scanners", icon: "🖨️", available: false },
];

export default function NewSessionPage() {
  return (
    <Suspense>
      <NewSessionForm />
    </Suspense>
  );
}

function NewSessionForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const defaultMethod = (searchParams.get("method") as InputMethod) || "upload";

  const [form, setForm] = useState<CreateSessionRequest>({
    exam_title: "",
    subject: "",
    grade: "",
    class_name: "",
    curriculum: "",
    academic_year: "",
    term: "",
    exam_date: null,
    total_marks: 0,
    time_allowed_minutes: null,
    expected_pages_per_student: 1,
    paper_type: "open_ended",
    input_method: defaultMethod,
    language: "English",
    total_students: 0,
    teacher_notes: "",
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (field: keyof CreateSessionRequest, value: unknown) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.exam_title.trim()) {
      setError("Exam title is required.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const session = await createSession(form);
      router.push(
        form.input_method === "smart_scan"
          ? `/teacher/exam-marking/${session.session_id}/scan`
          : `/teacher/exam-marking/${session.session_id}`,
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create session");
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">New Marking Session</h1>
        <p className="text-sm text-gray-500 mt-1">
          Fill in the exam details. You can scan or upload papers once the session is created.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Exam Details */}
        <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h2 className="font-semibold text-gray-800">Exam Details</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[
              { field: "exam_title" as const, label: "Exam Title *", placeholder: "e.g. Grade 6 Science Midterm", required: true },
              { field: "subject" as const, label: "Subject", placeholder: "e.g. Science" },
              { field: "grade" as const, label: "Grade", placeholder: "e.g. Grade 6" },
              { field: "class_name" as const, label: "Class", placeholder: "e.g. Section A" },
              { field: "curriculum" as const, label: "Curriculum", placeholder: "e.g. Cambridge, CAPS, IB" },
              { field: "academic_year" as const, label: "Academic Year", placeholder: "e.g. 2025-2026" },
              { field: "term" as const, label: "Term", placeholder: "e.g. Term 2" },
              { field: "language" as const, label: "Language", placeholder: "e.g. English" },
            ].map(({ field, label, placeholder, required }) => (
              <div key={field} className={field === "exam_title" ? "sm:col-span-2" : ""}>
                <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
                <input
                  type="text"
                  required={required}
                  value={String(form[field] ?? "")}
                  onChange={(e) => update(field, e.target.value)}
                  placeholder={placeholder}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 outline-none"
                />
              </div>
            ))}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Exam Date</label>
              <input
                type="date"
                value={form.exam_date ?? ""}
                onChange={(e) => update("exam_date", e.target.value || null)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-300 outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Total Marks</label>
              <input
                type="number"
                min={0}
                value={form.total_marks ?? 0}
                onChange={(e) => update("total_marks", parseInt(e.target.value) || 0)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-300 outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Student Count</label>
              <input
                type="number"
                min={0}
                value={form.total_students ?? 0}
                onChange={(e) => update("total_students", parseInt(e.target.value) || 0)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-300 outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Pages per Student</label>
              <input
                type="number"
                min={1}
                value={form.expected_pages_per_student ?? 1}
                onChange={(e) => update("expected_pages_per_student", parseInt(e.target.value) || 1)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-300 outline-none"
              />
            </div>
          </div>
        </section>

        {/* Paper Type */}
        <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <h2 className="font-semibold text-gray-800">Paper Type</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {PAPER_TYPES.map((pt) => (
              <button
                key={pt.value}
                type="button"
                onClick={() => update("paper_type", pt.value)}
                className={`flex items-start gap-3 p-4 rounded-xl border-2 text-left transition-colors ${
                  form.paper_type === pt.value
                    ? "border-indigo-500 bg-indigo-50"
                    : "border-gray-200 hover:border-gray-300"
                }`}
              >
                <span className="text-xl mt-0.5">{pt.icon}</span>
                <div>
                  <p className="font-medium text-sm text-gray-800">{pt.label}</p>
                  <p className="text-xs text-gray-500">{pt.description}</p>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Input Method */}
        <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <h2 className="font-semibold text-gray-800">Input Method</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {INPUT_METHODS.map((im) => (
              <button
                key={im.value}
                type="button"
                disabled={!im.available}
                onClick={() => im.available && update("input_method", im.value)}
                className={`flex items-start gap-3 p-4 rounded-xl border-2 text-left transition-colors ${
                  !im.available
                    ? "border-gray-100 opacity-50 cursor-not-allowed"
                    : form.input_method === im.value
                      ? "border-indigo-500 bg-indigo-50"
                      : "border-gray-200 hover:border-gray-300"
                }`}
              >
                <span className="text-xl mt-0.5">{im.icon}</span>
                <div>
                  <p className="font-medium text-sm text-gray-800">
                    {im.label}
                    {!im.available && (
                      <span className="ml-1 text-xs bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded-full">Soon</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-500">{im.description}</p>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Teacher Notes */}
        <section className="bg-white border border-gray-200 rounded-xl p-5">
          <label className="block text-xs font-medium text-gray-600 mb-1">Teacher Notes (optional)</label>
          <textarea
            rows={3}
            value={form.teacher_notes ?? ""}
            onChange={(e) => update("teacher_notes", e.target.value)}
            placeholder="Any special instructions or notes for this session…"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-300 outline-none resize-none"
          />
        </section>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 px-4 py-3 rounded-xl">{error}</div>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={loading}
            className="flex-1 py-3 bg-indigo-600 text-white rounded-xl font-semibold hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Creating session…" : "Create Session"}
          </button>
          <button
            type="button"
            onClick={() => router.back()}
            className="px-6 py-3 bg-gray-100 text-gray-700 rounded-xl font-medium hover:bg-gray-200 transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
