# SchoolOS Phase 9D Data Imports

## Scope

Phase 9D final batch delivers:

- Phase 9D2: Leadership Data Import Workspace in frontend `/data`
- Phase 9D3: Import review workflow, import history, diagnostics surfacing, documentation, and final hardening checks

This builds on the backend import history foundation (`/leadership/imports/*`) and keeps legacy direct upload compatibility (`/ingest/*`) intact.

## Architecture

### Backend lifecycle

The leadership import lifecycle is implemented in `services/gateway/routers/imports.py` with tenant-scoped, role-gated endpoints:

- `POST /leadership/imports/preview`
- `POST /leadership/imports/{batch_id}/commit`
- `POST /leadership/imports/{batch_id}/cancel`
- `GET /leadership/imports`
- `GET /leadership/imports/summary`
- `GET /leadership/imports/{batch_id}`
- `GET /leadership/imports/{batch_id}/rows`
- `GET /leadership/imports/{batch_id}/errors.csv`

Core behavior:

- CSV parse and validation with strict UTF-8, row limits, and size limits
- Per-row classification (`valid`, `invalid`, `conflict`, `skipped`) during preview
- Explicit commit step that applies only eligible rows
- Batch and row persistence through `ImportBatch` and `ImportRowResult`
- Lifecycle-safe cancellation (no destructive rollback of already-created records)

### Frontend workspace

The `/data` page is now a leadership-only imports workspace with sections:

- New Import
- Preview
- Import History
- Batch Detail
- Error Review

A typed client module `frontend/src/lib/imports-api.ts` centralizes API interaction and error normalization.

### Compatibility mode

Legacy direct upload cards remain available under a collapsed `Legacy direct upload (compatibility)` section and continue using existing `/ingest/*` and timetable upload routes.

## Security and Access Control

- Role guard: only `principal` and `school_admin` can access `/data`
- Backend enforces leadership auth dependencies and tenant context
- Tenant isolation is maintained using `X-Tenant-Slug` and tenant-scoped queries
- Commit/cancel controls are disabled by status and action constraints
- Error exports are batch-scoped and tenant-scoped

## Workflow

1. Select entity type and CSV in New Import
2. Run Preview
3. Review diagnostics for invalid/conflict rows
4. Optionally export `errors.csv`
5. Confirm Commit
6. Review final batch details and row-level diagnostics in history/detail tabs

Important guarantees:

- Invalid/conflict rows are not applied during commit
- Cancelled or completed batches cannot be recommitted
- History is persistent for audit and operational traceability

## API Client Design

`frontend/src/lib/imports-api.ts` includes:

- `previewImport`
- `commitImport`
- `cancelImport`
- `listImportBatches`
- `getImportSummary`
- `getImportBatch`
- `listImportRows`
- `downloadImportErrors`

Design details:

- Uses shared `api` helper for standard authenticated calls
- Adds typed error wrapper `ImportsApiError`
- Supports client-side pagination wrappers for list endpoints
- Handles CSV download safely with blob URL creation/revocation and filename extraction

## Testing and Hardening

### Backend targeted tests

- `tests/test_phase_9d_import_preview_history.py`
- `tests/test_phase_9d_import_commit.py`

Coverage includes:

- route exposure and method constraints
- preview behavior, validation, role access
- commit transitions and row apply behavior
- cancel/list/summary/rows/errors flow
- migration head assertion

### Frontend targeted tests

- `frontend/src/app/data/data-imports.test.tsx`
- `frontend/src/components/sidebar.test.tsx`

Coverage includes:

- leadership-only page access
- preview and commit user flow
- history-to-detail inspection flow
- row diagnostic filtering
- legacy compatibility upload path
- sidebar label visibility for leadership nav

## Operational Notes

- No destructive migration changes were introduced in this final batch
- Existing backend import foundation and alembic head remain authoritative
- Legacy ingestion remains functional during leadership workspace rollout

## Change Summary

Frontend:

- Added `frontend/src/lib/imports-api.ts`
- Rebuilt `frontend/src/app/data/page.tsx` to leadership import workspace
- Added `frontend/src/app/data/data-imports.test.tsx`
- Updated `frontend/src/components/sidebar.tsx` label to Data Imports
- Updated `frontend/src/components/sidebar.test.tsx`

Documentation:

- Added `docs/phase-9d-data-imports.md`
