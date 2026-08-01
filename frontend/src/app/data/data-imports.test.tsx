import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import DataPage from "@/app/data/page";
import { useAuth } from "@/components/auth/auth-provider";
import {
  cancelImport,
  commitImport,
  downloadImportErrors,
  getImportBatch,
  getImportSummary,
  listImportBatches,
  listImportRows,
  previewImport,
} from "@/lib/imports-api";
import { apiUpload } from "@/lib/api";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/data",
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiUpload: vi.fn(),
}));

vi.mock("@/lib/imports-api", () => ({
  ImportsApiError: class ImportsApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
  previewImport: vi.fn(),
  commitImport: vi.fn(),
  cancelImport: vi.fn(),
  listImportBatches: vi.fn(),
  getImportSummary: vi.fn(),
  getImportBatch: vi.fn(),
  listImportRows: vi.fn(),
  downloadImportErrors: vi.fn(),
}));

const previewBatch = {
  id: "batch-preview-1",
  tenant_id: "tenant-1",
  entity_type: "subjects",
  original_filename: "subjects.csv",
  file_sha256: "a".repeat(64),
  status: "preview_ready",
  mode: "preview",
  created_by_user_id: "user-1",
  total_rows: 3,
  valid_rows: 2,
  invalid_rows: 1,
  created_rows: 0,
  updated_rows: 0,
  skipped_rows: 0,
  conflict_rows: 0,
  started_at: "2026-08-01T00:00:00Z",
  completed_at: "2026-08-01T00:00:05Z",
  committed_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:05Z",
  available_actions: ["commit", "cancel", "download_errors", "view_rows"],
};

const completedBatch = {
  ...previewBatch,
  status: "completed",
  created_rows: 2,
  committed_at: "2026-08-01T00:01:00Z",
  completed_at: "2026-08-01T00:01:00Z",
};

const rowDiagnostics = [
  {
    id: "row-1",
    row_number: 1,
    status: "valid",
    action: "create",
    entity_reference_id: null,
    error_code: null,
    error_message: null,
    field_errors: {},
    normalized_data: { code: "MATH", name: "Mathematics" },
  },
  {
    id: "row-2",
    row_number: 2,
    status: "invalid",
    action: "none",
    entity_reference_id: null,
    error_code: "missing_required_field",
    error_message: "name is required",
    field_errors: { name: "required" },
    normalized_data: { code: "ENG" },
  },
];

function seedApiMocks() {
  (getImportSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    total_batches: 1,
    by_entity_type: { subjects: 1 },
    by_status: { preview_ready: 1 },
    by_mode: { preview: 1 },
  });

  (listImportBatches as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [previewBatch],
    total: 1,
    page: 1,
    pageSize: 10,
  });

  (previewImport as ReturnType<typeof vi.fn>).mockResolvedValue({
    batch: previewBatch,
    rows: rowDiagnostics,
  });

  (commitImport as ReturnType<typeof vi.fn>).mockResolvedValue({
    batch: completedBatch,
    rows: rowDiagnostics.map((row) => ({ ...row, status: row.status === "valid" ? "created" : "invalid" })),
  });

  (cancelImport as ReturnType<typeof vi.fn>).mockResolvedValue({
    ...previewBatch,
    status: "cancelled",
  });

  (getImportBatch as ReturnType<typeof vi.fn>).mockResolvedValue(completedBatch);

  (listImportRows as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: rowDiagnostics,
    total: rowDiagnostics.length,
    page: 1,
    pageSize: 20,
  });

  (downloadImportErrors as ReturnType<typeof vi.fn>).mockResolvedValue("import-errors-batch-preview-1.csv");

  (apiUpload as ReturnType<typeof vi.fn>).mockResolvedValue({
    inserted: 1,
    skipped: 0,
    errors: [],
  });
}

describe("data imports workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seedApiMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("allows principal to access Data Imports", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      user: { role: "principal", is_active: true },
    });

    render(<DataPage />);
    expect(await screen.findByText("Data Imports")).toBeInTheDocument();
  });

  it("blocks teacher from leadership-only data imports", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      user: { role: "teacher", is_active: true },
    });

    render(<DataPage />);
    expect(await screen.findByText("Only school leadership can access Data Imports.")).toBeInTheDocument();
  });

  it("runs preview and commit workflow", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      user: { role: "principal", is_active: true },
    });

    render(<DataPage />);
    await screen.findByText("Data Imports");

    const fileInput = screen.getByLabelText("CSV file") as HTMLInputElement;
    const csv = new File(["code,name\nMATH,Mathematics\n"], "subjects.csv", { type: "text/csv" });
    fireEvent.change(fileInput, { target: { files: [csv] } });

    fireEvent.click(screen.getByRole("button", { name: "Preview Import" }));

    await waitFor(() => {
      expect(previewImport).toHaveBeenCalledWith("subjects", expect.any(File));
    });
    expect(await screen.findByRole("heading", { name: "Preview" })).toBeInTheDocument();
    expect(screen.getByText("preview_ready")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Commit Batch" }));
    await waitFor(() => {
      expect(commitImport).toHaveBeenCalledWith("batch-preview-1");
    });
    expect(await screen.findByRole("heading", { name: "Batch Detail" })).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("loads batch detail from history and applies row filters", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      user: { role: "school_admin", is_active: true },
    });

    render(<DataPage />);
    await screen.findByText("Data Imports");

    fireEvent.click(screen.getByRole("button", { name: "Import History" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect" }));

    await waitFor(() => {
      expect(getImportBatch).toHaveBeenCalledWith("batch-preview-1");
      expect(listImportRows).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Review Row Diagnostics" }));
    const comboboxes = screen.getAllByRole("combobox");
    fireEvent.change(comboboxes[0], { target: { value: "invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(listImportRows).toHaveBeenLastCalledWith(
        "batch-preview-1",
        expect.objectContaining({ status: "invalid" }),
      );
    });
  });

  it("keeps legacy direct upload compatibility", async () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({
      isHydrating: false,
      isAuthenticated: true,
      user: { role: "principal", is_active: true },
    });

    render(<DataPage />);
    await screen.findByText("Data Imports");

    fireEvent.click(screen.getByText("Legacy direct upload (compatibility)"));
    const details = screen.getByText("Legacy direct upload (compatibility)").closest("details");
    expect(details).not.toBeNull();

    const input = details?.querySelector('input[type="file"]') as HTMLInputElement;
    const csv = new File(["code,name\nMATH,Mathematics\n"], "subjects.csv", { type: "text/csv" });
    fireEvent.change(input, { target: { files: [csv] } });

    await waitFor(() => {
      expect(apiUpload).toHaveBeenCalledWith("/ingest/subjects", expect.any(File));
    });
  });
});
