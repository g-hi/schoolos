"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  bulkMarkTeacherAttendance,
  ensureTeacherAttendanceRegister,
  getTeacherAttendanceRegister,
  getTeacherAttendanceToday,
  markAllPresentTeacherAttendance,
  submitTeacherAttendanceRegister,
  type TeacherAttendanceRegisterDetail,
  type TeacherAttendanceRegisterRecord,
  type TeacherAttendanceTodayResponse,
} from "@/lib/teacher-api";

function friendlyAttendanceStatus(status: string): string {
  if (status === "not_started") return "Not started";
  if (status === "incomplete") return "In progress";
  if (status === "submitted") return "Submitted";
  if (status === "finalized") return "Finalized";
  if (status === "unavailable") return "Unavailable";
  if (status === "parallel_unresolved") return "Parallel roster unresolved";
  if (status === "parallel_roster_membership_unresolved") return "Parallel roster unresolved";
  if (status === "open") return "Open";
  return status;
}

function friendlyRegisterStatus(status: string): string {
  if (status === "open") return "Open";
  if (status === "submitted") return "Submitted";
  if (status === "finalized") return "Finalized";
  return status;
}

function AttendancePageLoading() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <div className="animate-pulse space-y-3">
        <div className="h-5 w-44 rounded bg-gray-100" />
        <div className="h-4 w-72 rounded bg-gray-100" />
        <div className="h-24 rounded bg-gray-50" />
      </div>
    </div>
  );
}

export default function TeacherAttendancePage() {
  const auth = useAuth();
  const [today, setToday] = useState<TeacherAttendanceTodayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSessionKey, setSelectedSessionKey] = useState<string | null>(null);
  const [register, setRegister] = useState<TeacherAttendanceRegisterDetail | null>(null);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [draftRecords, setDraftRecords] = useState<TeacherAttendanceRegisterRecord[]>([]);
  const [busy, setBusy] = useState(false);

  async function loadToday() {
    if (!auth.isAuthenticated || !auth.token) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await getTeacherAttendanceToday(undefined, auth.token);
      setToday(response);
      setSelectedSessionKey(null);
    } catch (err) {
      setError(err instanceof TeacherApiError ? err.message : "Unable to load attendance.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadToday();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, auth.token]);

  const sessions = useMemo(() => {
    const seen = new Map<string, TeacherAttendanceTodayResponse["items"][number]>();

    for (const item of today?.items ?? []) {
      if (!seen.has(item.class_facing_session_key)) {
        seen.set(item.class_facing_session_key, item);
      }
    }

    return Array.from(seen.values());
  }, [today]);

  async function openRegister(session: (typeof sessions)[number]) {
    if (!auth.token) return;
    setBusy(true);
    try {
      const result = await ensureTeacherAttendanceRegister(session.daily_session_id, auth.token);
      await loadRegister(result.register_id);
    } catch (err) {
      setError(err instanceof TeacherApiError ? err.message : "Unable to open register.");
    } finally {
      setBusy(false);
    }
  }

  async function loadRegister(registerId: string) {
    if (!auth.token) return;
    setRegisterLoading(true);
    try {
      const detail = await getTeacherAttendanceRegister(registerId, auth.token);
      setRegister(detail);
      setDraftRecords(detail.records);
      setSelectedSessionKey(register.class_facing_session_key);
    } catch (err) {
      setError(err instanceof TeacherApiError ? err.message : "Unable to load attendance.");
    } finally {
      setRegisterLoading(false);
    }
  }

  async function saveDraft(registerId: string) {
    if (!auth.token || !register) return;
    setSaveState("saving");
    try {
      const marks = draftRecords.map((rec) => ({
        student_id: rec.student_id,
        status: rec.attendance_status,
        minutes_late: rec.attendance_status === "late" ? rec.minutes_late ?? 0 : null,
      }));

      const result = await bulkMarkTeacherAttendance(registerId, marks, auth.token);
      setRegister((current) => current ? { ...current, register_status: result.register_status } : current);
      setSaveState("saved");
    } catch (err) {
      setSaveState("error");
      setError(err instanceof TeacherApiError ? err.message : "Unable to save attendance.");
    }
  }

  async function markAllPresent(registerId: string) {
    if (!auth.token) return;
    try {
      const result = await markAllPresentTeacherAttendance(registerId, auth.token);
      setRegister((current) => current ? { ...current, register_status: result.register_status } : current);
    } catch (err) {
      setError(err instanceof TeacherApiError ? err.message : "Unable to mark all present.");
    }
  }

  async function submit(registerId: string) {
    if (!auth.token) return;
    try {
      const result = await submitTeacherAttendanceRegister(registerId, auth.token);
      setRegister((current) => current ? { ...current, register_status: result.register_status } : current);
    } catch (err) {
      if (err instanceof TeacherApiError && err.status === 409) {
        setError("Complete attendance for all students before submitting.");
      } else {
        setError(err instanceof TeacherApiError ? err.message : "Unable to submit attendance.");
      }
    }
  }

  const available = sessions.filter((item) => item.attendance_status !== "parallel_unresolved" && item.attendance_status !== "unavailable");

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Today's Classes</h1>
            <p className="mt-1 text-sm text-gray-600">Teacher attendance workspace</p>
          </div>
          <div className="rounded-full border border-gray-200 px-3 py-1 text-sm text-gray-700">
            {today?.school_date ?? "Today"}
          </div>
        </div>
      </header>

      {error ? (
        <aside className="rounded-xl border border-rose-200 bg-rose-50 p-4" role="alert">
          <p className="text-sm font-semibold text-rose-900">Unable to load attendance</p>
          <p className="text-sm text-rose-800">{error}</p>
        </aside>
      ) : null}

      {loading ? <AttendancePageLoading /> : null}

      {!loading && !error && today && sessions.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-white p-8 text-center">
          <p className="text-sm font-semibold text-gray-900">No classes scheduled for this date.</p>
          <p className="mt-2 text-sm text-gray-600">No classes are currently available for attendance.</p>
        </div>
      ) : null}

      {!loading && !error && sessions.length > 0 ? (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sessions.map((item) => {
            const registerExists = Boolean(item.attendance_register_id);
            const isReadOnly = item.attendance_status === "submitted" || item.attendance_status === "finalized" || item.attendance_status === "finalized";
            const sessionSelected = selectedSessionKey === item.class_facing_session_key;

            return (
              <article key={item.class_facing_session_key} className={`rounded-2xl border p-5 ${sessionSelected ? "border-indigo-600 bg-indigo-50/40" : "border-gray-200 bg-white"}`}>
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{item.start_time} - {item.end_time}</p>
                    <h2 className="mt-2 text-lg font-semibold text-gray-900">{item.class_display_name || "Class"}</h2>
                    <p className="text-sm text-gray-700">{item.subject_name || "Subject"}</p>
                  </div>
                  <span className="inline-flex rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-semibold text-gray-700">
                    {friendlyAttendanceStatus(item.attendance_status)}
                  </span>
                </div>

                <div className="mt-4 flex items-center justify-between gap-3">
                  <span className="text-xs text-gray-500">{item.session_status}</span>
                  <span className="text-xs text-gray-500">{item.marked_count}/{item.expected_count} marked</span>
                </div>

                {item.attendance_status === "unavailable" ? (
                  <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                    Attendance unavailable for this session.
                  </div>
                ) : null}

                {item.attendance_status === "parallel_unresolved" || item.attendance_status === "parallel_roster_membership_unresolved" ? (
                  <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                    Attendance cannot be opened because student group membership for this parallel lesson has not been configured.
                  </div>
                ) : null}

                {!registerExists && item.attendance_status !== "unavailable" && item.attendance_status !== "parallel_unresolved" && item.attendance_status !== "parallel_roster_membership_unresolved" ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void openRegister(item)}
                    className="mt-4 w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    Take Attendance
                  </button>
                ) : null}

                {registerExists && item.attendance_register_id ? (
                  <button
                    type="button"
                    onClick={() => void loadRegister(item.attendance_register_id as string)}
                    className="mt-4 w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-900 hover:bg-gray-50"
                  >
                    Open Register
                  </button>
                ) : null}
              </article>
            );
          })}
        </section>
      ) : null}

      {registerLoading ? <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-700">Loading register...</div> : null}

      {register ? (
        <section className="rounded-2xl border border-gray-200 bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-gray-900">Register: {register.class_facing_session_key}</h2>
              <p className="text-sm text-gray-600">{friendlyRegisterStatus(register.register_status)}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void markAllPresent(register.register_id)}
                className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-100"
                disabled={register.register_status === "submitted" || register.register_status === "finalized"}
              >
                Mark All Present
              </button>
              <button
                type="button"
                onClick={() => void saveDraft(register.register_id)}
                className="rounded-lg border border-indigo-300 bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-800 hover:bg-indigo-100"
                disabled={register.register_status === "submitted" || register.register_status === "finalized"}
              >
                Save Attendance
              </button>
              <button
                type="button"
                onClick={() => void submit(register.register_id)}
                className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700"
                disabled={register.register_status === "submitted" || register.register_status === "finalized"}
              >
                Submit Attendance
              </button>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-4 text-sm text-gray-600">
            <span>{saveState === "saving" ? "Saving..." : saveState === "saved" ? "Saved" : saveState === "error" ? "Error" : "Ready"}</span>
            <span>{register.marked_count} marked</span>
            <span>{register.unmarked_count} unmarked</span>
          </div>

          <div className="mt-5 overflow-x-auto">
            <table className="min-w-full border border-gray-200">
              <thead>
                <tr className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-600">
                  <th className="px-3 py-2">Student</th>
                  <th className="px-3 py-2">Present</th>
                  <th className="px-3 py-2">Absent</th>
                  <th className="px-3 py-2">Late</th>
                  <th className="px-3 py-2">Excused</th>
                  <th className="px-3 py-2">Late Minutes</th>
                </tr>
              </thead>
              <tbody>
                {draftRecords.map((record) => (
                  <tr key={record.student_id} className="border-t border-gray-200">
                    <td className="px-3 py-3">
                      <div className="font-medium text-gray-900">{record.student_name}</div>
                      <div className="text-xs text-gray-500">{record.student_identifier || "Student"}</div>
                    </td>
                    <td className="px-3 py-3">
                      <label className="inline-flex items-center gap-2">
                        <input
                          aria-label="Present"
                          type="radio"
                          name={`attendance-${record.student_id}`}
                          checked={record.attendance_status === "present"}
                          disabled={register.register_status === "submitted" || register.register_status === "finalized"}
                          onChange={() => {
                            setDraftRecords((current) => current.map((row) => row.student_id === record.student_id ? { ...row, attendance_status: "present", minutes_late: null } : row));
                          }}
                        />
                        <span className="text-sm">Present</span>
                      </label>
                    </td>
                    <td className="px-3 py-3">
                      <label className="inline-flex items-center gap-2">
                        <input
                          aria-label="Absent"
                          type="radio"
                          name={`attendance-${record.student_id}`}
                          checked={record.attendance_status === "absent"}
                          disabled={register.register_status === "submitted" || register.register_status === "finalized"}
                          onChange={() => {
                            setDraftRecords((current) => current.map((row) => row.student_id === record.student_id ? { ...row, attendance_status: "absent", minutes_late: null } : row));
                          }}
                        />
                        <span className="text-sm">Absent</span>
                      </label>
                    </td>
                    <td className="px-3 py-3">
                      <label className="inline-flex items-center gap-2">
                        <input
                          aria-label="Late"
                          type="radio"
                          name={`attendance-${record.student_id}`}
                          checked={record.attendance_status === "late"}
                          disabled={register.register_status === "submitted" || register.register_status === "finalized"}
                          onChange={() => {
                            setDraftRecords((current) => current.map((row) => row.student_id === record.student_id ? { ...row, attendance_status: "late", minutes_late: row.minutes_late ?? 0 } : row));
                          }}
                        />
                        <span className="text-sm">Late</span>
                      </label>
                    </td>
                    <td className="px-3 py-3">
                      <label className="inline-flex items-center gap-2">
                        <input
                          aria-label="Excused"
                          type="radio"
                          name={`attendance-${record.student_id}`}
                          checked={record.attendance_status === "excused"}
                          disabled={register.register_status === "submitted" || register.register_status === "finalized"}
                          onChange={() => {
                            setDraftRecords((current) => current.map((row) => row.student_id === record.student_id ? { ...row, attendance_status: "excused", minutes_late: null } : row));
                          }}
                        />
                        <span className="text-sm">Excused</span>
                      </label>
                    </td>
                    <td className="px-3 py-3">
                      {record.attendance_status === "late" ? (
                        <label className="flex items-center gap-2">
                          <span className="text-sm">Minutes late</span>
                          <input
                            aria-label="Minutes late"
                            type="number"
                            min="0"
                            value={record.minutes_late ?? 0}
                            disabled={register.register_status === "submitted" || register.register_status === "finalized"}
                            onChange={(event) => {
                              const value = Number(event.target.value);
                              setDraftRecords((current) => current.map((row) => row.student_id === record.student_id ? { ...row, minutes_late: value } : row));
                            }}
                            className="w-24 rounded border border-gray-300 px-2 py-1"
                          />
                        </label>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
