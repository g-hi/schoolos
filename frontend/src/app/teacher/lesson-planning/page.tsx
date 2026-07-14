"use client";

import { useMemo, useState } from "react";
import { copilotApprove, copilotContinue, copilotRun } from "@/lib/api";
import type { LessonPlanInput, TeacherContext } from "@/lib/teacher-copilot/types";

const baseContext: TeacherContext = {
  curriculum: "International Primary Curriculum",
  grade: "Grade 6",
  subject: "Mathematics",
  school: "Greenwood International Academy",
  term: "Fall Semester · 2025–2026",
  language: "English",
  upcomingLessons: ["Fractions review", "Geometry investigation", "Science integration task"],
};

const defaultInput: LessonPlanInput = {
  curriculum: baseContext.curriculum,
  grade: baseContext.grade,
  subject: baseContext.subject,
  topic: "Fractions and decimals",
  duration: "45 minutes",
  learningObjectives: ["Understand equivalent fractions", "Apply fraction comparisons in simple problems"],
  teachingStrategy: "Inquiry-based learning with worked examples",
  differentiation: "Offer visual models and extension challenges",
  specialNeeds: "Provide chunking and scaffolded examples",
  assessmentMethod: "Observation checklist and exit ticket",
  homework: "Complete one practice worksheet",
  resources: "Projector, manipulatives, worksheet",
  language: baseContext.language,
  teacherNotes: "Keep the pace brisk and check understanding often.",
};

export default function LessonPlanningPage() {
  const [input, setInput] = useState<LessonPlanInput>(defaultInput);
  const [result, setResult] = useState<string>("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [workflowStatus, setWorkflowStatus] = useState<string | null>(null);
  const [workflowStep, setWorkflowStep] = useState<string | null>(null);
  const [clarificationQuestion, setClarificationQuestion] = useState<string>("");
  const [isGenerating, setIsGenerating] = useState(false);
  const progressLabel = useMemo(() => {
    if (workflowStatus === "pending_review" || workflowStatus === "approved" || workflowStep === "human_approval") return "Ready for review";
    if (workflowStep === "validation") return "Validating output";
    if (workflowStep === "lesson_planning" || workflowStep === "revision") return "Generating lesson";
    if (workflowStep === "context_loader" || workflowStep === "missing_information") return "Loading context";
    if (workflowStep === "request_validation" || workflowStep === "intent_router") return "Understanding request";
    if (workflowStatus === "error" || workflowStatus === "unsupported_intent") return "Safe fallback";
    return "Understanding request";
  }, [workflowStatus, workflowStep]);

  const handleGenerate = async () => {
    setIsGenerating(true);
    try {
      const response = requestId && workflowStatus === "needs_clarification"
        ? await copilotContinue({
            request_id: requestId,
            structured_input: {
              grade: input.grade,
              subject: input.subject,
              topic: input.topic,
              duration_minutes: Number(input.duration) || undefined,
            },
          })
        : await copilotRun({
            intent: "lesson_planning",
            message: `Create a ${input.grade} ${input.subject} lesson about ${input.topic}`,
            structured_input: {
              curriculum: input.curriculum,
              grade: input.grade,
              subject: input.subject,
              topic: input.topic,
              duration_minutes: Number(input.duration) || undefined,
            },
          });

      setRequestId(response.request_id);
      setWorkflowStatus(response.status);
      setWorkflowStep(response.execution.current_step);
      setClarificationQuestion(response.clarification_question || "");

      const rendered = typeof response.result?.raw_markdown === "string"
        ? response.result.raw_markdown
        : response.message;
      setResult(rendered);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = async () => {
    if (!requestId) return;
    setIsGenerating(true);
    try {
      const response = await copilotApprove({ request_id: requestId, approved: true });
      setWorkflowStatus(response.status);
      setWorkflowStep(response.execution.current_step);
      setResult(response.message);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.35em] text-indigo-600">Lesson Planning</p>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-gray-900">Create an AI-assisted lesson plan</h1>
            <p className="mt-3 text-sm leading-6 text-gray-600">This workspace runs the backend LangGraph workflow with teacher approval before use.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">{progressLabel}</span>
            <button
              type="button"
              onClick={handleGenerate}
              className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700"
            >
              {isGenerating ? "Generating..." : workflowStatus === "needs_clarification" ? "Continue" : "Generate plan"}
            </button>
            {workflowStatus === "pending_review" ? (
              <button type="button" onClick={handleApprove} className="rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700">
                Approve
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Lesson brief</h2>
          <div className="mt-4 space-y-3">
            <label className="block text-sm font-medium text-gray-700">
              Topic
              <input
                value={input.topic}
                onChange={(event) => setInput((prev) => ({ ...prev, topic: event.target.value }))}
                className="mt-2 w-full rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              Grade
              <input
                value={input.grade}
                onChange={(event) => setInput((prev) => ({ ...prev, grade: event.target.value }))}
                className="mt-2 w-full rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              Subject
              <input
                value={input.subject}
                onChange={(event) => setInput((prev) => ({ ...prev, subject: event.target.value }))}
                className="mt-2 w-full rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              Duration
              <input
                value={input.duration}
                onChange={(event) => setInput((prev) => ({ ...prev, duration: event.target.value }))}
                className="mt-2 w-full rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              Learning objectives
              <textarea
                rows={4}
                value={input.learningObjectives.join("\n")}
                onChange={(event) => setInput((prev) => ({ ...prev, learningObjectives: event.target.value.split("\n").filter(Boolean) }))}
                className="mt-2 w-full rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none"
              />
            </label>
          </div>
        </section>

        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Generated lesson plan</h2>
          {workflowStatus === "needs_clarification" && clarificationQuestion ? (
            <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {clarificationQuestion}
            </div>
          ) : null}
          <div className="mt-4 rounded-2xl border border-gray-200 bg-slate-50 p-4 text-sm leading-7 text-gray-700">
            {result ? (
              <div className="whitespace-pre-wrap">{result}</div>
            ) : (
              <p className="text-gray-500">Use the brief panel to describe the lesson and generate a structured plan.</p>
            )}
          </div>
          {requestId ? <p className="mt-3 text-xs text-gray-500">Request ID: {requestId}</p> : null}
        </section>
      </div>
    </div>
  );
}
