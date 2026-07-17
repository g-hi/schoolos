"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ChildSelector from "@/components/parent/child-selector";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import {
  ParentEmptyState,
  ParentErrorState,
  ParentPageSkeleton,
} from "@/components/parent/parent-page-states";
import {
  ParentApiError,
  ParentAssistantResponse,
  ParentStudentSummary,
  continueParentAssistant,
  getParentStudents,
  runParentAssistant,
} from "@/lib/parent-api";
import {
  readParentAssistantConversationId,
  readParentAssistantRequestId,
  writeParentAssistantConversationId,
  writeParentAssistantRequestId,
} from "@/lib/parent-auth";

interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  suggestions?: string[];
}

const INTRO_MESSAGE: AssistantMessage = {
  id: "intro",
  role: "assistant",
  text: "I can help with family summaries, linked children, timeline updates, pickup status, and timetable questions for your linked children. I provide information only.",
  suggestions: [
    "Summarize my family",
    "Show recent family updates",
    "Do I have an active pickup request?",
  ],
};

export default function ParentAssistant() {
  const auth = useParentAuth();
  const [students, setStudents] = useState<ParentStudentSummary[]>([]);
  const [activeStudentId, setActiveStudentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([INTRO_MESSAGE]);
  const [requestId, setRequestId] = useState<string | null>(() => readParentAssistantRequestId());
  const [conversationId, setConversationId] = useState<string | null>(() => readParentAssistantConversationId());
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStudents, setLoadingStudents] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    writeParentAssistantRequestId(requestId);
  }, [requestId]);

  useEffect(() => {
    writeParentAssistantConversationId(conversationId);
  }, [conversationId]);

  useEffect(() => {
    if (!auth.isAuthenticated || !auth.token) {
      setStudents([]);
      setActiveStudentId(null);
      setMessages([INTRO_MESSAGE]);
      setRequestId(null);
      setConversationId(null);
      setDraft("");
      setError(null);
      return;
    }

    setLoadingStudents(true);
    setError(null);
    void getParentStudents(auth.token)
      .then((response) => {
        setStudents(response.students);
        if (response.students.length > 0) {
          setActiveStudentId((prev) => prev ?? response.students[0].student_id);
        }
      })
      .catch((apiError: unknown) => {
        if (apiError instanceof ParentApiError) {
          setError(apiError.message);
          return;
        }
        setError("Unable to load linked children for the assistant.");
      })
      .finally(() => setLoadingStudents(false));
  }, [auth.isAuthenticated, auth.token]);

  const canSubmit = useMemo(() => {
    return Boolean(auth.token) && !loading && draft.trim().length > 0;
  }, [auth.token, loading, draft]);

  function appendAssistantResponse(response: ParentAssistantResponse) {
    const text = response.clarification_question || response.message;
    setMessages((prev) => [
      ...prev,
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text,
        suggestions: response.suggested_questions?.slice(0, 3) || [],
      },
    ]);
  }

  async function submitMessage(rawMessage: string) {
    if (!auth.token) return;
    const message = rawMessage.trim();
    if (!message || loading) return;

    setLoading(true);
    setError(null);

    setMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        role: "user",
        text: message,
      },
    ]);

    try {
      const response = requestId
        ? await continueParentAssistant(auth.token, {
            request_id: requestId,
            message,
            context: { active_student_id: activeStudentId },
          })
        : await runParentAssistant(auth.token, {
            message,
            conversation_id: conversationId,
            context: { active_student_id: activeStudentId },
          });

      setRequestId(response.request_id || null);
      setConversationId(response.conversation_id || conversationId || null);
      appendAssistantResponse(response);
    } catch (apiError: unknown) {
      if (apiError instanceof ParentApiError) {
        setError(apiError.message);
      } else {
        setError("Unable to reach the Parent Assistant right now.");
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          text: "I could not process that request right now. Please try again.",
        },
      ]);
    } finally {
      setLoading(false);
      setDraft("");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    void submitMessage(draft);
  }

  function handleNewConversation() {
    setRequestId(null);
    setConversationId(null);
    setMessages([INTRO_MESSAGE]);
    setDraft("");
    setError(null);
  }

  if (auth.isHydrating) {
    return <ParentPageSkeleton title="Loading Parent Assistant" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (loadingStudents) {
    return <ParentPageSkeleton title="Loading Parent Assistant" />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Parent Assistant</h1>
            <p className="mt-2 text-sm text-gray-600">
              Ask questions about authorized family information already available in SchoolOS.
            </p>
          </div>
          <button
            type="button"
            onClick={handleNewConversation}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
          >
            New conversation
          </button>
        </div>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        {students.length > 0 ? (
          <ChildSelector students={students} activeStudentId={activeStudentId} onChange={setActiveStudentId} />
        ) : (
          <ParentEmptyState
            title="No linked students"
            description="No students are currently linked to this parent account."
          />
        )}
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-label="Parent Assistant conversation">
        <div className="space-y-3">
          {messages.map((message) => (
            <article
              key={message.id}
              className={`rounded-xl border px-4 py-3 text-sm ${
                message.role === "assistant"
                  ? "border-indigo-100 bg-indigo-50 text-indigo-900"
                  : "border-gray-200 bg-gray-50 text-gray-900"
              }`}
            >
              <p className="whitespace-pre-wrap">{message.text}</p>
              {message.role === "assistant" && message.suggestions && message.suggestions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {message.suggestions.map((suggestion) => (
                    <button
                      key={`${message.id}-${suggestion}`}
                      type="button"
                      onClick={() => {
                        if (!loading) {
                          void submitMessage(suggestion);
                        }
                      }}
                      disabled={loading}
                      className="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-medium text-indigo-700 transition hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>

        {error && (
          <div className="mt-4">
            <ParentErrorState title="Assistant unavailable" description={error} />
          </div>
        )}

        <form className="mt-4 space-y-3" onSubmit={handleSubmit}>
          <label htmlFor="parent-assistant-input" className="block text-sm font-medium text-gray-700">
            Ask a question
          </label>
          <textarea
            id="parent-assistant-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
            placeholder="Example: Show recent family timeline updates"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-indigo-300"
          >
            {loading ? "Sending..." : "Send"}
          </button>
        </form>
      </section>
    </div>
  );
}