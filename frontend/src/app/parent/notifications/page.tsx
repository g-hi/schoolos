"use client";

import { useEffect, useState } from "react";
import {
  AnnouncementsApiError,
  getParentUnreadNotificationCount,
  listParentNotifications,
  listParentUnreadNotifications,
  markAllParentNotificationsRead,
  markParentNotificationRead,
  NotificationSummary,
  ParentNotificationListResponse,
} from "@/lib/announcements-api";
import { ParentEmptyState, ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";

const pageSizeOptions = [10, 20, 50] as const;
const parentNotificationsUpdatedEvent = "schoolos:parent-notifications-updated";

function apiMessage(error: unknown): string {
  if (error instanceof AnnouncementsApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

function readStateLabel(notification: NotificationSummary): { label: string; tone: string } {
  if (notification.read_at) {
    return { label: "Read", tone: "bg-emerald-100 text-emerald-700" };
  }
  return { label: "Unread", tone: "bg-amber-100 text-amber-700" };
}

export default function ParentNotificationsPage() {
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof pageSizeOptions)[number]>(10);
  const [notifications, setNotifications] = useState<ParentNotificationListResponse["items"]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [unreadCountError, setUnreadCountError] = useState<string | null>(null);
  const [mutationPendingId, setMutationPendingId] = useState<string | null>(null);
  const [markAllPending, setMarkAllPending] = useState(false);
  const [mutationMessage, setMutationMessage] = useState<string | null>(null);

  useEffect(() => {
    setSelectedId(null);
  }, [filter, page, pageSize]);

  useEffect(() => {
    let active = true;

    async function loadNotifications() {
      setListLoading(true);
      setListError(null);
      setMutationMessage(null);
      try {
        const response =
          filter === "unread"
            ? await listParentUnreadNotifications({ page, page_size: pageSize })
            : await listParentNotifications({ page, page_size: pageSize });
        if (active) {
          setNotifications(response.items);
        }
      } catch (error) {
        if (active) {
          setListError(apiMessage(error));
        }
      } finally {
        if (active) {
          setListLoading(false);
        }
      }
    }

    void loadNotifications();
    return () => {
      active = false;
    };
  }, [filter, page, pageSize]);

  useEffect(() => {
    let active = true;

    async function loadUnreadCount() {
      try {
        const response = await getParentUnreadNotificationCount();
        if (active) {
          setUnreadCount(response.unread_count);
          setUnreadCountError(null);
        }
      } catch (error) {
        if (active) {
          setUnreadCount(null);
          setUnreadCountError(apiMessage(error));
        }
      }
    }

    void loadUnreadCount();

    const handleUpdate = () => {
      void loadUnreadCount();
    };

    window.addEventListener(parentNotificationsUpdatedEvent, handleUpdate);
    return () => {
      active = false;
      window.removeEventListener(parentNotificationsUpdatedEvent, handleUpdate);
    };
  }, []);

  const selectedNotification = selectedId ? notifications.find((item) => item.id === selectedId) ?? null : null;
  const canGoPrev = page > 1;
  const canGoNext = notifications.length === pageSize;

  function notifySidebar() {
    window.dispatchEvent(new CustomEvent(parentNotificationsUpdatedEvent));
  }

  async function refreshAll() {
    setListLoading(true);
    setListError(null);
    try {
      const [listResponse, countResponse] = await Promise.all([
        filter === "unread"
          ? listParentUnreadNotifications({ page, page_size: pageSize })
          : listParentNotifications({ page, page_size: pageSize }),
        getParentUnreadNotificationCount(),
      ]);
      setNotifications(listResponse.items);
      if (selectedId && !listResponse.items.some((item) => item.id === selectedId)) {
        setSelectedId(null);
      }
      setUnreadCount(countResponse.unread_count);
      setUnreadCountError(null);
    } catch (error) {
      setListError(apiMessage(error));
    } finally {
      setListLoading(false);
    }
  }

  async function markOneAsRead(notification: NotificationSummary) {
    if (notification.read_at) {
      return;
    }
    setMutationPendingId(notification.id);
    setMutationMessage(null);
    try {
      await markParentNotificationRead(notification.id);
      setMutationMessage("Notification marked as read.");
      notifySidebar();
      await refreshAll();
    } catch (error) {
      setMutationMessage(apiMessage(error));
    } finally {
      setMutationPendingId(null);
    }
  }

  async function markAllAsRead() {
    if (unreadCount === 0) {
      return;
    }
    setMarkAllPending(true);
    setMutationMessage(null);
    try {
      await markAllParentNotificationsRead();
      setMutationMessage("All notifications marked as read.");
      notifySidebar();
      await refreshAll();
    } catch (error) {
      setMutationMessage(apiMessage(error));
    } finally {
      setMarkAllPending(false);
    }
  }

  if (listLoading) {
    return <ParentPageSkeleton title="Notifications" />;
  }

  if (listError) {
    return (
      <ParentErrorState
        title="Unable to load notifications"
        description={listError}
        actionLabel="Retry"
        onAction={() => {
          void refreshAll();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Notifications</h1>
          <p className="text-sm text-gray-600">Review notifications sent to your family and mark them as read.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void refreshAll();
            }}
            className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void markAllAsRead()}
            disabled={markAllPending || unreadCount === 0}
            className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {markAllPending ? "Marking all..." : "Mark all as read"}
          </button>
        </div>
      </header>

      <section className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Notifications</h2>
            <div className="flex flex-wrap items-center gap-3">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Filter</span>
                <select
                  value={filter}
                  onChange={(event) => setFilter(event.target.value as "all" | "unread")}
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="all">All</option>
                  <option value="unread">Unread</option>
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Page size</span>
                <select
                  value={pageSize}
                  onChange={(event) => setPageSize(Number(event.target.value) as (typeof pageSizeOptions)[number])}
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  {pageSizeOptions.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {unreadCountError ? <p className="mt-3 text-sm text-amber-700">Unread badge unavailable: {unreadCountError}</p> : null}

          <div className="mt-4 space-y-3">
            {notifications.length === 0 ? (
              <ParentEmptyState
                title="No notifications"
                description={filter === "unread" ? "You have no unread notifications right now." : "There are no notifications to show on this page."}
              />
            ) : (
              notifications.map((notification) => {
                const selected = notification.id === selectedId;
                const state = readStateLabel(notification);
                return (
                  <button
                    key={notification.id}
                    type="button"
                    onClick={() => setSelectedId(notification.id)}
                    className={`w-full rounded-2xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      selected ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-gray-100"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="truncate text-base font-semibold text-gray-900">{notification.title}</h3>
                        <p className="mt-1 line-clamp-2 text-sm text-gray-600">{notification.body}</p>
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${state.tone}`}>{state.label}</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
                      {notification.read_at ? (
                        <span>
                          Read at: <time dateTime={notification.read_at}>{notification.read_at}</time>
                        </span>
                      ) : (
                        <span>Unread</span>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3 border-t border-gray-200 pt-4 text-sm">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={!canGoPrev}
              className="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
            >
              Previous
            </button>
            <span className="text-gray-600">Page {page}</span>
            <button
              type="button"
              onClick={() => setPage((current) => current + 1)}
              disabled={!canGoNext}
              className="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
            >
              Next
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-gray-900">Notification detail</h2>
          {!selectedNotification ? (
            <ParentEmptyState title="Select a notification" description="Choose a notification from the list to review its content." />
          ) : (
            <div className="mt-4 space-y-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-semibold text-gray-900">{selectedNotification.title}</h3>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-700">{selectedNotification.body}</p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${readStateLabel(selectedNotification).tone}`}>
                  {readStateLabel(selectedNotification).label}
                </span>
              </div>

              <dl className="grid gap-3 text-sm text-gray-600">
                {selectedNotification.read_at ? (
                  <div className="rounded-xl bg-gray-50 p-3">
                    <dt className="font-medium text-gray-700">Read at</dt>
                    <dd>
                      <time dateTime={selectedNotification.read_at}>{selectedNotification.read_at}</time>
                    </dd>
                  </div>
                ) : null}
              </dl>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void markOneAsRead(selectedNotification)}
                  disabled={Boolean(selectedNotification.read_at) || mutationPendingId === selectedNotification.id}
                  className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {mutationPendingId === selectedNotification.id ? "Marking..." : "Mark as read"}
                </button>
              </div>

              {mutationMessage ? <p className="text-sm text-gray-700">{mutationMessage}</p> : null}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}