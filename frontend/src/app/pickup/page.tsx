"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import {
  TeacherApiError,
  PickupRequest,
  PickupStatus,
  listLeadershipPickupRequests,
  acknowledgeLeadershipPickupRequest,
  callLeadershipPickupRequest,
  prepareLeadershipPickupRequest,
  completeLeadershipPickupRequest,
  cancelLeadershipPickupRequest,
} from "@/lib/teacher-api";

const leadershipActiveStatuses = new Set<PickupStatus>(["requested", "acknowledged", "called", "prepared"]);

function getNextAction(status: PickupStatus): string | null {
  switch (status) {
    case "requested":
      return "acknowledge";
    case "acknowledged":
      return "call";
    case "called":
      return "prepare";
    case "prepared":
      return "complete";
    default:
      return null;
  }
}

function canCancel(status: PickupStatus): boolean {
  return ["requested", "acknowledged", "called", "prepared"].includes(status);
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
      return "You do not have permission to perform this action.";
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
    if (error.status === 409 && detail.includes("verification_method is required")) {
      return "Verification method is required for completion.";
    }
    if (error.status === 409 && detail.includes("verification_note is required")) {
      return "Verification note is required for completion.";
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
  onAction: (pickupId: string, action: "acknowledge" | "call" | "prepare" | "complete" | "cancel") => Promise<void>;
  onShowComplete: (pickup: PickupRequest) => void;
  onShowCancel: (pickup: PickupRequest) => void;
  actionPending: string | null;
}

function PickupCard({ pickup, onAction, onShowComplete, onShowCancel, actionPending }: PickupCardProps) {
  const nextAction = getNextAction(pickup.status);
  const shouldCancel = canCancel(pickup.status);
  const [actionError, setActionError] = useState<string | null>(null);
  const isPending = actionPending === pickup.pickup_id;

  async function handleQuickAction(action: "acknowledge" | "call" | "prepare") {
    setActionError(null);
    try {
      await onAction(pickup.pickup_id, action);
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
          <dt className="font-medium text-gray-700">Class ID</dt>
          <dd>{pickup.class_id}</dd>
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
        {pickup.verification_method ? (
          <div>
            <dt className="font-medium text-gray-700">Verification Method</dt>
            <dd>{pickup.verification_method}</dd>
          </div>
        ) : null}
        {pickup.verification_note ? (
          <div>
            <dt className="font-medium text-gray-700">Verification Note</dt>
            <dd>{pickup.verification_note}</dd>
          </div>
        ) : null}
      </dl>

      {nextAction && nextAction !== "complete" ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => handleQuickAction(nextAction as "acknowledge" | "call" | "prepare")}
            disabled={isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {isPending ? "Processing..." : `Mark as ${nextAction}`}
          </button>
        </div>
      ) : nextAction === "complete" ? (
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => onShowComplete(pickup)}
            disabled={isPending}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {isPending ? "Processing..." : "Complete & Verify"}
          </button>
          {shouldCancel ? (
            <button
              type="button"
              onClick={() => onShowCancel(pickup)}
              disabled={isPending}
              className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
            >
              Cancel
            </button>
          ) : null}
        </div>
      ) : shouldCancel ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => onShowCancel(pickup)}
            disabled={isPending}
            className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
          >
            Cancel
          </button>
        </div>
      ) : null}

      {actionError ? (
        <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" role="alert">
          {actionError}
        </p>
      ) : null}
    </article>
  );
}

interface CompleteFormProps {
  pickup: PickupRequest;
  onSubmit: (verificationMethod: string, verificationNote: string) => Promise<void>;
  onCancel: () => void;
  isLoading: boolean;
}

function CompleteForm({ pickup, onSubmit, onCancel, isLoading }: CompleteFormProps) {
  const [verificationMethod, setVerificationMethod] = useState("");
  const [verificationNote, setVerificationNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!verificationMethod.trim()) {
      setError("Verification method is required.");
      return;
    }
    if (!verificationNote.trim()) {
      setError("Verification note is required.");
      return;
    }

    try {
      await onSubmit(verificationMethod.trim(), verificationNote.trim());
    } catch (err) {
      setError(mapPickupError(err));
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-md w-full shadow-lg">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Complete & Verify Pickup</h2>
          <p className="mt-2 text-sm text-gray-600">
            Confirm that the student has been handed over to the authorized guardian.
            This action is performed by the school staff using authenticated access.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label htmlFor="pickup-student-info" className="block text-sm font-medium text-gray-700">
              Student
            </label>
            <p id="pickup-student-info" className="mt-1 p-2 bg-gray-50 rounded text-sm text-gray-700">
              {pickup.student_id}
            </p>
          </div>

          <div>
            <label htmlFor="verification-method" className="block text-sm font-medium text-gray-700">
              Verification Method *
            </label>
            <input
              id="verification-method"
              type="text"
              value={verificationMethod}
              onChange={(e) => setVerificationMethod(e.target.value)}
              placeholder="e.g., ID check, signature, photo"
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              disabled={isLoading}
            />
          </div>

          <div>
            <label htmlFor="verification-note" className="block text-sm font-medium text-gray-700">
              Verification Note *
            </label>
            <textarea
              id="verification-note"
              value={verificationNote}
              onChange={(e) => setVerificationNote(e.target.value)}
              placeholder="Document the handover details (e.g., Guardian name, time, condition of student)"
              rows={3}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              disabled={isLoading}
            />
          </div>

          {error ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {error}
            </p>
          ) : null}

          <div className="border-t border-gray-200 pt-4 flex gap-2">
            <button
              type="submit"
              disabled={isLoading}
              className="flex-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-gray-400"
            >
              {isLoading ? "Processing..." : "Confirm Completion"}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={isLoading}
              className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface CancelFormProps {
  pickup: PickupRequest;
  onSubmit: () => Promise<void>;
  onClose: () => void;
  isLoading: boolean;
}

function CancelForm({ pickup, onSubmit, onClose, isLoading }: CancelFormProps) {
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setError(null);
    try {
      await onSubmit();
    } catch (err) {
      setError(mapPickupError(err));
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-md w-full shadow-lg">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Cancel Pickup</h2>
          <p className="mt-2 text-sm text-gray-600">
            Cancel this pickup request for student {pickup.student_id}?
          </p>
        </div>

        <div className="p-6 space-y-4">
          {error ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {error}
            </p>
          ) : null}

          <div className="border-t border-gray-200 pt-4 flex gap-2">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isLoading}
              className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-gray-400"
            >
              {isLoading ? "Processing..." : "Cancel Pickup"}
            </button>
            <button
              type="button"
              onClick={onClose}
              disabled={isLoading}
              className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100"
            >
              Keep Pickup
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PickupPage() {
  const auth = useAuth();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pickups, setPickups] = useState<PickupRequest[]>([]);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<PickupStatus | null>(null);
  const [completePickup, setCompletePickup] = useState<PickupRequest | null>(null);
  const [cancelPickup, setCancelPickup] = useState<PickupRequest | null>(null);
  const [completeLoading, setCompleteLoading] = useState(false);
  const [cancelLoading, setCancelLoading] = useState(false);

  const activePickups = useMemo(
    () => pickups.filter((p) => leadershipActiveStatuses.has(p.status)),
    [pickups],
  );
  const historyPickups = useMemo(
    () => pickups.filter((p) => !leadershipActiveStatuses.has(p.status)),
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
      const response = await listLeadershipPickupRequests(
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
    action: "acknowledge" | "call" | "prepare" | "complete" | "cancel",
  ) {
    if (!auth.user?.authToken) {
      return;
    }

    setActionPending(pickupId);
    try {
      let result: PickupRequest;
      if (action === "acknowledge") {
        result = await acknowledgeLeadershipPickupRequest(pickupId, {}, auth.user.authToken);
      } else if (action === "call") {
        result = await callLeadershipPickupRequest(pickupId, {}, auth.user.authToken);
      } else if (action === "prepare") {
        result = await prepareLeadershipPickupRequest(pickupId, {}, auth.user.authToken);
      } else {
        return; // complete and cancel have separate handlers
      }
      setPickups((current) =>
        current.map((p) => (p.pickup_id === pickupId ? result : p)),
      );
    } finally {
      setActionPending(null);
    }
  }

  async function handleComplete(verificationMethod: string, verificationNote: string) {
    if (!auth.user?.authToken || !completePickup) {
      return;
    }

    setCompleteLoading(true);
    try {
      const result = await completeLeadershipPickupRequest(
        completePickup.pickup_id,
        { verification_method: verificationMethod, verification_note: verificationNote },
        auth.user.authToken,
      );
      setPickups((current) =>
        current.map((p) => (p.pickup_id === completePickup.pickup_id ? result : p)),
      );
      setCompletePickup(null);
    } finally {
      setCompleteLoading(false);
    }
  }

  async function handleCancel() {
    if (!auth.user?.authToken || !cancelPickup) {
      return;
    }

    setCancelLoading(true);
    try {
      const result = await cancelLeadershipPickupRequest(
        cancelPickup.pickup_id,
        {},
        auth.user.authToken,
      );
      setPickups((current) =>
        current.map((p) => (p.pickup_id === cancelPickup.pickup_id ? result : p)),
      );
      setCancelPickup(null);
    } finally {
      setCancelLoading(false);
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
        <h1 className="text-2xl font-bold text-gray-900">Pickup Oversight</h1>
        <p className="mt-2 text-sm text-gray-600">
          Manage tenant-wide pickup requests, verify student handover, and maintain the pickup log.
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
                onShowComplete={setCompletePickup}
                onShowCancel={setCancelPickup}
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
                onShowComplete={setCompletePickup}
                onShowCancel={setCancelPickup}
                actionPending={actionPending}
              />
            ))}
          </div>
        )}
      </section>

      {completePickup ? (
        <CompleteForm
          pickup={completePickup}
          onSubmit={handleComplete}
          onCancel={() => setCompletePickup(null)}
          isLoading={completeLoading}
        />
      ) : null}

      {cancelPickup ? (
        <CancelForm
          pickup={cancelPickup}
          onSubmit={handleCancel}
          onClose={() => setCancelPickup(null)}
          isLoading={cancelLoading}
        />
      ) : null}
    </div>
  );
}
