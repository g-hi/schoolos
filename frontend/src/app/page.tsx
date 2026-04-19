"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import StatCard from "@/components/stat-card";

interface DashboardData {
  period: string;
  academic_year: string;
  teacher_load: {
    total_teachers: number;
    overloaded_above_85pct: number;
    spare_capacity_below_50pct: number;
    overloaded_teachers: { name: string; load_pct: number; assigned: number; max: number }[];
  };
  substitutions: {
    since: string;
    total_substitutions: number;
    assigned: number;
    unassigned: number;
    most_called_substitutes: { teacher_id: string; name: string; times_substituted: number }[];
    most_absent_teachers: { teacher_id: string; name: string; absences: number }[];
    classes_needing_most_cover: { class_id: string; class: string; cover_count: number }[];
  };
  pickup: {
    since: string;
    total_requests: number;
    released: number;
    rejected_outside_geofence: number;
    pending: number;
    early_pickups: number;
    early_by_grade: { grade: string; early_pickups: number }[];
    avg_release_time_minutes: number | null;
  };
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<DashboardData>("/dashboard/summary")
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton />;
  if (!data) return <p className="text-red-500">Failed to load dashboard</p>;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Principal Dashboard</h1>
          <p className="text-sm text-gray-500">
            {data.academic_year} &middot; {data.period}
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); api<DashboardData>("/dashboard/summary").then(setData).catch(console.error).finally(() => setLoading(false)); }}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          Refresh
        </button>
      </div>

      <h2 className="text-lg font-semibold mb-3">Teacher Load</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <StatCard title="Total Teachers" value={data.teacher_load.total_teachers} color="indigo" />
        <StatCard title="Overloaded (>85%)" value={data.teacher_load.overloaded_above_85pct} color={data.teacher_load.overloaded_above_85pct > 0 ? "red" : "green"} />
        <StatCard title="Spare Capacity (<50%)" value={data.teacher_load.spare_capacity_below_50pct} color="amber" />
      </div>

      <h2 className="text-lg font-semibold mb-3">Substitutions</h2>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <StatCard title="Total" value={data.substitutions.total_substitutions} />
        <StatCard title="Assigned" value={data.substitutions.assigned} color="green" />
        <StatCard title="Unassigned" value={data.substitutions.unassigned} color={data.substitutions.unassigned > 0 ? "red" : "gray"} />
        <StatCard
          title="Most Absent"
          value={data.substitutions.most_absent_teachers[0]?.name || "None"}
          subtitle={data.substitutions.most_absent_teachers[0] ? `${data.substitutions.most_absent_teachers[0].absences} absences` : undefined}
          color="gray"
        />
      </div>

      <h2 className="text-lg font-semibold mb-3">Pickup Activity</h2>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <StatCard title="Total Requests" value={data.pickup.total_requests} />
        <StatCard title="Released" value={data.pickup.released} color="green" />
        <StatCard title="Rejected (Geofence)" value={data.pickup.rejected_outside_geofence} color={data.pickup.rejected_outside_geofence > 0 ? "red" : "gray"} />
        <StatCard title="Avg Release Time" value={data.pickup.avg_release_time_minutes ? `${data.pickup.avg_release_time_minutes} min` : "N/A"} color="gray" />
      </div>

      {data.teacher_load.overloaded_teachers.length > 0 && (
        <>
          <h2 className="text-lg font-semibold mb-3">Overloaded Teachers</h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-8">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">Teacher</th>
                  <th className="text-left px-4 py-3 font-medium">Load %</th>
                </tr>
              </thead>
              <tbody>
                {data.teacher_load.overloaded_teachers.map((t, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="px-4 py-3">{t.name}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-gray-200 rounded-full h-2">
                          <div className="bg-red-500 h-2 rounded-full" style={{ width: `${Math.min(t.load_pct, 100)}%` }} />
                        </div>
                        <span className="font-medium">{t.load_pct}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-6">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-gray-200 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 bg-gray-200 rounded-xl" />
        ))}
      </div>
    </div>
  );
}
