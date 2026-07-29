"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ParentLoginPanel from "@/components/parent/parent-login-panel";
import { useParentAuth } from "@/components/parent/parent-auth-provider";
import { ParentEmptyState, ParentErrorState, ParentPageSkeleton } from "@/components/parent/parent-page-states";
import {
  ParentApiError,
  ParentPickupRequest,
  ParentPickupStatus,
  ParentStudentSummary,
  cancelParentPickupRequest,
  createParentPickupRequest,
  getParentStudents,
  listParentPickupRequests,
} from "@/lib/parent-api";

const cancellableStatuses: ParentPickupStatus[] = ["requested", "acknowledged", "called", "prepared"];
const activeStatuses = new Set<ParentPickupStatus>(["requested", "acknowledged", "called", "prepared"]);

function statusBadgeClass(status: ParentPickupStatus): string {
  switch (status) {
    case "requested":
      return "bg-sky-100 text-sky-700";
    case "acknowledged":
      return "bg-indigo-100 text-indigo-700";
    case "called":
      return "bg-amber-100 text-amber-700";
    case "prepared":
      return "bg-purple-100 text-purple-700";
    case "completed":
      return "bg-emerald-100 text-emerald-700";
    case "cancelled":
      return "bg-gray-100 text-gray-700";
    case "released":
      return "bg-teal-100 text-teal-700";
    case "rejected_outside_geofence":
      return "bg-rose-100 text-rose-700";
    default:
      return "bg-gray-100 text-gray-700";
  }
}

function statusLabel(status: ParentPickupStatus): string {
  switch (status) {
    case "requested":
      return "Requested";
    case "acknowledged":
      return "Acknowledged";
    case "called":
      return "Called";
    case "prepared":
      return "Prepared";
    case "completed":
      return "Completed";
    case "cancelled":
      return "Cancelled";
    case "released":
      return "Released";
    case "rejected_outside_geofence":
      return "Rejected Outside Geofence";
    default:
      return status;
  }
}

function isCancellable(status: ParentPickupStatus): boolean {
  return cancellableStatuses.includes(status);
}

function mapPickupError(error: unknown): string {
  if (error instanceof ParentApiError) {
    const detail = error.message.toLowerCase();
    if (error.status === 401) {
      return "Your session has expired. Please sign in again.";
    }
    if (error.status === 403 && detail.includes("pickup is not allowed")) {
      return "Pickup permission is not granted for this student.";
    }
    if (error.status === 404 && detail.includes("no active family")) {
      return "No active family profile is available for this account.";
    }
    if (error.status === 404) {
      return "The pickup request or student record was not found.";
    }
    if (error.status === 409 && detail.includes("terminal status")) {
      return "This request is already completed or cancelled and cannot be changed.";
    }
    if (error.status === 409 && detail.includes("illegal pickup lifecycle transition")) {
      return "Cancellation is not allowed from the current pickup status.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

function formatDate(value: string | null): string {
  if (!value) {
    return "Not set";
  }
  return new Date(value).toLocaleString();
}

function resolveStudentLabel(students: ParentStudentSummary[], studentId: string): string {
  const student = students.find((item) => item.student_id === studentId);
  return student ? `${student.name} (${student.class_name})` : "Linked student";
}

function PickupCard({
  pickup,
  students,
  onCancel,
  cancelling,
}: {
  pickup: ParentPickupRequest;
  students: ParentStudentSummary[];
  onCancel: (pickupId: string) => void;
  cancelling: boolean;
}) {
  const canCancel = isCancellable(pickup.status);

  return (
    <article className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Pickup for {resolveStudentLabel(students, pickup.student_id)}</h3>
          <p className="mt-1 text-xs text-gray-500">Requested: {formatDate(pickup.requested_at)}</p>
        </div>
        <span className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs font-semibold ${statusBadgeClass(pickup.status)}`}>
          {statusLabel(pickup.status)}
        </span>
      </div>

      {pickup.notes ? <p className="mt-3 text-sm text-gray-700">{pickup.notes}</p> : null}

      <dl className="mt-3 grid gap-2 text-xs text-gray-600 sm:grid-cols-2">
        <div>
          <dt className="font-medium text-gray-700">Acknowledged</dt>
          <dd>{formatDate(pickup.acknowledged_at)}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-700">Called</dt>
          <dd>{formatDate(pickup.called_at)}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-700">Prepared</dt>
          <dd>{formatDate(pickup.prepared_at)}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-700">Completed</dt>
          <dd>{formatDate(pickup.completed_at)}</dd>
        </div>
      </dl>

      {canCancel ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => onCancel(pickup.pickup_id)}
            disabled={cancelling}
            className="rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
          >
            {cancelling ? "Cancelling..." : "Cancel request"}
          </button>
        </div>
      ) : null}
    </article>
  );
}

export default function ParentPickupPage() {
  const auth = useParentAuth();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [students, setStudents] = useState<ParentStudentSummary[]>([]);
  const [eligibleStudents, setEligibleStudents] = useState<ParentStudentSummary[]>([]);
  const [pickups, setPickups] = useState<ParentPickupRequest[]>([]);
  const [selectedStudentId, setSelectedStudentId] = useState<string>("");
  const [commandText, setCommandText] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitPending, setSubmitPending] = useState(false);
  const [cancelPendingId, setCancelPendingId] = useState<string | null>(null);

  const activePickups = useMemo(
    () => pickups.filter((pickup) => activeStatuses.has(pickup.status)),
    [pickups],
  );
  const historyPickups = useMemo(
    () => pickups.filter((pickup) => !activeStatuses.has(pickup.status)),
    [pickups],
  );

  async function loadPageData(token: string) {
    setLoading(true);
    setLoadError(null);
    try {
      const [studentsResponse, pickupsResponse] = await Promise.all([
        getParentStudents(token),
        listParentPickupRequests({ page: 1, page_size: 50 }, token),
      ]);
      const nextStudents = studentsResponse.students;
      const nextEligible = nextStudents.filter((student) => student.can_pickup);

      setStudents(nextStudents);
      setEligibleStudents(nextEligible);
      setPickups(pickupsResponse.items);
      setSelectedStudentId((current) => {
        if (current && nextEligible.some((student) => student.student_id === current)) {
          return current;
        }
        return nextEligible[0]?.student_id ?? "";
      });
    } catch (error) {
      setLoadError(mapPickupError(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated || !auth.token) {
      setLoading(false);
      return;
    }
    void loadPageData(auth.token);
  }, [auth.isAuthenticated, auth.token]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!auth.token) {
      return;
    }
    setSubmitError(null);
    setSubmitMessage(null);

    if (!selectedStudentId) {
      setSubmitError("Select an eligible student first.");
      return;
    }
    if (!commandText.trim()) {
      setSubmitError("Enter a pickup request note.");
      return;
    }

    setSubmitPending(true);
    try {
      await createParentPickupRequest(
        {
          student_id: selectedStudentId,
          command_text: commandText.trim(),
        },
        auth.token,
      );
      setCommandText("");
      setSubmitMessage("Pickup request submitted. Staff will acknowledge, prepare, and verify before completion.");
      await loadPageData(auth.token);
    } catch (error) {
      setSubmitError(mapPickupError(error));
    } finally {
      setSubmitPending(false);
    }
  }

  async function onCancel(pickupId: string) {
    if (!auth.token) {
      return;
    }
    const confirmed = window.confirm("Cancel this pickup request?");
    if (!confirmed) {
      return;
    }

    setCancelPendingId(pickupId);
    setSubmitError(null);
    setSubmitMessage(null);
    try {
      await cancelParentPickupRequest(pickupId, {}, auth.token);
      setSubmitMessage("Pickup request cancelled.");
      await loadPageData(auth.token);
    } catch (error) {
      setSubmitError(mapPickupError(error));
    } finally {
      setCancelPendingId(null);
    }
  }

  if (auth.isHydrating) {
    return <ParentPageSkeleton title="Loading pickup" />;
  }

  if (!auth.isAuthenticated) {
    return <ParentLoginPanel onLogin={auth.login} />;
  }

  if (loading) {
    return <ParentPageSkeleton title="Loading pickup" />;
  }

  if (loadError) {
    return (
      <ParentErrorState
        title="Unable to load pickup requests"
        description={loadError}
        actionLabel="Retry"
        onAction={() => {
          if (auth.token) {
            void loadPageData(auth.token);
          }
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <h1 className="text-2xl font-semibold text-gray-900">Parent Pickup</h1>
        <p className="mt-2 text-sm text-gray-600">
          Request pickup for your linked students. School staff must acknowledge, prepare, and verify the student before completion.
        </p>
      </header>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-lg font-semibold text-gray-900">Create pickup request</h2>
        {eligibleStudents.length === 0 ? (
          <ParentEmptyState
            title="No eligible linked students"
            description="Your account has no linked students with pickup permission. Contact school administration if this is unexpected."
          />
        ) : (
          <form className="mt-4 space-y-4" onSubmit={onSubmit}>
            <div>
              <label htmlFor="pickup-student" className="block text-sm font-medium text-gray-700">
                Eligible student
              </label>
              <select
                id="pickup-student"
                value={selectedStudentId}
                onChange={(event) => setSelectedStudentId(event.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                {eligibleStudents.map((student) => (
                  <option key={student.student_id} value={student.student_id}>
                    {student.name} ({student.class_name})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="pickup-command" className="block text-sm font-medium text-gray-700">
                Pickup note
              </label>
              <textarea
                id="pickup-command"
                value={commandText}
                onChange={(event) => setCommandText(event.target.value)}
                rows={3}
                placeholder="Example: I am at the main gate for pickup."
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={submitPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-400"
            >
              {submitPending ? "Submitting..." : "Submit pickup request"}
            </button>
          </form>
        )}

        {submitError ? (
          <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {submitError}
          </p>
        ) : null}

        {submitMessage ? (
          <p className="mt-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700" role="status">
            {submitMessage}
          </p>
        ) : null}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">Active pickup requests</h2>
          <button
            type="button"
            onClick={() => {
              if (auth.token) {
                void loadPageData(auth.token);
              }
            }}
            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>

        {activePickups.length === 0 ? (
          <ParentEmptyState
            title="No active pickup requests"
            description="When you submit a pickup request, it appears here until completed or cancelled."
          />
        ) : (
          <div className="grid gap-3">
            {activePickups.map((pickup) => (
              <PickupCard
                key={pickup.pickup_id}
                pickup={pickup}
                students={students}
                onCancel={onCancel}
                cancelling={cancelPendingId === pickup.pickup_id}
              />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900">Pickup history</h2>
        {historyPickups.length === 0 ? (
          <ParentEmptyState
            title="No pickup history"
            description="Completed, cancelled, released, or rejected requests appear here."
          />
        ) : (
          <div className="grid gap-3">
            {historyPickups.map((pickup) => (
              <PickupCard
                key={pickup.pickup_id}
                pickup={pickup}
                students={students}
                onCancel={onCancel}
                cancelling={cancelPendingId === pickup.pickup_id}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
