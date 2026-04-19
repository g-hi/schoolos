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
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [grade, setGrade] = useState("");
  const [section, setSection] = useState("");
  const [earlyOnly, setEarlyOnly] = useState(false);

  useEffect(() => {
    loadLogs();
    // eslint-disable-next-line
  }, []);

  async function loadLogs() {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: "100" };
      if (dateFrom) params.start_date = dateFrom;
      if (dateTo) params.end_date = dateTo;
      if (grade) params.grade = grade;
      if (section) params.section = section;
      if (earlyOnly) params.early_only = "true";
      const data = await api<PickupLog[]>("/pickup/log", { params });
      setLogs(data);
    } catch (err) {
      console.error(err);
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
      <h1 className="text-2xl font-bold">Pickup Requests (Admin)</h1>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Grade</label>
          <input
            type="text"
            value={grade}
            onChange={(e) => setGrade(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            placeholder="e.g. 3"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Section</label>
          <input
            type="text"
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            placeholder="e.g. B"
          />
        </div>
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={earlyOnly}
            onChange={(e) => setEarlyOnly(e.target.checked)}
            id="earlyOnly"
            className="mr-1"
          />
          <label htmlFor="earlyOnly" className="text-sm text-gray-700">Early Only</label>
        </div>
        <button
          onClick={loadLogs}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          Search
        </button>
      </div>

      {/* Pickup Log */}
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
