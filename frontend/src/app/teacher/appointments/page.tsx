"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  AppointmentMeetingMode,
  AppointmentStatus,
  AppointmentSummary,
  AppointmentsApiError,
  TeacherAppointmentDetail,
  cancelTeacherAppointment,
  completeTeacherAppointment,
  confirmTeacherAppointment,
  declineTeacherAppointment,
  getTeacherAppointment,
  listTeacherAppointments,
  rescheduleTeacherAppointment,
} from "@/lib/appointments-api";
import { ParentEmptyState, ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";

const meetingModes: AppointmentMeetingMode[] = ["in_person", "video", "phone"];

function statusBadgeClass(status: AppointmentStatus): string {
  if (status === "confirmed") return "bg-green-100 text-green-700";
  if (status === "requested") return "bg-blue-100 text-blue-700";
  if (status === "declined") return "bg-red-100 text-red-700";
  if (status === "cancelled") return "bg-gray-100 text-gray-700";
  return "bg-amber-100 text-amber-700";
}

function toDatetimeLocalValue(isoDate: string): string {
  const date = new Date(isoDate);
  const pad = (value: number) => String(value).padStart(2, "0");
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function toIsoFromLocal(localDatetime: string): string {
  return new Date(localDatetime).toISOString();
}

function readError(error: unknown): string {
  if (error instanceof AppointmentsApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected request failure.";
}

function teacherAllowedActions(status: AppointmentStatus) {
  return {
    canConfirm: status === "requested",
    canDecline: status === "requested",
    canCancel: status === "requested" || status === "confirmed",
    canComplete: status === "confirmed",
    canReschedule: status === "requested" || status === "confirmed",
  };
}

export default function TeacherAppointmentsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [appointments, setAppointments] = useState<AppointmentSummary[]>([]);

  const [selectedStatusFilter, setSelectedStatusFilter] = useState<AppointmentStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);

  const [selectedAppointmentId, setSelectedAppointmentId] = useState<string | null>(null);
  const [selectedAppointment, setSelectedAppointment] = useState<TeacherAppointmentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [actionPending, setActionPending] = useState<null | "confirm" | "decline" | "cancel" | "complete" | "reschedule">(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [rescheduleDateTime, setRescheduleDateTime] = useState("");
  const [rescheduleDuration, setRescheduleDuration] = useState<string>("");
  const [rescheduleTimezone, setRescheduleTimezone] = useState("");
  const [rescheduleMode, setRescheduleMode] = useState<AppointmentMeetingMode | "">("");
  const [rescheduleLocation, setRescheduleLocation] = useState("");
  const [rescheduleStaffNotes, setRescheduleStaffNotes] = useState("");

  const canGoPrev = page > 1;
  const canGoNext = appointments.length === pageSize;

  const loadAppointments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listTeacherAppointments({
        status: selectedStatusFilter === "all" ? undefined : selectedStatusFilter,
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
  }, [page, pageSize, selectedAppointmentId, selectedStatusFilter]);

  const loadAppointmentDetail = useCallback(async (appointmentId: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const response = await getTeacherAppointment(appointmentId);
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

  useEffect(() => {
    if (!selectedAppointment) return;
    setRescheduleDateTime(toDatetimeLocalValue(selectedAppointment.scheduled_start_at));
    setRescheduleDuration(String(selectedAppointment.duration_minutes));
    setRescheduleTimezone(selectedAppointment.timezone);
    setRescheduleMode(selectedAppointment.meeting_mode);
    setRescheduleLocation(selectedAppointment.location_or_link ?? "");
    setRescheduleStaffNotes(selectedAppointment.staff_notes ?? "");
  }, [selectedAppointment]);

  const refreshSelected = useCallback(async (appointmentId: string) => {
    await loadAppointments();
    await loadAppointmentDetail(appointmentId);
  }, [loadAppointmentDetail, loadAppointments]);

  async function onLifecycleAction(
    action: "confirm" | "decline" | "cancel" | "complete",
    appointmentId: string,
  ) {
    setActionError(null);
    setActionPending(action);
    try {
      if (action === "confirm") {
        await confirmTeacherAppointment(appointmentId);
      } else if (action === "decline") {
        await declineTeacherAppointment(appointmentId);
      } else if (action === "cancel") {
        await cancelTeacherAppointment(appointmentId);
      } else {
        await completeTeacherAppointment(appointmentId);
      }
      await refreshSelected(appointmentId);
    } catch (err) {
      setActionError(readError(err));
    } finally {
      setActionPending(null);
    }
  }

  function validateRescheduleForm(): string | null {
    if (!rescheduleDateTime) return "Select a new date and time.";
    const durationMinutes = Number(rescheduleDuration);
    if (!Number.isInteger(durationMinutes) || durationMinutes < 10 || durationMinutes > 180) {
      return "Duration must be between 10 and 180 minutes.";
    }
    const selectedDate = new Date(rescheduleDateTime);
    if (Number.isNaN(selectedDate.getTime()) || selectedDate <= new Date()) {
      return "Rescheduled time must be in the future.";
    }
    if (!rescheduleTimezone.trim()) return "Timezone is required.";
    if (!rescheduleMode) return "Meeting mode is required.";
    return null;
  }

  async function onReschedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAppointment) return;

    const validationError = validateRescheduleForm();
    if (validationError) {
      setActionError(validationError);
      return;
    }

    if (!window.confirm("Submit appointment reschedule?")) return;

    setActionError(null);
    setActionPending("reschedule");
    try {
      await rescheduleTeacherAppointment(selectedAppointment.id, {
        scheduled_start_at: toIsoFromLocal(rescheduleDateTime),
        duration_minutes: Number(rescheduleDuration),
        timezone: rescheduleTimezone,
        meeting_mode: rescheduleMode === "" ? null : rescheduleMode,
        location_or_link: rescheduleLocation.trim() || null,
        staff_notes: rescheduleStaffNotes.trim() || null,
      });
      await refreshSelected(selectedAppointment.id);
    } catch (err) {
      setActionError(readError(err));
    } finally {
      setActionPending(null);
    }
  }

  if (loading) {
    return <ParentPageSkeleton title="Teacher Appointments" />;
  }

  if (error) {
    return (
      <ParentErrorState
        title="Unable to load appointments"
        description={error}
        actionLabel="Retry"
        onAction={() => {
          void loadAppointments();
        }}
      />
    );
  }

  const actions = selectedAppointment ? teacherAllowedActions(selectedAppointment.status) : null;
  const anyPending = actionPending !== null;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Appointments</h1>
          <p className="text-sm text-gray-600">Manage parent meeting requests and appointment lifecycle actions.</p>
        </div>
        <button
          type="button"
          onClick={() => {
            void loadAppointments();
          }}
          className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Refresh
        </button>
      </header>

      <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Assigned appointments</h2>
            <label className="text-sm text-gray-700">
              <span className="sr-only">Filter by status</span>
              <select
                value={selectedStatusFilter}
                onChange={(event) => {
                  setPage(1);
                  setSelectedStatusFilter(event.target.value as AppointmentStatus | "all");
                }}
                className="rounded-lg border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="all">All statuses</option>
                <option value="requested">requested</option>
                <option value="confirmed">confirmed</option>
                <option value="declined">declined</option>
                <option value="cancelled">cancelled</option>
                <option value="completed">completed</option>
              </select>
            </label>
          </div>

          {appointments.length === 0 ? (
            <div className="mt-4">
              <ParentEmptyState
                title="No appointments yet"
                description="New parent requests will appear here."
              />
            </div>
          ) : (
            <ul className="mt-4 space-y-2" role="listbox" aria-label="Teacher appointments">
              {appointments.map((appointment) => (
                <li key={appointment.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedAppointmentId(appointment.id)}
                    className={`w-full rounded-xl border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${selectedAppointmentId === appointment.id ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-white hover:bg-gray-50"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-gray-900">{new Date(appointment.scheduled_start_at).toLocaleString()}</span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${statusBadgeClass(appointment.status)}`}>
                        {appointment.status}
                      </span>
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
            <span className="text-sm text-gray-600">Page {page}</span>
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

        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-gray-900">Appointment detail</h2>
          {detailLoading ? <p className="mt-4 text-sm text-gray-600">Loading appointment detail...</p> : null}
          {detailError ? <p className="mt-4 text-sm text-red-700">{detailError}</p> : null}
          {!detailLoading && !detailError && !selectedAppointment ? (
            <p className="mt-4 text-sm text-gray-600">Select an appointment to view details.</p>
          ) : null}
          {!detailLoading && selectedAppointment ? (
            <div className="mt-4 space-y-4">
              <div className="rounded-xl border border-gray-200 p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-gray-600">Status</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${statusBadgeClass(selectedAppointment.status)}`}>
                    {selectedAppointment.status}
                  </span>
                </div>
                <p className="mt-2 text-sm text-gray-700">Scheduled: {new Date(selectedAppointment.scheduled_start_at).toLocaleString()}</p>
                <p className="mt-2 text-sm text-gray-700">Parent notes: {selectedAppointment.parent_notes || "None"}</p>
                <p className="mt-1 text-sm text-gray-700">Staff notes: {selectedAppointment.staff_notes || "None"}</p>
                <p className="mt-1 text-xs text-gray-500">ID: {selectedAppointment.id}</p>
              </div>

              {actionError ? <p className="text-sm text-red-700">{actionError}</p> : null}

              {actions && (actions.canConfirm || actions.canDecline || actions.canCancel || actions.canComplete || actions.canReschedule) ? (
                <div className="space-y-4">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {actions.canConfirm ? (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm("Confirm this appointment?")) {
                            void onLifecycleAction("confirm", selectedAppointment.id);
                          }
                        }}
                        disabled={anyPending}
                        className="inline-flex items-center justify-center rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actionPending === "confirm" ? "Confirming..." : "Confirm"}
                      </button>
                    ) : null}

                    {actions.canDecline ? (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm("Decline this appointment?")) {
                            void onLifecycleAction("decline", selectedAppointment.id);
                          }
                        }}
                        disabled={anyPending}
                        className="inline-flex items-center justify-center rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actionPending === "decline" ? "Declining..." : "Decline"}
                      </button>
                    ) : null}

                    {actions.canCancel ? (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm("Cancel this appointment?")) {
                            void onLifecycleAction("cancel", selectedAppointment.id);
                          }
                        }}
                        disabled={anyPending}
                        className="inline-flex items-center justify-center rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actionPending === "cancel" ? "Cancelling..." : "Cancel"}
                      </button>
                    ) : null}

                    {actions.canComplete ? (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm("Mark this appointment as complete?")) {
                            void onLifecycleAction("complete", selectedAppointment.id);
                          }
                        }}
                        disabled={anyPending}
                        className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actionPending === "complete" ? "Completing..." : "Complete"}
                      </button>
                    ) : null}
                  </div>

                  {actions.canReschedule ? (
                    <form className="space-y-3 rounded-xl border border-gray-200 p-4" onSubmit={onReschedule}>
                      <h3 className="text-sm font-semibold text-gray-900">Reschedule</h3>
                      <p className="text-xs text-gray-500">Duration, timezone, and meeting mode are required by the backend for teacher reschedule requests.</p>

                      <div className="space-y-2">
                        <label htmlFor="reschedule-datetime" className="block text-sm font-medium text-gray-700">New date & time</label>
                        <input
                          id="reschedule-datetime"
                          type="datetime-local"
                          value={rescheduleDateTime}
                          onChange={(event) => setRescheduleDateTime(event.target.value)}
                          disabled={anyPending}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                          required
                        />
                      </div>

                      <div className="space-y-2">
                        <label htmlFor="reschedule-duration" className="block text-sm font-medium text-gray-700">Duration (minutes)</label>
                        <input
                          id="reschedule-duration"
                          type="number"
                          min={10}
                          max={180}
                          value={rescheduleDuration}
                          onChange={(event) => setRescheduleDuration(event.target.value)}
                          disabled={anyPending}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                          required
                        />
                      </div>

                      <div className="space-y-2">
                        <label htmlFor="reschedule-timezone" className="block text-sm font-medium text-gray-700">Timezone</label>
                        <input
                          id="reschedule-timezone"
                          type="text"
                          value={rescheduleTimezone}
                          onChange={(event) => setRescheduleTimezone(event.target.value)}
                          disabled={anyPending}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                          required
                        />
                      </div>

                      <div className="space-y-2">
                        <label htmlFor="reschedule-mode" className="block text-sm font-medium text-gray-700">Meeting mode</label>
                        <select
                          id="reschedule-mode"
                          value={rescheduleMode}
                          onChange={(event) => setRescheduleMode(event.target.value as AppointmentMeetingMode | "")}
                          disabled={anyPending}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                          required
                        >
                          <option value="" disabled>
                            Select a mode
                          </option>
                          {meetingModes.map((mode) => (
                            <option key={mode} value={mode}>{mode}</option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-2">
                        <label htmlFor="reschedule-location" className="block text-sm font-medium text-gray-700">Location or link (optional)</label>
                        <input
                          id="reschedule-location"
                          type="text"
                          value={rescheduleLocation}
                          onChange={(event) => setRescheduleLocation(event.target.value)}
                          disabled={anyPending}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                        />
                      </div>

                      <div className="space-y-2">
                        <label htmlFor="reschedule-staff-notes" className="block text-sm font-medium text-gray-700">Teacher notes (optional)</label>
                        <textarea
                          id="reschedule-staff-notes"
                          value={rescheduleStaffNotes}
                          onChange={(event) => setRescheduleStaffNotes(event.target.value)}
                          disabled={anyPending}
                          className="min-h-24 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                        />
                      </div>

                      <button
                        type="submit"
                        disabled={anyPending}
                        className="inline-flex w-full items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actionPending === "reschedule" ? "Rescheduling..." : "Reschedule appointment"}
                      </button>
                    </form>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-gray-600">No lifecycle actions are available for this status.</p>
              )}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
