# Phase 9E School Onboarding

## Purpose
Phase 9E introduces a leadership-only onboarding workflow that tracks school setup readiness across existing workspaces. It does not create, repair, or mutate operational data automatically.

## Data Model

### SchoolOnboardingRun
Persistent run-level lifecycle record per tenant:
- id
- tenant_id
- status (in_progress, paused, ready, completed, cancelled)
- current_step_key
- started_by_user_id
- completed_by_user_id
- started_at
- completed_at
- paused_at
- created_at
- updated_at

Constraints:
- Valid run statuses only.
- Completed runs require completed_at and completed_by_user_id.
- completed_at must be >= started_at.
- PostgreSQL partial unique index enforces one active non-terminal run per tenant.

### SchoolOnboardingStep
Persistent per-step status per run:
- id
- tenant_id
- onboarding_run_id
- step_key
- status (not_started, in_progress, blocked, completed, skipped)
- completion_source (computed, manual, imported)
- acknowledged_by_user_id
- acknowledged_at
- blocked_reason
- metadata_json
- created_at
- updated_at

Constraints:
- Valid step status values.
- Valid completion_source values.
- Unique run + step key.
- Manual completion and skipped states require acknowledgement actor/time.

## Fixed Step Catalogue
1. campus
2. academic_year
3. terms
4. grade_levels
5. subjects
6. classes
7. subject_offerings
8. people
9. family_relationships
10. teacher_assignments
11. student_enrolments
12. timetable
13. data_imports
14. readiness_review

Arbitrary client step keys are rejected server-side.

## Readiness Engine
Readiness is computed from live tenant-scoped operational data and returns grouped checks, step statuses, counts, percentage, and recommended actions.

Check severity meanings:
- complete: requirement satisfied
- blocking: completion is disallowed
- warning: non-blocking issue to resolve
- informational: advisory signal

## Persistent vs Computed State
- Persistent: run and step lifecycle records, acknowledgements, skip reasons, history.
- Computed: live readiness checks, blocker/warning counts, readiness percentage, recommended actions.

Frontend and clients must treat backend responses as authoritative.

## Lifecycle
Leadership controls run lifecycle through explicit actions:
- start
- current-step update
- acknowledge
- skip (optional step policy)
- pause
- resume
- complete
- cancel

Behavior:
- Completion is blocked while blockers remain.
- Warnings may remain at completion.
- Completed/cancelled runs are immutable.
- Cancellation preserves run and step history.

## Acknowledgement Policy
- Allowed only where backend permits.
- Requires explicit user intent.
- Never overrides computed blockers.
- Records actor and timestamp.

## Skip Policy
- Allowed only for explicitly optional steps.
- Current optional case: data_imports.
- Requires explicit non-empty reason.
- Skips are historical and auditable.

## Security and Access Controls
- Tenant-scoped on all onboarding reads/writes.
- Leadership-only roles: principal, school_admin.
- Actor must be active.
- Actor tenant must match resolved tenant.
- Step and run operations are tenant-isolated.

## Audit Events
Lifecycle writes are audited:
- onboarding.started
- onboarding.current_step.changed
- onboarding.step.acknowledged
- onboarding.step.skipped
- onboarding.paused
- onboarding.resumed
- onboarding.completed
- onboarding.cancelled

Audit payloads exclude secrets, raw credentials, invitation material, and CSV content.

## Migration
- Revision: c4f7a8e2d911
- Down revision: b3c7d9e4f512
- Additive schema change only
- Downgrade drops steps before runs

## Relationship to Phase 9A–9D
Phase 9E overlays guidance and readiness over existing setup workspaces from earlier phases:
- Academic Structure
- People & Families
- Data Imports
- Timetable

It does not duplicate those forms or APIs.

## Operational Workflow
1. Start onboarding.
2. Review blockers and warnings.
3. Open linked setup workspace.
4. Complete operational setup.
5. Return to onboarding.
6. Review recalculated readiness.
7. Acknowledge or skip only permitted optional items.
8. Resolve blockers.
9. Complete onboarding.
10. Retain history for audit.

## Security Boundaries
- No automatic operational record creation.
- No automatic blocker repair.
- No automatic skip.
- No automatic completion.
- No frontend authority to mutate status outside explicit API actions.

## Known Limitations
- History currently stores actor identifiers, not enriched profile names.
- Recommended actions are route-safe pointers, not auto-remediation.
- Readiness check details are bounded to exposed tenant-safe diagnostics.

## Future Dependencies
- Optional actor-display enrichment endpoint for history.
- Cross-module deep links with contextual prefilters.
- Expanded readiness checks for additional domain modules.
