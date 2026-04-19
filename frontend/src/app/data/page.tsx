"use client";

import { useState } from "react";
import { apiUpload } from "@/lib/api";

const endpoints = [
  { label: "Subjects", path: "/ingest/subjects" },
  { label: "Classes", path: "/ingest/classes" },
  { label: "Teachers", path: "/ingest/teachers" },
  { label: "Students", path: "/ingest/students" },
  { label: "Parents", path: "/ingest/parents" },
  { label: "Periods", path: "/timetable/periods" },
  { label: "Timetable", path: "/timetable/upload" },
];

interface UploadResult {
  inserted: number;
  skipped: number;
  errors: { row: number; error: string }[];
}

export default function DataPage() {
  const [results, setResults] = useState<Record<string, UploadResult | string>>({});
  const [uploading, setUploading] = useState<string | null>(null);

  async function handleUpload(label: string, path: string, file: File) {
    setUploading(label);
    try {
      const res = await apiUpload<UploadResult>(path, file);
      setResults((prev) => ({ ...prev, [label]: res }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [label]: String(err) }));
    } finally {
      setUploading(null);
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Data Upload</h1>
        <p className="text-sm text-gray-500 mt-1">
          Upload CSV files to populate the system. Order matters: Subjects → Classes → Teachers → Students → Parents → Periods → Timetable
        </p>
      </div>

      <div className="space-y-4">
        {endpoints.map((ep) => {
          const res = results[ep.label];
          const isError = typeof res === "string";
          const data = !isError ? (res as UploadResult | undefined) : undefined;

          return (
            <div
              key={ep.label}
              className="bg-white rounded-xl border border-gray-200 p-5"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-medium">{ep.label}</h3>
                  {isError && (
                    <p className="text-sm mt-1 text-red-600">{res as string}</p>
                  )}
                  {data && (
                    <p className="text-sm mt-1 text-green-600">
                      ✓ {data.inserted} inserted, {data.skipped} skipped
                      {data.errors.length > 0 && (
                        <span className="text-amber-600 ml-2">
                          ({data.errors.length} error{data.errors.length > 1 ? "s" : ""})
                        </span>
                      )}
                    </p>
                  )}
                </div>
                <label
                  className={`px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors ${
                    uploading === ep.label
                      ? "bg-gray-300 text-gray-500 cursor-wait"
                      : "bg-indigo-600 text-white hover:bg-indigo-700"
                  }`}
                >
                  {uploading === ep.label ? "Uploading..." : "Choose CSV"}
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    disabled={uploading === ep.label}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleUpload(ep.label, ep.path, file);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              {data && data.errors.length > 0 && (
                <div className="mt-3 bg-red-50 border border-red-100 rounded-lg p-3 text-xs space-y-1 max-h-32 overflow-auto">
                  {data.errors.map((err, i) => (
                    <div key={i} className="text-red-700">Row {err.row}: {err.error}</div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
