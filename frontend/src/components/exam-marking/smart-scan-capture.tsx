"use client";

import { useRef, useState } from "react";
import { uploadPage, type PageUploadResponse } from "@/lib/exam-marking-api";
import ScanQualityFeedback from "./scan-quality-feedback";

interface CapturedPage {
  file: File;
  previewUrl: string;
  pageNumber: number;
  uploadResponse?: PageUploadResponse;
  uploading?: boolean;
  uploadError?: string;
}

interface Props {
  sessionId: string;
  submissionId?: string;
  studentName?: string;
  studentCode?: string;
  onPageUploaded?: (response: PageUploadResponse, pageNumber: number) => void;
  onStudentComplete?: (pages: CapturedPage[]) => void;
}

/**
 * SmartScanCapture — mobile-first camera capture for exam papers.
 *
 * V1: Uses <input type="file" accept="image/*" capture="environment"> for
 * rear-camera access on mobile devices.
 *
 * Architecture note: This component wraps a ManualScanProvider.
 * Future V2 will implement AutoScanProvider via WebRTC getUserMedia +
 * edge detection + stability detection. Replace the capture trigger
 * without changing the parent page.
 */
export default function SmartScanCapture({
  sessionId,
  submissionId,
  studentName,
  studentCode,
  onPageUploaded,
  onStudentComplete,
}: Props) {
  const [pages, setPages] = useState<CapturedPage[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleCapture = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const pageNumber = pages.length + 1;
    const previewUrl = URL.createObjectURL(file);

    const newPage: CapturedPage = { file, previewUrl, pageNumber };
    setPages((prev) => [...prev, newPage]);

    // Reset input so the same file can be re-selected after retake
    e.target.value = "";

    // Auto-upload
    uploadPageAsync(newPage);
  };

  const uploadPageAsync = async (page: CapturedPage) => {
    setPages((prev) =>
      prev.map((p) =>
        p.pageNumber === page.pageNumber ? { ...p, uploading: true, uploadError: undefined } : p,
      ),
    );
    try {
      const response = await uploadPage(
        sessionId,
        page.file,
        page.pageNumber,
        submissionId,
        studentName,
        studentCode,
      );
      setPages((prev) =>
        prev.map((p) =>
          p.pageNumber === page.pageNumber ? { ...p, uploading: false, uploadResponse: response } : p,
        ),
      );
      onPageUploaded?.(response, page.pageNumber);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setPages((prev) =>
        prev.map((p) =>
          p.pageNumber === page.pageNumber ? { ...p, uploading: false, uploadError: msg } : p,
        ),
      );
    }
  };

  const retakePage = (pageNumber: number) => {
    setPages((prev) => {
      const updated = prev.filter((p) => p.pageNumber !== pageNumber);
      // Renumber remaining pages
      return updated.map((p, i) => ({ ...p, pageNumber: i + 1 }));
    });
  };

  const deletePage = (pageNumber: number) => {
    setPages((prev) => {
      const updated = prev.filter((p) => p.pageNumber !== pageNumber);
      return updated.map((p, i) => ({ ...p, pageNumber: i + 1 }));
    });
  };

  const reorderPage = (pageNumber: number, direction: "up" | "down") => {
    setPages((prev) => {
      const idx = prev.findIndex((p) => p.pageNumber === pageNumber);
      if (idx === -1) return prev;
      const newPages = [...prev];
      const swapIdx = direction === "up" ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= newPages.length) return prev;
      [newPages[idx], newPages[swapIdx]] = [newPages[swapIdx], newPages[idx]];
      return newPages.map((p, i) => ({ ...p, pageNumber: i + 1 }));
    });
  };

  const handleStudentComplete = () => {
    onStudentComplete?.(pages);
    setPages([]);
  };

  const pendingUploads = pages.filter((p) => p.uploading).length;
  const failedUploads = pages.filter((p) => p.uploadError).length;
  const retakeRequired = pages.filter((p) => p.uploadResponse?.retake_required).length;

  return (
    <div className="space-y-4">
      {/* Capture trigger */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-2 px-4 py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 transition-colors shadow-sm"
        >
          <span className="text-lg">📷</span>
          {pages.length === 0 ? "Scan Page 1" : `Scan Page ${pages.length + 1}`}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={handleCapture}
        />
        {pages.length > 0 && (
          <span className="text-sm text-gray-500">
            {pages.length} page{pages.length !== 1 ? "s" : ""} captured
          </span>
        )}
      </div>

      {/* Status summary */}
      {pendingUploads > 0 && (
        <div className="flex items-center gap-2 text-sm text-blue-600 bg-blue-50 px-3 py-2 rounded-lg">
          <span className="animate-spin">⏳</span>
          Uploading {pendingUploads} page{pendingUploads !== 1 ? "s" : ""}…
        </div>
      )}
      {failedUploads > 0 && (
        <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">
          {failedUploads} upload{failedUploads !== 1 ? "s" : ""} failed. Retry by deleting and re-scanning.
        </div>
      )}
      {retakeRequired > 0 && (
        <div className="text-sm text-orange-600 bg-orange-50 px-3 py-2 rounded-lg">
          {retakeRequired} page{retakeRequired !== 1 ? "s" : ""} need{retakeRequired === 1 ? "s" : ""} retaking.
        </div>
      )}

      {/* Page thumbnails */}
      {pages.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {pages.map((page) => (
            <div
              key={page.pageNumber}
              className="relative border border-gray-200 rounded-xl overflow-hidden bg-gray-50"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={page.previewUrl}
                alt={`Page ${page.pageNumber}`}
                className="w-full aspect-[3/4] object-cover"
              />

              {/* Page number badge */}
              <div className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-0.5 rounded-full">
                p.{page.pageNumber}
              </div>

              {/* Upload status overlay */}
              {page.uploading && (
                <div className="absolute inset-0 bg-black/30 flex items-center justify-center">
                  <span className="text-white text-2xl animate-spin">⏳</span>
                </div>
              )}

              {/* Quality feedback */}
              {page.uploadResponse && (
                <ScanQualityFeedback
                  qualityScore={page.uploadResponse.quality_score}
                  warnings={page.uploadResponse.quality_warnings}
                  retakeRequired={page.uploadResponse.retake_required}
                  compact
                />
              )}

              {/* Error badge */}
              {page.uploadError && (
                <div className="absolute top-2 right-2 bg-red-500 text-white text-xs px-2 py-0.5 rounded-full">
                  Failed
                </div>
              )}

              {/* Actions */}
              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-2 flex justify-between items-end">
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => reorderPage(page.pageNumber, "up")}
                    className="text-white/80 hover:text-white text-xs px-1"
                    title="Move up"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => reorderPage(page.pageNumber, "down")}
                    className="text-white/80 hover:text-white text-xs px-1"
                    title="Move down"
                  >
                    ↓
                  </button>
                </div>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => retakePage(page.pageNumber)}
                    className="text-yellow-300 hover:text-yellow-100 text-xs font-medium"
                    title="Retake"
                  >
                    Retake
                  </button>
                  <button
                    type="button"
                    onClick={() => deletePage(page.pageNumber)}
                    className="text-red-300 hover:text-red-100 text-xs font-medium ml-2"
                    title="Delete"
                  >
                    ✕
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Student complete button */}
      {pages.length > 0 && pendingUploads === 0 && (
        <div className="pt-2 border-t border-gray-100">
          <button
            type="button"
            onClick={handleStudentComplete}
            disabled={retakeRequired > 0}
            className="w-full py-3 bg-green-600 text-white rounded-xl font-semibold hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            ✓ Student Complete — Next Student
          </button>
          {retakeRequired > 0 && (
            <p className="text-xs text-orange-600 text-center mt-1">
              Retake {retakeRequired} page{retakeRequired !== 1 ? "s" : ""} before proceeding.
            </p>
          )}
        </div>
      )}

      {/* Architecture note for developers */}
      {/* V2: Replace ManualScanProvider with AutoScanProvider using:
          navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
          + edge detection (OpenCV.js) + stability detection.
          The parent page interface (onPageUploaded, onStudentComplete) stays unchanged. */}
    </div>
  );
}
