import Link from "next/link";
import { FamilyTimelineEvent } from "@/lib/parent-api";
import { ParentEmptyState } from "@/components/parent/parent-page-states";

export function isSafeParentActionUrl(url: string | null): url is string {
  if (!url) return false;
  if (!url.startsWith("/parent/")) return false;
  if (url.startsWith("//")) return false;
  const lowered = url.toLowerCase();
  if (lowered.startsWith("javascript:")) return false;
  if (lowered.includes("://")) return false;
  return true;
}

interface TimelineFeedProps {
  events: FamilyTimelineEvent[];
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

export default function TimelineFeed({ events, hasMore, loadingMore, onLoadMore }: TimelineFeedProps) {
  if (events.length === 0) {
    return (
      <ParentEmptyState
        title="No family timeline events yet"
        description="Timeline events will appear here as new parent-facing updates are published."
      />
    );
  }

  return (
    <section className="space-y-4" aria-label="Family timeline event list">
      <ul className="space-y-3">
        {events.map((event) => (
          <li key={event.event_id} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-900">{event.title}</h3>
                <p className="mt-1 text-sm text-gray-600">{event.description || "No additional details."}</p>
                <p className="mt-2 text-xs text-gray-500">{new Date(event.occurred_at).toLocaleString()}</p>
              </div>
              <span className="inline-flex w-fit rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-700">
                {event.event_category}
              </span>
            </div>

            {isSafeParentActionUrl(event.action_url) && (
              <div className="mt-3">
                <Link
                  href={event.action_url}
                  className="inline-flex rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
                >
                  Open related page
                </Link>
              </div>
            )}
          </li>
        ))}
      </ul>

      {hasMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loadingMore}
          className="inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-indigo-300"
        >
          {loadingMore ? "Loading more..." : "Load more"}
        </button>
      )}
    </section>
  );
}
