# Phase 10B Batch 1: Timetable Readiness Policy and Constraint Foundation

## Purpose
Phase 10B Batch 1 defines the canonical policy layer that governs timetable validity.
This batch does not generate timetable entries and does not implement the solver.

## Policy Model
New canonical entities:
- `TimetablePolicySet`
- `TimetablePolicySetVersion`
- `TimetableConstraint`
- `TimetableConstraintVersion`
- `TimetablePolicyException`

Policy sets are tenant-scoped and reference academic year, term, and optional campus scope.
They support explicit lifecycle and activation state separate from approval state.

## Constraint Model
Constraints are policy-set children with deterministic metadata:
- `constraint_type`
- `category`
- `enforcement_level`
- `scope_type`
- `scope_reference_id` / `scope_reference_code`
- `parameters_json` (variable parameters only)
- `weight`, `priority`
- `lifecycle_status`, `is_active`
- provenance and approval fields

Constraint versions are immutable records containing before/after snapshots and actor metadata.

## Exception Model
`TimetablePolicyException` supports explicit request and approval flow:
- targets either one policy set or one constraint
- stores scoped reference and reason
- supports optional start/end and expiry
- tracks approval state and actors

Exceptions are explicit records and do not silently mutate original constraints.

## Lifecycle
Policy and constraint lifecycle states:
- `draft`
- `pending_review`
- `approved`
- `active`
- `suspended`
- `retired`

Key behavior:
- Draft and pending-review records are non-operational.
- Approval does not imply activation.
- Activation is explicit and leadership-controlled.
- Active changes are versioned.
- Retirement preserves history.

Exception lifecycle states:
- `draft`
- `pending_review`
- `approved`
- `rejected`
- `revoked`

## Enforcement Levels
Controlled values:
- `hard`
- `soft`
- `preference`
- `advisory`

## Hard vs Soft Constraints
Hard constraints encode non-negotiable policy boundaries.
Soft/preference/advisory constraints encode optimization intent and tradeoffs.
This batch validates these deterministically but does not translate to solver directives yet.

## Supported Initial Constraint Types
Initial deterministic registry includes:
- `teacher_unavailable`
- `teacher_preferred_period`
- `teacher_max_daily_sessions`
- `teacher_max_consecutive_sessions`
- `teacher_min_break`
- `teacher_subject_eligibility`
- `class_unavailable`
- `class_max_daily_sessions`
- `subject_required_weekly_sessions`
- `subject_required_weekly_minutes`
- `subject_max_daily_sessions`
- `subject_spread_across_days`
- `subject_preferred_period`
- `room_required_type`
- `room_capacity`
- `room_unavailable`
- `fixed_session`
- `avoid_period`
- `preferred_period`
- `lunch_protection`
- `campus_travel_buffer`
- `balanced_teacher_load`
- `minimize_teacher_gaps`
- `minimize_room_changes`

## Validation
Deterministic validation enforces:
- tenant-scope resolution for policy scope and references
- academic year / term consistency
- effective-date range validity
- supported `constraint_type`
- category/enforcement/scope compatibility
- required parameter presence and type/range correctness
- `weight` and `priority` bounds
- duplicate active exact constraint rejection
- inactive or cross-tenant reference rejection
- exception expiry and target integrity checks

Validation errors return controlled `4xx` responses.

## Agent Boundaries
Read actions:
- `list_policy_sets`
- `get_policy_set`
- `list_constraints`
- `get_constraint`
- `get_constraint_type`
- `explain_constraint`
- `summarize_policy_effect`
- `list_pending_policy_reviews`
- `list_policy_exceptions`

Proposal actions:
- `propose_policy_set`
- `propose_constraint`
- `propose_constraint_priority`
- `propose_exception_request`
- `explain_policy_tradeoff`
- `identify_missing_constraints`

Human-authorized actions only:
- `approve_policy`
- `activate_policy`
- `suspend_policy`
- `retire_policy`
- `approve_constraint`
- `activate_constraint`
- `approve_exception`
- `revoke_exception`

## Human Approval
Approval and activation routes remain explicit leadership actions with audit events.
No agent proposal path can approve or activate policy artifacts.

## Authorization and Tenant Isolation
- Leadership dependencies enforce role checks (`principal`, `school_admin`).
- Inactive users are rejected.
- Tenant is derived from trusted resolver.
- Cross-tenant actor mismatch is rejected.
- No tenant query-parameter override is introduced.

## API Routes
Prefix:
- `/leadership/timetable-policies`

Policy sets:
- `GET /policy-sets`
- `POST /policy-sets`
- `GET /policy-sets/{policy_set_id}`
- `PATCH /policy-sets/{policy_set_id}`
- `POST /policy-sets/{policy_set_id}/submit`
- `POST /policy-sets/{policy_set_id}/approve`
- `POST /policy-sets/{policy_set_id}/activate`
- `POST /policy-sets/{policy_set_id}/suspend`
- `POST /policy-sets/{policy_set_id}/retire`
- `GET /policy-sets/{policy_set_id}/versions`

Constraints:
- `GET /policy-sets/{policy_set_id}/constraints`
- `POST /policy-sets/{policy_set_id}/constraints`
- `GET /constraints/{constraint_id}`
- `PATCH /constraints/{constraint_id}`
- `POST /constraints/{constraint_id}/submit`
- `POST /constraints/{constraint_id}/approve`
- `POST /constraints/{constraint_id}/activate`
- `POST /constraints/{constraint_id}/suspend`
- `POST /constraints/{constraint_id}/retire`
- `GET /constraints/{constraint_id}/versions`

Exceptions:
- `GET /exceptions`
- `POST /exceptions`
- `GET /exceptions/{exception_id}`
- `POST /exceptions/{exception_id}/submit`
- `POST /exceptions/{exception_id}/approve`
- `POST /exceptions/{exception_id}/reject`
- `POST /exceptions/{exception_id}/revoke`

Registry:
- `GET /constraint-types`
- `GET /constraint-types/{constraint_type}`

## Migration
Phase 10B Batch 1 migration:
- revision: `a84f2c1d9e30`
- down_revision: `f91c2d7a6b55`

Added objects:
- timetable policy sets and versions
- timetable constraints and versions
- timetable policy exceptions
- tenant/scope/lifecycle indexes and constraints

## Focused Tests
Focused tests cover:
- policy route contract
- registry type coverage and parameter checks
- lifecycle transitions and invalid transitions
- policy/constraint/exception metadata checks
- migration head and down-revision linkage
- agent boundary assertions
- authorization checks

## Deferred Work
Deferred to later batches:
- conflict diagnostics beyond exact duplicate guards
- policy management frontend workspace
- solver translation/mapping implementation
- timetable generation
- substitutions, attendance, duties
