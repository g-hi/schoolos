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
  errors: string[];
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
    <div>
      <h1 className="text-2xl font-bold mb-2">Data Upload</h1>
      <p className="text-sm text-gray-500 mb-6">
        Upload CSV files to populate the system. Order matters: Subjects → Classes → Teachers → Students → Parents → Periods → Timetable
      </p>

      <div className="space-y-4">
        {endpoints.map((ep) => (
          <div
            key={ep.label}
            className="bg-white rounded-xl border border-gray-200 p-5 flex items-center justify-between"
          >
            <div>
              <h3 className="font-medium">{ep.label}</h3>
              {results[ep.label] && (
                <p className="text-sm mt-1">
                  {typeof results[ep.label] === "string" ? (
                    <span className="text-red-600">{results[ep.label] as string}</span>
                  ) : (
                    <span className="text-green-600">
                      ✓ {(results[ep.label] as UploadResult).inserted} inserted,{" "}
                      {(results[ep.label] as UploadResult).skipped} skipped
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
        ))}
      </div>
    </div>
  );
}
