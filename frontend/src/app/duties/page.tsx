"use client";

import { useState, useEffect, useCallback } from "react";
import { api, apiPost } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://schoolos-gateway.onrender.com";
const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG || "greenwood";
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

interface SlotLocation {
  id: string;
  name: string;
  description: string | null;
}
interface SlotConfig {
  id: string;
  name: string;
  start_time: string;
  end_time: string;
  locations: SlotLocation[];
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
  const [slotConfigs, setSlotConfigs] = useState<SlotConfig[]>([]);
  const [newSlotName, setNewSlotName] = useState("");
  const [newSlotStart, setNewSlotStart] = useState("");
  const [newSlotEnd, setNewSlotEnd] = useState("");
  // Per-slot new-location input: slotId -> text
  const [locInputs, setLocInputs] = useState<Record<string, string>>({});

  // Roster state
  const [academicYear] = useState("2025-2026");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load slot-location config
  const loadConfig = useCallback(() => {
    api<SlotConfig[]>("/duties/slots-config").then(setSlotConfigs).catch(() => {});
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  // Load assignments on mount
  useEffect(() => {
    setLoading(true);
    api<Assignment[]>("/duties/", { params: { academic_year: academicYear } })
      .then(setAssignments)
      .catch(() => setAssignments([]))
      .finally(() => setLoading(false));
  }, [academicYear]);

  const addSlot = async () => {
    if (!newSlotName.trim() || !newSlotStart || !newSlotEnd) return;
    await apiPost("/duties/slots", {
      name: newSlotName.trim(),
      start_time: newSlotStart,
      end_time: newSlotEnd,
    });
    setNewSlotName("");
    setNewSlotStart("");
    setNewSlotEnd("");
    loadConfig();
  };

  const addLocationToSlot = async (slotId: string) => {
    const name = (locInputs[slotId] || "").trim();
    if (!name) return;
    try {
      await apiPost(`/duties/slots/${slotId}/locations`, { name });
      setLocInputs((prev) => ({ ...prev, [slotId]: "" }));
      loadConfig();
    } catch (e: unknown) {
      alert((e as Error).message);
    }
  };

  const removeLocationFromSlot = async (slotId: string, locationId: string) => {
    await api(`/duties/slots/${slotId}/locations/${locationId}`, { method: "DELETE" });
    loadConfig();
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

  // Build grid: "slot|location" -> day -> assignment
  const grid: Record<string, Record<number, Assignment>> = {};
  for (const a of assignments) {
    const key = `${a.slot}|${a.location}`;
    if (!grid[key]) grid[key] = {};
    grid[key][a.day_of_week] = a;
  }

  // Build row keys grouped by slot, ordered by time
  const rowKeys: { key: string; slot: string; location: string; slotTime: string }[] = [];
  const seen = new Set<string>();
  // Sort assignments by slot time for ordering
  const sorted = [...assignments].sort((a, b) => a.slot_time.localeCompare(b.slot_time));
  for (const a of sorted) {
    const key = `${a.slot}|${a.location}`;
    if (!seen.has(key)) {
      seen.add(key);
      rowKeys.push({ key, slot: a.slot, location: a.location, slotTime: a.slot_time });
    }
  }

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
        <div className="space-y-6">
          {/* Add New Slot */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-3">
            <h2 className="text-lg font-semibold text-gray-700">Add Duty Time Slot</h2>
            <div className="flex flex-wrap items-end gap-3">
              <input
                placeholder="Slot name (e.g. First Break)"
                value={newSlotName}
                onChange={(e) => setNewSlotName(e.target.value)}
                className="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[180px]"
              />
              <div className="flex gap-2">
                <input
                  type="time"
                  value={newSlotStart}
                  onChange={(e) => setNewSlotStart(e.target.value)}
                  className="border rounded-lg px-3 py-2 text-sm"
                />
                <span className="self-center text-gray-400">–</span>
                <input
                  type="time"
                  value={newSlotEnd}
                  onChange={(e) => setNewSlotEnd(e.target.value)}
                  className="border rounded-lg px-3 py-2 text-sm"
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

          {/* Slot Cards with Locations */}
          {slotConfigs.length === 0 && (
            <p className="text-sm text-gray-400">No duty slots yet. Add one above to get started.</p>
          )}

          {slotConfigs.map((slot) => (
            <div key={slot.id} className="bg-white rounded-xl shadow-sm border p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-gray-800">{slot.name}</h3>
                  <span className="text-xs text-gray-500">{slot.start_time} – {slot.end_time}</span>
                </div>
                <span className="text-xs bg-indigo-50 text-indigo-600 px-2 py-1 rounded-full">
                  {slot.locations.length} location{slot.locations.length !== 1 ? "s" : ""}
                </span>
              </div>

              {/* Location tags */}
              <div className="flex flex-wrap gap-2">
                {slot.locations.map((loc) => (
                  <span
                    key={loc.id}
                    className="inline-flex items-center gap-1 bg-gray-100 text-gray-700 text-xs px-2.5 py-1 rounded-full"
                  >
                    {loc.name}
                    <button
                      onClick={() => removeLocationFromSlot(slot.id, loc.id)}
                      className="text-gray-400 hover:text-red-500 ml-0.5"
                      title="Remove"
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>

              {/* Add location input */}
              <div className="flex gap-2">
                <input
                  placeholder="Type location name (e.g. Playground, Cafeteria)"
                  value={locInputs[slot.id] || ""}
                  onChange={(e) =>
                    setLocInputs((prev) => ({ ...prev, [slot.id]: e.target.value }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") addLocationToSlot(slot.id);
                  }}
                  className="border rounded-lg px-3 py-1.5 text-sm flex-1"
                />
                <button
                  onClick={() => addLocationToSlot(slot.id)}
                  disabled={!(locInputs[slot.id] || "").trim()}
                  className="bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-gray-800 disabled:opacity-40"
                >
                  + Add
                </button>
              </div>
            </div>
          ))}
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
              disabled={generating || slotConfigs.every((s) => s.locations.length === 0)}
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

          {slotConfigs.every((s) => s.locations.length === 0) && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
              Add duty slots and their locations in the <b>Setup</b> tab first. For each slot (e.g. First Break), type the locations that need coverage.
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
                    <th className="px-4 py-3 text-left font-semibold text-indigo-700">Slot / Location</th>
                    {DAY_NAMES.map((d) => (
                      <th key={d} className="px-4 py-3 text-center font-semibold text-indigo-700">{d}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rowKeys.map((row, i) => {
                    // Show slot header row if this is the first location of a new slot
                    const isFirstOfSlot = i === 0 || rowKeys[i - 1].slot !== row.slot;
                    return (
                      <>
                        {isFirstOfSlot && (
                          <tr key={`hdr-${row.slot}`} className="bg-indigo-50/50">
                            <td colSpan={6} className="px-4 py-2 font-semibold text-indigo-700 text-xs">
                              {row.slot} <span className="font-normal text-gray-400 ml-1">{row.slotTime}</span>
                            </td>
                          </tr>
                        )}
                        <tr key={row.key} className={i % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                          <td className="px-4 py-2 pl-8 text-gray-600 text-xs whitespace-nowrap">
                            {row.location}
                          </td>
                          {[0, 1, 2, 3, 4].map((dayIdx) => {
                            const a = grid[row.key]?.[dayIdx];
                            return (
                              <td key={dayIdx} className="px-4 py-2 text-center">
                                {a && a.teacher ? (
                                  <span className="font-medium text-indigo-700 text-xs">{a.teacher}</span>
                                ) : (
                                  <span className="text-gray-300">—</span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-400">No duty assignments yet. Click &quot;Generate Roster&quot; to create one.</p>
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
