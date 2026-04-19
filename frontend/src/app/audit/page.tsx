"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface AuditEntry {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_id: string | null;
  actor_name: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [action, setAction] = useState("");
  const [entity, setEntity] = useState("");
  const [actor, setActor] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    loadAudit();
  }, []);

  async function loadAudit() {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: "50" };
      if (action) params.action_prefix = action;
      if (entity) params.entity_type = entity;
      if (actor) params.actor_name = actor;
      if (dateFrom) params.from_date = dateFrom;
      if (dateTo) params.to_date = dateTo;
      const data = await api<AuditEntry[]>("/audit/", { params });
      setEntries(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Audit Trail</h1>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Action</label>
          <input
            type="text"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            placeholder="e.g. upload_csv"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Entity Type</label>
          <input
            type="text"
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            placeholder="e.g. subject"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Actor</label>
          <input
            type="text"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            placeholder="e.g. admin"
          />
        </div>
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
        <button
          onClick={loadAudit}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          Search
        </button>
      </div>

      {/* Audit Log */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-gray-500">Loading...</div>
        ) : entries.length === 0 ? (
          <div className="p-12 text-center text-gray-500">No audit entries found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Time</th>
                <th className="text-left px-4 py-3 font-medium">Action</th>
                <th className="text-left px-4 py-3 font-medium">Entity</th>
                <th className="text-left px-4 py-3 font-medium">Actor</th>
                <th className="text-left px-4 py-3 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {new Date(e.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-1 bg-indigo-50 text-indigo-700 rounded text-xs font-medium">
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-gray-700">{e.entity_type}</span>
                    {e.entity_id && <span className="text-gray-400 text-xs ml-1">#{e.entity_id.slice(0, 8)}</span>}
                  </td>
                  <td className="px-4 py-3">{e.actor_name || "—"}</td>
                  <td className="px-4 py-3">
                    {e.details ? (
                      <button
                        onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                        className="text-xs text-indigo-600 hover:underline"
                      >
                        {expanded === e.id ? "Hide" : "Show"}
                      </button>
                    ) : (
                      <span className="text-gray-400 text-xs">—</span>
                    )}
                    {expanded === e.id && e.details && (
                      <pre className="mt-2 bg-gray-50 rounded p-2 text-xs overflow-auto max-h-40 max-w-md">
                        {JSON.stringify(e.details, null, 2)}
                      </pre>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
