"use client";

import { useMemo, useState } from "react";
import { copilotApprove, copilotRun, type CopilotResponse } from "@/lib/api";

const assessmentTypes = [
  "Quiz",
  "Worksheet",
  "Homework",
  "Classwork",
  "Exit Ticket",
  "Practice Test",
  "Unit Test",
  "Midterm",
  "Final Exam",
  "Diagnostic Assessment",
  "Formative Assessment",
  "Summative Assessment",
  "Project",
  "Lab Activity",
  "Oral Assessment",
] as const;

const supportedQuestionTypes = [
  "Multiple Choice",
  "True / False",
  "Matching",
  "Fill in the Blank",
  "Short Answer",
  "Essay",
  "Problem Solving",
  "Diagram Labeling",
  "Programming Question",
  "Case Study",
  "Practical",
  "Mix of Question Types",
] as const;

const templates = ["Weekly Quiz", "Unit Test", "Midterm", "Final", "Homework", "Worksheet", "Exit Ticket"] as const;

const futureTools = ["Question Bank", "Rubrics", "Blueprint", "Difficulty Analysis", "Bloom Analysis", "Version A/B", "Analytics"] as const;
const exportTargets = ["Word", "PDF", "Google Docs", "Print", "Publish to LMS"] as const;

type Difficulty = "Easy" | "Medium" | "Hard";
type HistoryStatus = "draft" | "approved" | "rejected";

interface AssessmentQuestion {
  number: number;
  type: string;
  text: string;
  marks: number;
}

interface MarksAllocation {
  question: number;
  marks: number;
}

interface AssessmentPreviewData {
  instructions: string;
  questions: AssessmentQuestion[];
  marksAllocation: MarksAllocation[];
  totalMarks: number;
  teacherNotes: string;
  answerKeyPreview: string[];
  rubricPreview: string[];
  rawMarkdown: string;
}

interface AssessmentForm {
  curriculum: string;
  grade: string;
  subject: string;
  topic: string;
  learningObjectives: string;
  difficulty: Difficulty;
  assessmentType: string;
  questionTypes: string[];
  numberOfQuestions: number;
  marks: number;
  timeMinutes: number;
  language: string;
  specialNeeds: string;
  teacherNotes: string;
}

interface HistoryItem {
  id: string;
  requestId: string;
  generatedDate: string;
  subject: string;
  grade: string;
  assessmentType: string;
  status: HistoryStatus;
}

const defaultForm: AssessmentForm = {
  curriculum: "Cambridge",
  grade: "5",
  subject: "Science",
  topic: "Ecosystems",
  learningObjectives: "Identify ecosystem components\nExplain food chains\nApply conservation ideas to real scenarios",
  difficulty: "Medium",
  assessmentType: "Quiz",
  questionTypes: ["Multiple Choice", "Short Answer"],
  numberOfQuestions: 8,
  marks: 20,
  timeMinutes: 35,
  language: "English",
  specialNeeds: "Extra reading time for selected learners",
  teacherNotes: "Keep instructions concise and age-appropriate.",
};

const emptyPreview: AssessmentPreviewData = {
  instructions: "Generate an assessment to preview instructions, sections, questions, marks, answer key, and rubric.",
  questions: [],
  marksAllocation: [],
  totalMarks: 0,
  teacherNotes: "",
  answerKeyPreview: [],
  rubricPreview: [],
  rawMarkdown: "",
};

function toQuestionArray(value: unknown): AssessmentQuestion[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item, index) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      return {
        number: typeof row.number === "number" ? row.number : index + 1,
        type: typeof row.type === "string" ? row.type : "Question",
        text: typeof row.text === "string" ? row.text : "",
        marks: typeof row.marks === "number" ? row.marks : 0,
      };
    })
    .filter((item): item is AssessmentQuestion => Boolean(item && item.text));
}

function toMarksArray(value: unknown): MarksAllocation[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const question = typeof row.question === "number" ? row.question : 0;
      const marks = typeof row.marks === "number" ? row.marks : 0;
      if (!question) return null;
      return { question, marks };
    })
    .filter((item): item is MarksAllocation => Boolean(item));
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const row = item as Record<string, unknown>;
        if (typeof row.expected_answer === "string") return row.expected_answer;
        if (typeof row.criterion === "string" && typeof row.descriptor === "string") return `${row.criterion}: ${row.descriptor}`;
      }
      return "";
    })
    .filter(Boolean);
}

function normalizePreview(response: CopilotResponse): AssessmentPreviewData {
  const result = response.result && typeof response.result === "object" ? (response.result as Record<string, unknown>) : {};
  return {
    instructions: typeof result.instructions === "string" ? result.instructions : response.message,
    questions: toQuestionArray(result.questions),
    marksAllocation: toMarksArray(result.marks_allocation),
    totalMarks: typeof result.total_marks === "number" ? result.total_marks : 0,
    teacherNotes: typeof result.teacher_notes === "string" ? result.teacher_notes : "",
    answerKeyPreview: toStringList(result.answer_key_preview),
    rubricPreview: toStringList(result.rubric_preview),
    rawMarkdown: typeof result.raw_markdown === "string" ? result.raw_markdown : "",
  };
}

function formatLocalTime(value: Date): string {
  return value.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function AssessmentStudioPage() {
  const [form, setForm] = useState<AssessmentForm>(defaultForm);
  const [preview, setPreview] = useState<AssessmentPreviewData>(emptyPreview);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [status, setStatus] = useState<HistoryStatus>("draft");
  const [isRunning, setIsRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const totalAllocatedMarks = useMemo(() => preview.marksAllocation.reduce((sum, row) => sum + row.marks, 0), [preview.marksAllocation]);

  const updateForm = <K extends keyof AssessmentForm>(key: K, value: AssessmentForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const toggleQuestionType = (value: string) => {
    setForm((prev) => {
      const exists = prev.questionTypes.includes(value);
      const questionTypes = exists ? prev.questionTypes.filter((item) => item !== value) : [...prev.questionTypes, value];
      return {
        ...prev,
        questionTypes: questionTypes.length ? questionTypes : ["Mix of Question Types"],
      };
    });
  };

  const applyTemplate = (template: string) => {
    const templateMap: Record<string, Partial<AssessmentForm>> = {
      "Weekly Quiz": { assessmentType: "Quiz", numberOfQuestions: 8, marks: 16, timeMinutes: 25 },
      "Unit Test": { assessmentType: "Unit Test", numberOfQuestions: 20, marks: 50, timeMinutes: 70 },
      Midterm: { assessmentType: "Midterm", numberOfQuestions: 30, marks: 75, timeMinutes: 90 },
      Final: { assessmentType: "Final Exam", numberOfQuestions: 40, marks: 100, timeMinutes: 120 },
      Homework: { assessmentType: "Homework", numberOfQuestions: 10, marks: 20, timeMinutes: 30 },
      Worksheet: { assessmentType: "Worksheet", numberOfQuestions: 12, marks: 24, timeMinutes: 40 },
      "Exit Ticket": { assessmentType: "Exit Ticket", numberOfQuestions: 5, marks: 10, timeMinutes: 12 },
    };

    setForm((prev) => ({ ...prev, ...(templateMap[template] || {}) }));
  };

  const generateAssessment = async () => {
    setIsRunning(true);
    setErrorMessage(null);
    setStatus("draft");

    try {
      const learningObjectives = form.learningObjectives
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

      const response = await copilotRun({
        intent: "assessment_generation",
        message: `Generate ${form.assessmentType} for ${form.subject} - ${form.topic}`,
        structured_input: {
          curriculum: form.curriculum,
          grade: form.grade,
          subject: form.subject,
          topic: form.topic,
          learning_objectives: learningObjectives,
          difficulty: form.difficulty,
          assessment_type: form.assessmentType,
          question_types: form.questionTypes,
          number_of_questions: form.numberOfQuestions,
          total_marks: form.marks,
          duration_minutes: form.timeMinutes,
          language: form.language,
          special_needs: form.specialNeeds,
          teacher_notes: form.teacherNotes,
        },
      });

      setRequestId(response.request_id);
      setPreview(normalizePreview(response));

      const entry: HistoryItem = {
        id: `${response.request_id}-${Date.now()}`,
        requestId: response.request_id,
        generatedDate: formatLocalTime(new Date()),
        subject: form.subject,
        grade: form.grade,
        assessmentType: form.assessmentType,
        status: "draft",
      };
      setHistory((prev) => [entry, ...prev]);
    } catch {
      setErrorMessage("Assessment generation is currently unavailable. Please retry.");
    } finally {
      setIsRunning(false);
    }
  };

  const setHistoryStatus = (targetRequestId: string, nextStatus: HistoryStatus) => {
    setHistory((prev) => prev.map((item) => (item.requestId === targetRequestId ? { ...item, status: nextStatus } : item)));
  };

  const approveAssessment = async () => {
    if (!requestId) return;
    setIsRunning(true);
    try {
      await copilotApprove({ request_id: requestId, approved: true, notes: "Approved from Assessment Studio" });
      setStatus("approved");
      setHistoryStatus(requestId, "approved");
    } catch {
      setErrorMessage("Could not approve this assessment. Please retry.");
    } finally {
      setIsRunning(false);
    }
  };

  const rejectAssessment = async () => {
    if (!requestId) return;
    setIsRunning(true);
    try {
      await copilotApprove({ request_id: requestId, approved: false, notes: "Rejected from Assessment Studio" });
      setStatus("rejected");
      setHistoryStatus(requestId, "rejected");
    } catch {
      setErrorMessage("Could not update rejection status. Please retry.");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="space-y-6 lg:space-y-8">
      <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.35em] text-indigo-600">Assessment Studio</p>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-gray-900 sm:text-3xl">Enterprise assessment workspace</h1>
            <p className="mt-3 text-sm text-gray-600">Design, review, and approve high-quality assessments with a workflow-ready foundation for future assessment tools.</p>
          </div>
          <div className="rounded-2xl border border-indigo-100 bg-indigo-50/80 px-4 py-3 text-sm text-indigo-700">
            <p className="font-medium">Assessment Generation Agent active</p>
            <p className="mt-1">Question Bank, Rubrics, Blueprint, and Analytics are staged as future plugins.</p>
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {["Assessment Builder", "Assessment History", "Assessment Templates", "Question Types", "Assessment Preview"].map((item) => (
            <div key={item} className="rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-gray-600">
              {item}
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="space-y-6 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Assessment Builder</h2>
            <p className="mt-1 text-sm text-gray-500">Configure scope, rigor, and structure before generation.</p>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Curriculum</span>
              <input value={form.curriculum} onChange={(event) => updateForm("curriculum", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Grade</span>
              <input value={form.grade} onChange={(event) => updateForm("grade", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Subject</span>
              <input value={form.subject} onChange={(event) => updateForm("subject", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Topic</span>
              <input value={form.topic} onChange={(event) => updateForm("topic", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm md:col-span-2">
              <span className="font-medium text-gray-700">Learning Objectives (one per line)</span>
              <textarea
                value={form.learningObjectives}
                onChange={(event) => updateForm("learningObjectives", event.target.value)}
                rows={4}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700"
              />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Difficulty</span>
              <select value={form.difficulty} onChange={(event) => updateForm("difficulty", event.target.value as Difficulty)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700">
                <option value="Easy">Easy</option>
                <option value="Medium">Medium</option>
                <option value="Hard">Hard</option>
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Assessment Type</span>
              <select value={form.assessmentType} onChange={(event) => updateForm("assessmentType", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700">
                {assessmentTypes.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Number of Questions</span>
              <input
                type="number"
                min={1}
                max={100}
                value={form.numberOfQuestions}
                onChange={(event) => updateForm("numberOfQuestions", Number(event.target.value) || 1)}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700"
              />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Marks</span>
              <input type="number" min={1} value={form.marks} onChange={(event) => updateForm("marks", Number(event.target.value) || 1)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Time (minutes)</span>
              <input
                type="number"
                min={5}
                max={240}
                value={form.timeMinutes}
                onChange={(event) => updateForm("timeMinutes", Number(event.target.value) || 5)}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700"
              />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-gray-700">Language</span>
              <input value={form.language} onChange={(event) => updateForm("language", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm md:col-span-2">
              <span className="font-medium text-gray-700">Special Needs</span>
              <input value={form.specialNeeds} onChange={(event) => updateForm("specialNeeds", event.target.value)} className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700" />
            </label>
            <label className="space-y-2 text-sm md:col-span-2">
              <span className="font-medium text-gray-700">Teacher Notes</span>
              <textarea
                value={form.teacherNotes}
                onChange={(event) => {
                  updateForm("teacherNotes", event.target.value);
                  setPreview((prev) => ({ ...prev, teacherNotes: event.target.value }));
                }}
                rows={3}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-700"
              />
            </label>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
            <p className="text-sm font-semibold text-gray-800">Question Types</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {supportedQuestionTypes.map((item) => {
                const checked = form.questionTypes.includes(item);
                return (
                  <label key={item} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm ${checked ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-gray-200 bg-white text-gray-700"}`}>
                    <input type="checkbox" checked={checked} onChange={() => toggleQuestionType(item)} className="h-4 w-4" />
                    <span>{item}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void generateAssessment()}
              disabled={isRunning}
              className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
            >
              {isRunning ? "Generating..." : "Generate Assessment"}
            </button>
            <button
              type="button"
              onClick={() => void generateAssessment()}
              disabled={isRunning}
              className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-indigo-200"
            >
              Regenerate
            </button>
            <button
              type="button"
              onClick={() => setStatus("draft")}
              className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-indigo-200"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => void rejectAssessment()}
              disabled={!requestId || isRunning}
              className="rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Reject
            </button>
            <button
              type="button"
              onClick={() => void approveAssessment()}
              disabled={!requestId || isRunning}
              className="rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-300"
            >
              Approve
            </button>
            <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600">Status: {status}</span>
          </div>

          {errorMessage ? <p className="text-sm font-medium text-rose-600">{errorMessage}</p> : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-900">Assessment Templates</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {templates.map((template) => (
                  <button
                    key={template}
                    type="button"
                    onClick={() => applyTemplate(template)}
                    className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-semibold text-gray-700 transition hover:border-indigo-200 hover:text-indigo-700"
                  >
                    {template}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-900">Future Tools</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {futureTools.map((tool) => (
                  <span key={tool} className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-500">
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-gray-900">Assessment History</p>
              <span className="text-xs text-gray-500">Database integration ready</span>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-[0.15em] text-gray-500">
                  <tr>
                    <th className="pb-2">Status</th>
                    <th className="pb-2">Generated Date</th>
                    <th className="pb-2">Subject</th>
                    <th className="pb-2">Grade</th>
                    <th className="pb-2">Assessment Type</th>
                  </tr>
                </thead>
                <tbody>
                  {history.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-4 text-sm text-gray-500">
                        No generated assessments yet.
                      </td>
                    </tr>
                  ) : (
                    history.map((item) => (
                      <tr key={item.id} className="border-t border-gray-100">
                        <td className="py-2">
                          <span
                            className={`rounded-full px-2 py-1 text-xs font-semibold ${
                              item.status === "approved"
                                ? "bg-emerald-100 text-emerald-700"
                                : item.status === "rejected"
                                  ? "bg-rose-100 text-rose-700"
                                  : "bg-amber-100 text-amber-700"
                            }`}
                          >
                            {item.status}
                          </span>
                        </td>
                        <td className="py-2 text-gray-600">{item.generatedDate}</td>
                        <td className="py-2 text-gray-700">{item.subject}</td>
                        <td className="py-2 text-gray-700">{item.grade}</td>
                        <td className="py-2 text-gray-700">{item.assessmentType}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="space-y-4 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Assessment Preview</h2>
            <p className="mt-1 text-sm text-gray-500">Professional output view before approval and future export.</p>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">Instructions</p>
            <p className="mt-2 text-sm leading-6 text-gray-700">{preview.instructions}</p>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-gray-900">Questions</p>
              <span className="text-xs text-gray-500">{preview.questions.length} items</span>
            </div>
            <ol className="mt-3 space-y-3">
              {preview.questions.length === 0 ? (
                <li className="text-sm text-gray-500">Questions will appear after generation.</li>
              ) : (
                preview.questions.map((question) => (
                  <li key={`${question.number}-${question.type}`} className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.15em] text-gray-500">
                      Q{question.number} - {question.type}
                    </p>
                    <p className="mt-1 text-sm text-gray-700">{question.text}</p>
                    <p className="mt-2 text-xs font-medium text-gray-500">Marks: {question.marks}</p>
                  </li>
                ))
              )}
            </ol>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-900">Marks</p>
              <ul className="mt-2 space-y-1 text-sm text-gray-600">
                {preview.marksAllocation.map((row) => (
                  <li key={`m-${row.question}`}>
                    Q{row.question}: {row.marks}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-900">Total Marks</p>
              <p className="mt-2 text-2xl font-semibold text-gray-800">{preview.totalMarks || totalAllocatedMarks}</p>
              <p className="mt-1 text-xs text-gray-500">Calculated from marks allocation when needed.</p>
            </div>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-sm font-semibold text-gray-900">Teacher Notes</p>
            <p className="mt-2 text-sm text-gray-700">{preview.teacherNotes || "No notes provided."}</p>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-sm font-semibold text-gray-900">Answer Key Preview</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-700">
              {preview.answerKeyPreview.length ? preview.answerKeyPreview.map((item) => <li key={item}>{item}</li>) : <li>Answer key preview will appear after generation.</li>}
            </ul>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-sm font-semibold text-gray-900">Rubric Preview</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-700">
              {preview.rubricPreview.length ? preview.rubricPreview.map((item) => <li key={item}>{item}</li>) : <li>Rubric preview will appear after generation.</li>}
            </ul>
          </div>

          <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 p-4">
            <p className="text-sm font-semibold text-gray-900">Export</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {exportTargets.map((target) => (
                <button key={target} type="button" disabled className="cursor-not-allowed rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-semibold text-gray-500">
                  {target} - Coming Soon
                </button>
              ))}
            </div>
          </div>

          {preview.rawMarkdown ? (
            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-900">Model Draft (Markdown)</p>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap text-xs text-gray-600">{preview.rawMarkdown}</pre>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
