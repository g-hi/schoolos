"use client";

import { useEffect, useState } from "react";
import {
  AnnouncementsApiError,
  getParentAnnouncement,
  listParentAnnouncements,
  ParentAnnouncementSummary,
} from "@/lib/announcements-api";
import { ParentEmptyState, ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";

const pageSizeOptions = [10, 20, 50] as const;

function apiMessage(error: unknown): string {
  if (error instanceof AnnouncementsApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

function formatTimestamp(value: string | null): string {
  return value ?? "Not set";
}

export default function ParentAnnouncementsPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof pageSizeOptions)[number]>(10);
  const [listItems, setListItems] = useState<ParentAnnouncementSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ParentAnnouncementSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadAnnouncements() {
      setListLoading(true);
      setListError(null);
      setSelectedId(null);
      setSelectedDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      try {
        const response = await listParentAnnouncements({
          status: "published",
          page,
          page_size: pageSize,
        });
        if (active) {
          setListItems(response.items);
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

    void loadAnnouncements();
    return () => {
      active = false;
    };
  }, [page, pageSize]);

  useEffect(() => {
    if (!selectedId) {
      return;
    }

    const announcementId = selectedId;

    let active = true;
    setSelectedDetail(null);
    setDetailLoading(true);
    setDetailError(null);

    async function loadDetail() {
      try {
        const response = await getParentAnnouncement(announcementId);
        if (active) {
          setSelectedDetail(response);
        }
      } catch (error) {
        if (active) {
          setDetailError(apiMessage(error));
        }
      } finally {
        if (active) {
          setDetailLoading(false);
        }
      }
    }

    void loadDetail();
    return () => {
      active = false;
    };
  }, [selectedId]);

  const selectedSummary = selectedId ? listItems.find((item) => item.id === selectedId) ?? null : null;
  const detailSource = selectedDetail ?? selectedSummary;

  if (listLoading) {
    return <ParentPageSkeleton title="Announcements" />;
  }

  if (listError) {
    return (
      <ParentErrorState
        title="Unable to load announcements"
        description={listError}
        actionLabel="Retry"
        onAction={() => {
          setPage((current) => current);
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Announcements</h1>
          <p className="text-sm text-gray-600">Read published school announcements and review details.</p>
        </div>
        <button
          type="button"
          onClick={() => setPage((current) => current)}
          className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Refresh
        </button>
      </header>

      <section className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-gray-900">Published announcements</h2>
            <label className="text-sm text-gray-700">
              <span className="sr-only">Page size</span>
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

          <div className="mt-4 space-y-3">
            {listItems.length === 0 ? (
              <ParentEmptyState
                title="No published announcements"
                description="There are no published announcements to show yet."
              />
            ) : (
              listItems.map((item) => {
                const selected = item.id === selectedId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedId(item.id)}
                    className={`w-full rounded-2xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      selected ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-gray-100"
                    }`}
                  >
                    <h3 className="text-base font-semibold text-gray-900">{item.title}</h3>
                    <p className="mt-1 line-clamp-3 text-sm text-gray-600">{item.body}</p>
                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
                      <span>
                        Published: <time dateTime={item.published_at ?? item.created_at}>{formatTimestamp(item.published_at)}</time>
                      </span>
                      {item.read_at ? (
                        <span>
                          Read: <time dateTime={item.read_at}>{item.read_at}</time>
                        </span>
                      ) : null}
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
              disabled={page === 1}
              className="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
            >
              Previous
            </button>
            <span className="text-gray-600">Page {page}</span>
            <button
              type="button"
              onClick={() => setPage((current) => current + 1)}
              className="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-700 transition hover:bg-gray-100"
            >
              Next
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-gray-900">Announcement detail</h2>
          {!selectedId ? (
            <ParentEmptyState
              title="Select an announcement"
              description="Choose a published announcement from the list to view its detail."
            />
          ) : detailLoading ? (
            <ParentPageSkeleton title="Loading announcement" />
          ) : detailError ? (
            <ParentErrorState title="Unable to load announcement" description={detailError} />
          ) : detailSource ? (
            <div className="mt-4 space-y-5">
              <div>
                <h3 className="text-xl font-semibold text-gray-900">{detailSource.title}</h3>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-700">{detailSource.body}</p>
              </div>
              <dl className="grid gap-3 text-sm text-gray-600">
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Publication date</dt>
                  <dd>
                    {detailSource.published_at ? (
                      <time dateTime={detailSource.published_at}>{detailSource.published_at}</time>
                    ) : (
                      <span>Not set</span>
                    )}
                  </dd>
                </div>
                {selectedDetail?.read_at ? (
                  <div className="rounded-xl bg-gray-50 p-3">
                    <dt className="font-medium text-gray-700">Read at</dt>
                    <dd>
                      <time dateTime={selectedDetail.read_at}>{selectedDetail.read_at}</time>
                    </dd>
                  </div>
                ) : null}
                {selectedDetail?.timezone ? (
                  <div className="rounded-xl bg-gray-50 p-3">
                    <dt className="font-medium text-gray-700">Timezone</dt>
                    <dd>{selectedDetail.timezone}</dd>
                  </div>
                ) : null}
                {selectedDetail?.scheduled_at ? (
                  <div className="rounded-xl bg-gray-50 p-3">
                    <dt className="font-medium text-gray-700">Scheduled</dt>
                    <dd>
                      <time dateTime={selectedDetail.scheduled_at}>{selectedDetail.scheduled_at}</time>
                    </dd>
                  </div>
                ) : null}
                {selectedDetail?.archived_at ? (
                  <div className="rounded-xl bg-gray-50 p-3">
                    <dt className="font-medium text-gray-700">Archived</dt>
                    <dd>
                      <time dateTime={selectedDetail.archived_at}>{selectedDetail.archived_at}</time>
                    </dd>
                  </div>
                ) : null}
              </dl>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}