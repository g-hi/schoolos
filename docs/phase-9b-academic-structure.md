# Phase 9B — Academic Structure Documentation

## Overview

Phase 9B introduces a **canonical academic structure** for SchoolOS: a fully normalised hierarchy of campuses, academic years, terms, grade levels, canonical classes, subject offerings, teacher assignments, and student enrolments. It co-exists with legacy CSV-based class references for backwards compatibility.

---

## Architecture

### Canonical Entity Hierarchy

```
Campus
  └── Academic Year
        ├── Term (1-N per year)
        └── Grade Level (tenant-scoped, shared across years)
              └── Canonical Class (campus + year + grade_level + section)
                    ├── Subject Offering (grade_level + subject per year)
                    │     └── Teacher Assignment (subject_teacher type)
                    └── Teacher Assignment (homeroom type)
                          └── Student Enrolment (per student per canonical class)
```

### Legacy Compatibility Fields

All pre-existing `students.class_id` and `classes.*` rows are **legacy** references. A legacy class has no `campus_id`, `academic_year_id`, or `grade_level_id` set in the canonical model. These rows remain readable and do not require migration.

Canonical-first resolution: when both a canonical enrolment and a legacy `class_id` pointer exist, the canonical enrolment takes precedence in all leadership views.

---

## Data Models

### Campus

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| tenant_id | UUID | Multi-tenant isolation |
| name | string | Display name |
| code | string | Short identifier |
| description | string? | Optional |
| is_active | bool | Gate for new classes |

### Academic Year

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| name | string | e.g. "2026–2027" |
| start_date | date | ISO 8601 |
| end_date | date | ISO 8601 |
| is_current | bool | At most one per tenant |
| is_active | bool | Gate for new enrollments |

### Term

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| academic_year_id | UUID | FK → AcademicYear |
| name | string | "Term 1" |
| code | string | "T1" |
| start_date / end_date | date | Must be within year bounds |
| sequence | int | Ordering within year |
| is_active | bool | |

### Grade Level

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| tenant_id | UUID | Shared across years |
| name | string | "Grade 5" |
| code | string | "G5" |
| sequence | int | Ordering |
| is_active | bool | |

### Canonical Class

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| tenant_id / campus_id / academic_year_id / grade_level_id | UUID | Structural FKs |
| code | string | e.g. "5A" |
| section | string | e.g. "A" |
| class_teacher_id | UUID? | Homeroom teacher FK |
| is_active | bool | |

A class is **canonical** when `campus_id`, `academic_year_id`, and `grade_level_id` are all non-null. A class without these fields is **legacy**.

### Subject Offering

Represents a specific subject being offered to a grade level in a given year at a campus.

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| campus_id / academic_year_id / grade_level_id / subject_id | UUID | Structural FKs |
| is_active | bool | |

### Teacher Assignment

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| academic_year_id | UUID | FK |
| teacher_id | UUID | FK |
| class_id | UUID | FK → canonical class |
| subject_offering_id | UUID? | Required for subject_teacher type |
| assignment_type | enum | `homeroom` or `subject_teacher` |
| start_date / end_date | date | Assignment period |
| is_active | bool | |

**Important:** Only `start_date`, `end_date`, and `is_active` are patchable. Structural fields (teacher, class, subject offering) are **not** patchable. To reassign a teacher, deactivate the old assignment and create a new one.

### Student Enrolment

The canonical lifecycle record linking a student to a canonical class for a year.

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| student_id | UUID | FK |
| class_id | UUID | FK → canonical class |
| academic_year_id / grade_level_id | UUID | Denormalised for query efficiency |
| status | enum | `active`, `transferred`, `withdrawn`, `completed` |
| enrolled_on | date | Start date |
| exited_on | date? | Set on terminal transitions |
| exit_reason | string? | Optional narrative |

---

## Enrolment Lifecycle

```
create()  →  active
active    →  transferred  (via transfer endpoint; history is preserved)
active    →  withdrawn    (PATCH status=withdrawn + exited_on + exit_reason)
active    →  completed    (PATCH status=completed + exited_on)
```

Only `withdrawn` and `completed` transitions are valid via PATCH. Transfers **must** use the dedicated `POST /{id}/transfer` endpoint, which:
1. Marks the source enrolment as `transferred`
2. Creates a new `active` enrolment in the destination class
3. Sets the student's `class_id` legacy pointer to the destination class

---

## CSV Dual-Write Behaviour

When a student CSV row contains a `class_id`:

1. The student's `class_id` legacy pointer is updated.
2. If the class is **canonical** and no active enrolment exists for that student in the current academic year → a new enrolment is auto-created (`status=active`).
3. If an active enrolment already exists in a **different** class → the row is **rejected** with a conflict error. Use the transfer workflow instead.
4. If an active enrolment already exists in the **same** class → no-op (idempotent).

---

## Canonical-First Student-Class Resolution

When resolving a student's current class in any domain service:

1. Look for an `active` canonical enrolment for the current academic year.
2. If found, return `canonical_class.id`.
3. If not found, fall back to `students.class_id` (legacy pointer).

This ensures timetable, weekly reports, exams, and pickup all resolve canonical enrolments when available.

---

## Reconciliation Diagnostics

The `/leadership/student-enrollments/reconciliation` endpoint returns rows for students with detectable inconsistencies:

| Issue Code | Meaning | Recommended Action |
|---|---|---|
| `legacy_only` | Student has `class_id` but no canonical enrolment | Create a canonical enrolment via the Enrolments tab |
| `terminal_canonical_history_stale_class_id` | All canonical enrolments are terminal but `class_id` still points to a class | Update `class_id` via CSV re-import or create a new enrolment |
| `class_id_conflicts_with_active_enrollment` | `class_id` points to a different class than the active canonical enrolment | Use the transfer workflow or correct the legacy pointer |
| `multiple_active_enrollments` | Student has more than one `active` canonical enrolment | Withdraw all but one; investigate root cause |

**No automatic repairs are performed.** The reconciliation view is diagnostic-only.

---

## Role and Tenant Controls

- All leadership API routes require role `principal` or `school_admin`.
- All data is scoped by `tenant_id` extracted from the JWT.
- The `RoleGuard` component (applied automatically by `AppShell` for non-parent/non-teacher routes) prevents frontend access for other roles.
- `isLeadershipRole(role)` is the canonical check in both frontend and middleware.

---

## Migration Chain

| Revision | Description |
|---|---|
| `a69044576efe` | Initial schema (legacy classes, students, exam marking) |
| `b5f3e8c9a12d` | Parent experience (Phase 8.1) |
| `b6d4fe19f7c2` | Parent–teacher appointments (Phase 8.5a) |
| `c85b…` | Announcements (Phase 8.5b) |
| `d42f0d6ab9e1` | Weekly reports (Phase 8.4) |
| `e1f4a2c9d113` | Pickup secure lifecycle (Phase 8.6a) |
| *(Phase 9A)* | Campuses, academic years, terms, grade levels (master data) |
| *(Phase 9B1)* | Canonical classes (campus + year + grade_level FK columns) |
| *(Phase 9B2)* | Teacher assignments |
| *(Phase 9B3)* | Student enrollments (canonical lifecycle) |
| *(Phase 9B3.2 / 9B4)* | Ingestion dual-write, timetable canonical-first integration |
| `8c3f2b1e9d77` | **Current HEAD** — no further migrations in Phase 9B5/9B6 |

---

## Operational Setup Order

1. **Campus** — configure at least one active campus
2. **Academic Year** — configure the current year (set `is_current=true`)
3. **Terms** — add terms to each academic year (optional but recommended)
4. **Grade Levels** — configure all grade levels in sequence order
5. **Subjects** — import via CSV (`/ingest/subjects`) or API
6. **Classes** — create canonical classes (campus + year + grade + section)
7. **Subject Offerings** — link subjects to grade levels per year
8. **Teachers** — import via CSV (`/ingest/teachers`) or API
9. **Teacher Assignments** — assign homeroom and subject teachers to classes
10. **Students** — import via CSV (`/ingest/students`) or API
11. **Student Enrolments** — CSV dual-write auto-creates enrolments for canonical classes; or use the Enrolments tab
12. **Timetable** — import periods and timetable after classes and teachers are configured

---

## Known Compatibility Boundaries

- Legacy classes (no canonical fields) remain fully functional for timetable, exams, and reports.
- `students.class_id` is preserved as the legacy pointer; canonical enrolments take precedence in leadership views.
- A student can have at most **one** active canonical enrolment per academic year. Multiple active enrolments are a reconciliation issue.
- Deactivating a campus, year, or grade level does not cascade-delete existing classes or enrolments — it only gates creation of new records.
- Subject offerings are structural; activating/deactivating is the only supported mutation after creation.

---

## Future Phase Dependencies

### Phase 9C (planned)
- Subject-level grade book tied to subject offerings
- Subject offering ↔ teacher assignment ↔ grade entry workflow
- Term-level progress reports

### Phase 9D (planned)
- CSV import preview and history
- Bulk enrolment import
- Academic year promotion (bulk-copy canonical classes to new year)
- Bulk teacher assignment import

---

## Frontend Integration

### Routes

| Route | Component | Access |
|---|---|---|
| `/academic-structure` | `AcademicStructurePage` | principal, school_admin |
| `/data` | `DataPage` (updated guidance) | principal, school_admin |

### Sidebar

The `principalNav` array in `sidebar.tsx` includes:
```
{ href: "/academic-structure", label: "Academic Structure", icon: "🏗️" }
```
This appears between "Data Upload" and "Social Media".

### API Modules

| Module | Purpose |
|---|---|
| `@/lib/master-data-api` | Campuses, academic years, terms, grade levels |
| `@/lib/academic-structure-api` | Classes, subject offerings, teacher assignments |
| `@/lib/enrolment-api` | Student enrolments, reconciliation |

Each module follows the `XxxApiError` + `parseApiError()` + `authHeaders()` pattern from `teacher-api.ts`. Error messages are extracted from `{ detail: "..." }` API responses.
