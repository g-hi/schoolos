"use client";

import { useEffect, useState } from "react";
import { api, apiPost } from "@/lib/api";

interface PickupLog {
  id: string;
  student_name: string;
  parent_name: string;
  status: string;
  latitude: number;
  longitude: number;
  created_at: string;
  released_at: string | null;
}

export default function PickupPage() {
  const [logs, setLogs] = useState<PickupLog[]>([]);
  const [studentId, setStudentId] = useState("");
  const [lat, setLat] = useState("24.7136");
  const [lng, setLng] = useState("46.6753");
  const [result, setResult] = useState<string | null>(null);
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
    try {
      const res = await apiPost("/pickup/request", {
        student_id: studentId,
        latitude: parseFloat(lat),
        longitude: parseFloat(lng),
      });
      setResult(JSON.stringify(res, null, 2));
      loadLogs();
    } catch (err) {
      setResult(`Error: ${err}`);
    } finally {
      setLoading(false);
    }
  }

  const statusColor: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
    released: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Private Car Pickup</h1>

      {/* Request Form */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h2 className="font-semibold mb-4">Request Pickup</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Student ID</label>
            <input
              type="text"
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              placeholder="Student UUID"
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
          disabled={loading || !studentId}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Requesting..." : "Request Pickup"}
        </button>
        {result && (
          <pre className="mt-4 bg-gray-50 rounded-lg p-4 text-xs overflow-auto max-h-32">{result}</pre>
        )}
      </div>

      {/* Pickup Log */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Pickup Log</h2>
          <button onClick={loadLogs} className="text-sm text-indigo-600 hover:underline">Refresh</button>
        </div>
        {logs.length === 0 ? (
          <p className="text-gray-500 text-sm">No pickup requests yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Student</th>
                <th className="text-left px-4 py-3 font-medium">Parent</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-left px-4 py-3 font-medium">Requested</th>
                <th className="text-left px-4 py-3 font-medium">Released</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b last:border-0">
                  <td className="px-4 py-3">{l.student_name}</td>
                  <td className="px-4 py-3">{l.parent_name}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${statusColor[l.status] || "bg-gray-100"}`}>
                      {l.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{new Date(l.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-gray-500">{l.released_at ? new Date(l.released_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
