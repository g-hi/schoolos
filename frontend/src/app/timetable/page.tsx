"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface ApiTimetableEntry {
  id: string;
  day: string;
  day_of_week: number;
  period: { id: string; name: string; start_time: string; end_time: string };
  subject: { id: string; code: string; name: string };
  teacher: { id: string; name: string };
  class: { id: string; grade: string; section: string };
  is_active: boolean;
}

interface TimetableEntry {
  id: string;
  day_of_week: number;
  period_label: string;
  period_time: string;
  subject_name: string;
  teacher_name: string;
  class_name: string;
}

interface Teacher {
  teacher_id: string;
  name: string;
  assigned_periods: number;
  max_weekly_hours: number;
  load_pct: number;
  status: string;
}

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

function mapEntry(e: ApiTimetableEntry): TimetableEntry {
  return {
    id: e.id,
    day_of_week: e.day_of_week,
    period_label: e.period.name,
    period_time: `${e.period.start_time}–${e.period.end_time}`,
    subject_name: e.subject.name,
    teacher_name: e.teacher.name,
    class_name: `${e.class.grade} ${e.class.section}`,
  };
}

export default function TimetablePage() {
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"classes" | "teacher">("classes");
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [selectedTeacher, setSelectedTeacher] = useState("");
  const [selectedClass, setSelectedClass] = useState("");

  useEffect(() => {
    Promise.all([
      api<ApiTimetableEntry[]>("/timetable/"),
      api<{ teachers: Teacher[] }>("/dashboard/teacher-load"),
    ])
      .then(([ttData, tlData]) => {
        setEntries(ttData.map(mapEntry));
        setTeachers(tlData.teachers);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Build grid helper
  function buildGrid(data: TimetableEntry[]) {
    const byDay = data.reduce<Record<number, TimetableEntry[]>>((acc, e) => {
      (acc[e.day_of_week] ||= []).push(e);
      return acc;
    }, {});
    const periods = [...new Set(data.map((e) => e.period_label))].sort();
    return { byDay, periods };
  }

  // Filter entries based on active tab + selection
  const selectedTeacherObj = teachers.find((t) => t.teacher_id === selectedTeacher);
  const filteredEntries =
    tab === "teacher" && selectedTeacherObj
      ? entries.filter((e) => e.teacher_name === selectedTeacherObj.name)
      : tab === "classes" && selectedClass
      ? entries.filter((e) => e.class_name === selectedClass)
      : entries;
  const { byDay, periods } = buildGrid(filteredEntries);
  const classList = [...new Set(entries.map((e) => e.class_name))].sort();

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-48" />
        <div className="h-96 bg-gray-200 rounded-xl" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Timetable</h1>
        <button
          onClick={async () => {
            try {
              const pdfView = tab === "teacher" ? "teacher" : "class";
              const res = await fetch(
                `${process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com"}/timetable/download/pdf?view=${pdfView}`,
                { headers: { "X-Tenant-Slug": "greenwood" } }
              );
              if (!res.ok) throw new Error(await res.text());
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `timetable_${pdfView}.pdf`;
              a.click();
              URL.revokeObjectURL(url);
            } catch (err) {
              alert(String(err));
            }
          }}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          Download PDF ({tab === "teacher" ? "By Teacher" : "By Class"})
        </button>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mb-6 w-fit">
        <button
          onClick={() => setTab("classes")}
          className={`px-4 py-2 rounded-md text-sm font-medium transition ${
            tab === "classes"
              ? "bg-white text-indigo-700 shadow-sm"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          All Classes
        </button>
        <button
          onClick={() => setTab("teacher")}
          className={`px-4 py-2 rounded-md text-sm font-medium transition ${
            tab === "teacher"
              ? "bg-white text-indigo-700 shadow-sm"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          By Teacher
        </button>
      </div>

      {/* Class selector */}
      {tab === "classes" && (
        <div className="mb-6 flex items-center gap-4">
          <select
            value={selectedClass}
            onChange={(e) => setSelectedClass(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option value="">All classes</option>
            {classList.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          {selectedClass && (
            <span className="px-2 py-1 bg-indigo-50 text-indigo-700 rounded-md text-sm">
              {entries.filter((e) => e.class_name === selectedClass).length} periods/week
            </span>
          )}
        </div>
      )}

      {/* Teacher selector */}
      {tab === "teacher" && (
        <div className="mb-6 flex items-center gap-4">
          <select
            value={selectedTeacher}
            onChange={(e) => setSelectedTeacher(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option value="">Select a teacher…</option>
            {teachers.map((t) => (
              <option key={t.teacher_id} value={t.teacher_id}>
                {t.name}
              </option>
            ))}
          </select>
          {selectedTeacherObj && (
            <div className="flex gap-3 text-sm">
              <span className="px-2 py-1 bg-indigo-50 text-indigo-700 rounded-md">
                {selectedTeacherObj.assigned_periods} periods/week
              </span>
              <span className={`px-2 py-1 rounded-md ${
                selectedTeacherObj.load_pct > 80
                  ? "bg-red-50 text-red-700"
                  : selectedTeacherObj.load_pct > 50
                  ? "bg-amber-50 text-amber-700"
                  : "bg-green-50 text-green-700"
              }`}>
                {selectedTeacherObj.load_pct.toFixed(0)}% load
              </span>
            </div>
          )}
        </div>
      )}

      {/* Grid */}
      {tab === "teacher" && !selectedTeacher ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <p className="text-gray-500">Select a teacher above to view their weekly schedule.</p>
        </div>
      ) : filteredEntries.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <p className="text-gray-500">
            {tab === "teacher"
              ? "No classes assigned to this teacher yet."
              : "No timetable entries yet. Upload a timetable CSV from the Data Upload page."}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Period</th>
                {[0, 1, 2, 3, 4].map((d) => (
                  <th key={d} className="text-left px-4 py-3 font-medium text-gray-600">
                    {DAYS[d]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {periods.map((period) => (
                <tr key={period} className="border-b last:border-0">
                  <td className="px-4 py-3 font-medium text-gray-700 whitespace-nowrap">
                    <div>{period}</div>
                    {(byDay[0] || []).find((e) => e.period_label === period)?.period_time && (
                      <div className="text-[10px] text-gray-400">
                        {(byDay[0] || byDay[1] || byDay[2] || byDay[3] || byDay[4] || [])
                          .find((e) => e.period_label === period)?.period_time}
                      </div>
                    )}
                  </td>
                  {[0, 1, 2, 3, 4].map((day) => {
                    const cell = (byDay[day] || []).filter(
                      (e) => e.period_label === period
                    );
                    return (
                      <td key={day} className="px-4 py-3">
                        {cell.length === 0 ? (
                          <span className="text-gray-300">—</span>
                        ) : (
                          cell.map((e, i) => (
                            <div
                              key={i}
                              className="bg-indigo-50 border border-indigo-200 rounded-lg p-2 mb-1 last:mb-0"
                            >
                              <p className="font-medium text-indigo-800 text-xs">
                                {e.subject_name}
                              </p>
                              <p className="text-[11px] text-indigo-600">
                                {tab === "teacher"
                                  ? e.class_name
                                  : selectedClass
                                  ? e.teacher_name
                                  : `${e.teacher_name} · ${e.class_name}`}
                              </p>
                            </div>
                          ))
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
