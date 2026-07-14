"use client";

interface Props {
  proposedTotal: number;
  teacherFinalTotal?: number | null;
  maxMarks: number;
  percentage?: number | null;
  objectiveCount?: number;
  aiGradedCount?: number;
  deterministicCount?: number;
  unresolvedCount?: number;
  lowConfidenceCount?: number;
  tokenUsage?: { total_tokens?: number };
  estimatedCostUsd?: number;
}

export default function MarkSummary({
  proposedTotal,
  teacherFinalTotal,
  maxMarks,
  percentage,
  objectiveCount = 0,
  aiGradedCount = 0,
  deterministicCount = 0,
  unresolvedCount = 0,
  lowConfidenceCount = 0,
  tokenUsage,
  estimatedCostUsd,
}: Props) {
  const displayTotal = teacherFinalTotal ?? proposedTotal;
  const pct = percentage ?? (maxMarks > 0 ? Math.round((displayTotal / maxMarks) * 100) : 0);

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
      {/* Score */}
      <div className="flex items-end justify-between">
        <div>
          <p className="text-sm text-gray-500">
            {teacherFinalTotal !== null && teacherFinalTotal !== undefined
              ? "Teacher Final Mark"
              : "AI Proposed Mark"}
          </p>
          <p className="text-3xl font-bold text-gray-900 mt-0.5">
            {displayTotal} <span className="text-xl text-gray-400">/ {maxMarks}</span>
          </p>
          <p className="text-lg font-semibold text-indigo-600 mt-0.5">{pct}%</p>
        </div>
        {teacherFinalTotal === null || teacherFinalTotal === undefined ? (
          <div className="text-right">
            <p className="text-xs text-gray-500">AI Proposed</p>
            <p className="text-lg font-semibold text-gray-800">{proposedTotal}</p>
          </div>
        ) : (
          <div className="text-right">
            <p className="text-xs text-gray-500">AI Proposed</p>
            <p className="text-lg font-semibold text-gray-400 line-through">{proposedTotal}</p>
          </div>
        )}
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        {objectiveCount > 0 && (
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-500">Objective Qs</p>
            <p className="font-semibold text-gray-800">{deterministicCount}</p>
          </div>
        )}
        {aiGradedCount > 0 && (
          <div className="bg-purple-50 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-500">AI-Graded Qs</p>
            <p className="font-semibold text-purple-700">{aiGradedCount}</p>
          </div>
        )}
        {unresolvedCount > 0 && (
          <div className="bg-red-50 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-500">Unresolved</p>
            <p className="font-semibold text-red-600">{unresolvedCount}</p>
          </div>
        )}
        {lowConfidenceCount > 0 && (
          <div className="bg-orange-50 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-500">Low Confidence</p>
            <p className="font-semibold text-orange-600">{lowConfidenceCount}</p>
          </div>
        )}
      </div>

      {/* Token / cost (if used) */}
      {tokenUsage?.total_tokens ? (
        <div className="pt-2 border-t border-gray-100 text-xs text-gray-400 flex justify-between">
          <span>{tokenUsage.total_tokens.toLocaleString()} tokens</span>
          {estimatedCostUsd !== undefined && estimatedCostUsd > 0 && (
            <span>~${estimatedCostUsd.toFixed(4)} AI cost</span>
          )}
        </div>
      ) : null}
    </div>
  );
}
