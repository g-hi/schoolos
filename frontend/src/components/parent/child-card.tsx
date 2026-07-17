import Link from "next/link";
import { ParentStudentSummary } from "@/lib/parent-api";

interface ChildCardProps {
  student: ParentStudentSummary;
  isActive: boolean;
  onActivate: (studentId: string) => void;
}

export default function ChildCard({ student, isActive, onActivate }: ChildCardProps) {
  return (
    <article
      className={`rounded-2xl border bg-white p-4 shadow-sm transition ${
        isActive ? "border-indigo-300 ring-2 ring-indigo-100" : "border-gray-200"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{student.name}</h3>
          <p className="mt-1 text-sm text-gray-600">
            {student.class_name}
            {student.homeroom_teacher ? ` • ${student.homeroom_teacher}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onActivate(student.student_id)}
          aria-label={`Set ${student.name} as active child`}
          className="rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
        >
          {isActive ? "Selected" : "Select"}
        </button>
      </div>

      <div className="mt-4 flex justify-end">
        <Link
          href={`/parent/student/${student.student_id}`}
          className="inline-flex rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
        >
          View overview
        </Link>
      </div>
    </article>
  );
}
