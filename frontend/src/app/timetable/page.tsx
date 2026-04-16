"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface TimetableEntry {
  id: string;
  day_of_week: number;
  period_label: string;
  subject_name: string;
  teacher_name: string;
  class_name: string;
  room: string | null;
}

const DAYS = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

export default function TimetablePage() {
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<TimetableEntry[]>("/timetable/")
      .then(setEntries)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Group by day
  const byDay = entries.reduce<Record<number, TimetableEntry[]>>((acc, e) => {
    (acc[e.day_of_week] ||= []).push(e);
    return acc;
  }, {});

  // Get unique periods
  const periods = [...new Set(entries.map((e) => e.period_label))].sort();

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
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com"}/timetable/download/pdf?tenant=greenwood`}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
          target="_blank"
        >
          Download PDF
        </a>
      </div>

      {entries.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <p className="text-gray-500">No timetable entries yet. Upload a timetable CSV from the Data Upload page.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Period</th>
                {[1, 2, 3, 4, 5].map((d) => (
                  <th key={d} className="text-left px-4 py-3 font-medium text-gray-600">
                    {DAYS[d]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {periods.map((period) => (
                <tr key={period} className="border-b last:border-0">
                  <td className="px-4 py-3 font-medium text-gray-700">{period}</td>
                  {[1, 2, 3, 4, 5].map((day) => {
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
                                {e.teacher_name} &middot; {e.class_name}
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
