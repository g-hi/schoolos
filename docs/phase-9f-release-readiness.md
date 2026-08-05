# Phase 9F Release Readiness

## Purpose

Phase 9F validates SchoolOS school setup across Phases 9A through 9E, hardens release contracts, and adds a safe read-only smoke path for operational checks.

## Cross-Phase Architecture

Phase 9A establishes master data for campuses, years, terms, grade levels, and subjects.
Phase 9B adds canonical classes, subject offerings, teacher assignments, and student enrolments.
Phase 9C provisions people, invitations, activation, and family relationships.
Phase 9D adds CSV preview, validation, commit, history, and diagnostics.
Phase 9E adds persistent onboarding, readiness evaluation, guided setup, lifecycle actions, and history.
Phase 9F validates that the earlier phases continue to work together without changing their public contracts.

## Dependency Order

1. Campuses
2. Academic year and active term
3. Grade levels and subjects
4. Canonical classes and subject offerings
5. People provisioning
6. Teacher assignments and student enrolments
7. Family relationships
8. Timetable coverage
9. Import review and onboarding completion

## School Setup Lifecycle

1. Start onboarding.
2. Confirm blockers on an empty tenant.
3. Complete master data.
4. Complete academic structure.
5. Provision leadership, teacher, student, and parent records as needed.
6. Create canonical assignments, enrolments, and family links.
7. Add timetable coverage.
8. Recalculate readiness.
9. Resolve blockers.
10. Review warnings.
11. Complete onboarding.
12. Preserve onboarding and operational history.

## Local Validation Sequence

1. Confirm branch, clean tree, Alembic head, and SchoolOS `.venv` paths.
2. Run focused backend tests.
3. Run focused frontend tests.
4. Run `git diff --check`.
5. Reconfirm Alembic head and working tree state.

## Migration Expectations

No new migration is expected for Batch 1 unless a proven schema defect blocks release readiness. Historical migrations must remain unchanged.

## Frontend Build Expectations

Leadership routes for School Setup, Academic Structure, People, Data Imports, and Timetable must remain generated and TypeScript-clean. No sensitive fallback data should be introduced.

## Smoke Script Usage

Run from the repository root with the SchoolOS virtual environment.

```powershell
Set-Location C:\Users\Gampi\Downloads\schoolos
.\.venv\Scripts\python.exe scripts\phase_9f_smoke.py
```

For authenticated checks:

```powershell
$env:SCHOOLOS_SMOKE_BASE_URL = "http://127.0.0.1:8000"
$env:SCHOOLOS_SMOKE_BEARER_TOKEN = "<token>"
$env:SCHOOLOS_SMOKE_TENANT_SLUG = "greenwood"
.\.venv\Scripts\python.exe scripts\phase_9f_smoke.py
```

## Smoke Script Environment Variables

- `SCHOOLOS_SMOKE_BASE_URL`: optional, defaults to local gateway URL.
- `SCHOOLOS_SMOKE_BEARER_TOKEN`: optional, enables authenticated checks.
- `SCHOOLOS_SMOKE_TENANT_SLUG`: optional, required with bearer token.
- `SCHOOLOS_SMOKE_TIMEOUT_SEC`: optional request timeout override.

## Render Deployment Assumptions

- Backend exposes `/health`.
- Backend serves OpenAPI in non-restricted environments.
- Frontend points to the deployed gateway through `NEXT_PUBLIC_API_URL`.
- Deploy command continues to run Alembic before the application starts.

## Health Check Procedure

1. Call `/health`.
2. Confirm status is successful.
3. Optionally inspect `/openapi.json` route inventory.

## Authenticated Smoke Procedure

1. Provide a short-lived bearer token.
2. Provide the tenant slug.
3. Run the smoke script.
4. Review onboarding, imports, academic structure, people, and family summaries.

## Tenant Isolation Verification

- Readiness and onboarding history must remain tenant scoped.
- Cross-tenant leadership access must be rejected.
- Imports, people, classes, enrolments, and audit history must not bleed across tenants.

## Security Checks

- Never print or commit bearer tokens.
- Never print database URLs or credentials.
- Do not run mutation methods in smoke checks.
- Preserve public invitation acceptance only at its existing contract.

## Rollback Strategy

1. Identify the previous backend deploy.
2. Identify the previous frontend deploy.
3. Roll application versions back first.
4. Roll schema back only if the migration path is already documented and non-destructive.
5. Do not attempt automated destructive data rollback.

## Failure Triage

- `health` failure: verify gateway process, environment variables, and database reachability.
- OpenAPI failure: confirm deployment mode and FastAPI configuration.
- Leadership route failure: verify token role, tenant header, and user active state.
- Readiness blocker mismatch: inspect canonical class, enrolment, family, and timetable coverage.
- Import warning spike: review preview-ready and failed import batches.

## Known Non-Blocking Warnings

- Failed import batches remain warning-level.
- Preview-ready imports remain informational.
- Missing family coverage is warning-level when used for staged onboarding review.
- Historical inactive family relationships remain informational.

## Production Verification Checklist

1. Confirm backend `/health`.
2. Confirm frontend loads leadership routes.
3. Confirm leadership login works.
4. Confirm onboarding status loads.
5. Confirm readiness counts are tenant-scoped.
6. Confirm import history loads.
7. Confirm no browser console errors.
8. Confirm no secrets are exposed in logs.