import { fireEvent, render, screen } from "@testing-library/react";
import PdfIntakePanel from "@/app/leadership/calendar/pdf-intake-panel";

describe("pdf intake panel", () => {
  it("shows OCR-required guidance text", () => {
    render(
      <PdfIntakePanel
        imports={[]}
        selectedImport={{ document_id: "doc-1", import_batch_id: "batch-1", filename: "scan.pdf", status: "ocr_required", page_count: 1, extracted_char_count: 0, error: null }}
        pages={null}
        candidates={null}
        diagnostics={null}
        validation={null}
        loading={false}
        uploadState="ocr_required"
        onUpload={vi.fn(async () => {})}
        onSelectImport={vi.fn(async () => {})}
        onExtract={vi.fn(async () => {})}
        onValidate={vi.fn(async () => {})}
        onCommit={vi.fn(async () => {})}
        onCancelImport={vi.fn(async () => {})}
        onEditCandidate={vi.fn(async () => {})}
        onApproveCandidate={vi.fn(async () => {})}
        onRejectCandidate={vi.fn(async () => {})}
        onLoadPageEvidence={vi.fn(async () => {})}
        onLoadCandidatesPage={vi.fn(async () => {})}
      />,
    );
    expect(screen.getByText(/automatic OCR is not enabled in this phase/i)).toBeInTheDocument();
  });

  it("keeps commit disabled when blockers remain", () => {
    render(
      <PdfIntakePanel
        imports={[]}
        selectedImport={{ document_id: "doc-1", import_batch_id: "batch-1", filename: "calendar.pdf", status: "processed", page_count: 1, extracted_char_count: 44, error: null }}
        pages={null}
        candidates={null}
        diagnostics={null}
        validation={{ document_id: "doc-1", batch_id: "batch-1", status: "validation_failed", approved_candidates: 0, blocker_count: 3, warning_count: 1 }}
        loading={false}
        uploadState="review_ready"
        onUpload={vi.fn(async () => {})}
        onSelectImport={vi.fn(async () => {})}
        onExtract={vi.fn(async () => {})}
        onValidate={vi.fn(async () => {})}
        onCommit={vi.fn(async () => {})}
        onCancelImport={vi.fn(async () => {})}
        onEditCandidate={vi.fn(async () => {})}
        onApproveCandidate={vi.fn(async () => {})}
        onRejectCandidate={vi.fn(async () => {})}
        onLoadPageEvidence={vi.fn(async () => {})}
        onLoadCandidatesPage={vi.fn(async () => {})}
      />,
    );
    expect(screen.getByRole("button", { name: /commit approved candidates/i })).toBeDisabled();
  });

  it("rejects invalid extension in host behavior", async () => {
    const onUpload = vi.fn(async () => {});
    render(
      <PdfIntakePanel
        imports={[]}
        selectedImport={null}
        pages={null}
        candidates={null}
        diagnostics={null}
        validation={null}
        loading={false}
        uploadState="idle"
        onUpload={onUpload}
        onSelectImport={vi.fn(async () => {})}
        onExtract={vi.fn(async () => {})}
        onValidate={vi.fn(async () => {})}
        onCommit={vi.fn(async () => {})}
        onCancelImport={vi.fn(async () => {})}
        onEditCandidate={vi.fn(async () => {})}
        onApproveCandidate={vi.fn(async () => {})}
        onRejectCandidate={vi.fn(async () => {})}
        onLoadPageEvidence={vi.fn(async () => {})}
        onLoadCandidatesPage={vi.fn(async () => {})}
      />,
    );

    const fileInput = screen.getByLabelText(/choose calendar PDF/i) as HTMLInputElement;
    const badFile = new File(["hello"], "bad.txt", { type: "text/plain" });
    fireEvent.change(fileInput, { target: { files: [badFile] } });
    fireEvent.click(screen.getByRole("button", { name: /upload PDF/i }));

    expect(onUpload).toHaveBeenCalledWith(badFile);
  });
});
