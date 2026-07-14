"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { copilotApprove, copilotContinue, copilotRun } from "@/lib/api";
import type { ConversationMessage } from "@/lib/teacher-copilot/types";

type Message = ConversationMessage;

const recentConversations = [
  { id: 1, title: "Today's Lesson Planning", preview: "We'll prepare the next teaching sequence..." },
  { id: 2, title: "Grade 6 Mathematics Quiz", preview: "Assessment ideas for the next evaluation..." },
  { id: 3, title: "Parent Email", preview: "A polished message for families..." },
  { id: 4, title: "Report Comments", preview: "Progress summary notes for the term..." },
];

const suggestionCards = [
  "Create Lesson Plan",
  "Generate Assessment",
  "Create Exam",
  "Generate Report Comments",
  "Write Parent Message",
  "Explain Curriculum Topic",
  "Analyze Student Performance",
  "Ask about School Operations",
];

const teacherContextItems = [
  { label: "Subjects", value: "Mathematics · English · Science" },
  { label: "Classes", value: "Grade 6A · Grade 6B" },
  { label: "Upcoming Lessons", value: "3 lessons remaining today" },
  { label: "School", value: "Greenwood International Academy" },
  { label: "Current Term", value: "Fall Semester · 2025–2026" },
];

const disabledTools = ["Lesson Planning", "Assessments", "Exam Marking", "Parent Messages", "Reports", "Analytics"];

function getGreeting(date: Date) {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdownPreview(value: string) {
  const escaped = escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/^\s*[-•]\s+(.*)$/gm, "• $1")
    .replace(/\n/g, "<br />");
  return escaped;
}

function toProgressLabel(currentStep?: string, status?: string) {
  if (status === "pending_review" || status === "approved" || currentStep === "human_approval") return "Ready for review";
  if (currentStep === "validation") return "Validating output";
  if (currentStep === "lesson_planning" || currentStep === "revision") return "Generating lesson";
  if (currentStep === "context_loader" || currentStep === "missing_information") return "Loading context";
  if (currentStep === "request_validation" || currentStep === "intent_router") return "Understanding request";
  if (status === "error" || status === "unsupported_intent") return "Safe fallback";
  return "Understanding request";
}

export default function TeacherCopilotPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [activeConversation, setActiveConversation] = useState<string | null>(null);
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const [latestStatus, setLatestStatus] = useState<string | null>(null);
  const [latestStep, setLatestStep] = useState<string | null>(null);
  const [lastPrompt, setLastPrompt] = useState<string>("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const currentTime = useMemo(() => {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }, [messages]);

  const progressLabel = useMemo(() => toProgressLabel(latestStep ?? undefined, latestStatus ?? undefined), [latestStatus, latestStep]);

  const sendMessage = async (input: string) => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const userMessage: Message = {
      id: `${Date.now()}-user`,
      role: "user",
      content: trimmed,
      timestamp: currentTime,
    };

    setMessages((prev) => [...prev, userMessage]);
    setDraft("");
    setIsTyping(true);
    setLastPrompt(trimmed);

    try {
      const shouldContinue = activeRequestId && latestStatus === "needs_clarification";
      const numericDuration = Number(trimmed);
      const structuredInput = Number.isFinite(numericDuration)
        ? { duration_minutes: numericDuration }
        : {};

      const response = shouldContinue
        ? await copilotContinue({
            request_id: activeRequestId,
            message: trimmed,
            structured_input: structuredInput,
          })
        : await copilotRun({
            intent: "lesson_planning",
            message: trimmed,
            structured_input: { topic: trimmed },
          });

      setActiveRequestId(response.request_id);
      setLatestStatus(response.status);
      setLatestStep(response.execution.current_step);

      const result = response.result ?? {};
      const generatedMarkdown = typeof result.raw_markdown === "string" ? result.raw_markdown : null;
      const assistantContent = generatedMarkdown || response.clarification_question || response.message;

      const assistantMessage: Message = {
        id: `${Date.now()}-assistant`,
        role: "assistant",
        content: assistantContent,
        timestamp: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
        metadata: {
          intent: response.intent,
          requestId: response.request_id,
          status: response.status,
          step: response.execution.current_step,
          missingFields: response.missing_fields ?? [],
        },
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setActiveConversation("Custom prompt");
    } catch {
      const fallbackMessage: Message = {
        id: `${Date.now()}-assistant-fallback`,
        role: "assistant",
        content: "The backend lesson-planning workflow is currently unavailable. Please retry.",
        timestamp: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, fallbackMessage]);
      setLatestStatus("error");
      setLatestStep("fallback");
    } finally {
      setIsTyping(false);
    }
  };

  const handleApprove = async () => {
    if (!activeRequestId) return;
    setIsTyping(true);
    try {
      const response = await copilotApprove({ request_id: activeRequestId, approved: true });
      setLatestStatus(response.status);
      setLatestStep(response.execution.current_step);
      const assistantMessage: Message = {
        id: `${Date.now()}-assistant-approved`,
        role: "assistant",
        content: response.message,
        timestamp: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleRetry = async () => {
    if (!lastPrompt) return;
    await sendMessage(lastPrompt);
  };

  const handleSubmit = (event?: React.FormEvent) => {
    event?.preventDefault();
    void sendMessage(draft);
  };

  return (
    <div className="space-y-6 lg:space-y-8">
      <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.35em] text-indigo-600">Teacher Copilot</p>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-gray-900 sm:text-3xl">SchoolOS teacher workspace</h1>
            <p className="mt-3 text-sm text-gray-600">A conversational AI surface for future teacher agents, ready to grow without changing the current portal layout.</p>
          </div>
          <div className="rounded-2xl border border-indigo-100 bg-indigo-50/80 px-4 py-3 text-sm text-indigo-700">
            <p className="font-medium">{getGreeting(new Date())}, Mr. Ahmed</p>
            <p className="mt-1">A polished interface is ready for the next agent sprint.</p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)_280px]">
        <aside className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-[0.25em] text-gray-600">Recent conversations</h2>
            <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[11px] font-medium text-gray-600">Placeholder</span>
          </div>
          <div className="mt-4 space-y-2">
            {recentConversations.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveConversation(item.title)}
                className={`w-full rounded-2xl border p-3 text-left transition ${
                  activeConversation === item.title
                    ? "border-indigo-200 bg-indigo-50"
                    : "border-gray-200 bg-white hover:border-indigo-200 hover:bg-gray-50"
                }`}
              >
                <p className="text-sm font-medium text-gray-900">{item.title}</p>
                <p className="mt-1 text-xs text-gray-500">{item.preview}</p>
              </button>
            ))}
          </div>

          <div className="mt-6 rounded-2xl border border-dashed border-gray-300 p-3 text-sm text-gray-600">
            <p className="font-medium text-gray-900">Examples</p>
            <p className="mt-2">The left rail is intentionally scaffolded for future conversation history and agent switching.</p>
          </div>
        </aside>

        <section className="flex min-h-160 flex-col rounded-3xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-200 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Ask SchoolOS anything</h2>
                <p className="mt-1 text-sm text-gray-500">A professional workspace for lesson planning, parent communication, and future teacher agents.</p>
              </div>
              <div className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">{progressLabel}</div>
            </div>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto bg-slate-50/70 p-5">
            {messages.length === 0 && !isTyping ? (
              <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
                <div className="max-w-2xl">
                  <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">Welcome</p>
                  <h3 className="mt-3 text-xl font-semibold text-gray-900">Good Morning Mr. Ahmed</h3>
                  <p className="mt-2 text-sm leading-7 text-gray-600">How can I help you today?</p>
                </div>
                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  {suggestionCards.map((card) => (
                    <button
                      key={card}
                      type="button"
                      onClick={() => sendMessage(card)}
                      className="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-left text-sm font-medium text-gray-700 shadow-sm transition hover:border-indigo-200 hover:text-indigo-700"
                    >
                      {card}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[88%] rounded-3xl px-4 py-3 shadow-sm ${message.role === "user" ? "bg-indigo-600 text-white" : "border border-gray-200 bg-white text-gray-700"}`}>
                    <div className="text-sm leading-7" dangerouslySetInnerHTML={{ __html: renderMarkdownPreview(message.content) }} />
                    <p className={`mt-2 text-[11px] uppercase tracking-[0.2em] ${message.role === "user" ? "text-indigo-100" : "text-gray-400"}`}>
                      {message.timestamp}
                    </p>
                  </div>
                </div>
              ))
            )}

            {isTyping ? (
              <div className="flex justify-start">
                <div className="rounded-3xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                  <div className="flex items-center gap-2 text-sm text-gray-600">
                    <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-indigo-500" />
                    <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-indigo-500" />
                    <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-indigo-500" />
                    <span>Running backend graph workflow…</span>
                  </div>
                </div>
              </div>
            ) : null}

            {!isTyping && activeRequestId ? (
              <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  {latestStatus === "pending_review" ? (
                    <button type="button" onClick={handleApprove} className="rounded-full bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700">
                      Approve lesson
                    </button>
                  ) : null}
                  {latestStatus === "error" || latestStatus === "unsupported_intent" ? (
                    <button type="button" onClick={handleRetry} className="rounded-full bg-indigo-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-indigo-700">
                      Retry
                    </button>
                  ) : null}
                  <span className="text-xs text-gray-500">Request ID: {activeRequestId}</span>
                </div>
              </div>
            ) : null}
            <div ref={endRef} />
          </div>

          <form onSubmit={handleSubmit} className="border-t border-gray-200 bg-white p-4">
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
              <textarea
                className="w-full resize-none border-0 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400"
                rows={3}
                placeholder="Ask SchoolOS anything..."
                maxLength={400}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    handleSubmit();
                  }
                }}
              />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <button type="button" className="rounded-full border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600" disabled>
                    Attachment
                  </button>
                  <button type="button" className="rounded-full border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600" disabled>
                    Voice
                  </button>
                  <span className="text-xs uppercase tracking-[0.2em] text-gray-400">Enter to send · Shift + Enter for newline</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-500">{draft.length}/400</span>
                  <button type="submit" className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700">
                    Send
                  </button>
                </div>
              </div>
            </div>
          </form>
        </section>

        <aside className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-[0.25em] text-gray-600">Teacher context</h2>
            <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[11px] font-medium text-gray-600">Future ready</span>
          </div>
          <div className="mt-4 space-y-3">
            {teacherContextItems.map((item) => (
              <div key={item.label} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">{item.label}</p>
                <p className="mt-2 text-sm text-gray-700">{item.value}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-2xl border border-dashed border-gray-300 p-3">
            <p className="text-sm font-semibold text-gray-900">Future toolbar</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {disabledTools.map((tool) => (
                <span key={tool} className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500">
                  {tool}
                </span>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
