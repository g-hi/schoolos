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

## Phase 10B Batch 2
Batch 2 adds derived-only diagnostics for conflicts, feasibility, impact analysis, and resolution guidance.
The diagnostics layer is read-only and does not introduce a new migration.

New read routes:
- `/leadership/timetable-policies/diagnostics`
- `/leadership/timetable-policies/diagnostics/conflicts`
- `/leadership/timetable-policies/diagnostics/feasibility`
- `/leadership/timetable-policies/diagnostics/impact`
- `/leadership/timetable-policies/diagnostics/resolution-guidance`

Diagnostics are deterministic and use existing policy sets, constraints, exceptions, weekly requirements, rooms, school weeks, and bell schedule periods.
The setup centre now surfaces additive `policy_diagnostics` data and combines Phase 10A readiness with policy lifecycle readiness and policy diagnostics readiness.

## Phase 10B Batch 3
Batch 3 adds the deterministic policy readiness engine and the scheduling authorization gate.
It remains derived-only, read-only, and migration-free.

### Readiness Dimensions
The readiness engine evaluates these dimensions before scheduling can proceed:
- canonical Phase 10A input readiness
- effective policy-set selection and lifecycle readiness
- effective constraint coverage and precedence resolution
- diagnostic feasibility readiness
- approval queue readiness
- exception validity readiness
- coverage score and explanation

### Policy Precedence
Policy selection is deterministic and tenant-scoped.
Selection prefers:
- an active, applicable policy over draft, pending, suspended, retired, or expired records
- the most specific scope over a broader scope when both are applicable
- the higher version number when scope specificity is equal

Equal-priority contradictions do not silently resolve; they block readiness and are surfaced as blockers.

### Effective Constraints
The readiness engine computes the effective constraint set for the selected policy only.
It resolves active constraints deterministically and excludes draft and pending rows.
Approved exceptions only apply to explicit targets and are ignored when pending, expired, revoked, or duplicate.

### Coverage and Score
Coverage reports mandatory, optional, and not-applicable checks with a weight-based score breakdown.
Not-applicable dimensions are excluded from the denominator.
The score is explanatory, deterministic, and never overrides a blocker.

### Approval and Exception Readiness
The engine reports pending policy approvals, approved-but-inactive policies, pending constraint approvals, pending exception approvals, expired exceptions, conflicting exceptions, and resolved items.
The queues are read-only and exist only to explain what still needs leadership action.

### Generation Authorization
Generation authorization is the logical AND of:
- canonical input readiness
- policy lifecycle readiness
- policy coverage readiness
- diagnostic feasibility readiness
- exception readiness
- approval readiness

Any blocker in one dimension keeps `generation_allowed` false.

### Revalidation
`POST /leadership/timetable-setup/centre/revalidate` recomputes the derived setup-centre payload only.
It does not approve, activate, mutate, or generate timetable data.

### API Routes
Readiness routes under `/leadership/timetable-policies`:
- `GET /readiness`
- `GET /readiness/effective-policy`
- `GET /readiness/effective-constraints`
- `GET /readiness/authorization`

The existing setup-centre route also exposes the additive `policy_readiness` payload alongside Phase 10A fields and Batch 2 diagnostics.

### Agent Boundaries
Safe read actions only:
- inspect policy readiness
- inspect effective policy
- inspect effective constraints
- inspect scheduling authorization

The readiness surface does not authorize approval, activation, or timetable generation.

### Tenant Isolation
Every readiness and route evaluation remains tenant-scoped.
Cross-tenant actors are rejected, and cross-tenant policy, constraint, or exception rows are ignored.
There is no tenant query-parameter override.

### No Migration
Batch 3 does not add a migration.
Alembic head remains `a84f2c1d9e30`.

### Deferred Work
Deferred to later batches:
- timetable generation
- solver translation
- any frontend policy work
- any persistent readiness cache or approval automation
