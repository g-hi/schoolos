import { render, screen } from "@testing-library/react";
import PdfIntakePanel from "@/app/leadership/calendar/pdf-intake-panel";

describe("candidate review presentation", () => {
  it("renders source evidence, confidence, and separate approve/reject controls", () => {
    render(
      <PdfIntakePanel
        imports={[]}
        selectedImport={{ document_id: "doc-1", import_batch_id: "batch-1", filename: "calendar.pdf", status: "processed", page_count: 2, extracted_char_count: 220, error: null }}
        pages={null}
        candidates={{
          page: 1,
          page_size: 10,
          total: 1,
          items: [
            {
              id: "cand-1",
              source_document_id: "doc-1",
              source_page_id: "p-1",
              proposed_event_name: "Holiday",
              proposed_description: "Holiday note",
              proposed_start_date: "2026-12-01",
              proposed_end_date: "2026-12-01",
              proposed_event_type: "public_holiday",
              proposed_teaching_day_effect: "non_teaching_day",
              confidence_score: 41,
              candidate_status: "proposed",
              date_parse_status: "ambiguous",
              uncertainty_note: "ambiguous",
              classification_json: { explanation: "Matched loosely" },
              validation_issues_json: { warnings: ["ambiguous"], blockers: [] },
              source_payload: { page_number: 2, line: "1/12/26 Holiday" },
              applied_event_id: null,
            },
          ],
        }}
        diagnostics={null}
        validation={{ document_id: "doc-1", batch_id: "batch-1", status: "validated", approved_candidates: 0, blocker_count: 0, warning_count: 1 }}
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

    expect(screen.getByText(/source page: 2/i)).toBeInTheDocument();
    expect(screen.getByText(/confidence: 41/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Approve$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject with reason/i })).toBeInTheDocument();
    expect(screen.getByText(/requires human review due to low confidence or ambiguity/i)).toBeInTheDocument();
  });
});
