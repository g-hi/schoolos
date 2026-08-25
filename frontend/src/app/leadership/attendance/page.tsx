"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  correctLeadershipAttendanceRegister,
  finalizeLeadershipAttendanceRegister,
  getLeadershipAttendanceDailySummary,
  getLeadershipAttendanceRegister,
  listLeadershipAttendanceRegisters,
  type LeadershipAttendanceDailySummary,
  type LeadershipAttendanceRegisterDetail,
  type LeadershipAttendanceRegisterListItem,
} from "@/lib/teacher-api";

function localToday(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function statusLabel(status: string): string {
  if (status === "open") return "Open";
  if (status === "submitted") return "Submitted";
  if (status === "finalized") return "Finalized";
  if (status === "not_started") return "Not started";
  if (status === "parallel_unresolved") return "Parallel unresolved";
  return status.replaceAll("_", " ");
}

function statusTone(status: string): string {
  if (status === "finalized") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (status === "submitted") {
    return "border-sky-200 bg-sky-50 text-sky-800";
  }
  if (status === "open") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function attendanceTone(status: string): string {
  if (status === "present") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (status === "absent") {
    return "border-rose-200 bg-rose-50 text-rose-800";
  }
  if (status === "late") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (status === "excused") {
    return "border-sky-200 bg-sky-50 text-sky-800";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function errorMessage(error: unknown): string {
  if (error instanceof TeacherApiError) {
    return error.message;
  }
  return "Unable to complete the attendance operation.";
}

export default function LeadershipAttendancePage() {
  const auth = useAuth();

  const [schoolDate, setSchoolDate] = useState(localToday);
  const [summary, setSummary] =
    useState<LeadershipAttendanceDailySummary | null>(null);
  const [registers, setRegisters] =
    useState<LeadershipAttendanceRegisterListItem[]>([]);
  const [selectedRegister, setSelectedRegister] =
    useState<LeadershipAttendanceRegisterDetail | null>(null);

  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [correctionStudentId, setCorrectionStudentId] =
    useState<string | null>(null);
  const [correctionStatus, setCorrectionStatus] = useState("present");
  const [correctionReason, setCorrectionReason] = useState("");

  const loadWorkspace = useCallback(async () => {
    if (
      !auth.isAuthenticated ||
      !auth.token ||
      auth.user?.role !== "principal"
    ) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const [summaryResponse, registerResponse] = await Promise.all([
        getLeadershipAttendanceDailySummary(schoolDate, auth.token),
        listLeadershipAttendanceRegisters(schoolDate, auth.token),
      ]);

      setSummary(summaryResponse);
      setRegisters(registerResponse);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [
    auth.isAuthenticated,
    auth.token,
    auth.user?.role,
    schoolDate,
  ]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const sortedRegisters = useMemo(() => {
    return [...registers].sort((a, b) => {
      const timeCompare = (a.start_time ?? "").localeCompare(
        b.start_time ?? "",
      );

      if (timeCompare !== 0) return timeCompare;

      return a.class_display_name.localeCompare(b.class_display_name);
    });
  }, [registers]);

  const actionRequired =
    (summary?.not_started ?? 0) +
    (summary?.open ?? 0) +
    (summary?.parallel_unresolved ?? 0);

  async function openRegister(registerId: string) {
    if (!auth.token) return;

    setDetailLoading(true);
    setError(null);
    setCorrectionStudentId(null);
    setCorrectionReason("");

    try {
      const response = await getLeadershipAttendanceRegister(
        registerId,
        auth.token,
      );
      setSelectedRegister(response);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDetailLoading(false);
    }
  }

  async function finalizeRegister() {
    if (!auth.token || !selectedRegister) return;

    setBusy(true);
    setError(null);

    try {
      await finalizeLeadershipAttendanceRegister(
        selectedRegister.register_id,
        auth.token,
      );

      const refreshed = await getLeadershipAttendanceRegister(
        selectedRegister.register_id,
        auth.token,
      );

      setSelectedRegister(refreshed);
      await loadWorkspace();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function applyCorrection() {
    if (
      !auth.token ||
      !selectedRegister ||
      !correctionStudentId ||
      correctionReason.trim().length === 0
    ) {
      return;
    }

    setBusy(true);
    setError(null);

    try {
      await correctLeadershipAttendanceRegister(
        selectedRegister.register_id,
        {
          student_id: correctionStudentId,
          new_status: correctionStatus,
          correction_reason: correctionReason.trim(),
        },
        auth.token,
      );

      const refreshed = await getLeadershipAttendanceRegister(
        selectedRegister.register_id,
        auth.token,
      );

      setSelectedRegister(refreshed);
      setCorrectionStudentId(null);
      setCorrectionReason("");

      await loadWorkspace();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <h1 className="text-xl font-semibold text-slate-900">
          Attendance Operations
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Sign in to access leadership attendance operations.
        </p>
      </div>
    );
  }

  if (auth.user?.role !== "principal") {
    return (
      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6">
        <h1 className="text-xl font-semibold text-amber-950">
          Attendance Operations
        </h1>
        <p className="mt-2 text-sm text-amber-800">
          Principal access is required for this workspace.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="rounded-3xl border border-slate-200 bg-linear-to-br from-slate-950 via-slate-900 to-blue-950 p-6 text-white shadow-lg">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-300">
              Leadership Operations
            </p>

            <h1 className="mt-2 text-3xl font-bold tracking-tight">
              Attendance Command Centre
            </h1>

            <p className="mt-2 max-w-2xl text-sm text-slate-200">
              Monitor daily attendance completion, review registers, finalize
              submitted attendance, and apply reasoned corrections.
            </p>
          </div>

          <label className="rounded-2xl border border-white/20 bg-white/10 p-4">
            <span className="block text-xs font-semibold uppercase tracking-wide text-slate-300">
              School date
            </span>

            <input
              type="date"
              aria-label="School date"
              value={schoolDate}
              onChange={(event) => {
                setSchoolDate(event.target.value);
                setSelectedRegister(null);
              }}
              className="mt-2 rounded-lg border border-white/30 bg-white px-3 py-2 text-sm font-medium text-slate-900"
            />
          </label>
        </div>
      </header>

      {error ? (
        <aside
          role="alert"
          className="rounded-2xl border border-rose-200 bg-rose-50 p-4"
        >
          <p className="font-semibold text-rose-900">
            Attendance operation failed
          </p>
          <p className="mt-1 text-sm text-rose-800">{error}</p>
        </aside>
      ) : null}

      {loading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="animate-pulse space-y-3">
            <div className="h-5 w-48 rounded bg-slate-100" />
            <div className="h-20 rounded bg-slate-50" />
            <div className="h-20 rounded bg-slate-50" />
          </div>
        </section>
      ) : null}

      {!loading && summary ? (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <SummaryCard
              label="Eligible sessions"
              value={summary.eligible_sessions}
            />
            <SummaryCard
              label="Not started"
              value={summary.not_started}
            />
            <SummaryCard label="Open" value={summary.open} />
            <SummaryCard
              label="Submitted"
              value={summary.submitted}
            />
            <SummaryCard
              label="Finalized"
              value={summary.finalized}
            />
          </section>

          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
            <SummaryCard
              label="Expected students"
              value={summary.expected_students}
            />
            <SummaryCard label="Present" value={summary.present} />
            <SummaryCard label="Absent" value={summary.absent} />
            <SummaryCard label="Late" value={summary.late} />
            <SummaryCard label="Excused" value={summary.excused} />
            <SummaryCard label="Unmarked" value={summary.unmarked} />
          </section>

          {actionRequired > 0 ? (
            <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
              <p className="text-sm font-semibold text-amber-950">
                {actionRequired} session
                {actionRequired === 1 ? "" : "s"} require attention.
              </p>

              <p className="mt-1 text-sm text-amber-800">
                This includes registers that have not started, remain open, or
                have unresolved parallel-roster membership.
              </p>
            </section>
          ) : null}
        </>
      ) : null}

      {!loading && sortedRegisters.length === 0 ? (
        <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <h2 className="font-semibold text-slate-900">
            No attendance registers for this date
          </h2>
          <p className="mt-2 text-sm text-slate-600">
            Registers will appear here after teachers open attendance for
            eligible sessions.
          </p>
        </section>
      ) : null}

      {!loading && sortedRegisters.length > 0 ? (
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 p-5">
            <h2 className="text-lg font-semibold text-slate-900">
              Register inventory
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              School-wide attendance register status for {schoolDate}.
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Class</th>
                  <th className="px-4 py-3">Subject</th>
                  <th className="px-4 py-3">Teacher</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Marked</th>
                  <th className="px-4 py-3">Present</th>
                  <th className="px-4 py-3">Absent</th>
                  <th className="px-4 py-3">Late</th>
                  <th className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>

              <tbody className="divide-y divide-slate-100">
                {sortedRegisters.map((register) => (
                  <tr key={register.register_id}>
                    <td className="whitespace-nowrap px-4 py-4 text-slate-700">
                      {register.start_time && register.end_time
                        ? `${register.start_time} - ${register.end_time}`
                        : "—"}
                    </td>

                    <td className="px-4 py-4">
                      <p className="font-semibold text-slate-900">
                        {register.class_display_name}
                      </p>
                      <p className="text-xs text-slate-500">
                        {register.class_code ?? ""}
                      </p>
                    </td>

                    <td className="px-4 py-4 text-slate-700">
                      {register.subject_name ?? "—"}
                    </td>

                    <td className="px-4 py-4 text-slate-700">
                      {register.teacher_name ?? "—"}
                    </td>

                    <td className="px-4 py-4">
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(
                          register.status,
                        )}`}
                      >
                        {statusLabel(register.status)}
                      </span>
                    </td>

                    <td className="px-4 py-4 font-medium text-slate-900">
                      {register.marked}/{register.expected}
                    </td>

                    <td className="px-4 py-4 text-slate-700">
                      {register.present}
                    </td>

                    <td className="px-4 py-4 text-slate-700">
                      {register.absent}
                    </td>

                    <td className="px-4 py-4 text-slate-700">
                      {register.late}
                    </td>

                    <td className="px-4 py-4 text-right">
                      <button
                        type="button"
                        onClick={() => void openRegister(register.register_id)}
                        className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                      >
                        Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {detailLoading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-600">Loading register…</p>
        </section>
      ) : null}

      {selectedRegister && !detailLoading ? (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 p-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Register detail
              </p>

              <h2 className="mt-1 text-lg font-semibold text-slate-900">
                Attendance register
              </h2>

              <p className="mt-1 text-sm text-slate-600">
                {selectedRegister.marked_count}/
                {selectedRegister.expected_count} students marked
              </p>
            </div>

            <div className="flex items-center gap-3">
              <span
                className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${statusTone(
                  selectedRegister.register_status,
                )}`}
              >
                {statusLabel(selectedRegister.register_status)}
              </span>

              {selectedRegister.register_status === "submitted" ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void finalizeRegister()}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busy ? "Working…" : "Finalize register"}
                </button>
              ) : null}
            </div>
          </div>

          <div className="divide-y divide-slate-100">
            {selectedRegister.records.map((record) => {
              const correctionOpen =
                correctionStudentId === record.student_id;

              const correctionAllowed =
                selectedRegister.register_status === "submitted" ||
                selectedRegister.register_status === "finalized";

              return (
                <div key={record.student_id} className="p-5">
                  <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-semibold text-slate-900">
                        {record.student_name}
                      </p>

                      <p className="text-xs text-slate-500">
                        {record.student_identifier ?? "No student code"}
                      </p>
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${attendanceTone(
                          record.status,
                        )}`}
                      >
                        {statusLabel(record.status)}
                      </span>

                      {record.status === "late" &&
                      record.minutes_late !== null ? (
                        <span className="text-xs text-slate-500">
                          {record.minutes_late} min late
                        </span>
                      ) : null}

                      {correctionAllowed ? (
                        <button
                          type="button"
                          onClick={() => {
                            setCorrectionStudentId(
                              correctionOpen ? null : record.student_id,
                            );
                            setCorrectionStatus(record.status);
                            setCorrectionReason("");
                          }}
                          className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                        >
                          {correctionOpen ? "Cancel" : "Correct"}
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {correctionOpen ? (
                    <div className="mt-4 grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-[180px_1fr_auto] md:items-end">
                      <label>
                        <span className="text-xs font-semibold text-slate-700">
                          New status
                        </span>

                        <select
                          aria-label={`New status for ${record.student_name}`}
                          value={correctionStatus}
                          onChange={(event) =>
                            setCorrectionStatus(event.target.value)
                          }
                          className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                        >
                          <option value="present">Present</option>
                          <option value="absent">Absent</option>
                          <option value="late">Late</option>
                          <option value="excused">Excused</option>
                        </select>
                      </label>

                      <label>
                        <span className="text-xs font-semibold text-slate-700">
                          Correction reason
                        </span>

                        <input
                          aria-label={`Correction reason for ${record.student_name}`}
                          value={correctionReason}
                          onChange={(event) =>
                            setCorrectionReason(event.target.value)
                          }
                          placeholder="Explain why this attendance record is being corrected"
                          className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                        />
                      </label>

                      <button
                        type="button"
                        disabled={
                          busy || correctionReason.trim().length === 0
                        }
                        onClick={() => void applyCorrection()}
                        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Apply correction
                      </button>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-3xl font-bold tracking-tight text-slate-900">
        {value}
      </p>
    </div>
  );
}