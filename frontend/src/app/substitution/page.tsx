"use client";

import { useState } from "react";
import { apiPost, api } from "@/lib/api";

interface Substitution {
  id: string;
  date: string;
  absent_teacher_name: string;
  substitute_teacher_name: string | null;
  subject_name: string;
  class_name: string;
  period_label: string;
  status: string;
  confidence_score: number | null;
}

export default function SubstitutionPage() {
  const [teacherIds, setTeacherIds] = useState("");
  const [date, setDate] = useState(new Date().toISOString().split("T")[0]);
  const [result, setResult] = useState<unknown>(null);
  const [subs, setSubs] = useState<Substitution[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleReport() {
    setLoading(true);
    setError("");
    try {
      const names = teacherIds.split(",").map((s) => s.trim()).filter(Boolean);
      const res = await apiPost("/substitution/report", {
        absent_teachers: names,
        date,
      });
      setResult(res);
      loadSubs();
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadSubs() {
    try {
      const data = await api<Substitution[]>("/substitution/", {
        params: { date },
      });
      setSubs(data);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Teacher Substitution</h1>

      {/* Report Form */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h2 className="font-semibold mb-4">Report Absent Teachers</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Teacher Names (comma-separated)
            </label>
            <input
              type="text"
              value={teacherIds}
              onChange={(e) => setTeacherIds(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              placeholder="John Smith, Sara Jones"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Date
            </label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>
        <button
          onClick={handleReport}
          disabled={loading}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Processing..." : "Generate Substitution Plan"}
        </button>
        {error && <p className="text-red-500 text-sm mt-2">{error}</p>}
        {result !== null && (
          <pre className="mt-4 bg-gray-50 rounded-lg p-4 text-xs overflow-auto max-h-48">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>

      {/* Substitution List */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Substitutions for {date}</h2>
          <button
            onClick={loadSubs}
            className="text-sm text-indigo-600 hover:underline"
          >
            Refresh
          </button>
        </div>
        {subs.length === 0 ? (
          <p className="text-gray-500 text-sm">No substitutions found for this date.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Absent</th>
                <th className="text-left px-4 py-3 font-medium">Substitute</th>
                <th className="text-left px-4 py-3 font-medium">Subject</th>
                <th className="text-left px-4 py-3 font-medium">Class</th>
                <th className="text-left px-4 py-3 font-medium">Period</th>
                <th className="text-left px-4 py-3 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {subs.map((s) => (
                <tr key={s.id} className="border-b last:border-0">
                  <td className="px-4 py-3">{s.absent_teacher_name}</td>
                  <td className="px-4 py-3">{s.substitute_teacher_name || "—"}</td>
                  <td className="px-4 py-3">{s.subject_name}</td>
                  <td className="px-4 py-3">{s.class_name}</td>
                  <td className="px-4 py-3">{s.period_label}</td>
                  <td className="px-4 py-3">
                    {s.confidence_score != null ? (
                      <span className={`font-medium ${s.confidence_score >= 70 ? "text-green-600" : s.confidence_score >= 40 ? "text-amber-600" : "text-red-600"}`}>
                        {s.confidence_score}%
                      </span>
                    ) : "—"}
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
