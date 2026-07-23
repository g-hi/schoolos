"use client";

import { useCallback, useEffect, useState } from "react";
import RoleGuard from "@/components/auth/role-guard";
import {
  AppointmentStatus,
  AppointmentsApiError,
  LeadershipAppointmentDetail,
  LeadershipAppointmentSummary,
  listLeadershipAppointments,
  getLeadershipAppointment,
} from "@/lib/appointments-api";
import { ReportEmptyState, ReportErrorState, ReportPageSkeleton, ReportStatusBadge } from "@/components/reports/report-page-states";

function readError(error: unknown): string {
  if (error instanceof AppointmentsApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected request failure.";
}

function formatDisplayDate(value: string): string {
  return new Date(value).toLocaleString();
}

function appointmentSummaryLabel(appointment: LeadershipAppointmentSummary): string {
  return `${formatDisplayDate(appointment.scheduled_start_at)} · ${appointment.status}`;
}

function getAppliedFilters(status: AppointmentStatus | "all", dateFrom: string, dateTo: string) {
  return {
    status: status === "all" ? undefined : status,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };
}

export default function LeadershipAppointmentsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [appointments, setAppointments] = useState<LeadershipAppointmentSummary[]>([]);

  const [selectedStatusFilter, setSelectedStatusFilter] = useState<AppointmentStatus | "all">("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);

  const [selectedAppointmentId, setSelectedAppointmentId] = useState<string | null>(null);
  const [selectedAppointment, setSelectedAppointment] = useState<LeadershipAppointmentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const canGoPrev = page > 1;
  const canGoNext = appointments.length === pageSize;

  const loadAppointments = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSelectedAppointment(null);
    setDetailError(null);
    try {
      const response = await listLeadershipAppointments({
        ...getAppliedFilters(selectedStatusFilter, dateFrom, dateTo),
        page,
        page_size: pageSize,
      });
      setAppointments(response.items);
      if (response.items.length === 0) {
        setSelectedAppointmentId(null);
      } else if (!selectedAppointmentId || !response.items.some((item) => item.id === selectedAppointmentId)) {
        setSelectedAppointmentId(response.items[0].id);
      }
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, page, pageSize, selectedAppointmentId, selectedStatusFilter]);

  const loadAppointmentDetail = useCallback(async (appointmentId: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const response = await getLeadershipAppointment(appointmentId);
      setSelectedAppointment(response);
    } catch (err) {
      setDetailError(readError(err));
      setSelectedAppointment(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAppointments();
  }, [loadAppointments]);

  useEffect(() => {
    if (!selectedAppointmentId) {
      setSelectedAppointment(null);
      return;
    }
    void loadAppointmentDetail(selectedAppointmentId);
  }, [loadAppointmentDetail, selectedAppointmentId]);

  const selectedAppointmentSummary = selectedAppointmentId
    ? appointments.find((item) => item.id === selectedAppointmentId) ?? null
    : null;

  if (loading) {
    return <ReportPageSkeleton title="Loading appointments" />;
  }

  if (error) {
    return <ReportErrorState title="Appointments unavailable" description={error} actionLabel="Retry" onAction={() => void loadAppointments()} />;
  }

  return (
    <RoleGuard allowedRoles={["principal", "school_admin"]} forbiddenMessage="Permission denied. Leadership access is required for appointments.">
      <div className="space-y-6">
        <header className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-indigo-600">Leadership appointments</p>
          <h1 className="mt-2 text-2xl font-semibold text-gray-900">Appointments overview</h1>
          <p className="mt-2 text-sm text-gray-600">Review appointment status, schedule, parent notes, and staff notes across the tenant.</p>
        </header>

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="space-y-2">
              <label htmlFor="appointment-status" className="block text-sm font-medium text-gray-700">Status</label>
              <select
                id="appointment-status"
                value={selectedStatusFilter}
                onChange={(event) => {
                  setPage(1);
                  setSelectedStatusFilter(event.target.value as AppointmentStatus | "all");
                }}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="all">All statuses</option>
                <option value="requested">requested</option>
                <option value="confirmed">confirmed</option>
                <option value="declined">declined</option>
                <option value="cancelled">cancelled</option>
                <option value="completed">completed</option>
              </select>
            </div>

            <div className="space-y-2">
              <label htmlFor="date-from" className="block text-sm font-medium text-gray-700">From date</label>
              <input
                id="date-from"
                type="date"
                value={dateFrom}
                onChange={(event) => {
                  setPage(1);
                  setDateFrom(event.target.value);
                }}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="date-to" className="block text-sm font-medium text-gray-700">To date</label>
              <input
                id="date-to"
                type="date"
                value={dateTo}
                onChange={(event) => {
                  setPage(1);
                  setDateTo(event.target.value);
                }}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <div className="flex items-end gap-2">
              <button
                type="button"
                onClick={() => {
                  void loadAppointments();
                }}
                className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelectedStatusFilter("all");
                  setDateFrom("");
                  setDateTo("");
                  setPage(1);
                }}
                className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
              >
                Reset
              </button>
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
          <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-gray-900">Tenant-wide appointments</h2>
              <span className="text-sm text-gray-500">Page {page}</span>
            </div>

            {appointments.length === 0 ? (
              <div className="mt-4">
                <ReportEmptyState title="No appointments found" description="Try adjusting the status or date filters." />
              </div>
            ) : (
              <ul className="mt-4 space-y-2" role="listbox" aria-label="Leadership appointments">
                {appointments.map((appointment) => (
                  <li key={appointment.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedAppointmentId(appointment.id)}
                      className={`w-full rounded-xl border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${selectedAppointmentId === appointment.id ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-white hover:bg-gray-50"}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-gray-900">{appointmentSummaryLabel(appointment)}</span>
                        <ReportStatusBadge status={appointment.status} />
                      </div>
                      <p className="mt-1 text-xs text-gray-500">ID: {appointment.id}</p>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={!canGoPrev}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => setPage((current) => current + 1)}
                disabled={!canGoNext}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">Appointment detail</h2>
            {detailLoading ? <p className="mt-4 text-sm text-gray-600">Loading appointment detail...</p> : null}
            {detailError ? <p className="mt-4 text-sm text-red-700">{detailError}</p> : null}
            {!detailLoading && !detailError && !selectedAppointment ? (
              <p className="mt-4 text-sm text-gray-600">Select an appointment to view its detail.</p>
            ) : null}
            {!detailLoading && selectedAppointment ? (
              <div className="mt-4 space-y-4">
                <div className="rounded-xl border border-gray-200 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm text-gray-600">Status</span>
                    <ReportStatusBadge status={selectedAppointment.status} />
                  </div>
                  <p className="mt-2 text-sm text-gray-700">Scheduled: {selectedAppointmentSummary ? formatDisplayDate(selectedAppointmentSummary.scheduled_start_at) : "Not set"}</p>
                  <p className="mt-1 text-xs text-gray-500">ID: {selectedAppointment.id}</p>
                </div>

                <dl className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-gray-200 p-4">
                    <dt className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">Parent notes</dt>
                    <dd className="mt-2 text-sm text-gray-700">{selectedAppointment.parent_notes || "None returned"}</dd>
                  </div>
                  <div className="rounded-xl border border-gray-200 p-4">
                    <dt className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">Staff notes</dt>
                    <dd className="mt-2 text-sm text-gray-700">{selectedAppointment.staff_notes || "None returned"}</dd>
                  </div>
                </dl>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </RoleGuard>
  );
}
