"use client";

interface Props {
  qualityScore: number | null;
  warnings: string[];
  retakeRequired: boolean;
  compact?: boolean;
}

const WARNING_LABELS: Record<string, string> = {
  blur: "Blurry",
  glare: "Glare",
  low_lighting: "Low Light",
  cropped_page: "Page Cropped",
  wrong_orientation: "Wrong Orientation",
  incomplete_page: "Incomplete",
  obstruction: "Obstruction",
  perspective_distortion: "Distortion",
};

export default function ScanQualityFeedback({ qualityScore, warnings, retakeRequired, compact }: Props) {
  if (!compact) {
    return (
      <div className={`rounded-xl p-4 ${retakeRequired ? "bg-red-50 border border-red-200" : warnings.length > 0 ? "bg-yellow-50 border border-yellow-200" : "bg-green-50 border border-green-200"}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-medium text-sm">
            {retakeRequired ? "⚠ Retake Required" : warnings.length > 0 ? "⚡ Quality Warning" : "✓ Good Quality"}
          </span>
          {qualityScore !== null && (
            <span className="text-sm font-semibold">
              {Math.round(qualityScore * 100)}%
            </span>
          )}
        </div>
        {warnings.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {warnings.map((w) => (
              <span key={w} className="text-xs px-2 py-0.5 bg-white/80 rounded-full border">
                {WARNING_LABELS[w] ?? w}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Compact mode — shown on thumbnail overlay
  return (
    <div
      className={`absolute bottom-0 left-0 right-0 text-xs text-center py-0.5 ${
        retakeRequired ? "bg-red-500/90 text-white" : warnings.length > 0 ? "bg-yellow-400/90 text-black" : "bg-green-500/90 text-white"
      }`}
    >
      {retakeRequired ? "Retake" : warnings.length > 0 ? `${warnings.length} warning${warnings.length !== 1 ? "s" : ""}` : "✓"}
    </div>
  );
}
