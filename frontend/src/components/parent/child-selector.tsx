"use client";

import { ParentStudentSummary } from "@/lib/parent-api";

interface ChildSelectorProps {
  students: ParentStudentSummary[];
  activeStudentId: string | null;
  onChange: (studentId: string) => void;
}

export default function ChildSelector({ students, activeStudentId, onChange }: ChildSelectorProps) {
  if (students.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <label htmlFor="parent-student-selector" className="text-sm font-medium text-gray-700">
        Select child
      </label>
      <select
        id="parent-student-selector"
        value={activeStudentId ?? students[0].student_id}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
        aria-label="Select child"
      >
        {students.map((student) => (
          <option key={student.student_id} value={student.student_id}>
            {student.name} - {student.class_name}
          </option>
        ))}
      </select>
    </div>
  );
}
