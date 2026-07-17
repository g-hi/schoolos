"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import {
  FamilyMeResponse,
  FamilyTimelineEvent,
  ParentApiError,
  getFamilyMe,
  getFamilyTimeline,
} from "@/lib/parent-api";
import TimelineFeed from "@/components/parent/timeline-feed";
import {
  ParentErrorState,
  ParentPageSkeleton,
} from "@/components/parent/parent-page-states";

const PAGE_SIZE = 10;

interface TimelineState {
  family: FamilyMeResponse | null;
  events: FamilyTimelineEvent[];
  nextCursor: string | null;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  statusCode: number | null;
}

export default function ParentFamilyTimelinePage() {
  const auth = useParentAuth();
  const [state, setState] = useState<TimelineState>({
    family: null,
    events: [],
    nextCursor: null,
    hasMore: false,
    loading: false,
    loadingMore: false,
    error: null,
    statusCode: null,
  });

  const [studentFilter, setStudentFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  const categoryOptions = useMemo(() => {
    const values = Array.from(new Set(state.events.map((event) => event.event_category)));
    return values.sort();
  }, [state.events]);

  async function loadInitial(token: string) {
    setState((prev) => ({ ...prev, loading: true, error: null, statusCode: null }));

    try {
      const [family, timeline] = await Promise.all([
        getFamilyMe(token),
        getFamilyTimeline({
          token,
          limit: PAGE_SIZE,
          studentId: studentFilter || undefined,
          category: categoryFilter || undefined,
        }),
      ]);

      setState({
        family,
        events: timeline.events,
        nextCursor: timeline.next_cursor,
        hasMore: timeline.has_more,
        loading: false,
        loadingMore: false,
        error: null,
        statusCode: null,
      });
    } catch (error) {
      if (error instanceof ParentApiError) {
        setState({
          family: null,
          events: [],
          nextCursor: null,
          hasMore: false,
          loading: false,
          loadingMore: false,
          error: error.message,
          statusCode: error.status,
        });
        return;
      }

      setState({
        family: null,
        events: [],
        nextCursor: null,
        hasMore: false,
        loading: false,
        loadingMore: false,
        error: "Unable to load timeline.",
        statusCode: null,
      });
    }
  }

  async function loadMore() {
    if (!auth.token || !state.nextCursor || !state.hasMore) return;

    setState((prev) => ({ ...prev, loadingMore: true }));
    try {
      const timeline = await getFamilyTimeline({
        token: auth.token,
        limit: PAGE_SIZE,
        cursor: state.nextCursor,
        studentId: studentFilter || undefined,
        category: categoryFilter || undefined,
      });

      setState((prev) => ({
        ...prev,
        events: [...prev.events, ...timeline.events],
        nextCursor: timeline.next_cursor,
        hasMore: timeline.has_more,
        loadingMore: false,
      }));
    } catch (error) {
      if (error instanceof ParentApiError) {
        setState((prev) => ({
          ...prev,
          loadingMore: false,
          error: error.message,
          statusCode: error.status,
        }));
        return;
      }

      setState((prev) => ({
        ...prev,
        loadingMore: false,
        error: "Unable to load more timeline events.",
        statusCode: null,
      }));
    }
  }

  useEffect(() => {
    if (!auth.token || !auth.isAuthenticated) {
      setState({
        family: null,
        events: [],
        nextCursor: null,
        hasMore: false,
        loading: false,
        loadingMore: false,
        error: null,
        statusCode: null,
      });
      return;
    }

    void loadInitial(auth.token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.token, auth.isAuthenticated, studentFilter, categoryFilter]);

  if (auth.isHydrating) {
    return <ParentPageSkeleton title="Loading family timeline" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (state.loading) {
    return <ParentPageSkeleton title="Loading family timeline" />;
  }

  if (state.statusCode === 404) {
    return (
      <ParentErrorState
        title="Family timeline is not available"
        description={state.error || "No active family was found for this account."}
      />
    );
  }

  if (state.statusCode === 403) {
    return (
      <ParentErrorState
        title="Access denied"
        description="This account cannot access the family timeline."
      />
    );
  }

  if (state.error && !state.family) {
    return (
      <ParentErrorState
        title="Unable to load family timeline"
        description={state.error}
        actionLabel="Retry"
        onAction={() => {
          if (auth.token) {
            void loadInitial(auth.token);
          }
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Family Timeline</h1>
            <p className="mt-1 text-sm text-gray-600">{state.family?.family_name || "Your family"}</p>
          </div>
          <Link
            href="/parent"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
          >
            Back to Family Hub
          </Link>
        </div>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-label="Timeline filters">
        <h2 className="text-lg font-semibold text-gray-900">Filters</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="timeline-student-filter" className="mb-1 block text-sm font-medium text-gray-700">
              Child
            </label>
            <select
              id="timeline-student-filter"
              value={studentFilter}
              onChange={(event) => setStudentFilter(event.target.value)}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            >
              <option value="">All children</option>
              {(state.family?.students ?? []).map((student) => (
                <option key={student.student_id} value={student.student_id}>
                  {student.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="timeline-category-filter" className="mb-1 block text-sm font-medium text-gray-700">
              Category
            </label>
            <select
              id="timeline-category-filter"
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            >
              <option value="">All categories</option>
              {categoryOptions.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <TimelineFeed
        events={state.events}
        hasMore={state.hasMore}
        loadingMore={state.loadingMore}
        onLoadMore={loadMore}
      />

      {state.error && state.family && (
        <ParentErrorState title="Timeline update issue" description={state.error} />
      )}
    </div>
  );
}
