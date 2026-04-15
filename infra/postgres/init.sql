-- =============================================================================
-- SchoolOS – PostgreSQL Initialization Script
--
-- This file runs ONCE when the Docker postgres container first starts.
-- It creates all tables, indexes, Row-Level Security policies, and seeds
-- a demo school so you can test immediately.
--
-- After this runs, the SQLAlchemy models (models.py) stay in sync with it.
-- Future schema changes go through Alembic migrations (Phase 1+).
-- =============================================================================

-- Enable the UUID generation extension (built into Postgres 15+, but safe to add)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================================
-- TABLES
-- =============================================================================

-- ── Tenants (one row = one school) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name       VARCHAR(255) NOT NULL,
    slug       VARCHAR(100) UNIQUE NOT NULL,  -- URL-safe school identifier
    settings   JSONB        NOT NULL DEFAULT '{}',
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Users (all humans: admins, principals, teachers, parents, staff) ─────────
CREATE TABLE IF NOT EXISTS users (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name              VARCHAR(255) NOT NULL,
    email             VARCHAR(255),
    phone             VARCHAR(50),
    role              VARCHAR(50)  NOT NULL,
    password_hash     VARCHAR(255),
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    preferred_channel VARCHAR(20)  NOT NULL DEFAULT 'whatsapp',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_role    CHECK (role IN ('school_admin','principal','teacher','parent','staff')),
    CONSTRAINT valid_channel CHECK (preferred_channel IN ('whatsapp','sms','email'))
);

-- ── Subjects (Math, English, Science…) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS subjects (
    id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name      VARCHAR(255) NOT NULL,
    code      VARCHAR(50)  NOT NULL,

    UNIQUE (tenant_id, code)   -- 'MATH' can exist in multiple schools
);

-- ── Teachers (extends users with school-specific data) ────────────────────────
CREATE TABLE IF NOT EXISTS teachers (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id          UUID        NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    employee_id      VARCHAR(100),
    max_weekly_hours INTEGER     NOT NULL DEFAULT 20,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Teacher ↔ Subject mapping (many-to-many) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS teacher_subjects (
    teacher_id UUID NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    PRIMARY KEY (teacher_id, subject_id)
);

-- ── Classes (e.g., Grade 5 Section A, academic year 2025-2026) ───────────────
CREATE TABLE IF NOT EXISTS classes (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    grade            VARCHAR(50) NOT NULL,
    section          VARCHAR(50) NOT NULL,
    academic_year    VARCHAR(20) NOT NULL,
    class_teacher_id UUID        REFERENCES teachers(id),

    UNIQUE (tenant_id, grade, section, academic_year)
);

-- ── Students ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS students (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    class_id     UUID         NOT NULL REFERENCES classes(id),
    name         VARCHAR(255) NOT NULL,
    student_code VARCHAR(100),          -- school's own ID number
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Student ↔ Parent mapping (many-to-many) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS student_parents (
    student_id    UUID        NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    parent_id     UUID        NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    relation_type VARCHAR(50) NOT NULL DEFAULT 'parent',       -- mother/father/guardian
    PRIMARY KEY (student_id, parent_id)
);

-- ── Audit Log (immutable, append-only) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    action      VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id   UUID,
    actor_id    UUID         REFERENCES users(id),
    details     JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Periods (named time slots in the school day) ──────────────────────────────
CREATE TABLE IF NOT EXISTS periods (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name       VARCHAR(50)  NOT NULL,   -- "Period 1", "Break", "Period 2"
    sort_order INTEGER      NOT NULL,   -- controls display order
    start_time VARCHAR(5)   NOT NULL,   -- "08:00"
    end_time   VARCHAR(5)   NOT NULL,   -- "08:45"
    CONSTRAINT uq_period_order_per_tenant UNIQUE (tenant_id, sort_order)
);

-- ── Timetable Entries (one cell in the weekly schedule grid) ──────────────────
CREATE TABLE IF NOT EXISTS timetable_entries (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    academic_year VARCHAR(20) NOT NULL,
    day_of_week   INTEGER     NOT NULL,   -- 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    period_id     UUID        NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
    class_id      UUID        NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    subject_id    UUID        NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    teacher_id    UUID        NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- A class cannot have two lessons in the same slot
    CONSTRAINT uq_class_slot   UNIQUE (tenant_id, academic_year, day_of_week, period_id, class_id),
    -- A teacher cannot be in two places at once
    CONSTRAINT uq_teacher_slot UNIQUE (tenant_id, academic_year, day_of_week, period_id, teacher_id),
    CONSTRAINT valid_day_of_week CHECK (day_of_week BETWEEN 0 AND 6)
);


-- =============================================================================
-- INDEXES
-- Fast lookups by tenant_id (used on every single query due to RLS).
-- Fast lookups by action and time (used by the audit trail queries).
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_users_tenant_id           ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subjects_tenant_id        ON subjects(tenant_id);
CREATE INDEX IF NOT EXISTS idx_teachers_tenant_id        ON teachers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_classes_tenant_id         ON classes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_students_tenant_id        ON students(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id      ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action         ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at     ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_periods_tenant_id         ON periods(tenant_id);
CREATE INDEX IF NOT EXISTS idx_timetable_tenant_id       ON timetable_entries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_timetable_class_day       ON timetable_entries(class_id, day_of_week);
CREATE INDEX IF NOT EXISTS idx_timetable_teacher_day     ON timetable_entries(teacher_id, day_of_week);


-- =============================================================================
-- ROW-LEVEL SECURITY (RLS)
--
-- How it works in plain English:
--   1. Every table has tenant_id on every row.
--   2. We enable RLS on each table.
--   3. We create a POLICY that says: only return rows where
--      tenant_id matches the PostgreSQL session variable 'app.tenant_id'.
--   4. Before every query, the application runs:
--         SET LOCAL app.tenant_id = '<uuid-of-the-school>';
--   5. With RLS active, even a bug in the application code cannot
--      accidentally leak data from one school to another.
--
-- The 'TRUE' flag in current_setting('app.tenant_id', TRUE) means:
-- "return NULL instead of raising an error if the variable is not set."
-- The policy then blocks the query (NULL ≠ any UUID), which is safe.
-- =============================================================================

-- Helper function: safely reads the current tenant from the session.
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
BEGIN
    RETURN current_setting('app.tenant_id', TRUE)::UUID;
EXCEPTION
    WHEN OTHERS THEN RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- Enable RLS on every tenant-scoped table
ALTER TABLE users            ENABLE ROW LEVEL SECURITY;
ALTER TABLE subjects         ENABLE ROW LEVEL SECURITY;
ALTER TABLE teachers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE teacher_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE classes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE students         ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_parents  ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE periods          ENABLE ROW LEVEL SECURITY;
ALTER TABLE timetable_entries ENABLE ROW LEVEL SECURITY;

-- Direct tenant_id policies
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON subjects
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON teachers
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON classes
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON students
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON audit_logs
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON periods
    USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation ON timetable_entries
    USING (tenant_id = current_tenant_id());

-- Join-based policies for tables without a direct tenant_id column
CREATE POLICY tenant_isolation ON teacher_subjects
    USING (
        teacher_id IN (
            SELECT id FROM teachers WHERE tenant_id = current_tenant_id()
        )
    );

CREATE POLICY tenant_isolation ON student_parents
    USING (
        student_id IN (
            SELECT id FROM students WHERE tenant_id = current_tenant_id()
        )
    );


-- =============================================================================
-- APPLICATION ROLE
--
-- The app connects as 'schoolos_user' (defined in docker-compose.yml).
-- This role can read/write all tables but does NOT bypass RLS.
-- Only the postgres superuser bypasses RLS (used for migrations only).
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'schoolos_app') THEN
        CREATE ROLE schoolos_app LOGIN PASSWORD 'schoolos_pass';
    END IF;
END
$$;

GRANT USAGE  ON SCHEMA public             TO schoolos_app;
GRANT ALL    ON ALL TABLES IN SCHEMA public    TO schoolos_app;
GRANT ALL    ON ALL SEQUENCES IN SCHEMA public TO schoolos_app;
GRANT EXECUTE ON FUNCTION current_tenant_id() TO schoolos_app;


-- =============================================================================
-- SEED DATA
-- A demo school inserted so you can test the API immediately after startup.
-- 'ON CONFLICT DO NOTHING' makes this safe to re-run.
-- =============================================================================

INSERT INTO tenants (name, slug, settings)
VALUES (
    'Greenwood International School',
    'greenwood',
    '{
        "timezone":    "Asia/Riyadh",
        "language":    "en",
        "sms_enabled":      true,
        "whatsapp_enabled": true,
        "email_enabled":    true,
        "academic_year":    "2025-2026"
    }'
)
ON CONFLICT (slug) DO NOTHING;
