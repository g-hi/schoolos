"use client";

import { useState } from "react";

interface QuestionResponse {
  question_number: number;
  question_type: string;
  extracted_answer: string;
  extraction_confidence: number;
  correct_answer: string;
  proposed_marks: number;
  max_marks: number;
  teacher_final_marks?: number;
  grading_method: string;
  confidence: number;
  confidence_band?: string;
  ambiguous_mark: boolean;
  requires_teacher_review: boolean;
  teacher_overridden?: boolean;
  teacher_comment?: string;
  evidence: Record<string, unknown>;
  rubric_result?: {
    criteria?: { criterion: string; awarded: number; max: number; evidence: string }[];
    feedback?: string;
  };
  status: string;
}

interface Props {
  response: QuestionResponse;
  onOverride?: (questionNumber: number, marks: number, comment: string) => void;
}

const GRADING_METHOD_LABELS: Record<string, string> = {
  omr: "OMR",
  vision: "Computer Vision",
  deterministic: "Deterministic",
  rubric_ai: "AI Rubric",
};

const BAND_COLORS: Record<string, string> = {
  high: "text-green-600",
  medium: "text-yellow-600",
  low: "text-red-600",
};

export default function QuestionReviewRow({ response, onOverride }: Props) {
  const [editing, setEditing] = useState(false);
  const [marks, setMarks] = useState<string>(String(response.teacher_final_marks ?? response.proposed_marks));
  const [comment, setComment] = useState(response.teacher_comment ?? "");
  const [showRubric, setShowRubric] = useState(false);

  const handleSave = () => {
    const val = parseFloat(marks);
    if (!isNaN(val) && val >= 0 && val <= response.max_marks) {
      onOverride?.(response.question_number, val, comment);
      setEditing(false);
    }
  };

  const confidenceLabel = response.confidence !== null
    ? `${Math.round(response.confidence * 100)}%`
    : "—";

  const displayedMarks = response.teacher_final_marks ?? response.proposed_marks;

  return (
    <div
      className={`rounded-xl border p-4 space-y-3 ${
        response.status === "unresolved"
          ? "border-red-200 bg-red-50"
          : response.confidence_band === "low"
            ? "border-orange-200 bg-orange-50"
            : response.teacher_overridden
              ? "border-indigo-200 bg-indigo-50"
              : "border-gray-200 bg-white"
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-gray-900">Q{response.question_number}</span>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
            {response.question_type.replace("_", " ")}
          </span>
          <span className="text-xs text-gray-500">
            {GRADING_METHOD_LABELS[response.grading_method] ?? response.grading_method}
          </span>
          {response.ambiguous_mark && (
            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">Ambiguous</span>
          )}
          {response.status === "unresolved" && (
            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">Unresolved</span>
          )}
          {response.teacher_overridden && (
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">Overridden</span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-sm font-medium ${BAND_COLORS[response.confidence_band ?? "high"] ?? "text-gray-500"}`}>
            {confidenceLabel}
          </span>
        </div>
      </div>

      {/* Answer comparison */}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xs text-gray-500 mb-0.5">Student Answer</p>
          <p className="text-gray-800 font-medium">{response.extracted_answer || "—"}</p>
        </div>
        {response.correct_answer && (
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Correct Answer</p>
            <p className="text-gray-800">{response.correct_answer}</p>
          </div>
        )}
      </div>

      {/* Marks */}
      <div className="flex items-center gap-4">
        <div>
          <p className="text-xs text-gray-500 mb-0.5">AI Proposed</p>
          <p className="font-semibold text-gray-800">
            {response.proposed_marks} / {response.max_marks}
          </p>
        </div>
        {response.teacher_final_marks !== undefined && response.teacher_final_marks !== null && (
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Teacher Final</p>
            <p className="font-semibold text-indigo-700">
              {response.teacher_final_marks} / {response.max_marks}
            </p>
          </div>
        )}
      </div>

      {/* Override editor */}
      {editing ? (
        <div className="space-y-2 pt-2 border-t border-gray-200">
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-600 w-24 shrink-0">Final marks:</label>
            <input
              type="number"
              min={0}
              max={response.max_marks}
              step={0.5}
              value={marks}
              onChange={(e) => setMarks(e.target.value)}
              className="w-24 border border-gray-300 rounded-lg px-2 py-1 text-sm"
            />
            <span className="text-xs text-gray-500">/ {response.max_marks}</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-600 w-24 shrink-0">Comment:</label>
            <input
              type="text"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Optional comment…"
              className="flex-1 border border-gray-300 rounded-lg px-2 py-1 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleSave}
              className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700"
            >
              Save Override
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 bg-gray-100 text-gray-700 text-xs rounded-lg hover:bg-gray-200"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-xs px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100"
          >
            Override Mark
          </button>
          {response.rubric_result?.criteria && response.rubric_result.criteria.length > 0 && (
            <button
              type="button"
              onClick={() => setShowRubric(!showRubric)}
              className="text-xs px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200"
            >
              {showRubric ? "Hide" : "Show"} Rubric
            </button>
          )}
        </div>
      )}

      {/* Rubric breakdown */}
      {showRubric && response.rubric_result?.criteria && (
        <div className="pt-2 border-t border-gray-200 space-y-1">
          <p className="text-xs font-medium text-gray-600 mb-1">Rubric Breakdown</p>
          {response.rubric_result.criteria.map((c, i) => (
            <div key={i} className="flex justify-between text-xs text-gray-600">
              <span>{c.criterion}</span>
              <span className="font-medium">{c.awarded}/{c.max}</span>
            </div>
          ))}
          {response.rubric_result.feedback && (
            <p className="text-xs text-gray-500 mt-1 italic">{response.rubric_result.feedback}</p>
          )}
        </div>
      )}
    </div>
  );
}
