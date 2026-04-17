"use client";

import { useEffect, useState } from "react";
import { apiPost, api } from "@/lib/api";

interface Period {
  id: string;
  name: string;
  start_time: string;
  end_time: string;
}

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

const today = new Date().toISOString().split("T")[0];

export default function SubstitutionPage() {
  const [teacherIds, setTeacherIds] = useState("");
  const [date, setDate] = useState(today);
  const [absenceType, setAbsenceType] = useState<"whole" | "specific">("whole");
  const [periods, setPeriods] = useState<Period[]>([]);
  const [selectedPeriods, setSelectedPeriods] = useState<string[]>([]);
  const [result, setResult] = useState<unknown>(null);
  const [subs, setSubs] = useState<Substitution[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Period[]>("/timetable/periods").then(setPeriods).catch(console.error);
  }, []);

  function togglePeriod(name: string) {
    setSelectedPeriods((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]
    );
  }

  async function handleReport() {
    setLoading(true);
    setError("");
    try {
      const names = teacherIds.split(",").map((s) => s.trim()).filter(Boolean);
      const payload: Record<string, unknown> = {
        absent_teachers: names,
        date,
      };
      if (absenceType === "specific" && selectedPeriods.length > 0) {
        payload.absent_periods = selectedPeriods;
      }
      const res = await apiPost("/substitution/report", payload);
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
              min={today}
              onChange={(e) => setDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>

        {/* Absence type */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Absence Type</label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="absenceType"
                checked={absenceType === "whole"}
                onChange={() => { setAbsenceType("whole"); setSelectedPeriods([]); }}
                className="accent-indigo-600"
              />
              Whole Day
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="absenceType"
                checked={absenceType === "specific"}
                onChange={() => setAbsenceType("specific")}
                className="accent-indigo-600"
              />
              Specific Periods
            </label>
          </div>
        </div>

        {/* Period checkboxes */}
        {absenceType === "specific" && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">Select Periods</label>
            <div className="flex flex-wrap gap-2">
              {periods.map((p) => (
                <label
                  key={p.id}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm cursor-pointer transition ${
                    selectedPeriods.includes(p.name)
                      ? "bg-indigo-50 border-indigo-300 text-indigo-700"
                      : "bg-white border-gray-200 text-gray-600 hover:border-gray-300"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedPeriods.includes(p.name)}
                    onChange={() => togglePeriod(p.name)}
                    className="accent-indigo-600"
                  />
                  {p.name}
                  <span className="text-[10px] text-gray-400">{p.start_time}–{p.end_time}</span>
                </label>
              ))}
            </div>
          </div>
        )}
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
