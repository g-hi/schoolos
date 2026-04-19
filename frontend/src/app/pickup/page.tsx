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
  const [parentPhone, setParentPhone] = useState("");
  const [commandText, setCommandText] = useState("Pick up my child");
  const [lat, setLat] = useState("24.7136");
  const [lng, setLng] = useState("46.6753");
  const [result, setResult] = useState<PickupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadLogs();
  }, []);

  async function loadLogs() {
    try {
      const data = await api<PickupLog[]>("/pickup/log");
      setLogs(data);
    } catch (err) {
      console.error(err);
    }
  }

  async function requestPickup() {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await apiPost<PickupResponse>("/pickup/request", {
        parent_phone: parentPhone,
        command_text: commandText,
        latitude: parseFloat(lat),
        longitude: parseFloat(lng),
      });
      setResult(res);
      loadLogs();
    } catch (err) {
      setError(`${err}`);
    } finally {
      setLoading(false);
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
      <h1 className="text-2xl font-bold">Private Car Pickup</h1>

      {/* Request Form */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold mb-4">Parent Pickup Request</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Parent Phone</label>
            <input
              type="text"
              value={parentPhone}
              onChange={(e) => setParentPhone(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              placeholder="+971501234567"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Message</label>
            <input
              type="text"
              value={commandText}
              onChange={(e) => setCommandText(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              placeholder="Pick up my child"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Latitude</label>
            <input
              type="text"
              value={lat}
              onChange={(e) => setLat(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Longitude</label>
            <input
              type="text"
              value={lng}
              onChange={(e) => setLng(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>
        <button
          onClick={requestPickup}
          disabled={loading || !parentPhone}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Processing..." : "Send Pickup Request"}
        </button>
      </div>

      {/* Agent Response */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
      )}

      {result && (
        <div className={`rounded-xl border-2 p-6 ${result.approved ? "border-green-300 bg-green-50" : "border-red-300 bg-red-50"}`}>
          {/* Step-by-step agent flow */}
          <div className="space-y-3 mb-5">
            {result.steps.map((s, i) => (
              <div key={i} className="flex items-start gap-3">
                <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold ${
                  s.passed ? "bg-green-500 text-white" : "bg-red-500 text-white"
                }`}>
                  {s.passed ? "✓" : "✗"}
                </div>
                <div>
                  <div className="text-sm font-semibold text-gray-800">{s.label}</div>
                  <div className="text-sm text-gray-600">{s.detail}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Big result message */}
          <div className={`rounded-lg p-5 text-center ${result.approved ? "bg-green-100" : "bg-red-100"}`}>
            <div className={`text-2xl font-bold mb-1 ${result.approved ? "text-green-800" : "text-red-800"}`}>
              {result.message}
            </div>
            <div className="text-sm text-gray-600">
              {result.student} &middot; {result.class} &middot; Parent: {result.parent}
            </div>
            {result.early_pickup && (
              <div className="mt-2 inline-block px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-medium">
                ⚠ Early Pickup
              </div>
            )}
            {result.approved && result.teacher_notified && (
              <div className="mt-2 text-xs text-green-600">Teacher has been notified</div>
            )}
          </div>
        </div>
      )}

      {/* Pickup Log */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Pickup Log</h2>
          <button onClick={loadLogs} className="text-sm text-indigo-600 hover:underline">Refresh</button>
        </div>
        {logs.length === 0 ? (
          <p className="text-gray-500 text-sm py-8 text-center">No pickup requests yet.</p>
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
