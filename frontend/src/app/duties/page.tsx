"use client";

import { useState, useEffect } from "react";
import { api, apiPost } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";
const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

interface Location {
  id: string;
  name: string;
  description: string | null;
}
interface Slot {
  id: string;
  name: string;
  start_time: string;
  end_time: string;
}
interface Assignment {
  id: string;
  day: string;
  day_of_week: number;
  slot: string;
  slot_time: string;
  location: string;
  teacher: string | null;
  reasoning: string | null;
}

export default function DutyPage() {
  const [tab, setTab] = useState<"roster" | "setup">("roster");

  // Setup state
  const [locations, setLocations] = useState<Location[]>([]);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [newLocName, setNewLocName] = useState("");
  const [newLocDesc, setNewLocDesc] = useState("");
  const [newSlotName, setNewSlotName] = useState("");
  const [newSlotStart, setNewSlotStart] = useState("");
  const [newSlotEnd, setNewSlotEnd] = useState("");

  // Roster state
  const [academicYear] = useState("2025-2026");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load setup data
  useEffect(() => {
    api<Location[]>("/duties/locations").then(setLocations).catch(() => {});
    api<Slot[]>("/duties/slots").then(setSlots).catch(() => {});
  }, []);

  // Load assignments on mount
  useEffect(() => {
    setLoading(true);
    api<Assignment[]>("/duties/", { params: { academic_year: academicYear } })
      .then(setAssignments)
      .catch(() => setAssignments([]))
      .finally(() => setLoading(false));
  }, [academicYear]);

  const addLocation = async () => {
    if (!newLocName.trim()) return;
    const loc = await apiPost<Location>("/duties/locations", {
      name: newLocName.trim(),
      description: newLocDesc.trim() || null,
    });
    setLocations((prev) => [...prev, loc]);
    setNewLocName("");
    setNewLocDesc("");
  };

  const addSlot = async () => {
    if (!newSlotName.trim() || !newSlotStart || !newSlotEnd) return;
    const slot = await apiPost<Slot>("/duties/slots", {
      name: newSlotName.trim(),
      start_time: newSlotStart,
      end_time: newSlotEnd,
    });
    setSlots((prev) => [...prev, slot]);
    setNewSlotName("");
    setNewSlotStart("");
    setNewSlotEnd("");
  };

  const generate = async () => {
    setGenerating(true);
    try {
      await apiPost("/duties/generate", {
        academic_year: academicYear,
      });
      // Reload assignments
      const data = await api<Assignment[]>("/duties/", { params: { academic_year: academicYear } });
      setAssignments(data);
    } catch (e: unknown) {
      alert((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const resetDuties = async () => {
    if (!confirm("Clear all duty assignments for this academic year? You can regenerate after.")) return;
    await api("/duties/reset", { method: "DELETE", params: { academic_year: academicYear } });
    setAssignments([]);
  };

  const downloadPdf = async () => {
    const res = await fetch(
      `${API_BASE}/duties/download/pdf?academic_year=${academicYear}`,
      { headers: { "X-Tenant-Slug": TENANT } }
    );
    if (!res.ok) return alert("PDF download failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `duty_roster_${academicYear}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Build grid: slot -> day -> assignment
  const grid: Record<string, Record<number, Assignment>> = {};
  for (const a of assignments) {
    if (!grid[a.slot]) grid[a.slot] = {};
    grid[a.slot][a.day_of_week] = a;
  }

  const slotNames = [...new Set(assignments.map((a) => a.slot))];
  // Order slot names by earliest time
  slotNames.sort((a, b) => {
    const aTime = assignments.find((x) => x.slot === a)?.slot_time || "";
    const bTime = assignments.find((x) => x.slot === b)?.slot_time || "";
    return aTime.localeCompare(bTime);
  });

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-800">Duty Schedule</h1>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-gray-200">
        <button
          onClick={() => setTab("roster")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "roster"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Weekly Roster
        </button>
        <button
          onClick={() => setTab("setup")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "setup"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Setup (Locations & Slots)
        </button>
      </div>

      {/* ── SETUP TAB ─────────────────────────────────────────── */}
      {tab === "setup" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Locations */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-700">Duty Locations</h2>
            <div className="space-y-2">
              {locations.map((l) => (
                <div key={l.id} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <div>
                    <span className="font-medium text-sm">{l.name}</span>
                    {l.description && <span className="text-xs text-gray-500 ml-2">{l.description}</span>}
                  </div>
                </div>
              ))}
              {locations.length === 0 && <p className="text-sm text-gray-400">No locations yet.</p>}
            </div>
            <div className="flex flex-col gap-2">
              <input
                placeholder="Location name (e.g. Main Gate)"
                value={newLocName}
                onChange={(e) => setNewLocName(e.target.value)}
                className="border rounded-lg px-3 py-2 text-sm"
              />
              <input
                placeholder="Description (optional)"
                value={newLocDesc}
                onChange={(e) => setNewLocDesc(e.target.value)}
                className="border rounded-lg px-3 py-2 text-sm"
              />
              <button
                onClick={addLocation}
                disabled={!newLocName.trim()}
                className="bg-indigo-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                Add Location
              </button>
            </div>
          </div>

          {/* Duty Slots */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-700">Duty Time Slots</h2>
            <div className="space-y-2">
              {slots.map((s) => (
                <div key={s.id} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <span className="font-medium text-sm">{s.name}</span>
                  <span className="text-xs text-gray-500">{s.start_time} – {s.end_time}</span>
                </div>
              ))}
              {slots.length === 0 && <p className="text-sm text-gray-400">No duty slots yet.</p>}
            </div>
            <div className="flex flex-col gap-2">
              <input
                placeholder="Slot name (e.g. Morning Arrival)"
                value={newSlotName}
                onChange={(e) => setNewSlotName(e.target.value)}
                className="border rounded-lg px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <input
                  type="time"
                  value={newSlotStart}
                  onChange={(e) => setNewSlotStart(e.target.value)}
                  className="border rounded-lg px-3 py-2 text-sm flex-1"
                />
                <input
                  type="time"
                  value={newSlotEnd}
                  onChange={(e) => setNewSlotEnd(e.target.value)}
                  className="border rounded-lg px-3 py-2 text-sm flex-1"
                />
              </div>
              <button
                onClick={addSlot}
                disabled={!newSlotName.trim() || !newSlotStart || !newSlotEnd}
                className="bg-indigo-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                Add Slot
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── ROSTER TAB ─────────────────────────────────────────── */}
      {tab === "roster" && (
        <div className="space-y-4">
          {/* Controls */}
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-sm text-gray-600 bg-gray-100 px-3 py-1.5 rounded-lg">
              Academic Year: <b>{academicYear}</b>
            </span>
            <button
              onClick={generate}
              disabled={generating || slots.length === 0 || locations.length === 0}
              className="bg-indigo-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
            >
              {generating ? "Generating…" : "Generate Roster"}
            </button>
            {assignments.length > 0 && (
              <>
                <button
                  onClick={downloadPdf}
                  className="bg-green-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-green-700"
                >
                  Download PDF
                </button>
                <button
                  onClick={resetDuties}
                  className="bg-red-500 text-white text-sm px-4 py-2 rounded-lg hover:bg-red-600"
                >
                  Reset
                </button>
              </>
            )}
          </div>

          {(slots.length === 0 || locations.length === 0) && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
              Please add duty locations and time slots in the <b>Setup</b> tab before generating a roster.
            </div>
          )}

          {/* Grid */}
          {loading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : assignments.length > 0 ? (
            <div className="bg-white rounded-xl shadow-sm border overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-indigo-50">
                    <th className="px-4 py-3 text-left font-semibold text-indigo-700">Duty Slot</th>
                    {DAY_NAMES.map((d) => (
                      <th key={d} className="px-4 py-3 text-center font-semibold text-indigo-700">{d}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {slotNames.map((slotName, i) => (
                    <tr key={slotName} className={i % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                      <td className="px-4 py-3 font-medium text-gray-700 whitespace-nowrap">
                        {slotName}
                        <div className="text-xs text-gray-400">
                          {assignments.find((a) => a.slot === slotName)?.slot_time}
                        </div>
                      </td>
                      {[0, 1, 2, 3, 4].map((dayIdx) => {
                        const a = grid[slotName]?.[dayIdx];
                        return (
                          <td key={dayIdx} className="px-4 py-3 text-center">
                            {a && a.teacher ? (
                              <div className="bg-indigo-50 rounded-lg px-2 py-1 inline-block">
                                <div className="font-medium text-indigo-700 text-xs">{a.teacher}</div>
                                <div className="text-[11px] text-gray-500">@ {a.location}</div>
                              </div>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-400">No duty assignments for this week. Click &quot;Generate Roster&quot; to create one.</p>
          )}

          {/* Summary */}
          {assignments.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">AI Reasoning</h3>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {assignments
                  .filter((a) => a.teacher && a.reasoning)
                  .map((a) => (
                    <div key={a.id} className="text-xs text-gray-600">
                      <span className="font-medium">{a.day} · {a.slot} · {a.location}:</span>{" "}
                      {a.teacher} — <span className="italic text-gray-500">{a.reasoning}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
