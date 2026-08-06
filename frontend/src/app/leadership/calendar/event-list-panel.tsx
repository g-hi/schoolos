"use client";

import { useMemo, useState } from "react";
import type { ManualEvent } from "@/lib/timetable-calendar-api";
import { allowedActions, lifecycleBadgeTone, publicationLabel, reviewBadgeTone, summaryForAudience } from "@/app/leadership/calendar/calendar-utils";

interface EventListPanelProps {
  events: ManualEvent[];
  loading: boolean;
  onSelect: (eventId: string) => void;
  onAction: (item: ManualEvent, action: string) => void;
}

export default function EventListPanel({ events, loading, onSelect, onAction }: EventListPanelProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const filtered = useMemo(() => {
    return events.filter((item) => {
      if (search && !item.event_name.toLowerCase().includes(search.toLowerCase())) return false;
      if (statusFilter !== "all" && item.lifecycle_status !== statusFilter) return false;
      if (typeFilter !== "all" && item.event_type !== typeFilter) return false;
      if (sourceFilter !== "all" && item.source_type !== sourceFilter) return false;
      if (dateFrom && item.start_date < dateFrom) return false;
      if (dateTo && item.end_date > dateTo) return false;
      return true;
    });
  }, [events, search, statusFilter, typeFilter, sourceFilter, dateFrom, dateTo]);

  const uniqueTypes = Array.from(new Set(events.map((item) => item.event_type))).sort();
  const uniqueSources = Array.from(new Set(events.map((item) => item.source_type))).sort();

  if (loading) {
    return <p className="text-sm text-gray-600">Loading events...</p>;
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <input
          aria-label="Search events"
          placeholder="Search event name"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <select aria-label="Filter by lifecycle status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
          <option value="all">All lifecycle status</option>
          <option value="draft">draft</option>
          <option value="pending_review">pending_review</option>
          <option value="approved">approved</option>
          <option value="published">published</option>
          <option value="rescheduled">rescheduled</option>
          <option value="cancelled">cancelled</option>
          <option value="archived">archived</option>
        </select>
        <select aria-label="Filter by event type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
          <option value="all">All event types</option>
          {uniqueTypes.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <select aria-label="Filter by source type" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
          <option value="all">All source types</option>
          {uniqueSources.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <input aria-label="Start date from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        <input aria-label="End date to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
      </div>

      {filtered.length === 0 ? (
        <p className="rounded-xl border border-dashed border-gray-300 bg-white p-6 text-sm text-gray-600">No upcoming events.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
              <tr>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Dates</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Lifecycle</th>
                <th className="px-3 py-2">Publication</th>
                <th className="px-3 py-2">Audience</th>
                <th className="px-3 py-2">Approval</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => {
                const actions = allowedActions(item);
                return (
                  <tr key={item.id} className="border-t border-gray-100 align-top">
                    <td className="px-3 py-3">
                      <button type="button" onClick={() => onSelect(item.id)} className="text-left font-semibold text-indigo-700 hover:underline">
                        {item.event_name}
                      </button>
                      <p className="mt-1 text-xs text-gray-500">v{item.version_number}</p>
                    </td>
                    <td className="px-3 py-3 text-gray-700">{item.event_type}</td>
                    <td className="px-3 py-3 text-gray-700">{item.start_date} to {item.end_date}</td>
                    <td className="px-3 py-3 text-gray-700">{item.source_type}</td>
                    <td className="px-3 py-3"><span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${lifecycleBadgeTone(item.lifecycle_status)}`}>{item.lifecycle_status}</span></td>
                    <td className="px-3 py-3 text-gray-700">{publicationLabel(item)}</td>
                    <td className="px-3 py-3 text-gray-700">{summaryForAudience(item)}</td>
                    <td className="px-3 py-3"><span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${reviewBadgeTone(item.review_status)}`}>{item.review_status}</span></td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-1">
                        {actions.map((action) => (
                          <button
                            key={action}
                            type="button"
                            onClick={() => onAction(item, action)}
                            className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                          >
                            {action}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
