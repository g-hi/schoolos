"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  PickupRequest,
  PickupStatus,
  listTeacherPickupRequests,
  acknowledgeTeacherPickupRequest,
  callTeacherPickupRequest,
  prepareTeacherPickupRequest,
} from "@/lib/teacher-api";

const teacherActiveStatuses = new Set<PickupStatus>(["requested", "acknowledged", "called", "prepared"]);

function getNextAction(status: PickupStatus): string | null {
  switch (status) {
    case "requested":
      return "acknowledge";
    case "acknowledged":
      return "call";
    case "called":
      return "prepare";
    case "prepared":
      return null; // Teacher cannot complete
    default:
      return null;
  }
}

function statusBadgeClass(status: PickupStatus): string {
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

function statusLabel(status: PickupStatus): string {
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

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString();
}

function mapPickupError(error: unknown): string {
  if (error instanceof TeacherApiError) {
    const detail = error.message.toLowerCase();
    if (error.status === 401) {
      return "Your session has expired. Please sign in again.";
    }
    if (error.status === 403) {
      return "You do not have access to this pickup request.";
    }
    if (error.status === 404) {
      return "The pickup request was not found.";
    }
    if (error.status === 409 && detail.includes("terminal status")) {
      return "This request is in a terminal status and cannot be changed.";
    }
    if (error.status === 409 && detail.includes("illegal pickup lifecycle transition")) {
      return "This action is not allowed from the current pickup status.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

interface PickupCardProps {
  pickup: PickupRequest;
  onAction: (pickupId: string, action: "acknowledge" | "call" | "prepare") => Promise<void>;
  actionPending: string | null;
}

function PickupCard({ pickup, onAction, actionPending }: PickupCardProps) {
  const nextAction = getNextAction(pickup.status);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const isPending = actionPending === pickup.pickup_id;

  async function handleAction(action: "acknowledge" | "call" | "prepare") {
    setActionError(null);
    setActionSuccess(null);
    try {
      await onAction(pickup.pickup_id, action);
      setActionSuccess(`Pickup marked as ${action}.`);
    } catch (error) {
      setActionError(mapPickupError(error));
    }
  }

  return (
    <article className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">
            Student ID: {pickup.student_id}
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            Requested: {formatDate(pickup.requested_at)}
          </p>
        </div>
        <span className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs font-semibold ${statusBadgeClass(pickup.status)}`}>
          {statusLabel(pickup.status)}
        </span>
      </div>

      {pickup.notes ? (
        <p className="mt-3 text-sm text-gray-700">Note: {pickup.notes}</p>
      ) : null}

      <dl className="mt-3 grid gap-2 text-xs text-gray-600 sm:grid-cols-2">
        <div>
          <dt className="font-medium text-gray-700">Parent ID</dt>
          <dd>{pickup.parent_id}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-700">Channel</dt>
          <dd>{pickup.channel || "—"}</dd>
        </div>
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

      {nextAction ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => handleAction(nextAction as "acknowledge" | "call" | "prepare")}
            disabled={isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {isPending ? "Processing..." : `Mark as ${nextAction}`}
          </button>
        </div>
      ) : null}

      {actionError ? (
        <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" role="alert">
          {actionError}
        </p>
      ) : null}

      {actionSuccess ? (
        <p className="mt-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-700" role="status">
          {actionSuccess}
        </p>
      ) : null}
    </article>
  );
}

export default function StudentPickupPage() {
  const auth = useAuth();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pickups, setPickups] = useState<PickupRequest[]>([]);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<PickupStatus | null>(null);

  const activePickups = useMemo(
    () => pickups.filter((p) => teacherActiveStatuses.has(p.status)),
    [pickups],
  );
  const historyPickups = useMemo(
    () => pickups.filter((p) => !teacherActiveStatuses.has(p.status)),
    [pickups],
  );

  async function loadPickups() {
    if (!auth.isAuthenticated || !auth.user) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setLoadError(null);
    try {
      const response = await listTeacherPickupRequests(
        {
          status: statusFilter || undefined,
          page: 1,
          page_size: 50,
        },
        auth.user?.authToken,
      );
      setPickups(response.items);
    } catch (error) {
      setLoadError(mapPickupError(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPickups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, statusFilter]);

  async function handleAction(
    pickupId: string,
    action: "acknowledge" | "call" | "prepare",
  ) {
    if (!auth.user?.authToken) {
      return;
    }

    setActionPending(pickupId);
    try {
      let result: PickupRequest;
      if (action === "acknowledge") {
        result = await acknowledgeTeacherPickupRequest(pickupId, {}, auth.user.authToken);
      } else if (action === "call") {
        result = await callTeacherPickupRequest(pickupId, {}, auth.user.authToken);
      } else {
        result = await prepareTeacherPickupRequest(pickupId, {}, auth.user.authToken);
      }
      setPickups((current) =>
        current.map((p) => (p.pickup_id === pickupId ? result : p)),
      );
    } finally {
      setActionPending(null);
    }
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-gray-700">Please log in to view pickup requests.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="rounded-lg border border-gray-200 bg-white p-6">
        <h1 className="text-2xl font-bold text-gray-900">Student Pickup</h1>
        <p className="mt-2 text-sm text-gray-600">
          Monitor pickup confirmations, release requests, and early dismissal activity for classes under your care.
        </p>
      </header>

      <div className="flex gap-3 flex-wrap items-center">
        <button
          onClick={() => void loadPickups()}
          disabled={loading}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>

        <select
          value={statusFilter || ""}
          onChange={(e) => setStatusFilter((e.target.value as PickupStatus) || null)}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option value="">All statuses</option>
          <option value="requested">Requested</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="called">Called</option>
          <option value="prepared">Prepared</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {loadError ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6" role="alert">
          <p className="font-semibold text-red-900">Error loading pickups</p>
          <p className="mt-1 text-sm text-red-700">{loadError}</p>
        </div>
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">Active pickups</h2>
        </div>

        {loading ? (
          <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
            <p className="text-gray-500">Loading pickups...</p>
          </div>
        ) : activePickups.length === 0 ? (
          <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
            <p className="text-gray-500">No active pickup requests.</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {activePickups.map((pickup) => (
              <PickupCard
                key={pickup.pickup_id}
                pickup={pickup}
                onAction={handleAction}
                actionPending={actionPending}
              />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900">Pickup history</h2>

        {historyPickups.length === 0 ? (
          <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
            <p className="text-gray-500">
              Completed, cancelled, released, or rejected requests appear here.
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {historyPickups.map((pickup) => (
              <PickupCard
                key={pickup.pickup_id}
                pickup={pickup}
                onAction={handleAction}
                actionPending={actionPending}
              />
            ))}
          </div>
        )}
      </section>

      <div className="text-center text-sm text-gray-500 pb-6">
        <Link href="/teacher" className="text-indigo-600 hover:underline">
          Back to teacher dashboard
        </Link>
      </div>
    </div>
  );
}
