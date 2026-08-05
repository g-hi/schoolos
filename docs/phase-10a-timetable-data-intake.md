# Phase 10A Batch 1: Timetable Data Intake Foundation

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

## Future Excel Workbook Workflow (Deferred)
Planned later:
- SchoolOS workbook templates
- flexible column mapping
- multi-sheet ingestion
- approval of imported candidates before operational use

## Future PDF Calendar Workflow (Deferred)
Planned later:
- extraction of candidate calendar entries
- mandatory leadership review and approval boundaries

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
- Revision: `9a10b1c2d3e4`
- Down revision: `c4f7a8e2d911`
- Scope: additive Phase 10A canonical intake schema

## API Routes
Prefix: `/leadership/timetable-setup`

Implemented groups:
- calendar list/create/update/approve/reject/deactivate
- school-week list/create/update
- bell schedules list/create/update/deactivate
- bell periods list/create/update/deactivate
- rooms list/create/update/deactivate
- teaching requirements list/create/update/deactivate
- readiness summary and detailed checks

No destructive DELETE routes are added.

## Focused Test Commands
Phase 10A:
- `python -m pytest -q tests/test_phase_10a_calendar_models.py tests/test_phase_10a_bell_schedules.py tests/test_phase_10a_rooms.py tests/test_phase_10a_teaching_requirements.py tests/test_phase_10a_timetable_readiness.py tests/test_phase_10a_timetable_setup_routes.py`

Relevant regressions:
- `python -m pytest -q tests/test_phase_9e_onboarding_workflow.py tests/test_phase_9e_readiness_engine.py tests/test_phase_9f_school_setup_e2e.py`

## Deferred Work
This batch does not include:
- Excel parsing
- flexible workbook mapping
- PDF extraction
- timetable generation
- attendance
- substitution
- duties
- conversational UI
