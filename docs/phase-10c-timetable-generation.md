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
