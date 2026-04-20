"use client";

import { useEffect, useState } from "react";
import { api, apiPost } from "@/lib/api";

interface PickupLog {
  pickup_id: string;
  student: string;
  parent: string;
  class: string;
  status: string;
  channel: string | null;
  within_geofence: boolean;
  distance_meters: number | null;
  early_pickup: boolean;
  requested_at: string;
  released_at: string | null;
  notes: string | null;
}

interface AgentStep {
  step: string;
  label: string;
  passed: boolean;
  detail: string;
}

interface PickupResponse {
  pickup_id: string;
  status: string;
  student: string;
  parent: string;
  class: string;
  approved: boolean;
  message: string;
  teacher_notified?: boolean;
  distance_meters: number;
  geofence_radius_m: number;
  early_pickup?: boolean;
  steps: AgentStep[];
}

export default function PickupPage() {
  const [logs, setLogs] = useState<PickupLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    loadLogs();
    // eslint-disable-next-line
  }, []);

  async function loadLogs() {
    setLoading(true);
    try {
      const data = await api<PickupLog[]>("/pickup/log", { params: { limit: "100" } });
      setLogs(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleAction(pickup_id: string, action: "approve" | "reject") {
    setActionLoading(pickup_id + action);
    try {
      await apiPost(`/pickup/${pickup_id}/${action}`);
      await loadLogs();
    } catch (err) {
      alert("Failed to update status");
    } finally {
      setActionLoading(null);
    }
  }

  const statusColor: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
    requested: "bg-amber-100 text-amber-700",
    released: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
    rejected_outside_geofence: "bg-red-100 text-red-700",
    queued: "bg-blue-100 text-blue-700",
  };


  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold mb-4">Pickup Requests (Admin)</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Pickup Log</h2>
          <button onClick={loadLogs} className="text-sm text-indigo-600 hover:underline">Refresh</button>
        </div>
        {loading ? (
          <div className="py-12 text-center text-gray-500">Loading...</div>
        ) : logs.length === 0 ? (
          <p className="text-gray-500 text-sm py-8 text-center">No pickup requests found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">Student</th>
                  <th className="text-left px-4 py-3 font-medium">Parent</th>
                  <th className="text-left px-4 py-3 font-medium">Class</th>
                  <th className="text-left px-4 py-3 font-medium">Status</th>
                  <th className="text-left px-4 py-3 font-medium">Geofence</th>
                  <th className="text-left px-4 py-3 font-medium">Requested</th>
                  <th className="text-left px-4 py-3 font-medium">Released</th>
                  <th className="text-left px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.pickup_id} className="border-b last:border-0 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{l.student}</td>
                    <td className="px-4 py-3">{l.parent}</td>
                    <td className="px-4 py-3 text-gray-500">{l.class}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${statusColor[l.status] || "bg-gray-100"}`}>
                        {l.status === "rejected_outside_geofence" ? "rejected" : l.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {l.within_geofence ? (
                        <span className="text-green-600 text-xs font-medium">✓ Inside</span>
                      ) : (
                        <span className="text-red-600 text-xs">✗ {l.distance_meters?.toFixed(0)}m away</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{new Date(l.requested_at).toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{l.released_at ? new Date(l.released_at).toLocaleString() : "—"}</td>
                    <td className="px-4 py-3">
                      {l.status === "pending" || l.status === "requested" ? (
                        <div className="flex gap-2">
                          <button
                            className="px-3 py-1 bg-green-600 text-white rounded text-xs font-medium disabled:opacity-50"
                            disabled={actionLoading === l.pickup_id + "approve"}
                            onClick={() => handleAction(l.pickup_id, "approve")}
                          >
                            {actionLoading === l.pickup_id + "approve" ? "Approving..." : "Approve"}
                          </button>
                          <button
                            className="px-3 py-1 bg-red-600 text-white rounded text-xs font-medium disabled:opacity-50"
                            disabled={actionLoading === l.pickup_id + "reject"}
                            onClick={() => handleAction(l.pickup_id, "reject")}
                          >
                            {actionLoading === l.pickup_id + "reject" ? "Rejecting..." : "Reject"}
                          </button>
                        </div>
                      ) : (
                        <span className="text-gray-400 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
