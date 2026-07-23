"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AppointmentMeetingMode,
  AppointmentStatus,
  AppointmentSummary,
  AppointmentsApiError,
  CreateParentAppointmentRequest,
  EligibleAppointmentTeacherOption,
  cancelParentAppointment,
  createParentAppointment,
  getEligibleAppointmentTeachers,
  getParentAppointment,
  listParentAppointments,
  rescheduleParentAppointment,
} from "@/lib/appointments-api";
import { ParentEmptyState, ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";
import { api } from "@/lib/api";

interface ParentStudentOption {
  student_id: string;
  name: string;
}

interface ParentStudentsResponse {
  students: ParentStudentOption[];
}

const meetingModes: AppointmentMeetingMode[] = ["in_person", "video", "phone"];

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

function getInitialDatetimeLocal(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  return toDatetimeLocalValue(date.toISOString());
}

function toIsoFromLocal(localDatetime: string): string {
  return new Date(localDatetime).toISOString();
}

function canParentModify(status: AppointmentStatus): boolean {
  return status === "requested" || status === "confirmed";
}

function statusBadgeClass(status: AppointmentStatus): string {
  if (status === "confirmed") return "bg-green-100 text-green-700";
  if (status === "requested") return "bg-blue-100 text-blue-700";
  if (status === "declined") return "bg-red-100 text-red-700";
  if (status === "cancelled") return "bg-gray-100 text-gray-700";
  return "bg-amber-100 text-amber-700";
}

export default function ParentAppointmentsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [appointments, setAppointments] = useState<AppointmentSummary[]>([]);
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<AppointmentStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);

  const [selectedAppointmentId, setSelectedAppointmentId] = useState<string | null>(null);
  const [selectedAppointment, setSelectedAppointment] = useState<AppointmentSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [students, setStudents] = useState<ParentStudentOption[]>([]);
  const [studentsLoading, setStudentsLoading] = useState(true);
  const [studentsError, setStudentsError] = useState<string | null>(null);

  const [selectedStudentId, setSelectedStudentId] = useState<string>("");
  const [eligibleOptions, setEligibleOptions] = useState<EligibleAppointmentTeacherOption[]>([]);
  const [eligibleLoading, setEligibleLoading] = useState(false);
  const [eligibleError, setEligibleError] = useState<string | null>(null);
  const [selectedTeacherOption, setSelectedTeacherOption] = useState<string>("");

  const [createDateTime, setCreateDateTime] = useState(getInitialDatetimeLocal());
  const [createDuration, setCreateDuration] = useState(30);
  const [createTimezone, setCreateTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [createMode, setCreateMode] = useState<AppointmentMeetingMode>("in_person");
  const [createLocation, setCreateLocation] = useState("");
  const [createReason, setCreateReason] = useState("");
  const [createNotes, setCreateNotes] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createPending, setCreatePending] = useState(false);

  const [rescheduleDateTime, setRescheduleDateTime] = useState(getInitialDatetimeLocal());
  const [rescheduleDuration, setRescheduleDuration] = useState(30);
  const [rescheduleTimezone, setRescheduleTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [rescheduleMode, setRescheduleMode] = useState<AppointmentMeetingMode>("in_person");
  const [rescheduleLocation, setRescheduleLocation] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [reschedulePending, setReschedulePending] = useState(false);
  const [cancelPending, setCancelPending] = useState(false);

  const canGoPrev = page > 1;
  const canGoNext = appointments.length === pageSize;

  useEffect(() => {
    const loadStudents = async () => {
      setStudentsLoading(true);
      setStudentsError(null);
      try {
        const response = await api<ParentStudentsResponse>("/parent/students");
        setStudents(response.students);
        if (response.students.length > 0) {
          setSelectedStudentId((current) => current || response.students[0].student_id);
        }
      } catch (err) {
        setStudentsError(readError(err));
      } finally {
        setStudentsLoading(false);
      }
    };

    void loadStudents();
  }, []);

  const loadAppointments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listParentAppointments({
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
  }, [page, pageSize, selectedStatusFilter, selectedAppointmentId]);

  useEffect(() => {
    void loadAppointments();
  }, [loadAppointments]);

  useEffect(() => {
    if (!selectedStudentId) {
      setEligibleOptions([]);
      setSelectedTeacherOption("");
      return;
    }
    void loadEligibleOptions(selectedStudentId);
  }, [selectedStudentId]);

  useEffect(() => {
    if (!selectedAppointmentId) {
      setSelectedAppointment(null);
      return;
    }
    void loadAppointmentDetail(selectedAppointmentId);
  }, [selectedAppointmentId]);

  useEffect(() => {
    if (!selectedAppointment) return;
    setRescheduleDateTime(toDatetimeLocalValue(selectedAppointment.scheduled_start_at));
  }, [selectedAppointment]);

  const selectedTeacher = useMemo(
    () => eligibleOptions.find((option) => optionKey(option) === selectedTeacherOption) || null,
    [eligibleOptions, selectedTeacherOption],
  );

  async function loadEligibleOptions(studentId: string) {
    setEligibleLoading(true);
    setEligibleError(null);
    try {
      const response = await getEligibleAppointmentTeachers(studentId);
      setEligibleOptions(response.options);
      setSelectedTeacherOption(response.options.length > 0 ? optionKey(response.options[0]) : "");
    } catch (err) {
      setEligibleError(readError(err));
      setEligibleOptions([]);
      setSelectedTeacherOption("");
    } finally {
      setEligibleLoading(false);
    }
  }

  async function loadAppointmentDetail(appointmentId: string) {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const response = await getParentAppointment(appointmentId);
      setSelectedAppointment(response);
    } catch (err) {
      setDetailError(readError(err));
      setSelectedAppointment(null);
    } finally {
      setDetailLoading(false);
    }
  }

  function validateCreateForm(): string | null {
    if (!selectedStudentId) return "Select a student.";
    if (!selectedTeacher) return "Select a teacher/subject option.";
    if (!createDateTime) return "Select appointment date and time.";
    if (!Number.isInteger(createDuration) || createDuration < 10 || createDuration > 180) {
      return "Duration must be between 10 and 180 minutes.";
    }
    const selectedDate = new Date(createDateTime);
    if (Number.isNaN(selectedDate.getTime()) || selectedDate <= new Date()) {
      return "Appointment time must be in the future.";
    }
    if (!createTimezone.trim()) return "Timezone is required.";
    return null;
  }

  async function onCreateAppointment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);
    setActionError(null);
    const validationError = validateCreateForm();
    if (validationError) {
      setCreateError(validationError);
      return;
    }
    if (!selectedTeacher) return;

    const payload: CreateParentAppointmentRequest = {
      student_id: selectedStudentId,
      teacher_id: selectedTeacher.teacher_id,
      subject_id: selectedTeacher.subject_id,
      timetable_entry_id: selectedTeacher.timetable_entry_id,
      requested_start_at: toIsoFromLocal(createDateTime),
      duration_minutes: createDuration,
      timezone: createTimezone,
      meeting_mode: createMode,
      location_or_link: createLocation.trim() || null,
      reason: createReason.trim() || null,
      parent_notes: createNotes.trim() || null,
    };

    setCreatePending(true);
    try {
      const created = await createParentAppointment(payload);
      setSelectedAppointmentId(created.appointment.id);
      setCreateReason("");
      setCreateNotes("");
      setCreateLocation("");
      setCreateDateTime(getInitialDatetimeLocal());
      await loadAppointments();
      await loadAppointmentDetail(created.appointment.id);
    } catch (err) {
      setCreateError(readError(err));
    } finally {
      setCreatePending(false);
    }
  }

  async function onCancelAppointment() {
    if (!selectedAppointment) return;
    if (!canParentModify(selectedAppointment.status)) return;
    if (!window.confirm("Cancel this appointment?")) return;

    setCancelPending(true);
    setActionError(null);
    try {
      await cancelParentAppointment(selectedAppointment.id);
      await loadAppointments();
      await loadAppointmentDetail(selectedAppointment.id);
    } catch (err) {
      setActionError(readError(err));
    } finally {
      setCancelPending(false);
    }
  }

  function validateRescheduleForm(): string | null {
    if (!rescheduleDateTime) return "Select a new date and time.";
    if (!Number.isInteger(rescheduleDuration) || rescheduleDuration < 10 || rescheduleDuration > 180) {
      return "Duration must be between 10 and 180 minutes.";
    }
    const selectedDate = new Date(rescheduleDateTime);
    if (Number.isNaN(selectedDate.getTime()) || selectedDate <= new Date()) {
      return "Rescheduled time must be in the future.";
    }
    if (!rescheduleTimezone.trim()) return "Timezone is required.";
    return null;
  }

  async function onRescheduleAppointment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAppointment) return;
    if (!canParentModify(selectedAppointment.status)) return;

    const validationError = validateRescheduleForm();
    if (validationError) {
      setActionError(validationError);
      return;
    }

    if (!window.confirm("Submit appointment reschedule?")) return;

    setReschedulePending(true);
    setActionError(null);
    try {
      await rescheduleParentAppointment(selectedAppointment.id, {
        scheduled_start_at: toIsoFromLocal(rescheduleDateTime),
        duration_minutes: rescheduleDuration,
        timezone: rescheduleTimezone,
        meeting_mode: rescheduleMode,
        location_or_link: rescheduleLocation.trim() || null,
      });
      await loadAppointments();
      await loadAppointmentDetail(selectedAppointment.id);
    } catch (err) {
      setActionError(readError(err));
    } finally {
      setReschedulePending(false);
    }
  }

  if (loading) {
    return <ParentPageSkeleton title="Appointments" />;
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

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Appointments</h1>
          <p className="text-sm text-gray-600">Create, review, cancel, and reschedule your teacher appointments.</p>
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

      <section className="rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">New appointment</h2>
        <form className="mt-4 grid gap-4 md:grid-cols-2" onSubmit={onCreateAppointment}>
          <div className="space-y-2">
            <label htmlFor="student" className="block text-sm font-medium text-gray-700">Student</label>
            <select
              id="student"
              value={selectedStudentId}
              onChange={(event) => setSelectedStudentId(event.target.value)}
              disabled={studentsLoading || createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              {students.length === 0 ? <option value="">No students found</option> : null}
              {students.map((student) => (
                <option key={student.student_id} value={student.student_id}>{student.name}</option>
              ))}
            </select>
            {studentsError ? <p className="text-sm text-red-700">{studentsError}</p> : null}
          </div>

          <div className="space-y-2">
            <label htmlFor="teacher-option" className="block text-sm font-medium text-gray-700">Teacher/Subject</label>
            <select
              id="teacher-option"
              value={selectedTeacherOption}
              onChange={(event) => setSelectedTeacherOption(event.target.value)}
              disabled={eligibleLoading || createPending || !selectedStudentId}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              {eligibleOptions.length === 0 ? <option value="">No eligible options</option> : null}
              {eligibleOptions.map((option) => (
                <option key={optionKey(option)} value={optionKey(option)}>
                  {option.teacher_name} {option.subject_name ? `• ${option.subject_name}` : "• Homeroom"}
                </option>
              ))}
            </select>
            {eligibleError ? <p className="text-sm text-red-700">{eligibleError}</p> : null}
          </div>

          <div className="space-y-2">
            <label htmlFor="appointment-datetime" className="block text-sm font-medium text-gray-700">Date & time</label>
            <input
              id="appointment-datetime"
              type="datetime-local"
              value={createDateTime}
              onChange={(event) => setCreateDateTime(event.target.value)}
              disabled={createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="appointment-duration" className="block text-sm font-medium text-gray-700">Duration (minutes)</label>
            <input
              id="appointment-duration"
              type="number"
              min={10}
              max={180}
              value={createDuration}
              onChange={(event) => setCreateDuration(Number(event.target.value))}
              disabled={createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="appointment-timezone" className="block text-sm font-medium text-gray-700">Timezone</label>
            <input
              id="appointment-timezone"
              type="text"
              value={createTimezone}
              onChange={(event) => setCreateTimezone(event.target.value)}
              disabled={createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="appointment-mode" className="block text-sm font-medium text-gray-700">Meeting mode</label>
            <select
              id="appointment-mode"
              value={createMode}
              onChange={(event) => setCreateMode(event.target.value as AppointmentMeetingMode)}
              disabled={createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              {meetingModes.map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </div>

          <div className="space-y-2 md:col-span-2">
            <label htmlFor="appointment-location" className="block text-sm font-medium text-gray-700">Location or link (optional)</label>
            <input
              id="appointment-location"
              type="text"
              value={createLocation}
              onChange={(event) => setCreateLocation(event.target.value)}
              disabled={createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div className="space-y-2 md:col-span-2">
            <label htmlFor="appointment-reason" className="block text-sm font-medium text-gray-700">Reason (optional)</label>
            <input
              id="appointment-reason"
              type="text"
              value={createReason}
              onChange={(event) => setCreateReason(event.target.value)}
              disabled={createPending}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div className="space-y-2 md:col-span-2">
            <label htmlFor="appointment-notes" className="block text-sm font-medium text-gray-700">Parent notes (optional)</label>
            <textarea
              id="appointment-notes"
              value={createNotes}
              onChange={(event) => setCreateNotes(event.target.value)}
              disabled={createPending}
              className="min-h-24 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          {createError ? <p className="md:col-span-2 text-sm text-red-700">{createError}</p> : null}

          <div className="md:col-span-2 flex justify-end">
            <button
              type="submit"
              disabled={createPending || studentsLoading || !selectedStudentId || !selectedTeacher}
              className="inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {createPending ? "Creating..." : "Create appointment"}
            </button>
          </div>
        </form>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Your appointments</h2>
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
                description="Create your first appointment using the form above."
              />
            </div>
          ) : (
            <ul className="mt-4 space-y-2" role="listbox" aria-label="Parent appointments">
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
                <p className="mt-1 text-xs text-gray-500">ID: {selectedAppointment.id}</p>
              </div>

              {actionError ? <p className="text-sm text-red-700">{actionError}</p> : null}

              {canParentModify(selectedAppointment.status) ? (
                <div className="space-y-4">
                  <button
                    type="button"
                    onClick={() => {
                      void onCancelAppointment();
                    }}
                    disabled={cancelPending || reschedulePending}
                    className="inline-flex w-full items-center justify-center rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {cancelPending ? "Cancelling..." : "Cancel appointment"}
                  </button>

                  <form className="space-y-3 rounded-xl border border-gray-200 p-4" onSubmit={onRescheduleAppointment}>
                    <h3 className="text-sm font-semibold text-gray-900">Reschedule</h3>
                    <div className="space-y-2">
                      <label htmlFor="reschedule-datetime" className="block text-sm font-medium text-gray-700">New date & time</label>
                      <input
                        id="reschedule-datetime"
                        type="datetime-local"
                        value={rescheduleDateTime}
                        onChange={(event) => setRescheduleDateTime(event.target.value)}
                        disabled={reschedulePending || cancelPending}
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
                        onChange={(event) => setRescheduleDuration(Number(event.target.value))}
                        disabled={reschedulePending || cancelPending}
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
                        disabled={reschedulePending || cancelPending}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                        required
                      />
                    </div>

                    <div className="space-y-2">
                      <label htmlFor="reschedule-mode" className="block text-sm font-medium text-gray-700">Meeting mode</label>
                      <select
                        id="reschedule-mode"
                        value={rescheduleMode}
                        onChange={(event) => setRescheduleMode(event.target.value as AppointmentMeetingMode)}
                        disabled={reschedulePending || cancelPending}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      >
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
                        disabled={reschedulePending || cancelPending}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      />
                    </div>

                    <button
                      type="submit"
                      disabled={reschedulePending || cancelPending}
                      className="inline-flex w-full items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {reschedulePending ? "Rescheduling..." : "Reschedule appointment"}
                    </button>
                  </form>
                </div>
              ) : (
                <p className="text-sm text-gray-600">This appointment can no longer be modified.</p>
              )}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function optionKey(option: EligibleAppointmentTeacherOption): string {
  return `${option.teacher_id}|${option.subject_id ?? "none"}|${option.timetable_entry_id ?? "none"}`;
}

function readError(error: unknown): string {
  if (error instanceof AppointmentsApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected request failure.";
}
