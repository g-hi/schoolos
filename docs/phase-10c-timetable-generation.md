# Phase 10C Batch 1: Scheduling Domain, Flexibility, and Generation Controls Foundation

## Purpose
Phase 10C Batch 1 defines the canonical scheduling-control domain that future deterministic timetable generation will consume.
This batch does not run a solver, does not generate timetable sessions, does not generate candidates, and does not publish a timetable.

## Roadmap Context
Phase 10C progression:
1. Batch 1 (this batch): generation controls domain and APIs
2. Batch 2 (deferred): scheduling problem builder
3. Batch 3 (deferred): CP-SAT solver integration
4. Later batches (deferred): candidate review/versioning/publishing and frontend workflows

## Generation Modes
`TimetableGenerationConfiguration` supports controlled modes:
- `standard`: approved setup and policy defaults
- `customized`: approved setup/policy plus principal-defined generation controls
- `repair`: baseline-aware regeneration with disruption-aware controls

Validation contract:
- `repair` requires baseline reference
- `standard` and `customized` do not require baseline
- unsupported mode values are rejected

## Lifecycle
Generation configuration lifecycle:
- `draft`
- `ready_for_review`
- `approved`
- `superseded`
- `cancelled`

Operational rules:
- only `draft` is freely editable
- submit requires deterministic validation
- approval is explicit human leadership action
- approval does not run solver
- approval does not create timetable sessions
- approval does not publish timetable

## Principal-Only Teacher Preferences
`TimetableTeacherSchedulingPreference` stores leadership-entered scheduling preferences.
Teachers do not submit timetable preferences through SchoolOS in this phase.
Leadership configures approved preferences after handling teacher requests outside the scheduling workflow.

Supported preference types include:
- avoid first/last period
- avoid or prefer selected periods
- unavailable selected periods
- grouped free periods preference
- avoid or prefer selected days
- temporary accommodation

Strengths are controlled and solver-agnostic:
- `hard`
- `strong`
- `normal`
- `low`

No raw solver weights are exposed in leadership APIs.

## Generation Overrides
`TimetableGenerationOverride` stores generation-specific temporary instructions.
Overrides:
- belong to exactly one generation configuration
- can be hard or preference-like via strength
- are scoped explicitly
- are not promoted silently to permanent policy

## Locking Model
`TimetableGenerationLock` supports repair/regeneration protection states:
- `locked`
- `prefer_to_keep`
- `flexible`

Lock targets support:
- session reference
- teacher
- class
- subject
- grade
- room
- day
- period
- period range

Manual hard locks are explicitly distinguishable from proposed/system protection using `is_manual_hard_lock` and provenance.
Department-level locking is deferred until a canonical tenant-scoped department entity is introduced for timetable domain references.

## Impact-Aware Repair Contract
Repair controls are represented in generation configuration repair scope metadata and validated against controlled values.
Controlled repair reasons include:
- teacher departure/replacement/assignment or availability change
- class added/removed/requirement change
- room unavailable/change
- policy change
- bell structure change
- manual adjustment
- other controlled reason

Scope levels currently supported:
- `minimum`
- `affected_entities`
- `grade`
- `whole_school`

`department` scope expansion remains deferred until a canonical department entity is consistently available.

## Stability and Change Budget
Stability is user-facing and controlled:
- `very_high`
- `high`
- `balanced`
- `flexible`

These values are deterministic inputs for future objective mapping; no CP-SAT coefficients are exposed here.

## Bell Schedule Independence
Generation configurations reference canonical bell schedules (`BellSchedule`) rather than embedding clock-time assignments.
Architectural contract:
- timetable assignment is logical day + logical period
- bell schedule maps period -> clock times

Changing clock times while retaining the same logical periods does not require timetable regeneration.
Changing logical period structure may require future impact analysis and repair.

No duplicate bell model is introduced in Phase 10C.

## One Canonical Timetable, Multiple Derived Views
Phase 10C preserves one authoritative timetable concept.
No separate authoritative teacher-table or class-table timetable persistence is introduced.
Future views remain derived from canonical assignments.

## Parallel Lesson Blocks
Parallel lesson structures are represented by:
- `TimetableParallelLessonBlock`
- `TimetableParallelLessonChild`

Supported block types:
- `foreign_language`
- `electives`
- `split_class`
- `other_parallel`

Parallel lesson blocks do not require student membership in Phase 10C.

Example support:
- Grade 8A Foreign Language block with French/German/Spanish children at the same logical period
- class-facing label remains one class block
- teacher-facing assignment is per child component

Phase 10C does not implement student-level scheduling.

## Generation Objectives
Controlled objective keys:
- satisfy hard constraints
- teacher preferences
- workload balance
- subject distribution
- minimize teacher gaps
- minimize room changes
- minimize timetable disruption
- preference fairness
- preserve existing assignments

Controlled leadership priorities:
- `critical`
- `high`
- `normal`
- `low`

## Deterministic Validation and Readiness Integration
Generation validation is deterministic and checks:
- tenant ownership
- academic year/term/campus scope consistency
- generation mode and baseline requirement
- bell schedule context compatibility
- preference strength/type constraints
- lock/override/parallel reference scope validity
- effective-date correctness

Phase 10C validation integrates with Phase 10B policy readiness.
Future generation eligibility requires:
- Phase 10B scheduling authorization gate readiness
- Phase 10C generation configuration validation

This batch still does not execute generation.

## API Surface
Leadership routes use prefix:
- `/leadership/timetable-generation`

Implemented contracts cover:
- generation configurations: list/create/detail/update/validate/submit/approve/cancel/supersede
- teacher preferences: list/create/detail/update/deactivate
- generation overrides: list/create/update/remove (while editable)
- locks: list/create/update/remove (while editable)
- parallel lesson blocks: list/create/detail/update/deactivate
- configuration summary including readiness and control counts

No solver execution endpoint is introduced.
No `POST /generate` route exists in this batch.

## Authorization and Tenant Isolation
This capability is leadership-controlled:
- allowed: `principal`, `school_admin`
- rejected: `teacher`, `parent`, `student`
- inactive leadership rejected

Tenant context is resolved from authenticated dependencies.
No tenant query-parameter override is introduced.

## Agent and Human Boundaries
Read actions include:
- inspect generation configuration
- summarize generation controls
- list preferences, locks, parallel blocks
- explain strength, repair scope, readiness, bell schedule effect

Proposal actions include:
- propose preference/override/lock/repair scope/stability/objectives/parallel block configuration

Human-authorized actions include:
- approve generation configuration
- approve permanent policy changes
- remove principal hard lock
- start solver generation
- approve timetable candidate
- publish timetable

Agent proposals remain non-operational and cannot auto-approve.

## Explicit Deferrals
Deferred from Batch 1:
- solver implementation
- scheduling problem builder
- timetable candidate generation and persistence
- timetable publication/versioning workflows
- teacher-facing timetable UI
- student-level scheduling and student membership in parallel blocks

## Phase 10C Batch 2: Canonical Scheduling Problem Builder

### Architectural Separation
Batch 2 adds a deterministic transformation layer:

Canonical data + effective policy + approved generation controls + overrides/locks/preferences + parallel blocks + repair metadata
-> immutable `SchedulingProblem`
-> future CP-SAT solver input (deferred to Batch 3)

The solver contract is now explicit: future solving consumes the normalized problem object and does not query arbitrary ORM tables directly.

### SchedulingProblem Contract
The normalized contract includes:
- tenant/context metadata (`tenant_id`, `academic_year_id`, `term_id`, optional `campus_id`)
- generation metadata (`generation_configuration_id`, `generation_mode`, `stability_mode`)
- deterministic provenance (`source_fingerprint`, `source_revision`)
- school week + logical periods + bell schedule reference
- normalized entities (teachers, classes, subjects, rooms)
- teaching requirements, fixed sessions, policy constraints, preferences, overrides, locks

## Phase 10C Batch 4: Transient Candidate Generation, Scoring, and Explainability

### Purpose
Batch 4 adds a non-persistent candidate layer on top of Batch 2 + Batch 3:
- normalized `SchedulingProblem`
- deterministic CP-SAT solve attempts with bounded profile variants
- transient candidate scoring/comparison/explainability payloads

Batch 4 is explicitly preview-only and does not change canonical timetable state.

### Scope Added
- Candidate preview orchestration in memory only.
- Deterministic candidate identity from assignment fingerprint.
- Candidate profile strategy (`configured`, `balanced`, `preference_focused`, `compactness_focused`, `stability_focused`, `distribution_focused`).
- Candidate deduplication by normalized assignment fingerprint.
- Candidate quality components derived from solver objective components.
- Pairwise candidate comparison with assignment deltas and metric deltas.
- Explainability facts from diagnostics and objective component outcomes.

### API Surface Added
Leadership preview endpoint:
- `POST /leadership/timetable-generation/configurations/{configuration_id}/candidates/preview`

Input controls include:
- candidate count
- max solver time
- candidate profiles
- comparison toggle
- explainability facts toggle
- response mode (`summary` or `detailed`)

Response includes:
- scheduling problem summary and solver eligibility gate
- transient candidate result bundle
- explicit non-actions contract proving no persistence/publication side effects

### Explicit Non-Actions (Batch 4)
Batch 4 does not do any of the following:
- persist candidate rows to database
- create timetable version rows
- approve or publish a timetable
- send notifications
- invoke external AI providers for solving
- run student-level scheduling

### Explainability Contract
Each candidate provides:
- quality components with key/priority/score/max-score/evidence
- objective-derived explanation facts
- diagnostic-derived explanation facts
- summary dimensions (preferences, fairness, workload, teacher gaps, subject distribution, rooms, repair impact)

### Determinism Contract
For equivalent problem fingerprint and options:
- normalized assignment ordering is stable
- assignment fingerprint is stable
- candidate identifier is stable

### Phase 10C-5 Deferral
Deferred to later phase (Phase 10C-5 and beyond):
- candidate persistence and review workflow state machine
- timetable version persistence and canonical publication
- rollout/notification orchestration
- operational approval workflows beyond preview
- parallel lesson blocks and children
- repair scope and baseline summary
- objective priorities
- validation summary + blockers/warnings/exclusions
- `solver_eligible` gate (no solver execution)

No ORM rows are returned in the contract. No DB session state is exposed.

### Logical Period Normalization
Placement identity remains logical:
- day key + period number (for example `Monday + P3`)

Clock times are metadata only:
- `starts_at`, `ends_at`, `duration_minutes`

Result:
- changing only start/end clock values preserves logical placement identity
- changing logical period structure changes the scheduling domain

No duplicate bell schedule persistence is introduced.

### Entity Normalization (No Students)
Teacher normalization includes:
- active user state
- eligible subject IDs from canonical qualifications
- weekly load limit hints
- available/unavailable logical periods
- fixed assignment references

Class normalization includes:
- grade reference
- campus context
- schedulable logical periods
- requirement/fixed-session/block references

Subject normalization includes:
- code/name
- weekly session and minute demand aggregates
- room requirements
- teacher eligibility map

Room normalization includes:
- room type/capacity/campus
- specialist capabilities
- availability windows derived from operational constraints

No student-level scheduling data is included.

### Requirements, Fixed Sessions, Parallel Blocks
Weekly requirements normalize to deterministic records with:
- class/subject/teacher linkage
- weekly sessions/minutes
- period-distribution bounds
- room-type expectation
- fixed-session rule references

Fixed sessions are normalized separately from:
- baseline assignments
- preferences
- locks
- overrides

Parallel blocks are fully normalized with synchronization semantics.
Foreign Language example supported:
- class-facing block: Grade 8A `Foreign Language`
- child tracks: French, German, Spanish
- children share synchronization semantics without introducing student membership

### Policy Readiness Integration and Solver Eligibility
Batch 2 consumes Phase 10B readiness output and operational effective constraints.

`solver_eligible` requires all of:
- Phase 10B `generation_allowed == true`
- generation configuration validation true
- problem-builder validation true
- configuration lifecycle approved

A high readiness score never overrides a blocker.

### Repair Baseline Behavior
Repair mode still requires a baseline reference.

Because SchoolOS does not yet expose a durable canonical published timetable baseline model, Batch 2 returns a controlled unsupported baseline normalization state:
- `baseline.supported = false`
- explicit reason string
- empty baseline assignments

No baseline assignments are fabricated.

### Locks, Preferences, Overrides, Objectives
Locks stay separate from other semantics and preserve:
- `locked`, `prefer_to_keep`, `flexible`
- manual hard-lock provenance
- canonical target validation

## Phase 10C Batch 5: Canonical Timetable Versions, Human Approval, Publication, and Repair Baseline

### Canonical Persistence
Batch 5 introduces one durable canonical timetable model:
- `Timetable`: tenant/year/term/campus container for a logical school timetable
- `TimetableVersion`: immutable snapshot lifecycle and effective-date history
- `TimetableVersionAssignment`: immutable canonical assignment rows for each version

There is one authoritative timetable source. Class-facing and teacher-facing timetable views are derived from the same published canonical assignments.

### Version Lifecycle
Batch 5 lifecycle states:
- `candidate`
- `under_review`
- `approved`
- `published`
- `superseded`
- `cancelled`

Transition rules:
- `candidate -> under_review`
- `under_review -> approved`
- `approved -> published`
- `candidate/under_review/approved -> cancelled`

`candidate -> published` direct transition is not allowed.
Published assignments are immutable. A timetable change creates a new candidate/version.

### Human Authority
Leadership access remains tenant-scoped.

Principal-only actions:
- approve timetable version
- publish timetable version

School admin may continue read and preparation actions under leadership policy, but final approval/publication stays principal-only in Batch 5.

### Candidate Materialization Security
Materialization route:
- `POST /leadership/timetable-generation/configurations/{configuration_id}/versions/from-candidate`

The server does not trust client assignment payloads. It:
- rebuilds scheduling problem
- verifies expected problem fingerprint
- deterministically regenerates transient candidates
- finds the requested candidate by `candidate_id`
- persists only server-produced canonical assignments

If fingerprints do not match, the route returns controlled stale preview conflict (`stale_candidate_preview`).

### Effective-Dated Publication and Supersession
Batch 5 supports effective-date semantics using half-open operational intervals:
- conceptual interval: `[effective_from, effective_until)`

When publishing a successor version:
- previous overlapping published version is closed at successor `effective_from`
- previous version is marked `superseded`
- historical assignments remain immutable and queryable

Operational lookup is by tenant + timetable scope + date, not by latest created version.

### Repair Baseline Integration
Generation configuration now supports canonical baseline reference via:
- `baseline_timetable_version_id`

Repair problem building can load real persisted baseline assignments from immutable timetable versions and normalize them into the existing scheduling-problem baseline contract.

The CP-SAT solver remains DB-independent.

### Repair Impact Preview
Leadership impact preview route:
- `POST /leadership/timetable-generation/configurations/{configuration_id}/repair/impact-preview`

Returns deterministic classification counts and affected entities:
- directly affected
- conditionally movable
- protected
- manually locked

Scope levels supported:
- `minimum`
- `affected_entities`
- `grade`
- `whole_school`

No silent scope expansion is performed.

### Version Diff
Leadership diff route:
- `GET /leadership/timetable-generation/timetable-versions/{version_id}/diff/{other_version_id}`

Diff compares immutable snapshots by stable canonical assignment identity and reports:
- moved period/span
- teacher changes
- room changes
- added/removed occurrences
- class-facing parallel block movement
- unchanged percentage

Multi-period sessions are preserved as one occurrence with occupied span.
Parallel block context is preserved for class-facing interpretation.

### Additional Leadership Routes
- `GET /leadership/timetable-generation/timetables`
- `GET /leadership/timetable-generation/timetables/{timetable_id}`
- `GET /leadership/timetable-generation/timetables/{timetable_id}/versions`
- `GET /leadership/timetable-generation/timetable-versions/{version_id}`
- `POST /leadership/timetable-generation/timetable-versions/{version_id}/submit`
- `POST /leadership/timetable-generation/timetable-versions/{version_id}/approve`
- `POST /leadership/timetable-generation/timetable-versions/{version_id}/publish`
- `POST /leadership/timetable-generation/timetable-versions/{version_id}/cancel`
- `GET /leadership/timetable-generation/timetables/{timetable_id}/effective-version?on=YYYY-MM-DD`

### Explicit Non-Actions in Batch 5
Batch 5 does not:
- send teacher/parent/student notifications
- add frontend timetable UI
- create student-level scheduling
- allow agent autonomous approve/publish actions

Department lock target remains unsupported in lock normalization.

Teacher preference strengths remain symbolic:
- hard, strong, normal, low

Generation objectives remain symbolic with deterministic defaults for standard mode and disruption-preserving defaults for repair mode.
No CP-SAT coefficient mapping is introduced.

### Determinism, Immutability, Performance
Determinism guarantees include:
- stable sorting
- stable identifiers
- deterministic source fingerprint over normalized content

Immutability:
- normalized problem structures are frozen/read-only after construction

Performance approach:
- batch-load canonical inputs by scope
- use in-memory maps for normalization
- avoid audit/PDF/import-history payloads for problem construction

### API Inspection Routes (Leadership Only)
Added under existing timetable-generation routes:
- `POST /leadership/timetable-generation/configurations/{id}/problem/validate`
- `GET /leadership/timetable-generation/configurations/{id}/problem/summary`
- `POST /leadership/timetable-generation/configurations/{id}/problem/preview`

These routes do not:
- run solver
- generate timetable candidates
- publish timetables

### Agent/Human Boundaries (Batch 2)
Added safe read/proposal contracts for scheduling-problem inspection and correction planning.

Human-only operations remain explicit for:
- solver start
- solver eligibility override
- candidate approval
- timetable publish

## Phase 10C Batch 3: OR-Tools CP-SAT Solver Engine

### Scope Added
Batch 3 introduces a deterministic CP-SAT scheduling engine that consumes only the immutable `SchedulingProblem` contract from Batch 2.

Implemented solver package:
- `services/gateway/timetable_setup/solver/contracts.py`
- `services/gateway/timetable_setup/solver/constraint_registry.py`
- `services/gateway/timetable_setup/solver/objective_registry.py`
- `services/gateway/timetable_setup/solver/cp_sat_solver.py`
- `services/gateway/timetable_setup/solver/diagnostics.py`

The solver is currently an internal engine boundary and is validated through synthetic/unit tests.

### Hard Constraint Coverage
Batch 3 hard constraints include:
- exactly-one placement per occurrence
- class collision prevention per logical slot
- teacher collision prevention across normal and parallel-child assignments
- room collision prevention across normal and parallel-child assignments
- fixed-session enforcement
- supported teacher/class/room unavailability constraints
- teacher daily and consecutive load limits
- hard preference enforcement for supported hard preference types
- parallel block synchronization (`same_period`) and frequency consistency checks

Unsupported hard policies produce deterministic blocker diagnostics and return `invalid_problem` without partial execution.

### Soft Objective Coverage
Batch 3 objective model includes:
- teacher preference penalties
- subject distribution penalties
- teacher gap minimization
- workload balance
- preference fairness
- baseline disruption minimization
- preserve-existing-assignment preference (`prefer_to_keep`)

Priority mapping is hierarchical (`critical` > `high` > `normal` > `low`) through deterministic coefficient synthesis.
Stability mode influences disruption penalty intensity (`very_high`, `high`, `balanced`, `flexible`).

### Repair and Lock Semantics
Batch 3 enforces controlled lock behavior:
- only `session_reference` lock targets are accepted for hard enforcement
- unsupported lock targets with hard lock state are blocked with diagnostics
- lock-based constraints requiring baseline context are blocked when baseline support is unavailable

Repair mode baseline behavior remains conservative and deterministic.

### Determinism and Safety
Deterministic solver behavior is supported by options such as:
- explicit random seed
- single-worker deterministic mode
- fixed status mapping and diagnostics contract

The solver does not mutate `SchedulingProblem` input data.
The solver does not perform arbitrary ORM/table reads.

### Explicit Deferrals (Still Not Included)
Batch 3 does not add:
- timetable candidate persistence
- published timetable/version persistence
- student-level scheduling
- production timetable generation endpoint/workflow

These remain deferred to later Phase 10C batches.
