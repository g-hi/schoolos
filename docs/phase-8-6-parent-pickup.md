# Phase 8.6 Parent Pickup

## Purpose
Phase 8.6 delivers a secure, authenticated, tenant-scoped student pickup workflow across parent, teacher, and leadership roles.

## Scope
Included:
- Parent pickup request creation, tracking, history, and cancellation
- Teacher queue actions (acknowledge, call, prepare)
- Leadership queue actions (acknowledge, call, prepare, complete, cancel)
- Completion verification requirements
- Audit logging, parent notifications, and family timeline writes

Excluded future scope:
- Camera recognition
- Automatic student release
- GPS tracking
- Bus tracking
- Visitor management
- Biometric verification

## Architecture Overview
- API gateway routes pickup endpoints via `services/gateway/routers/pickup.py`.
- Identity is resolved from authenticated dependencies:
  - Parent: `resolve_authenticated_parent`
  - Teacher: `resolve_authenticated_teacher` plus teacher profile linkage
  - Leadership: `resolve_authenticated_leadership`
- Tenant isolation is enforced by tenant dependency resolution and tenant-scoped queries.
- Frontend routes call role-specific APIs using bearer token from AuthContext.

## Database Migration Revision
- Revision: `e1f4a2c9d113`
- File: `alembic/versions/e1f4a2c9d113_phase_86a_pickup_secure_lifecycle.py`
- Down revision: `c85b_announcements`

## PickupRequest Fields Added
- `acknowledged_at`
- `called_at`
- `prepared_at`
- `completed_at`
- `cancelled_at`
- `cancelled_by` (FK -> users.id)
- `verified_by` (FK -> users.id)
- `verified_at`
- `verification_method`
- `verification_note`

## Lifecycle State Machine
States:
- `requested`
- `acknowledged`
- `called`
- `prepared`
- `completed`
- `cancelled`
- Legacy readable statuses: `released`, `rejected_outside_geofence`

Valid transitions:
- `requested -> acknowledged`
- `requested -> cancelled`
- `acknowledged -> called`
- `acknowledged -> cancelled`
- `called -> prepared`
- `called -> cancelled`
- `prepared -> completed`
- `prepared -> cancelled`

Terminal statuses:
- `completed`
- `cancelled`
- `released` (legacy)
- `rejected_outside_geofence` (legacy)

Rules:
- Skipped transitions return `409 Conflict`.
- Terminal statuses are read-only.
- Repeating the same transition on the same state is idempotent.

## Authenticated Role Matrix
Parent:
- `POST /parent/pickup-requests`
- `GET /parent/pickup-requests`
- `GET /parent/pickup-requests/{pickup_id}`
- `POST /parent/pickup-requests/{pickup_id}/cancel`
- `GET /parent/students`

Teacher:
- `GET /teacher/pickup-requests`
- `GET /teacher/pickup-requests/{pickup_id}`
- `POST /teacher/pickup-requests/{pickup_id}/acknowledge`
- `POST /teacher/pickup-requests/{pickup_id}/call`
- `POST /teacher/pickup-requests/{pickup_id}/prepare`

Leadership:
- `GET /leadership/pickup-requests`
- `GET /leadership/pickup-requests/{pickup_id}`
- `POST /leadership/pickup-requests/{pickup_id}/acknowledge`
- `POST /leadership/pickup-requests/{pickup_id}/call`
- `POST /leadership/pickup-requests/{pickup_id}/prepare`
- `POST /leadership/pickup-requests/{pickup_id}/complete`
- `POST /leadership/pickup-requests/{pickup_id}/cancel`

## Parent Workflow
1. Parent selects an eligible linked student (`can_pickup=true`).
2. Parent submits pickup request.
3. Parent tracks active request status updates.
4. Parent can cancel only in active states.
5. Completed/cancelled/legacy statuses are visible in history.

## Teacher Workflow
1. Teacher sees scoped queue for authorized class/student relationships.
2. Teacher processes: requested -> acknowledge -> call -> prepare.
3. Teacher cannot complete or verify.

## Leadership Workflow
1. Leadership sees tenant-wide queue.
2. Leadership can acknowledge, call, prepare, complete, and cancel.
3. Completion requires mandatory verification fields.

## Mandatory Completion Verification
`POST /leadership/pickup-requests/{pickup_id}/complete` requires:
- `verification_method` (non-empty)
- `verification_note` (non-empty)

On completion, backend records:
- `verified_by`
- `verified_at`
- `completed_at`

## Tenant Isolation
- Every pickup query and transition is scoped by tenant ID.
- Cross-tenant actor access is rejected.

## Teacher Class Restrictions
- Teacher must have a valid teacher profile in tenant.
- Teacher actions require class or assigned pickup access for the request.

## can_pickup Enforcement
- Parent must have `StudentParent.can_pickup=true` for target student.
- If false, creation returns `403 Forbidden`.

## Audit Events
Pickup lifecycle emits audit actions, including:
- `pickup.requested`
- `pickup.acknowledged`
- `pickup.called`
- `pickup.prepared`
- `pickup.completed`
- `pickup.cancelled`

## Notifications
Parent notifications are triggered for staff transitions:
- Acknowledge
- Call
- Prepare
- Complete
- Cancel

## Family Timeline Integration
Pickup lifecycle writes timeline events when an active family linkage exists.

## Legacy Endpoint Deprecation Behavior
Legacy endpoints are retained as explicit deprecations and return `410 Gone`:
- `POST /pickup/request`
- `POST /pickup/release`
- `GET /pickup/log`

## API Endpoint Table
| Role | Method | Path | Notes |
| --- | --- | --- | --- |
| Parent | POST | /parent/pickup-requests | Create request |
| Parent | GET | /parent/pickup-requests | List with optional status/page/page_size |
| Parent | GET | /parent/pickup-requests/{pickup_id} | Get single request |
| Parent | POST | /parent/pickup-requests/{pickup_id}/cancel | Cancel active request |
| Parent | GET | /parent/students | Eligible-linked-student source |
| Teacher | GET | /teacher/pickup-requests | Scoped queue |
| Teacher | GET | /teacher/pickup-requests/{pickup_id} | Scoped detail |
| Teacher | POST | /teacher/pickup-requests/{pickup_id}/acknowledge | Transition |
| Teacher | POST | /teacher/pickup-requests/{pickup_id}/call | Transition |
| Teacher | POST | /teacher/pickup-requests/{pickup_id}/prepare | Transition |
| Leadership | GET | /leadership/pickup-requests | Tenant-wide queue |
| Leadership | GET | /leadership/pickup-requests/{pickup_id} | Tenant-wide detail |
| Leadership | POST | /leadership/pickup-requests/{pickup_id}/acknowledge | Transition |
| Leadership | POST | /leadership/pickup-requests/{pickup_id}/call | Transition |
| Leadership | POST | /leadership/pickup-requests/{pickup_id}/prepare | Transition |
| Leadership | POST | /leadership/pickup-requests/{pickup_id}/complete | Requires verification fields |
| Leadership | POST | /leadership/pickup-requests/{pickup_id}/cancel | Transition |

## Frontend Routes
- Parent: `/parent/pickup`
- Teacher: `/teacher/student-pickup`
- Leadership: `/pickup`

## Empty and Controlled Error States
Parent:
- No active requests
- No history
- No eligible linked students
- Session-expired and controlled API error messages

Teacher:
- Missing profile/access controlled state (`403`)
- Empty active queue

Leadership:
- Empty tenant queue
- Terminal requests shown as read-only

## Phase 8.5D Provisioning Dependency
Live end-to-end demonstration requires:
- Parent user with active family/student linkage and `StudentParent.can_pickup=true`
- Teacher user with valid teacher profile and authorized class/student relationship

Current controlled production messages on parent and teacher pickup pages are expected when these relationships are missing and do not indicate a pickup workflow defect.

## Automated Test Coverage
Primary backend pickup suite:
- `tests/test_phase_86a_pickup.py`

Coverage includes:
- Lifecycle and transition controls
- Completion verification fields
- Tenant/class authorization boundaries
- Idempotency and terminal protections
- Legacy status readability
- Audit/notification/timeline side effects

Frontend pickup tests:
- `frontend/src/app/parent/pickup/page.test.tsx`
- `frontend/src/app/teacher/student-pickup/page.test.tsx`
- `frontend/src/app/pickup/page.test.tsx`
- `frontend/src/components/sidebar.test.tsx` (pickup navigation entries)

## Local Validation Commands
Backend:
- `./.venv/Scripts/python.exe -m pytest -q tests/test_phase_86a_pickup.py`
- `./.venv/Scripts/python.exe -m pytest -q`

Frontend:
- `Set-Location frontend`
- `npm run test`
- `npm run build`
- `Set-Location ..`

Repository checks:
- `git diff --check`
- `./.venv/Scripts/alembic.exe heads`
- `git status --short`
- `git diff --stat`

## Render Deployment Readiness Checklist
- Pickup router is registered in gateway app startup (`services/gateway/main.py`).
- Render service uses repository `master` branch via Docker runtime (`render.yaml`).
- Container startup applies `alembic upgrade head` before `uvicorn` (`Dockerfile`).
- Required production env vars are present (`DATABASE_URL`, `APP_ENV`, `SECRET_KEY`, and communication keys as applicable).
- Deployment should proceed only after validation suites pass.

## Migration Deployment Order
1. Deploy code containing revision `e1f4a2c9d113`.
2. Run migration to head in deployment startup.
3. Start API process only after migration succeeds.
4. Serve frontend with matching API contract.

## Rollback Procedure
1. Stop rollout to prevent mixed-version writes.
2. Revert application to previous known-good release.
3. Keep schema at current head unless a separately approved migration rollback plan is executed.
4. Re-run validation tests against reverted application code.

## Known Non-Blocking Warnings
- Controlled parent no-eligible-linked-students state can occur when linkage or pickup permission is absent.
- Controlled teacher access/profile state can occur when teacher profile or class linkage is absent.
- Empty leadership queue is valid when no active requests exist.
