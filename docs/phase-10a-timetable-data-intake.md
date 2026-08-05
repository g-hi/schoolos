# Phase 10A Batches 1-3A: Timetable Data Intake, Workbook Imports, and Calendar Lifecycle

## AI-Native Policy Alignment
SchoolOS remains an AI-native operating system with explicit human oversight.
This batch enforces:
- visibility and explainability of setup state
- tenant isolation and role-scoped control
- deterministic validation and policy checks
- auditable state transitions
- no silent operational activation from extracted or agent-proposed data

## Purpose
Phase 10A Batch 1 introduces canonical timetable-input records for manual leadership configuration.
It prepares trusted operational inputs for later import, extraction, and generation phases.

## Reuse of Phase 9 Foundations
This batch reuses existing canonical foundations from Phase 9:
- campuses, academic years, terms, grade levels
- canonical classes and subject catalog
- teacher identities and assignment context
- onboarding/readiness and audit conventions

Legacy `Period` and `TimetableEntry` remain intact for existing timetable workflows.
New Phase 10A entities are additive and serve canonical intake readiness.

## Canonical Timetable-Input Architecture
New canonical entities:
- `OperationalCalendarEvent`
- `SchoolWeekConfig`
- `BellSchedule`
- `BellSchedulePeriod`
- `TeachingRoom`
- `WeeklyTeachingRequirement`

All are tenant-scoped and non-destructive (deactivation over deletion).

## Manual Setup Workflow
1. Configure school-week operational weekdays.
2. Configure one or more bell schedules and periods.
3. Configure teaching rooms and specialist capabilities.
4. Enter class-subject weekly teaching requirements.
5. Add operational calendar events.
6. Review readiness blockers/warnings/information.

## Official Workbook Template
Leadership can download the official workbook template:
- GET /leadership/timetable-setup/imports/template

Template sheets:
- Instructions
- Teachers
- Classes
- Subjects
- Rooms
- School Week
- Periods
- Teaching Requirements
- Teacher Availability
- Fixed Sessions
- Constraints

Instructions explicitly describe required/optional sheets, accepted formats,
cross-sheet references, and that upload is preview-only until explicit commit.

## Workbook Upload Safety Controls
Workbook upload route:
- POST /leadership/timetable-setup/imports/workbooks

Supported type:
- .xlsx only

Rejected:
- .xls
- .xlsm
- malformed ZIP/XLSX
- macro-enabled workbooks (vbaProject.bin)
- external workbook links
- empty uploads
- oversized files
- excessive sheets/rows/columns

Workbook content is parsed read-only with formula values only.
No workbook bytes are persisted indefinitely.

## Workbook Lifecycle
Workbook batches reuse Phase 9D import history structures (`ImportBatch`, `ImportRowResult`) with Batch 2 extensions.

Lifecycle statuses:
- uploaded
- parsing
- mapping_required
- preview_ready
- validation_failed
- validated
- committed
- failed
- cancelled

Commit is blocked unless mapping is resolved, validation passes, and actor/tenant constraints are satisfied.

## Detection, Mapping, Preview
Additional routes:
- GET /leadership/timetable-setup/imports/workbooks
- GET /leadership/timetable-setup/imports/workbooks/{batch_id}
- GET /leadership/timetable-setup/imports/workbooks/{batch_id}/sheets
- GET /leadership/timetable-setup/imports/workbooks/{batch_id}/preview
- PATCH /leadership/timetable-setup/imports/workbooks/{batch_id}/mappings

Behavior:
- deterministic sheet detection from canonical names/aliases/header similarity
- explainable column mapping proposals with confidence and reasons
- required field mapping blockers
- paginated row previews and diagnostics
- explicit admin confirmation/overrides for uncertain mappings

## Deterministic Validation
Validation route:
- POST /leadership/timetable-setup/imports/workbooks/{batch_id}/validate

Diagnostics route:
- GET /leadership/timetable-setup/imports/workbooks/{batch_id}/diagnostics

Diagnostics are categorized as:
- blocker
- warning
- information

Validation checks include required-sheet presence, required mapping completeness,
duplicate identifiers, time validity, period overlap, and reference integrity.

## Controlled Commit
Commit and cancel routes:
- POST /leadership/timetable-setup/imports/workbooks/{batch_id}/commit
- POST /leadership/timetable-setup/imports/workbooks/{batch_id}/cancel

Commit controls:
- tenant scoped
- leadership-only
- transactional
- idempotent (duplicate commit blocked)
- audited
- readiness recomputation after successful commit

Commit summary returns create/update/unchanged/skipped/rejected counts.
Committed Phase 10A records use provenance `source_type=excel_import`.

## Agent-Compatible Boundaries
Safe proposal/inspection contracts now include:
- inspect_workbook
- propose_sheet_mappings
- propose_column_mappings
- explain_workbook_diagnostics
- validate_workbook
- summarize_commit_plan

These remain separate from human-controlled mapping confirmation and commit execution.

## Future PDF Calendar Workflow (Deferred)
Planned later:
- extraction of candidate calendar entries
- mandatory leadership review and approval boundaries

## Batch 3A Calendar Lifecycle and PDF Intake
Batch 3A introduces backend-only support for:
- safe PDF intake for calendar extraction
- deterministic candidate extraction (no OCR)
- manual apply/reject controls for extracted candidates
- versioned calendar updates with supersession history
- stakeholder impact capture and notification planning

New backend entities:
- `CalendarSourceDocument`
- `CalendarSourcePage`
- `CalendarEventCandidate`

`OperationalCalendarEvent` lifecycle additions:
- `lifecycle_status` (`draft`, `pending_review`, `approved`, `published`, `superseded`, `archived`, `rejected`)
- `version_number` and `previous_version_event_id`
- `change_reason` and `impact_scope_json`
- `notification_plan_status` and `notification_plan_json`
- `published_at` and `published_by_user_id`

Import reuse:
- `ImportBatch` and `ImportRowResult` now also support `calendar_pdf` batches with `import_format=pdf`.

## Provenance and Review States
Supported provenance (`source_type`):
- manual
- excel_import
- csv_import
- pdf_extraction
- agent_recommendation
- system_generated

Review lifecycle (`review_status`):
- pending_review
- approved
- rejected

Manual leadership-created records can be approved immediately, but all state transitions are audited.

## Approval Boundaries
- Pending candidate data is non-operational.
- Approval is explicit leadership action.
- Agent proposal contracts create only pending-review candidates.
- No automatic approval path is introduced.

## Readiness Categories
Deterministic readiness checks classify outcomes as:
- blocker
- warning
- information

Output includes check key, title, severity, status, explanation, affected counts, route guidance, and timestamp.

## Tenant and Role Controls
- Tenant is resolved from trusted tenant dependency.
- Leadership APIs require `principal` or `school_admin`.
- Inactive actors are rejected.
- Cross-tenant actor mismatch is rejected.

## Agent-Compatible Action Boundaries
Service-layer contracts exist for future safe invocation:
- `propose_calendar_entry`
- `propose_bell_schedule`
- `propose_room_mapping`
- `propose_teaching_requirement`
- `run_timetable_readiness`

These are explicitly separate from leadership approval actions.

## Audit Behavior
All important create/update/approve/reject/deactivate transitions emit audit actions via shared audit helper.

## Migration
- Batch 1 revision: `9a10b1c2d3e4`
- Batch 2 revision: `d2f6e7a9b4c1`
- Batch 2 down revision: `9a10b1c2d3e4`
- Scope: extends shared import history structures for workbook metadata and diagnostics

## API Routes
Prefix: `/leadership/timetable-setup`

Implemented groups:
- calendar list/create/update/approve/reject/deactivate
- calendar PDF intake upload/detail
- calendar candidate apply/reject
- calendar version creation and publish
- calendar notification plan drafting
- school-week list/create/update
- bell schedules list/create/update/deactivate
- bell periods list/create/update/deactivate
- rooms list/create/update/deactivate
- teaching requirements list/create/update/deactivate
- readiness summary and detailed checks

Workbook import prefix:
- `/leadership/timetable-setup/imports/...`
- template download, upload, list/detail, sheets/preview, mapping patch,
  validate, commit, cancel, diagnostics

Calendar intake/lifecycle prefix additions:
- `/leadership/timetable-setup/calendar/pdf-intake/upload`
- `/leadership/timetable-setup/calendar/pdf-intake/imports`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/pages`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/extract`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/candidates`
- `/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}`
- `/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}/approve`
- `/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}/reject`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/validate`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/commit`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/cancel`
- `/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/diagnostics`
- `/leadership/timetable-setup/calendar/events`
- `/leadership/timetable-setup/calendar/events/{event_id}`
- `/leadership/timetable-setup/calendar/events/{event_id}/submit`
- `/leadership/timetable-setup/calendar/events/{event_id}/approve`
- `/leadership/timetable-setup/calendar/events/{event_id}/publish`
- `/leadership/timetable-setup/calendar/events/{event_id}/reschedule`
- `/leadership/timetable-setup/calendar/events/{event_id}/cancel`
- `/leadership/timetable-setup/calendar/events/{event_id}/restore`
- `/leadership/timetable-setup/calendar/events/{event_id}/archive`
- `/leadership/timetable-setup/calendar/events/{event_id}/versions`
- `/leadership/timetable-setup/calendar/events/{event_id}/impact`
- `/leadership/timetable-setup/calendar/events/{event_id}/notification-plan`
- `/leadership/timetable-setup/calendar/notification-plans`
- `/leadership/timetable-setup/calendar/notification-plans/{plan_id}`
- `/leadership/timetable-setup/calendar/notification-plans/{plan_id}/approve`
- `/leadership/timetable-setup/calendar/notification-plans/{plan_id}/cancel`

No destructive DELETE routes are added.

## Focused Test Commands
Batch 2 workbook tests:
- `python -m pytest -q tests/test_phase_10a_excel_template.py tests/test_phase_10a_excel_upload.py tests/test_phase_10a_excel_mapping.py tests/test_phase_10a_excel_validation.py tests/test_phase_10a_excel_commit.py tests/test_phase_10a_excel_routes.py`

Batch 1 regressions:
- `python -m pytest -q tests/test_phase_10a_calendar_models.py tests/test_phase_10a_bell_schedules.py tests/test_phase_10a_rooms.py tests/test_phase_10a_teaching_requirements.py tests/test_phase_10a_timetable_readiness.py tests/test_phase_10a_timetable_setup_routes.py tests/test_phase_10a_migration.py`

Relevant regressions:
- `python -m pytest -q tests/test_phase_9d_import_preview_history.py tests/test_phase_9d_import_commit.py`

## Deferred Work
This batch does not include:
- frontend workbook pages
- timetable generation
- attendance
- substitution
- duties
- conversational UI
