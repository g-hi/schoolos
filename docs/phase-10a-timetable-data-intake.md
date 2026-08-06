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

## Batch 4A Unified Timetable Setup Centre
Batch 4A adds the backend-only unified setup centre used by leadership to inspect readiness and pending work across calendar, workbook, PDF, room, schedule, and requirement inputs.

Centre routes:
- GET /leadership/timetable-setup/centre/summary
- GET /leadership/timetable-setup/centre/steps
- GET /leadership/timetable-setup/centre/steps/{step_key}
- GET /leadership/timetable-setup/centre/issues
- GET /leadership/timetable-setup/centre/approvals
- GET /leadership/timetable-setup/centre/activity
- GET /leadership/timetable-setup/centre/recommendations
- POST /leadership/timetable-setup/centre/revalidate

Centre behavior:
- deterministic step registry with weighted progress and applicable/excluded step accounting
- provenance summaries for source, review, and lifecycle states
- import summaries for workbook and PDF intake status buckets
- approval queue aggregation with leadership-only human authorization cues
- issue aggregation with controlled filters and pagination
- recent activity filtering with tenant-safe audit summaries
- revalidate recomputes readiness without mutating canonical state

Agent guidance contracts for Batch 4A remain read/propose only:
- get_setup_centre_summary
- get_setup_steps
- get_setup_step_detail
- get_unified_setup_issues
- get_pending_setup_approvals
- get_recent_setup_activity
- explain_setup_progress
- explain_generation_readiness
- recommend_next_setup_action
- propose_issue_resolution_plan
- propose_setup_sequence
- summarize_pending_reviews
- summarize_import_status
- explain_readiness_blocker

Batch 4A does not introduce auto-approval, commit, publish, or timetable generation behavior.

## Batch 4B Unified Timetable Setup Centre Frontend
Batch 4B adds the leadership frontend workspace for the unified timetable setup centre.

Frontend route:
- /leadership/timetable-setup

Navigation:
- adds a leadership sidebar entry for Timetable Setup
- preserves the existing Academic Calendar entry
- remains hidden from teachers, parents, students, inactive users, and unauthorized roles through existing leadership guards

Workspace structure:
- Overview
- Setup Steps
- Issues
- Approvals
- Imports
- Activity

Overview content:
- overall setup percentage and weighted progress explanation
- generation readiness status and blocker relationship
- pending approvals and last calculation time
- recommended next actions
- provenance summary and import status summary

Step, issue, approval, import, and activity content:
- 11 deterministic setup steps are shown in backend order
- filters and pagination follow backend-supported fields only
- approval rows stay read-only and link to the controlled workflow route
- workbook and PDF import summaries distinguish validated from committed state
- recent activity remains paginated and safe

Revalidation:
- recalculate-only action
- no canonical record mutation
- no import approval, commit, publish, or timetable generation

Accessibility and responsiveness:
- tabbed workspace with labelled controls
- readable cards and stacked layouts on narrow screens
- explicit text labels for progress, blockers, and approval requirements

Frontend tests cover:
- leadership navigation visibility
- API auth header and filter encoding
- summary, tab switching, issue, approval, import, activity, and revalidation rendering

Batch 4B does not add timetable generation.

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

## Local Database Verification Limitation
- Alembic `heads` and `history` checks are mandatory in release verification.
- Online upgrade/downgrade rehearsal is optional when PostgreSQL is unavailable locally.
- A local connection refusal is an environment limitation, not by itself a migration defect.

## Deferred Work
This batch does not include:
- frontend workbook pages
- timetable generation
- attendance
- substitution
- duties
- conversational UI

## Batch 3B Leadership Calendar Workspace

### Frontend Route and Navigation
- Route: `/leadership/calendar`
- Leadership sidebar includes **Academic Calendar** navigation.
- Access remains leadership-only (`principal`, `school_admin`) with explicit guard messaging for unauthorized users.

### Workspace Sections
- Overview
- Calendar Events
- Add Event
- PDF Imports
- Review Candidates
- Notification Plans
- Change History

### Manual Event User Journey
1. Leadership opens **Add Event**.
2. Draft event fields are completed with structured scope.
3. Save draft calls `POST /leadership/timetable-setup/calendar/events`.
4. Draft stays non-published; separate lifecycle actions control submit/approve/publish.

### PDF Intake User Journey
1. Upload text-based PDF through `POST /leadership/timetable-setup/calendar/pdf-intake/upload`.
2. Review import status, extraction readiness, pages, and diagnostics.
3. Trigger extraction with `POST /.../extract`.
4. Validate candidates with `POST /.../validate`.
5. Commit approved candidates with `POST /.../commit` only when blockers are clear.

### Candidate Review User Journey
1. Review candidate proposal, source page evidence, confidence, uncertainty, warnings, and blockers.
2. Edit candidate proposal when needed.
3. Approve or reject explicitly (separate actions).
4. Commit remains separate from approve.

### Lifecycle Actions
- Supported actions: edit draft, submit, approve, publish, reschedule, cancel, restore, archive.
- UI only surfaces actions valid for current lifecycle state.
- Reschedule and cancel require reason input.

### Version History Display
- Immutable versions are shown chronologically from `/events/{event_id}/versions`.
- Displays change type, changed fields, previous/new values, reason, source type, and notification plan linkage.

### Stakeholder Impact Preview
- Uses `/events/{event_id}/impact` deterministic payload.
- Displays affected count, role/grade/class/department breakdowns, unresolved targeting issues, privacy notes, and recommended channels.

### Notification Plan Approval
- Lists and details from `/calendar/notification-plans` and `/calendar/notification-plans/{plan_id}`.
- Approval and cancellation actions call explicit endpoints.
- High-impact plans show warning that authorized human approval is required.

### Agent Suggestions and Human Boundaries
- UI labels proposals as suggestions and confidence-based interpretations.
- Source evidence, agent proposal, deterministic validation, human decision, and operational records are visibly separated.
- No automatic finalization implied by agent-generated data.

### Accessibility and Responsive Behavior
- Keyboard-accessible tabs and controls.
- Labeled form fields and alert/status messaging.
- Mobile-friendly stacked cards and action controls preserved on narrow screens.

### Frontend Tests Added
- `frontend/src/app/leadership/calendar/__tests__/calendar-page.test.tsx`
- `frontend/src/app/leadership/calendar/__tests__/manual-event-form.test.tsx`
- `frontend/src/app/leadership/calendar/__tests__/event-lifecycle.test.tsx`
- `frontend/src/app/leadership/calendar/__tests__/pdf-import.test.tsx`
- `frontend/src/app/leadership/calendar/__tests__/candidate-review.test.tsx`
- `frontend/src/app/leadership/calendar/__tests__/event-impact.test.tsx`
- `frontend/src/app/leadership/calendar/__tests__/notification-plans.test.tsx`
- `frontend/src/lib/__tests__/timetable-calendar-api.test.ts`

### Deferred in this Batch
- External email/SMS/WhatsApp/push delivery execution
- OCR for scanned PDFs
- Timetable generation
