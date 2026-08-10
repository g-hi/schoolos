"""
SchoolOS – Core Database Models
================================
Every model inherits from Base and has a tenant_id column.
This is the multi-tenancy contract: one row per school, isolated by RLS.

Model hierarchy:
  Tenant
    └── User  (admins, principals, teachers, parents, staff)
          └── Teacher  (extends User with school-specific fields)
                └── TeacherSubject  (which subjects a teacher can teach)
    └── Subject
    └── Class  (e.g., Grade 5 Section A)
          └── Student
                └── StudentParent  (links students to their parents)
    └── AuditLog  (immutable record of every important action)
"""

import uuid
from datetime import datetime, date as date_type

from sqlalchemy import (
    and_,
    UUID,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from shared.db.base import Base


# ─────────────────────────────────────────────────────────────────────────────
# Tenant  (one row = one school)
# ─────────────────────────────────────────────────────────────────────────────

class Tenant(Base):
    """
    The root of multi-tenancy. Every other table has a tenant_id FK pointing here.

    slug: short URL-safe name used to identify a school in API calls and subdomains.
          e.g., 'greenwood' → greenwood.schoolos.com or X-Tenant-Slug: greenwood

    settings: a flexible JSON bag for school-level configuration:
              timezone, language, which channels are enabled, etc.
              We use JSON rather than columns so we don't need migrations
              every time a school wants a new setting.
    """
    __tablename__ = "tenants"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name:       Mapped[str]       = mapped_column(String(255), nullable=False)
    slug:       Mapped[str]       = mapped_column(String(100), unique=True, nullable=False)
    settings:   Mapped[dict]      = mapped_column(JSON, default=dict)
    is_active:  Mapped[bool]      = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# Campus  (tenant-scoped campus catalogue)
# ─────────────────────────────────────────────────────────────────────────────

class Campus(Base):
    __tablename__ = "campuses"

    id:          Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:   Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:        Mapped[str]            = mapped_column(String(255), nullable=False)
    code:        Mapped[str]            = mapped_column(String(50), nullable=False)
    description: Mapped[str | None]     = mapped_column(Text, nullable=True)
    is_active:   Mapped[bool]           = mapped_column(Boolean, default=True, nullable=False)
    created_at:  Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:  Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_campus_code_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# AcademicYear  (tenant-scoped year boundaries)
# ─────────────────────────────────────────────────────────────────────────────

class AcademicYear(Base):
    __tablename__ = "academic_years"

    id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:       Mapped[str]            = mapped_column(String(50), nullable=False)
    start_date: Mapped[date_type]      = mapped_column(Date, nullable=False)
    end_date:   Mapped[date_type]      = mapped_column(Date, nullable=False)
    is_current: Mapped[bool]           = mapped_column(Boolean, default=False, nullable=False)
    is_active:  Mapped[bool]           = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_academic_year_name_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Term  (subdivision of an academic year)
# ─────────────────────────────────────────────────────────────────────────────

class Term(Base):
    __tablename__ = "terms"

    id:               Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False, index=True)
    name:             Mapped[str]       = mapped_column(String(100), nullable=False)
    code:             Mapped[str]       = mapped_column(String(50), nullable=False)
    start_date:       Mapped[date_type] = mapped_column(Date, nullable=False)
    end_date:         Mapped[date_type] = mapped_column(Date, nullable=False)
    sequence:         Mapped[int]       = mapped_column(Integer, nullable=False)
    is_active:        Mapped[bool]      = mapped_column(Boolean, default=True, nullable=False)
    created_at:       Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:       Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_terms_sequence_positive"),
        UniqueConstraint("tenant_id", "academic_year_id", "code", name="uq_term_code_per_year_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GradeLevel  (tenant-scoped grade taxonomy)
# ─────────────────────────────────────────────────────────────────────────────

class GradeLevel(Base):
    __tablename__ = "grade_levels"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:       Mapped[str]       = mapped_column(String(100), nullable=False)
    code:       Mapped[str]       = mapped_column(String(50), nullable=False)
    sequence:   Mapped[int]       = mapped_column(Integer, nullable=False)
    is_active:  Mapped[bool]      = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_grade_levels_sequence_positive"),
        UniqueConstraint("tenant_id", "code", name="uq_grade_level_code_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# User  (all humans in the system)
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    """
    Single user table for every type of person.

    Why one table instead of separate teacher/parent tables?
    - A person can be both a parent and a teacher at the same school.
    - Authentication is the same for everyone (phone/email + JWT).
    - Role determines what they can see and do.

    preferred_channel: how this person receives notifications.
                       The communication gateway (Phase 4) reads this field
                       to decide whether to send WhatsApp, SMS, or email.
    """
    __tablename__ = "users"

    id:                Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:              Mapped[str]            = mapped_column(String(255), nullable=False)
    email:             Mapped[str | None]     = mapped_column(String(255))
    phone:             Mapped[str | None]     = mapped_column(String(50))
    role:              Mapped[str]            = mapped_column(String(50), nullable=False)
    password_hash:     Mapped[str | None]     = mapped_column(String(255))
    is_active:         Mapped[bool]           = mapped_column(Boolean, default=True)
    preferred_channel: Mapped[str]            = mapped_column(String(20), default="whatsapp")
    created_at:        Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('school_admin','principal','teacher','parent','staff')",
            name="valid_role",
        ),
        CheckConstraint(
            "preferred_channel IN ('whatsapp','sms','email')",
            name="valid_channel",
        ),
    )


class AccountInvitation(Base):
    """
    One-time account setup invitation for teacher/parent accounts.

    Raw invitation tokens are never stored. Only token_hash (sha256 hex) is
    persisted. Invitation state is derived from accepted_at/revoked_at/expires_at.
    """

    __tablename__ = "account_invitations"

    id:                 Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:          Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id:            Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    invited_email:      Mapped[str]              = mapped_column(String(255), nullable=False)
    role:               Mapped[str]              = mapped_column(String(50), nullable=False)
    token_hash:         Mapped[str]              = mapped_column(String(64), nullable=False, unique=True)
    expires_at:         Mapped[datetime]         = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at:        Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at:         Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at:         Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:         Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("accepted_at IS NULL OR revoked_at IS NULL", name="ck_account_invitations_accepted_or_revoked"),
        CheckConstraint("expires_at > created_at", name="ck_account_invitations_expires_after_created"),
        CheckConstraint("role IN ('school_admin','principal','teacher','parent','staff')", name="ck_account_invitations_role"),
        CheckConstraint("invited_email = lower(invited_email)", name="ck_account_invitations_email_normalized"),
        Index(
            "uq_account_invitations_pending_per_user",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=and_(accepted_at.is_(None), revoked_at.is_(None)),
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Subject
# ─────────────────────────────────────────────────────────────────────────────

class Subject(Base):
    """
    Subjects taught at the school (e.g., Mathematics, English, Biology).

    code: short identifier used in timetables and substitution logic,
          e.g., 'MATH', 'ENG', 'BIO'.
          Must be unique per tenant (two schools can both have 'MATH').
    """
    __tablename__ = "subjects"

    id:        Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:      Mapped[str]       = mapped_column(String(255), nullable=False)
    code:      Mapped[str]       = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_subject_code_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SubjectOffering  (canonical subject availability by scope)
# ─────────────────────────────────────────────────────────────────────────────

class SubjectOffering(Base):
    __tablename__ = "subject_offerings"

    id:               Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    campus_id:        Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="RESTRICT"), nullable=False)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False)
    grade_level_id:   Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=False)
    subject_id:       Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False)
    is_active:        Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default="true")
    created_at:       Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:       Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "campus_id",
            "academic_year_id",
            "grade_level_id",
            "subject_id",
            name="uq_subject_offering_scope",
        ),
        Index("ix_subject_offerings_tenant_id", "tenant_id"),
        Index("ix_subject_offerings_campus_id", "campus_id"),
        Index("ix_subject_offerings_academic_year_id", "academic_year_id"),
        Index("ix_subject_offerings_grade_level_id", "grade_level_id"),
        Index("ix_subject_offerings_subject_id", "subject_id"),
        Index("ix_subject_offerings_is_active", "is_active"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Teacher  (extends User)
# ─────────────────────────────────────────────────────────────────────────────

class Teacher(Base):
    """
    Teacher-specific profile data. Linked 1-to-1 with a User row.

    max_weekly_hours: the timetabling and substitution engines use this cap
                      to avoid over-scheduling a teacher.
                      Default 20 hours/week = roughly 4 periods/day.
    """
    __tablename__ = "teachers"

    id:                        Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:                 Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id:                   Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("users.id",    ondelete="CASCADE"), unique=True, nullable=False)
    employee_id:               Mapped[str | None] = mapped_column(String(100))
    max_weekly_hours:          Mapped[int]        = mapped_column(Integer, default=20)
    max_substitutions_per_week: Mapped[int]       = mapped_column(Integer, default=2)   # 0 = never assign as sub
    created_at:                Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships — SQLAlchemy loads these automatically when accessed
    user:     Mapped["User"]                 = relationship("User", lazy="joined")
    subjects: Mapped[list["TeacherSubject"]] = relationship("TeacherSubject", back_populates="teacher", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────────────────
# TeacherSubject  (many-to-many: teachers ↔ subjects)
# ─────────────────────────────────────────────────────────────────────────────

class TeacherSubject(Base):
    """
    Records which subjects a teacher is qualified to teach.

    This is used by the substitution engine in Phase 3:
    'Find all teachers who teach Maths and are free at 2nd period.'
    """
    __tablename__ = "teacher_subjects"

    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True)

    teacher: Mapped["Teacher"] = relationship("Teacher", back_populates="subjects")
    subject: Mapped["Subject"] = relationship("Subject")


# ─────────────────────────────────────────────────────────────────────────────
# TeacherAssignment  (canonical teacher assignment history)
# ─────────────────────────────────────────────────────────────────────────────

class TeacherAssignment(Base):
    __tablename__ = "teacher_assignments"

    id:               Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    teacher_id:       Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False, index=True)
    class_id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True)
    subject_offering_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subject_offerings.id", ondelete="RESTRICT"), nullable=True, index=True)
    assignment_type:  Mapped[str]            = mapped_column(String(50), nullable=False, index=True)
    start_date:       Mapped[date_type]      = mapped_column(Date, nullable=False)
    end_date:         Mapped[date_type | None] = mapped_column(Date, nullable=True)
    is_active:        Mapped[bool]           = mapped_column(Boolean, nullable=False, server_default="true")
    created_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("assignment_type IN ('homeroom', 'subject_teacher')", name="ck_teacher_assignments_type"),
        CheckConstraint(
            "(assignment_type = 'homeroom' AND subject_offering_id IS NULL) OR "
            "(assignment_type = 'subject_teacher' AND subject_offering_id IS NOT NULL)",
            name="ck_teacher_assignments_subject_scope",
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_teacher_assignments_date_range"),
        Index(
            "uq_teacher_assignments_active_homeroom_class",
            "tenant_id",
            "academic_year_id",
            "class_id",
            unique=True,
            postgresql_where=and_(is_active.is_(True), assignment_type == "homeroom"),
        ),
        Index(
            "uq_teacher_assignments_active_subject_teacher",
            "tenant_id",
            "academic_year_id",
            "teacher_id",
            "class_id",
            "subject_offering_id",
            unique=True,
            postgresql_where=and_(is_active.is_(True), assignment_type == "subject_teacher"),
        ),
        Index("ix_teacher_assignments_tenant_id", "tenant_id"),
        Index("ix_teacher_assignments_academic_year_id", "academic_year_id"),
        Index("ix_teacher_assignments_teacher_id", "teacher_id"),
        Index("ix_teacher_assignments_class_id", "class_id"),
        Index("ix_teacher_assignments_subject_offering_id", "subject_offering_id"),
        Index("ix_teacher_assignments_assignment_type", "assignment_type"),
        Index("ix_teacher_assignments_is_active", "is_active"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Class  (a group of students, e.g., Grade 5-A)
# ─────────────────────────────────────────────────────────────────────────────

class Class(Base):
    """
    Represents a class group for a specific academic year.

    academic_year: e.g., '2025-2026'. We scope classes to a year so that
                   historical timetables are preserved when a new term starts.

    The unique constraint prevents creating 'Grade 5 Section A' twice
    in the same year for the same school.
    """
    __tablename__ = "classes"

    id:               Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    grade:            Mapped[str]            = mapped_column(String(50), nullable=False)
    section:          Mapped[str]            = mapped_column(String(50), nullable=False)
    academic_year:    Mapped[str]            = mapped_column(String(20), nullable=False)
    class_teacher_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=True)
    campus_id:        Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="RESTRICT"), nullable=True)
    academic_year_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=True)
    grade_level_id:   Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=True)
    code:             Mapped[str | None]       = mapped_column(String(50), nullable=True)
    is_active:        Mapped[bool]             = mapped_column(Boolean, nullable=False, server_default="true")
    updated_at:       Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "((campus_id IS NULL AND academic_year_id IS NULL AND grade_level_id IS NULL) OR "
            "(campus_id IS NOT NULL AND academic_year_id IS NOT NULL AND grade_level_id IS NOT NULL))",
            name="ck_classes_canonical_scope_all_or_none",
        ),
        Index(
            "uq_classes_legacy_identity",
            "tenant_id",
            "grade",
            "section",
            "academic_year",
            unique=True,
            postgresql_where=((campus_id.is_(None)) & (academic_year_id.is_(None)) & (grade_level_id.is_(None))),
        ),
        Index(
            "uq_classes_canonical_section",
            "tenant_id",
            "campus_id",
            "academic_year_id",
            "grade_level_id",
            "section",
            unique=True,
            postgresql_where=(
                (campus_id.is_not(None))
                & (academic_year_id.is_not(None))
                & (grade_level_id.is_not(None))
                & (is_active.is_(True))
            ),
        ),
        Index(
            "uq_classes_code_per_academic_year",
            "tenant_id",
            "academic_year_id",
            "code",
            unique=True,
            postgresql_where=(
                (academic_year_id.is_not(None))
                & (code.is_not(None))
                & (is_active.is_(True))
            ),
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Student
# ─────────────────────────────────────────────────────────────────────────────

class Student(Base):
    """
    A student enrolled at the school.

    student_code: the school's own ID number (from their SIS/admin system).
                  We store it alongside our internal UUID so we can
                  match CSV imports back to existing records.
    """
    __tablename__ = "students"

    id:           Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id:     Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    name:         Mapped[str]            = mapped_column(String(255), nullable=False)
    student_code: Mapped[str | None]     = mapped_column(String(100))
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    parents: Mapped[list["StudentParent"]] = relationship("StudentParent", back_populates="student", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────────────────
# StudentEnrollment  (canonical student enrollment history)
# ─────────────────────────────────────────────────────────────────────────────

class StudentEnrollment(Base):
    __tablename__ = "student_enrollments"

    id:               Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    student_id:       Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True)
    class_id:         Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True)
    grade_level_id:   Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    status:           Mapped[str]                = mapped_column(String(20), nullable=False, server_default="active", index=True)
    enrolled_on:      Mapped[date_type]          = mapped_column(Date, nullable=False)
    exited_on:        Mapped[date_type | None]   = mapped_column(Date, nullable=True)
    exit_reason:      Mapped[str | None]         = mapped_column(Text, nullable=True)
    created_at:       Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:       Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'transferred', 'withdrawn', 'completed')", name="ck_student_enrollments_status"),
        CheckConstraint(
            "(status = 'active' AND exited_on IS NULL) OR "
            "(status IN ('transferred', 'withdrawn', 'completed') AND exited_on IS NOT NULL)",
            name="ck_student_enrollments_exit_presence",
        ),
        CheckConstraint("exited_on IS NULL OR exited_on >= enrolled_on", name="ck_student_enrollments_date_range"),
        Index(
            "uq_student_enrollments_active_student_year",
            "tenant_id",
            "academic_year_id",
            "student_id",
            unique=True,
            postgresql_where=(status == "active"),
        ),
        Index("ix_student_enrollments_tenant_id", "tenant_id"),
        Index("ix_student_enrollments_academic_year_id", "academic_year_id"),
        Index("ix_student_enrollments_student_id", "student_id"),
        Index("ix_student_enrollments_class_id", "class_id"),
        Index("ix_student_enrollments_grade_level_id", "grade_level_id"),
        Index("ix_student_enrollments_status", "status"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# StudentParent  (many-to-many: students ↔ parent users)
# ─────────────────────────────────────────────────────────────────────────────

class StudentParent(Base):
    """
    Links a student to their parent user account.

    One student can have multiple parents (mother + father).
    One parent can have multiple students (siblings).

    relationship field: 'mother', 'father', 'guardian', etc.
                        Stored for display purposes only — does not affect system logic.
    """
    __tablename__ = "student_parents"

    student_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    parent_id:     Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("users.id",    ondelete="CASCADE"), primary_key=True)
    relation_type: Mapped[str]                = mapped_column(String(50), default="parent")  # mother/father/guardian

    # ── Phase 8.1 Parent Experience columns ──────────────────────────────────
    # family_id is nullable to preserve legacy rows that pre-date the Parent
    # Experience platform. The application layer requires family_id for all
    # newly created Parent Experience relationships.
    # Do not set NOT NULL until a controlled backfill of legacy data is complete.
    family_id:           Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=None,
    )
    is_primary:          Mapped[bool]             = mapped_column(Boolean, nullable=False, server_default="false")
    can_pickup:          Mapped[bool]             = mapped_column(Boolean, nullable=False, server_default="true")
    can_view_academics:  Mapped[bool]             = mapped_column(Boolean, nullable=False, server_default="true")
    can_view_behaviour:  Mapped[bool]             = mapped_column(Boolean, nullable=False, server_default="true")
    is_active:           Mapped[bool]             = mapped_column(Boolean, nullable=False, server_default="true")
    created_at:          Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at:          Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped["Student"] = relationship("Student", back_populates="parents")
    parent:  Mapped["User"]    = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
# ImportBatch / ImportRowResult  (CSV import history)
# ─────────────────────────────────────────────────────────────────────────────

class ImportBatch(Base):
    """
    Tracks one leadership import attempt.

    A batch stores the file metadata, the import kind, the execution mode,
    and the final row counts so import history can be reviewed later without
    re-running the CSV.
    """

    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    conflict_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    import_format: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    rows: Mapped[list["ImportRowResult"]] = relationship("ImportRowResult", back_populates="batch", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("entity_type IN ('subjects','classes','teachers','students','parents','timetable_workbook','calendar_pdf')", name="ck_import_batches_entity_type"),
        CheckConstraint("mode IN ('preview','commit','workbook')", name="ck_import_batches_mode"),
        CheckConstraint("status IN ('uploaded','validating','preview_ready','invalid','committing','completed','completed_with_errors','failed','cancelled','parsing','mapping_required','validation_failed','validated','committed')", name="ck_import_batches_status"),
        CheckConstraint("import_format IS NULL OR import_format IN ('csv','xlsx','pdf')", name="ck_import_batches_format"),
    )


class ImportRowResult(Base):
    """
    Stores the outcome for one CSV row within a batch.
    """

    __tablename__ = "import_row_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sheet_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    source_column: Mapped[str | None] = mapped_column(String(120), nullable=True)
    field_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    field_errors: Mapped[dict] = mapped_column(JSON, default=dict)
    normalized_data: Mapped[dict] = mapped_column(JSON, default=dict)
    row_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    batch: Mapped["ImportBatch"] = relationship("ImportBatch", back_populates="rows")

    __table_args__ = (
        CheckConstraint("row_number > 0", name="ck_import_row_results_row_number_positive"),
        CheckConstraint("status IN ('valid','invalid','conflict','created','updated','skipped','failed')", name="ck_import_row_results_status"),
        CheckConstraint("action IN ('create','update','skip','none')", name="ck_import_row_results_action"),
        CheckConstraint("severity IS NULL OR severity IN ('blocker','warning','information')", name="ck_import_row_results_severity"),
        UniqueConstraint("import_batch_id", "row_number", name="uq_import_row_results_batch_row"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SchoolOnboardingRun / SchoolOnboardingStep  (Phase 9E onboarding workflow)
# ─────────────────────────────────────────────────────────────────────────────

class SchoolOnboardingRun(Base):
    __tablename__ = "school_onboarding_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    current_step_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('in_progress','paused','ready','completed','cancelled')", name="ck_school_onboarding_runs_status"),
        CheckConstraint("(status <> 'completed') OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL)", name="ck_school_onboarding_runs_completed_fields"),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="ck_school_onboarding_runs_completed_after_started"),
        Index(
            "uq_school_onboarding_runs_active_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=and_(status.in_(["in_progress", "paused", "ready"])),
        ),
    )


class SchoolOnboardingStep(Base):
    __tablename__ = "school_onboarding_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    onboarding_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("school_onboarding_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    completion_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('not_started','in_progress','blocked','completed','skipped')", name="ck_school_onboarding_steps_status"),
        CheckConstraint("completion_source IS NULL OR completion_source IN ('computed','manual','imported')", name="ck_school_onboarding_steps_completion_source"),
        CheckConstraint(
            "(completion_source <> 'manual' AND status <> 'skipped') OR (acknowledged_by_user_id IS NOT NULL AND acknowledged_at IS NOT NULL)",
            name="ck_school_onboarding_steps_manual_ack",
        ),
        UniqueConstraint("onboarding_run_id", "step_key", name="uq_school_onboarding_steps_run_step"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 10A Timetable Setup Foundation (canonical intake records)
# ─────────────────────────────────────────────────────────────────────────────

class OperationalCalendarEvent(Base):
    __tablename__ = "operational_calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    academic_year_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True)
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="SET NULL"), nullable=True, index=True)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    end_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    is_all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    teaching_day_effect: Mapped[str] = mapped_column(String(40), nullable=False, server_default="no_change")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending_review", index=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    original_source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    previous_version_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operational_calendar_events.id", ondelete="SET NULL"), nullable=True, index=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notification_plan_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="not_planned", index=True)
    notification_plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_operational_calendar_event_date_range"),
        CheckConstraint(
            "event_type IN ('teaching_day_override','public_holiday','school_holiday','examination_period','professional_development','parent_conference','school_event','half_day','special_schedule','term_boundary','information_only')",
            name="ck_operational_calendar_event_type",
        ),
        CheckConstraint(
            "teaching_day_effect IN ('no_change','non_teaching_day','teaching_day','special_schedule')",
            name="ck_operational_calendar_teaching_day_effect",
        ),
        CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_operational_calendar_source_type",
        ),
        CheckConstraint(
            "review_status IN ('pending_review','approved','rejected')",
            name="ck_operational_calendar_review_status",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','pending_review','approved','published','rescheduled','cancelled','superseded','archived','rejected')",
            name="ck_operational_calendar_lifecycle_status",
        ),
        CheckConstraint("version_number > 0", name="ck_operational_calendar_version_number_positive"),
        CheckConstraint(
            "notification_plan_status IN ('not_planned','planned','queued','sent','cancelled')",
            name="ck_operational_calendar_notification_plan_status",
        ),
        Index(
            "uq_operational_calendar_event_active_identity",
            "tenant_id",
            "campus_id",
            "academic_year_id",
            "term_id",
            "event_name",
            "start_date",
            "end_date",
            "event_type",
            unique=True,
            postgresql_where=and_(is_active.is_(True)),
        ),
    )


class CalendarSourceDocument(Base):
    __tablename__ = "calendar_source_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pdf_upload")
    extraction_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="uploaded", index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    extracted_char_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("source_type IN ('pdf_upload','manual_text')", name="ck_calendar_source_documents_source_type"),
        CheckConstraint(
            "extraction_status IN ('uploaded','processing','ocr_required','review_ready','processed','failed','cancelled','committed')",
            name="ck_calendar_source_documents_extraction_status",
        ),
        CheckConstraint("page_count >= 0", name="ck_calendar_source_documents_page_count_non_negative"),
        CheckConstraint("extracted_char_count >= 0", name="ck_calendar_source_documents_char_count_non_negative"),
    )


class CalendarSourcePage(Base):
    __tablename__ = "calendar_source_pages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calendar_source_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_excerpt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extracted_char_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("page_number > 0", name="ck_calendar_source_pages_page_number_positive"),
        CheckConstraint("extracted_char_count >= 0", name="ck_calendar_source_pages_char_count_non_negative"),
        UniqueConstraint("source_document_id", "page_number", name="uq_calendar_source_pages_document_page"),
    )


class CalendarEventCandidate(Base):
    __tablename__ = "calendar_event_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calendar_source_documents.id", ondelete="SET NULL"), nullable=True, index=True)
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calendar_source_pages.id", ondelete="SET NULL"), nullable=True, index=True)
    proposed_event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    proposed_end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    proposed_event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    proposed_teaching_day_effect: Mapped[str] = mapped_column(String(40), nullable=False, server_default="no_change")
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="proposed", index=True)
    date_parse_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="missing")
    uncertainty_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classification_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_issues_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operational_calendar_events.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "proposed_end_date IS NULL OR proposed_start_date IS NULL OR proposed_end_date >= proposed_start_date",
            name="ck_calendar_event_candidates_date_range",
        ),
        CheckConstraint(
            "proposed_event_type IN ('teaching_day_override','public_holiday','school_holiday','examination_period','professional_development','parent_conference','school_event','half_day','special_schedule','term_boundary','information_only')",
            name="ck_calendar_event_candidates_event_type",
        ),
        CheckConstraint(
            "proposed_teaching_day_effect IN ('no_change','non_teaching_day','teaching_day','special_schedule')",
            name="ck_calendar_event_candidates_teaching_day_effect",
        ),
        CheckConstraint("confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)", name="ck_calendar_event_candidates_confidence_score"),
        CheckConstraint(
            "candidate_status IN ('proposed','edited','approved','rejected','committed')",
            name="ck_calendar_event_candidates_status",
        ),
        CheckConstraint(
            "date_parse_status IN ('parsed','ambiguous','hijri_unresolved','invalid_range','missing')",
            name="ck_calendar_event_candidates_date_parse_status",
        ),
    )


class CalendarEventVersion(Base):
    __tablename__ = "calendar_event_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("operational_calendar_events.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    changed_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    affected_stakeholder_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notification_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calendar_notification_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_calendar_event_versions_version_positive"),
        CheckConstraint(
            "change_type IN ('created','edited','submitted','approved','published','rescheduled','scope_changed','location_changed','cancelled','restored','archived')",
            name="ck_calendar_event_versions_change_type",
        ),
        CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_calendar_event_versions_source_type",
        ),
        UniqueConstraint("event_id", "version_number", "change_type", name="uq_calendar_event_versions_event_version_change"),
    )


class CalendarNotificationPlan(Base):
    __tablename__ = "calendar_notification_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("operational_calendar_events.id", ondelete="CASCADE"), nullable=False, index=True)
    event_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    audience_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_message: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    urgency: Mapped[str] = mapped_column(String(30), nullable=False, server_default="normal")
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    approval_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outbox_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    delivery_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    audit_reference_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    related_notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("event_version_number > 0", name="ck_calendar_notification_plans_version_positive"),
        CheckConstraint(
            "trigger_reason IN ('event_published','reminder','event_updated','event_rescheduled','event_cancelled','urgent_change','weekly_calendar_summary')",
            name="ck_calendar_notification_plans_trigger_reason",
        ),
        CheckConstraint("affected_count >= 0", name="ck_calendar_notification_plans_affected_count_non_negative"),
        CheckConstraint("urgency IN ('low','normal','high','critical')", name="ck_calendar_notification_plans_urgency"),
        CheckConstraint(
            "approval_status IN ('draft','pending_approval','approved','scheduled','ready','dispatched','partially_failed','failed','cancelled')",
            name="ck_calendar_notification_plans_approval_status",
        ),
        CheckConstraint(
            "outbox_status IN ('draft','pending_approval','approved','scheduled','ready','dispatched','partially_failed','failed','cancelled')",
            name="ck_calendar_notification_plans_outbox_status",
        ),
    )


class SchoolWeekConfig(Base):
    __tablename__ = "school_week_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    academic_year_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True)
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    operational_weekdays: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_school_week_source_type",
        ),
        CheckConstraint(
            "review_status IN ('pending_review','approved','rejected')",
            name="ck_school_week_review_status",
        ),
        Index(
            "uq_school_week_default_active_scope",
            "tenant_id",
            "campus_id",
            "academic_year_id",
            "term_id",
            unique=True,
            postgresql_where=and_(is_active.is_(True), is_default.is_(True)),
        ),
    )


class BellSchedule(Base):
    __tablename__ = "bell_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    academic_year_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True)
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="SET NULL"), nullable=True, index=True)
    school_week_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("school_week_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="normal")
    effective_start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_bell_schedule_effective_date_range",
        ),
        CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_bell_schedule_source_type",
        ),
        CheckConstraint(
            "review_status IN ('pending_review','approved','rejected')",
            name="ck_bell_schedule_review_status",
        ),
        Index(
            "uq_bell_schedule_default_active_scope",
            "tenant_id",
            "campus_id",
            "academic_year_id",
            "term_id",
            unique=True,
            postgresql_where=and_(is_active.is_(True), is_default.is_(True)),
        ),
    )


class BellSchedulePeriod(Base):
    __tablename__ = "bell_schedule_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    bell_schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bell_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    applicable_grade_level_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("grade_levels.id", ondelete="SET NULL"), nullable=True, index=True)
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    is_teaching_period: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_break: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_lunch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("period_number > 0", name="ck_bell_schedule_period_number_positive"),
        Index(
            "uq_bell_schedule_period_number_active",
            "tenant_id",
            "bell_schedule_id",
            "period_number",
            unique=True,
            postgresql_where=and_(is_active.is_(True)),
        ),
    )


class TeachingRoom(Base):
    __tablename__ = "teaching_rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    room_code: Mapped[str] = mapped_column(String(50), nullable=False)
    room_name: Mapped[str] = mapped_column(String(255), nullable=False)
    room_type: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    floor_or_location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    specialist_capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    accessibility_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("capacity >= 0", name="ck_teaching_rooms_capacity_non_negative"),
        CheckConstraint(
            "room_type IN ('standard_classroom','science_lab','computer_lab','art_room','music_room','sports_space','library','examination_hall','multipurpose','virtual')",
            name="ck_teaching_rooms_room_type",
        ),
        CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_teaching_rooms_source_type",
        ),
        CheckConstraint(
            "review_status IN ('pending_review','approved','rejected')",
            name="ck_teaching_rooms_review_status",
        ),
        UniqueConstraint("tenant_id", "campus_id", "room_code", name="uq_teaching_rooms_code_per_scope"),
    )


class WeeklyTeachingRequirement(Base):
    __tablename__ = "weekly_teaching_requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="RESTRICT"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False, index=True)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True)
    sessions_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    periods_per_session: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    min_daily_sessions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_daily_sessions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    double_period_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")
    specialist_room_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_period_numbers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    forbidden_period_numbers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    has_fixed_sessions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fixed_session_rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("sessions_per_week > 0", name="ck_weekly_teaching_requirements_sessions_positive"),
        CheckConstraint("periods_per_session > 0", name="ck_weekly_teaching_requirements_periods_per_session_positive"),
        CheckConstraint("min_daily_sessions >= 0", name="ck_weekly_teaching_requirements_min_daily_non_negative"),
        CheckConstraint("max_daily_sessions >= min_daily_sessions", name="ck_weekly_teaching_requirements_daily_bounds"),
        CheckConstraint("priority > 0", name="ck_weekly_teaching_requirements_priority_positive"),
        CheckConstraint(
            "double_period_mode IN ('none','preferred','required')",
            name="ck_weekly_teaching_requirements_double_period_mode",
        ),
        CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_weekly_teaching_requirements_source_type",
        ),
        CheckConstraint(
            "review_status IN ('pending_review','approved','rejected')",
            name="ck_weekly_teaching_requirements_review_status",
        ),
        Index(
            "uq_weekly_teaching_requirements_active_identity",
            "tenant_id",
            "campus_id",
            "academic_year_id",
            "term_id",
            "class_id",
            "subject_id",
            unique=True,
            postgresql_where=and_(is_active.is_(True)),
        ),
    )


class TimetablePolicySet(Base):
    __tablename__ = "timetable_policy_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", index=True)
    effective_start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('draft','pending_review','approved','active','suspended','retired')",
            name="ck_timetable_policy_sets_lifecycle_status",
        ),
        CheckConstraint("version_number > 0", name="ck_timetable_policy_sets_version_positive"),
        CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_timetable_policy_sets_effective_date_range",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_default','approved_exception')",
            name="ck_timetable_policy_sets_source_type",
        ),
        Index(
            "uq_timetable_policy_sets_active_scope",
            "tenant_id",
            "academic_year_id",
            "term_id",
            "campus_id",
            unique=True,
            postgresql_where=and_(is_active.is_(True), lifecycle_status == "active"),
        ),
    )


class TimetablePolicySetVersion(Base):
    __tablename__ = "timetable_policy_set_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_policy_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_timetable_policy_set_versions_version_positive"),
        CheckConstraint(
            "change_type IN ('created','edited','submitted','approved','activated','suspended','retired')",
            name="ck_timetable_policy_set_versions_change_type",
        ),
        UniqueConstraint("policy_set_id", "version_number", "change_type", name="uq_timetable_policy_set_versions_event_version_change"),
    )


class TimetablePolicyConstraint(Base):
    __tablename__ = "timetable_policy_constraints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_policy_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    constraint_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    enforcement_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    scope_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    scope_reference_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default="1")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    effective_start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "category IN ('resource','teacher','class','subject','room','time','workload','distribution','curriculum','campus','policy','preference')",
            name="ck_timetable_policy_constraints_category",
        ),
        CheckConstraint(
            "enforcement_level IN ('hard','soft','preference','advisory')",
            name="ck_timetable_policy_constraints_enforcement_level",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','pending_review','approved','active','suspended','retired')",
            name="ck_timetable_policy_constraints_lifecycle_status",
        ),
        CheckConstraint(
            "scope_type IN ('whole_school','campus','department','grade','class','subject','teacher','room','period','policy_set')",
            name="ck_timetable_policy_constraints_scope_type",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_default','approved_exception')",
            name="ck_timetable_policy_constraints_source_type",
        ),
        CheckConstraint("version_number > 0", name="ck_timetable_policy_constraints_version_positive"),
        CheckConstraint("weight > 0 AND weight <= 1000", name="ck_timetable_policy_constraints_weight_bounds"),
        CheckConstraint("priority > 0 AND priority <= 1000", name="ck_timetable_policy_constraints_priority_bounds"),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)",
            name="ck_timetable_policy_constraints_confidence_score",
        ),
        CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_timetable_policy_constraints_effective_date_range",
        ),
    )


class TimetablePolicyConstraintVersion(Base):
    __tablename__ = "timetable_policy_constraint_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    constraint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_policy_constraints.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_timetable_policy_constraint_versions_version_positive"),
        CheckConstraint(
            "change_type IN ('created','edited','submitted','approved','activated','suspended','retired')",
            name="ck_timetable_policy_constraint_versions_change_type",
        ),
        UniqueConstraint("constraint_id", "version_number", "change_type", name="uq_timetable_policy_constraint_versions_event_version_change"),
    )


class TimetablePolicyException(Base):
    __tablename__ = "timetable_policy_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_policy_sets.id", ondelete="SET NULL"), nullable=True, index=True)
    constraint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_policy_constraints.id", ondelete="SET NULL"), nullable=True, index=True)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    scope_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    scope_reference_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    approval_state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('whole_school','campus','department','grade','class','subject','teacher','room','period','policy_set')",
            name="ck_timetable_policy_exceptions_scope_type",
        ),
        CheckConstraint(
            "approval_state IN ('draft','pending_review','approved','rejected','revoked')",
            name="ck_timetable_policy_exceptions_approval_state",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_timetable_policy_exceptions_date_range",
        ),
        CheckConstraint(
            "(policy_set_id IS NOT NULL) <> (constraint_id IS NOT NULL)",
            name="ck_timetable_policy_exceptions_single_target",
        ),
    )


class TimetableGenerationConfiguration(Base):
    __tablename__ = "timetable_generation_configurations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    bell_schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bell_schedules.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(30), nullable=False, server_default="standard", index=True)
    stability_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="balanced")
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft", index=True)
    baseline_reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    baseline_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    baseline_timetable_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    effective_start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    objective_priorities_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    repair_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effective_context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_configuration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_generation_configurations.id", ondelete="SET NULL"), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "generation_mode IN ('standard','customized','repair')",
            name="ck_timetable_generation_configurations_mode",
        ),
        CheckConstraint(
            "stability_mode IN ('very_high','high','balanced','flexible')",
            name="ck_timetable_generation_configurations_stability_mode",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','ready_for_review','approved','superseded','cancelled')",
            name="ck_timetable_generation_configurations_lifecycle_status",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_generated')",
            name="ck_timetable_generation_configurations_source_type",
        ),
        CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_timetable_generation_configurations_effective_date_range",
        ),
        CheckConstraint("version_number > 0", name="ck_timetable_generation_configurations_version_positive"),
        CheckConstraint(
            "generation_mode <> 'repair' OR baseline_reference_id IS NOT NULL OR baseline_timetable_version_id IS NOT NULL",
            name="ck_timetable_generation_configurations_repair_baseline_required",
        ),
        Index(
            "ix_timetable_generation_configurations_scope_status",
            "tenant_id",
            "academic_year_id",
            "term_id",
            "campus_id",
            "lifecycle_status",
        ),
    )


class Timetable(Base):
    __tablename__ = "timetables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="active", index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_timetables_status"),
        UniqueConstraint("tenant_id", "academic_year_id", "term_id", "campus_id", name="uq_timetables_scope"),
        Index("ix_timetables_scope", "tenant_id", "academic_year_id", "term_id", "campus_id", "status"),
    )


class TimetableVersion(Base):
    __tablename__ = "timetable_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timetable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetables.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_configuration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_generation_configurations.id", ondelete="SET NULL"), nullable=True, index=True)
    source_candidate_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_problem_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_problem_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_assignment_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(30), nullable=False, server_default="standard", index=True)
    baseline_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="candidate", index=True)
    effective_from: Mapped[date_type | None] = mapped_column(Date, nullable=True, index=True)
    effective_until: Mapped[date_type | None] = mapped_column(Date, nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    superseded_by_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_profile: Mapped[str | None] = mapped_column(String(60), nullable=True)
    quality_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    repair_impact_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    diff_summary_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    solver_provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_timetable_versions_version_positive"),
        CheckConstraint(
            "generation_mode IN ('standard','customized','repair')",
            name="ck_timetable_versions_generation_mode",
        ),
        CheckConstraint(
            "lifecycle_status IN ('candidate','under_review','approved','published','superseded','cancelled')",
            name="ck_timetable_versions_lifecycle_status",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
            name="ck_timetable_versions_effective_date_range",
        ),
        UniqueConstraint("timetable_id", "version_number", name="uq_timetable_versions_timetable_version_number"),
        Index("ix_timetable_versions_scope", "tenant_id", "timetable_id", "lifecycle_status", "effective_from", "effective_until"),
    )


class TimetableVersionAssignment(Base):
    __tablename__ = "timetable_version_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    timetable_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    occurrence_id: Mapped[str] = mapped_column(String(180), nullable=False)
    requirement_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    class_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subject_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teacher_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    room_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    day_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    periods_per_session: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    occupied_period_keys_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parallel_block_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    parallel_child_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    lock_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    protection_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    assignment_key: Mapped[str] = mapped_column(String(260), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("periods_per_session > 0", name="ck_timetable_version_assignments_periods_per_session_positive"),
        CheckConstraint(
            "lock_state IS NULL OR lock_state IN ('locked','prefer_to_keep','flexible')",
            name="ck_timetable_version_assignments_lock_state",
        ),
        UniqueConstraint("timetable_version_id", "assignment_key", name="uq_timetable_version_assignments_version_assignment_key"),
        Index("ix_timetable_version_assignments_version_class_day", "timetable_version_id", "class_id", "day_key"),
        Index("ix_timetable_version_assignments_version_teacher_day", "timetable_version_id", "teacher_id", "day_key"),
    )


class TimetableGenerationObjective(Base):
    __tablename__ = "timetable_generation_objectives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    configuration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_generation_configurations.id", ondelete="CASCADE"), nullable=False, index=True)
    objective_key: Mapped[str] = mapped_column(String(60), nullable=False)
    priority_level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "objective_key IN ('satisfy_hard_constraints','teacher_preferences','workload_balance','subject_distribution','minimize_teacher_gaps','minimize_room_changes','minimize_timetable_disruption','preference_fairness','preserve_existing_assignments')",
            name="ck_timetable_generation_objectives_key",
        ),
        CheckConstraint(
            "priority_level IN ('critical','high','normal','low')",
            name="ck_timetable_generation_objectives_priority",
        ),
        UniqueConstraint("configuration_id", "objective_key", name="uq_timetable_generation_objectives_configuration_key"),
    )


class TimetableTeacherSchedulingPreference(Base):
    __tablename__ = "timetable_teacher_scheduling_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    preference_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    strength: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal", index=True)
    weekdays_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    period_numbers_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    effective_start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    temporary_accommodation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    leadership_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "preference_type IN ('avoid_first_period','avoid_last_period','avoid_selected_periods','prefer_selected_periods','unavailable_selected_periods','prefer_grouped_free_periods','prefer_selected_days','avoid_selected_days','temporary_accommodation')",
            name="ck_timetable_teacher_preferences_type",
        ),
        CheckConstraint(
            "strength IN ('hard','strong','normal','low')",
            name="ck_timetable_teacher_preferences_strength",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_generated')",
            name="ck_timetable_teacher_preferences_source_type",
        ),
        CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_timetable_teacher_preferences_effective_date_range",
        ),
    )


class TimetableGenerationOverride(Base):
    __tablename__ = "timetable_generation_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    configuration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_generation_configurations.id", ondelete="CASCADE"), nullable=False, index=True)
    override_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    strength: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal", index=True)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    scope_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    scope_reference_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "override_type IN ('teacher_free_period','class_subject_timing_preference','room_avoidance','repair_assignment_protection','other_override')",
            name="ck_timetable_generation_overrides_type",
        ),
        CheckConstraint(
            "strength IN ('hard','strong','normal','low')",
            name="ck_timetable_generation_overrides_strength",
        ),
        CheckConstraint(
            "scope_type IN ('whole_school','campus','department','grade','class','subject','teacher','room','day','period','period_range','session_reference')",
            name="ck_timetable_generation_overrides_scope_type",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_generated')",
            name="ck_timetable_generation_overrides_source_type",
        ),
    )


class TimetableGenerationLock(Base):
    __tablename__ = "timetable_generation_locks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    configuration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_generation_configurations.id", ondelete="CASCADE"), nullable=False, index=True)
    lock_state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="flexible", index=True)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    target_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    target_reference_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_end_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_manual_hard_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "lock_state IN ('locked','prefer_to_keep','flexible')",
            name="ck_timetable_generation_locks_state",
        ),
        CheckConstraint(
            "target_type IN ('session_reference','teacher','class','subject','grade','room','day','period','period_range')",
            name="ck_timetable_generation_locks_target_type",
        ),
        CheckConstraint("day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)", name="ck_timetable_generation_locks_day_of_week"),
        CheckConstraint("period_number IS NULL OR period_number > 0", name="ck_timetable_generation_locks_period_number_positive"),
        CheckConstraint(
            "period_end_number IS NULL OR period_number IS NULL OR period_end_number >= period_number",
            name="ck_timetable_generation_locks_period_range",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_generated')",
            name="ck_timetable_generation_locks_source_type",
        ),
    )


class TimetableParallelLessonBlock(Base):
    __tablename__ = "timetable_parallel_lesson_blocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True)
    display_label: Mapped[str] = mapped_column(String(160), nullable=False)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    synchronization_requirement: Mapped[str] = mapped_column(String(30), nullable=False, server_default="same_period")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "block_type IN ('foreign_language','electives','split_class','other_parallel')",
            name="ck_timetable_parallel_blocks_type",
        ),
        CheckConstraint(
            "synchronization_requirement IN ('same_period','same_day')",
            name="ck_timetable_parallel_blocks_sync_requirement",
        ),
        CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_generated')",
            name="ck_timetable_parallel_blocks_source_type",
        ),
    )


class TimetableParallelLessonChild(Base):
    __tablename__ = "timetable_parallel_lesson_children"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    parallel_block_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_parallel_lesson_blocks.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("weekly_teaching_requirements.id", ondelete="SET NULL"), nullable=True, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True)
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teaching_rooms.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requirement_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "(requirement_id IS NOT NULL) OR (subject_id IS NOT NULL)",
            name="ck_timetable_parallel_children_requirement_or_subject",
        ),
        CheckConstraint(
            "sequence_order IS NULL OR sequence_order > 0",
            name="ck_timetable_parallel_children_sequence_positive",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# AuditLog  (immutable event log)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Period  (a named time slot in the school day)
# ─────────────────────────────────────────────────────────────────────────────

class Period(Base):
    """
    Defines the time slots in a school day: Period 1, Period 2, etc.

    Each school configures its own periods. A typical school might have:
      Period 1: 08:00 – 08:45
      Period 2: 08:50 – 09:35
      ...

    sort_order controls display order on the timetable.
    start_time / end_time are stored as strings (HH:MM) — simple and timezone-safe.
    """
    __tablename__ = "periods"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:       Mapped[str]       = mapped_column(String(50), nullable=False)   # e.g. "Period 1", "Break"
    sort_order: Mapped[int]       = mapped_column(Integer, nullable=False)      # 1, 2, 3 …
    start_time: Mapped[str]       = mapped_column(String(5), nullable=False)    # "08:00"
    end_time:   Mapped[str]       = mapped_column(String(5), nullable=False)    # "08:45"

    __table_args__ = (
        UniqueConstraint("tenant_id", "sort_order", name="uq_period_order_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TimetableEntry  (one cell in the timetable grid)
# ─────────────────────────────────────────────────────────────────────────────

class TimetableEntry(Base):
    """
    One slot in the weekly timetable:
        On <day_of_week>, during <period>, <class> has <subject> taught by <teacher>.

    day_of_week: 0=Monday … 4=Friday (integer, not string, so sorting works).

    academic_year: scopes entries to the current school year.
                   When a new year starts, old entries stay in the DB for history.

    is_active: allows soft-disable of a single slot without deleting it.
               The substitution engine uses this — a disabled slot means the
               original teacher is absent and a substitute is in place.

    The unique constraint prevents scheduling the same class twice in one slot,
    or the same teacher in two places at once.
    """
    __tablename__ = "timetable_entries"

    id:            Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:     Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year: Mapped[str]            = mapped_column(String(20), nullable=False)
    day_of_week:   Mapped[int]            = mapped_column(Integer, nullable=False)        # 0=Mon … 4=Fri
    period_id:     Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("periods.id", ondelete="CASCADE"), nullable=False)
    class_id:      Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id:    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    teacher_id:    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    is_active:     Mapped[bool]           = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    period:  Mapped["Period"]  = relationship("Period")
    klass:   Mapped["Class"]   = relationship("Class")
    subject: Mapped["Subject"] = relationship("Subject")
    teacher: Mapped["Teacher"] = relationship("Teacher")

    __table_args__ = (
        # A class can only have one lesson per slot
        UniqueConstraint("tenant_id", "academic_year", "day_of_week", "period_id", "class_id",
                         name="uq_class_slot"),
        # A teacher can only be in one place per slot
        UniqueConstraint("tenant_id", "academic_year", "day_of_week", "period_id", "teacher_id",
                         name="uq_teacher_slot"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="valid_day_of_week"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# AuditLog  (immutable event log)
# ─────────────────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """
    Immutable record of every significant action in the system.

    Design rules:
    - Rows are NEVER updated or deleted during normal operation.
    - Every service writes here — not just admins.
    - The 'details' JSON captures before/after state so you can reconstruct
      exactly what changed and why.

    action examples:
      'substitution.approved', 'timetable.created', 'fee_reminder.sent',
      'pickup.released', 'dashboard.viewed'

    This answers questions like:
      "Who approved the substitution for Grade 5 Maths on April 10?"
      "What changed in the timetable last Tuesday?"
    """
    __tablename__ = "audit_logs"

    id:          Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:   Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    action:      Mapped[str]            = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None]     = mapped_column(String(100))
    entity_id:   Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id:    Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    details:     Mapped[dict]           = mapped_column(JSON, default=dict)
    created_at:  Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Appointment  (Phase 8.5A — parent/teacher meeting lifecycle)
# ─────────────────────────────────────────────────────────────────────────────

class Appointment(Base):
    """
    Represents a parent-initiated appointment request tied to a student,
    family, and an eligible teacher-subject option.
    """
    __tablename__ = "appointments"

    id:                    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:             Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id:             Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id:            Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id:             Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id:            Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id:            Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True)
    timetable_entry_id:    Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    status:                Mapped[str]            = mapped_column(String(20), nullable=False, default="requested", index=True)
    requested_start_at:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    scheduled_start_at:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes:      Mapped[int]            = mapped_column(Integer, nullable=False)
    timezone:              Mapped[str]            = mapped_column(String(60), nullable=False)
    meeting_mode:          Mapped[str]            = mapped_column(String(20), nullable=False)
    location_or_link:      Mapped[str | None]     = mapped_column(Text, nullable=True)
    reason:                Mapped[str | None]     = mapped_column(Text, nullable=True)
    parent_notes:          Mapped[str | None]     = mapped_column(Text, nullable=True)
    staff_notes:           Mapped[str | None]     = mapped_column(Text, nullable=True)
    created_at:            Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at:            Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    confirmed_at:          Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at:           Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at:          Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at:          Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by:          Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    student: Mapped["Student"] = relationship("Student")
    teacher: Mapped["Teacher"] = relationship("Teacher")
    subject: Mapped["Subject | None"] = relationship("Subject")
    timetable_entry: Mapped["TimetableEntry | None"] = relationship("TimetableEntry")
    parent: Mapped["User"] = relationship("User", foreign_keys=[parent_id])
    cancelled_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[cancelled_by])

    __table_args__ = (
        CheckConstraint("status IN ('requested','confirmed','declined','cancelled','completed')", name="valid_appointment_status"),
        CheckConstraint("meeting_mode IN ('in_person','video','phone')", name="valid_appointment_meeting_mode"),
        CheckConstraint("duration_minutes BETWEEN 10 AND 180", name="valid_appointment_duration"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TimetableConstraint  (natural-language scheduling rules)
# ─────────────────────────────────────────────────────────────────────────────

class TimetableConstraint(Base):
    """
    Stores scheduling constraints entered by the admin in plain English.

    How it works:
    1. Admin types: "Teacher John should not teach in Period 4"
    2. Groq LLM parses this into structured JSON.
    3. Both the raw text AND the parsed JSON are saved here.
    4. When the OR-Tools solver runs, it reads all is_active=True rows
       and enforces them as hard constraints.

    constraint_type examples:
      'teacher_unavailable'  — teacher blocked from a period
      'class_unavailable'    — class blocked from a period (e.g., sports day)
      'teacher_max_daily'    — teacher can teach at most N periods per day
      'subject_first_period' — a subject must always be in period 1
      'no_back_to_back'      — teacher/class cannot have the same subject twice in a row

    data (JSON) structure depends on constraint_type, e.g.:
      teacher_unavailable  → {"teacher_id": "uuid", "day_of_week": 0, "period_order": 4}
      teacher_max_daily    → {"teacher_id": "uuid", "max_periods": 3}
    """
    __tablename__ = "timetable_constraints"

    id:              Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:       Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_text:        Mapped[str]       = mapped_column(Text, nullable=False)         # original plain-English input
    constraint_type: Mapped[str]       = mapped_column(String(50), nullable=False)   # parsed category
    data:            Mapped[dict]      = mapped_column(JSON, default=dict)            # structured parsed form
    is_active:       Mapped[bool]      = mapped_column(Boolean, default=True)        # toggle without deleting
    academic_year:   Mapped[str]       = mapped_column(String(20), nullable=False)   # e.g. "2025-2026"
    created_at:      Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# Substitution  (Phase 3 — teacher absence cover)
# ─────────────────────────────────────────────────────────────────────────────

class Substitution(Base):
    """
    Records a teacher substitution for a specific date.

    How it works:
    1. Admin reports absent teachers for a date.
    2. System finds the absent teacher's timetable entries for that day.
    3. For each slot, it finds the best available substitute and saves it here.

    status values:
      'assigned'               — a substitute was found and assigned
      'no_substitute_found'    — no qualified, available teacher could be found

    email_sent:    True once the assignment email has been sent via SendGrid.
    sms_sent:      True once the assignment SMS has been sent via Twilio.
    reminder_sent: True once the 5-minute-before reminder has been sent.

    absent_teacher_id:     the teacher who is absent
    substitute_teacher_id: the teacher covering (null if none found)
    timetable_entry_id:    the original slot being covered
    date:                  the actual calendar date (not day_of_week)
    """
    __tablename__ = "substitutions"

    id:                      Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:               Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    date:                    Mapped[date_type]            = mapped_column(Date, nullable=False, index=True)
    academic_year:           Mapped[str]                  = mapped_column(String(20), nullable=False)
    timetable_entry_id:      Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_entries.id", ondelete="CASCADE"), nullable=False)
    absent_teacher_id:       Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=False)
    substitute_teacher_id:   Mapped[uuid.UUID | None]    = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=True)
    status:                  Mapped[str]                  = mapped_column(String(30), nullable=False, default="assigned")
    email_sent:              Mapped[bool]                 = mapped_column(Boolean, default=False)
    sms_sent:                Mapped[bool]                 = mapped_column(Boolean, default=False)
    reminder_sent:           Mapped[bool]                 = mapped_column(Boolean, default=False)
    confidence_score:        Mapped[int | None]           = mapped_column(Integer, nullable=True)            # 0–100
    confidence_reasons:      Mapped[dict | None]          = mapped_column(JSON, nullable=True)               # breakdown
    created_at:              Mapped[datetime]             = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    timetable_entry:   Mapped["TimetableEntry"]    = relationship("TimetableEntry")
    absent_teacher:    Mapped["Teacher"]            = relationship("Teacher", foreign_keys=[absent_teacher_id])
    substitute_teacher: Mapped["Teacher | None"]   = relationship("Teacher", foreign_keys=[substitute_teacher_id])


# ─────────────────────────────────────────────────────────────────────────────
# Message  (Phase 4 — parent communication audit log)
# ─────────────────────────────────────────────────────────────────────────────

class Message(Base):
    """
    Logs every outbound notification sent to parents (or teachers).

    channel values: 'whatsapp' | 'sms' | 'email'
    message_type values:
      'substitution_alert'  — parent notified of teacher absence cover
      'daily_digest'        — tomorrow's schedule for a student
      'broadcast'           — admin announcement (holiday, trip, event)

    status values: 'sent' | 'failed' | 'skipped'
      skipped = recipient had no phone/email for the requested channel

    recipient_id: the User (parent) who received the message.
    student_id:   the student this message is about (nullable for broadcasts).
    """
    __tablename__ = "messages"

    id:           Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    student_id:   Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=True)
    channel:      Mapped[str]            = mapped_column(String(20), nullable=False)           # whatsapp / sms / email
    message_type: Mapped[str]            = mapped_column(String(50), nullable=False, index=True)
    body:         Mapped[str]            = mapped_column(Text, nullable=False)
    status:       Mapped[str]            = mapped_column(String(20), nullable=False, default="sent")
    error:        Mapped[str | None]     = mapped_column(Text, nullable=True)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    recipient: Mapped["User"]           = relationship("User", foreign_keys=[recipient_id])
    student:   Mapped["Student | None"] = relationship("Student")


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publication_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    publication_claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("status IN ('draft','scheduled','publishing','published','archived')", name="valid_announcement_status"),
    )


class AnnouncementTarget(Base):
    __tablename__ = "announcement_targets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    announcement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_key: Mapped[str] = mapped_column(String(300), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=True, index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("target_type IN ('school','grade','class','family','student')", name="valid_announcement_target_type"),
        CheckConstraint("(target_type = 'school' AND grade IS NULL AND class_id IS NULL AND family_id IS NULL AND student_id IS NULL) OR (target_type = 'grade' AND grade IS NOT NULL AND class_id IS NULL AND family_id IS NULL AND student_id IS NULL) OR (target_type = 'class' AND grade IS NULL AND class_id IS NOT NULL AND family_id IS NULL AND student_id IS NULL) OR (target_type = 'family' AND grade IS NULL AND class_id IS NULL AND family_id IS NOT NULL AND student_id IS NULL) OR (target_type = 'student' AND grade IS NULL AND class_id IS NULL AND family_id IS NULL AND student_id IS NOT NULL)", name="valid_announcement_target_shape"),
        UniqueConstraint("announcement_id", "target_key", name="uq_announcement_target_key"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    announcement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("delivery_status IN ('pending','delivered','partial','failed','skipped')", name="valid_notification_delivery_status"),
        UniqueConstraint("announcement_id", "recipient_user_id", name="uq_announcement_notification_recipient"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PickupRequest  (Phase 5 — private car pickup with geofence)
# ─────────────────────────────────────────────────────────────────────────────

class PickupRequest(Base):
    """
    Records a parent pickup request and the full release lifecycle.

    status values:
        'requested'                 — parent request accepted (inside geofence)
        'rejected_outside_geofence' — request rejected due to GPS distance
        'released'                  — teacher confirmed release

    channel values:
        'whatsapp' | 'sms'

    early_pickup:
        True when requested before class dismissal time.
    """
    __tablename__ = "pickup_requests"

    id:                Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:         Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id:         Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    student_id:        Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True)
    class_id:          Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True)
    teacher_id:        Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=True)
    channel:           Mapped[str]              = mapped_column(String(20), nullable=False)
    command_text:      Mapped[str]              = mapped_column(Text, nullable=False)
    parent_latitude:   Mapped[float]            = mapped_column(Float, nullable=False)
    parent_longitude:  Mapped[float]            = mapped_column(Float, nullable=False)
    distance_meters:   Mapped[float]            = mapped_column(Float, nullable=False)
    geofence_radius_m: Mapped[int]              = mapped_column(Integer, nullable=False, default=150)
    within_geofence:   Mapped[bool]             = mapped_column(Boolean, nullable=False, default=False)
    early_pickup:      Mapped[bool]             = mapped_column(Boolean, nullable=False, default=False)
    status:            Mapped[str]              = mapped_column(String(50), nullable=False, default="requested", index=True)
    requested_at:      Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    acknowledged_at:   Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    called_at:         Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    prepared_at:       Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at:      Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at:      Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by:      Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_by:       Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at:       Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    verification_method: Mapped[str | None]     = mapped_column(String(100), nullable=True)
    verification_note: Mapped[str | None]       = mapped_column(Text, nullable=True)
    released_at:       Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    notes:             Mapped[str | None]       = mapped_column(Text, nullable=True)

    # Relationships
    parent:  Mapped["User"]           = relationship("User", foreign_keys=[parent_id])
    student: Mapped["Student"]        = relationship("Student")
    klass:   Mapped["Class"]          = relationship("Class")
    teacher: Mapped["Teacher | None"] = relationship("Teacher", foreign_keys=[teacher_id])
    cancelled_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[cancelled_by])
    verified_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by])


# ─────────────────────────────────────────────────────────────────────────────
# SocialMention  (Component 10 — marketing intelligence)
# ─────────────────────────────────────────────────────────────────────────────

class SocialMention(Base):
    """
    A single mention of the school on social media.

    Data enters via CSV/JSON import or future API feeds.
    Groq LLM analyses unprocessed mentions for sentiment and topics.

    platform:  'instagram' | 'facebook' | 'twitter' | 'tiktok' | 'linkedin' | 'other'
    sentiment: 'positive' | 'negative' | 'neutral' | None (unprocessed)
    topics:    JSON list of extracted topics, e.g. ["bus delays", "new playground"]
    is_competitor: True if this mention is about a competitor school
    """
    __tablename__ = "social_mentions"

    id:             Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    platform:       Mapped[str]                 = mapped_column(String(50), nullable=False, index=True)
    author:         Mapped[str | None]          = mapped_column(String(255), nullable=True)
    text:           Mapped[str]                 = mapped_column(Text, nullable=False)
    url:            Mapped[str | None]          = mapped_column(Text, nullable=True)
    posted_at:      Mapped[datetime]            = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sentiment:      Mapped[str | None]          = mapped_column(String(20), nullable=True, index=True)
    sentiment_score: Mapped[float | None]       = mapped_column(Float, nullable=True)       # -1.0 to 1.0
    topics:         Mapped[list | None]         = mapped_column(JSON, nullable=True)
    is_competitor:  Mapped[bool]                = mapped_column(Boolean, default=False)
    competitor_name: Mapped[str | None]         = mapped_column(String(255), nullable=True)
    engagement:     Mapped[int | None]          = mapped_column(Integer, nullable=True)      # likes+comments+shares
    processed:      Mapped[bool]                = mapped_column(Boolean, default=False, index=True)
    created_at:     Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# DutyLocation  (named places where teachers supervise)
# ─────────────────────────────────────────────────────────────────────────────

class DutyLocation(Base):
    """
    A named location in the school where duty is required
    (e.g. Main Gate, Playground, Cafeteria, Corridor A).
    """
    __tablename__ = "duty_locations"

    id:          Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:   Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:        Mapped[str]       = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active:   Mapped[bool]      = mapped_column(Boolean, default=True)
    created_at:  Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_duty_location_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DutySlot  (time windows for duties: Morning, Break, Lunch, Closing, etc.)
# ─────────────────────────────────────────────────────────────────────────────

class DutySlot(Base):
    """
    A named time window when duty coverage is needed.
    Not the same as timetable periods — these can be Morning Arrival,
    Break, Lunch, Closing, etc.
    """
    __tablename__ = "duty_slots"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name:       Mapped[str]       = mapped_column(String(100), nullable=False)   # e.g. "Morning Arrival", "Break", "Lunch", "Closing"
    start_time: Mapped[str]       = mapped_column(String(5), nullable=False)     # "07:30"
    end_time:   Mapped[str]       = mapped_column(String(5), nullable=False)     # "08:00"
    is_active:  Mapped[bool]      = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_duty_slot_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DutySlotLocation  (which locations need coverage during which slot)
# ─────────────────────────────────────────────────────────────────────────────

class DutySlotLocation(Base):
    """
    Maps which locations need duty coverage during a specific duty slot.
    E.g. "First Break" → [Playground, Cafeteria, Corridor A].
    Admins configure this per-slot before generating the roster.
    """
    __tablename__ = "duty_slot_locations"

    id:          Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:   Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_id:     Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("duty_slots.id", ondelete="CASCADE"), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="CASCADE"), nullable=False)
    created_at:  Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    slot:     Mapped["DutySlot"]     = relationship("DutySlot")
    location: Mapped["DutyLocation"] = relationship("DutyLocation")

    __table_args__ = (
        UniqueConstraint("tenant_id", "slot_id", "location_id", name="uq_slot_location_per_tenant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DutyAssignment  (recurring weekly pattern for the term/year)
# ─────────────────────────────────────────────────────────────────────────────

class DutyAssignment(Base):
    """
    Assigns a teacher to cover a duty location during a duty slot on a
    specific day of the week.  This is a **recurring weekly pattern** that
    applies for the entire academic_year / term.  It is generated once and
    only adjusted when a teacher leaves or the timetable changes.
    """
    __tablename__ = "duty_assignments"

    id:              Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:       Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id:      Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    duty_slot_id:    Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("duty_slots.id", ondelete="CASCADE"), nullable=False)
    location_id:     Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="CASCADE"), nullable=False)
    day_of_week:     Mapped[int]        = mapped_column(Integer, nullable=False)           # 0=Mon … 4=Fri
    academic_year:   Mapped[str]        = mapped_column(String(20), nullable=False)
    ai_reasoning:    Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at:      Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    teacher:       Mapped["Teacher"]      = relationship("Teacher")
    duty_slot:     Mapped["DutySlot"]     = relationship("DutySlot")
    location:      Mapped["DutyLocation"] = relationship("DutyLocation")

    __table_args__ = (
        # Same teacher can't be in two places at the same time on the same day
        UniqueConstraint("tenant_id", "teacher_id", "duty_slot_id", "day_of_week", "academic_year",
                         name="uq_teacher_duty_slot_day"),
        # Same location+slot+day can only have one teacher
        UniqueConstraint("tenant_id", "location_id", "duty_slot_id", "day_of_week", "academic_year",
                         name="uq_location_duty_slot_day"),
        CheckConstraint("day_of_week BETWEEN 0 AND 4", name="valid_duty_day"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CopilotCheckpoint  (persistent graph checkpoint storage)
# ─────────────────────────────────────────────────────────────────────────────

class CopilotCheckpoint(Base):
    """
    Persists copilot workflow checkpoints for resume/review actions.
    Tenant isolation is enforced by tenant_id filtering and RLS.
    """
    __tablename__ = "copilot_checkpoints"

    request_id: Mapped[str]             = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_slug: Mapped[str]            = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[str]                = mapped_column(String(128), nullable=False, index=True)
    intent: Mapped[str]                 = mapped_column(String(64), nullable=False, index=True)
    graph_state: Mapped[dict]           = mapped_column(JSON, default=dict)
    current_status: Mapped[str]         = mapped_column(String(40), nullable=False, default="pending")
    approval_status: Mapped[str]        = mapped_column(String(40), nullable=False, default="pending")
    retry_count: Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)


# ─────────────────────────────────────────────────────────────────────────────
# MarkingSession  (Assessment Review & Marking Studio — session container)
# ─────────────────────────────────────────────────────────────────────────────

class MarkingSession(Base):
    """
    A single marking session owned by one teacher at one school.

    Every AssessmentSubmission, ScannedPage, and QuestionResponse belongs to
    a MarkingSession.  The session tracks cumulative progress across the
    student queue so an interrupted scanning session can be resumed.

    copilot_request_id links to the CopilotCheckpoint that holds the
    session-level LangGraph state (answer key, rubric, context).
    """
    __tablename__ = "marking_sessions"

    session_id:              Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:               Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id:              Mapped[str]            = mapped_column(String(128), nullable=False, index=True)
    exam_title:              Mapped[str]            = mapped_column(String(255), nullable=False)
    subject:                 Mapped[str | None]     = mapped_column(String(100))
    grade:                   Mapped[str | None]     = mapped_column(String(50))
    class_name:              Mapped[str | None]     = mapped_column(String(100))
    curriculum:              Mapped[str | None]     = mapped_column(String(100))
    academic_year:           Mapped[str | None]     = mapped_column(String(20))
    term:                    Mapped[str | None]     = mapped_column(String(50))
    exam_date:               Mapped[date_type | None] = mapped_column(Date)
    total_marks:             Mapped[int | None]     = mapped_column(Integer)
    time_allowed_minutes:    Mapped[int | None]     = mapped_column(Integer)
    expected_pages_per_student: Mapped[int]         = mapped_column(Integer, default=1)
    paper_type:              Mapped[str]            = mapped_column(String(50), default="open_ended")
    input_method:            Mapped[str]            = mapped_column(String(50), default="upload")
    language:                Mapped[str]            = mapped_column(String(50), default="English")
    total_students:          Mapped[int]            = mapped_column(Integer, default=0)
    captured_students:       Mapped[int]            = mapped_column(Integer, default=0)
    processed_students:      Mapped[int]            = mapped_column(Integer, default=0)
    pending_students:        Mapped[int]            = mapped_column(Integer, default=0)
    flagged_students:        Mapped[int]            = mapped_column(Integer, default=0)
    approved_students:       Mapped[int]            = mapped_column(Integer, default=0)
    average_confidence:      Mapped[float | None]   = mapped_column(Float)
    student_queue:           Mapped[list]           = mapped_column(JSON, default=list)
    copilot_request_id:      Mapped[str | None]     = mapped_column(String(64), ForeignKey("copilot_checkpoints.request_id", ondelete="SET NULL"), nullable=True)
    status:                  Mapped[str]            = mapped_column(String(50), nullable=False, default="draft")
    teacher_notes:           Mapped[str | None]     = mapped_column(Text)
    created_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "paper_type IN ('scantron','printed_mcq','mixed','open_ended')",
            name="valid_paper_type",
        ),
        CheckConstraint(
            "status IN ('draft','scanning','uploading','processing','needs_clarification',"
            "'pending_review','partially_approved','approved','rejected','failed')",
            name="valid_marking_session_status",
        ),
        CheckConstraint(
            "input_method IN ('smart_scan','upload','office_scanner')",
            name="valid_input_method",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# AssessmentSubmission  (one student's paper within a MarkingSession)
# ─────────────────────────────────────────────────────────────────────────────

class AssessmentSubmission(Base):
    """
    Represents a single student's submission within a marking session.

    Named 'AssessmentSubmission' (not 'StudentPaper') so this model can
    support scanned papers, uploaded files, future online submissions,
    assignments, and LMS imports without a schema change.

    copilot_request_id stores the LangGraph graph state for this specific
    submission so processing can be resumed after a gateway restart.
    """
    __tablename__ = "assessment_submissions"

    submission_id:           Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id:              Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("marking_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:               Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    student_name:            Mapped[str | None]     = mapped_column(String(255))
    student_code:            Mapped[str | None]     = mapped_column(String(100))
    paper_type:              Mapped[str]            = mapped_column(String(50), default="open_ended")
    processing_pipeline:     Mapped[str | None]     = mapped_column(String(50))
    status:                  Mapped[str]            = mapped_column(String(50), nullable=False, default="pending")
    proposed_total:          Mapped[float | None]   = mapped_column(Float)
    teacher_final_total:     Mapped[float | None]   = mapped_column(Float)
    max_marks:               Mapped[int | None]     = mapped_column(Integer)
    percentage:              Mapped[float | None]   = mapped_column(Float)
    confidence_score:        Mapped[float | None]   = mapped_column(Float)
    unanswered_count:        Mapped[int]            = mapped_column(Integer, default=0)
    unresolved_count:        Mapped[int]            = mapped_column(Integer, default=0)
    low_confidence_count:    Mapped[int]            = mapped_column(Integer, default=0)
    objective_question_count: Mapped[int]           = mapped_column(Integer, default=0)
    ai_graded_count:         Mapped[int]            = mapped_column(Integer, default=0)
    deterministic_count:     Mapped[int]            = mapped_column(Integer, default=0)
    teacher_overridden:      Mapped[bool]           = mapped_column(Boolean, default=False)
    teacher_comments:        Mapped[str | None]     = mapped_column(Text)
    tokens_used:             Mapped[int]            = mapped_column(Integer, default=0)
    estimated_cost_usd:      Mapped[float]          = mapped_column(Float, default=0.0)
    approved_by:             Mapped[str | None]     = mapped_column(String(128))
    approved_at:             Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    copilot_request_id:      Mapped[str | None]     = mapped_column(String(64), ForeignKey("copilot_checkpoints.request_id", ondelete="SET NULL"), nullable=True)
    created_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "paper_type IN ('scantron','printed_mcq','mixed','open_ended')",
            name="valid_submission_paper_type",
        ),
        CheckConstraint(
            "status IN ('pending','processing','pending_review','approved','rejected','failed')",
            name="valid_submission_status",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ScannedPage  (one physical or digital page within a submission)
# ─────────────────────────────────────────────────────────────────────────────

class ScannedPage(Base):
    """
    Represents a single page of an AssessmentSubmission.

    storage_key is a path or reference to the stored file — NEVER the raw
    binary content.  Raw images are kept out of the database and out of
    LangGraph state to protect student privacy and to avoid payload bloat.

    quality_warnings is a JSON list of warning codes, e.g.:
        ["blur", "low_lighting", "perspective_distortion"]
    """
    __tablename__ = "scanned_pages"

    page_id:                 Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id:           Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("assessment_submissions.submission_id", ondelete="CASCADE"), nullable=False, index=True)
    session_id:              Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("marking_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:               Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number:             Mapped[int]            = mapped_column(Integer, nullable=False)
    expected_page_count:     Mapped[int]            = mapped_column(Integer, default=1)
    storage_key:             Mapped[str]            = mapped_column(String(500), nullable=False)
    original_filename:       Mapped[str | None]     = mapped_column(String(255))
    file_type:               Mapped[str | None]     = mapped_column(String(20))
    source:                  Mapped[str]            = mapped_column(String(50), default="upload")
    quality_score:           Mapped[float | None]   = mapped_column(Float)
    quality_warnings:        Mapped[list]           = mapped_column(JSON, default=list)
    retake_required:         Mapped[bool]           = mapped_column(Boolean, default=False)
    accepted_for_processing: Mapped[bool]           = mapped_column(Boolean, default=True)
    page_status:             Mapped[str]            = mapped_column(String(50), default="pending")
    upload_complete:         Mapped[bool]           = mapped_column(Boolean, default=True)
    created_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "source IN ('smart_scan','upload','office_scanner')",
            name="valid_page_source",
        ),
        CheckConstraint(
            "page_status IN ('pending','accepted','rejected','retake_required')",
            name="valid_page_status",
        ),
        UniqueConstraint("submission_id", "page_number", name="uq_page_per_submission"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# QuestionResponse  (one question's extracted answer and proposed mark)
# ─────────────────────────────────────────────────────────────────────────────

class QuestionResponse(Base):
    """
    Stores the per-question result for a single AssessmentSubmission.

    grading_method records which pipeline produced the proposed mark:
        omr            → bubble-sheet recognition, no LLM
        vision         → computer-vision MCQ detection, no LLM
        deterministic  → rule-based comparison, no LLM
        rubric_ai      → rubric-aware LLM grading

    All proposed marks are status='proposed' until the teacher explicitly
    approves or overrides them.  status='unresolved' blocks final approval.

    evidence and rubric_result are JSON blobs so the review UI can show
    exactly what the AI (or OCR) detected without a separate API call.
    """
    __tablename__ = "question_responses"

    response_id:             Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id:           Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("assessment_submissions.submission_id", ondelete="CASCADE"), nullable=False, index=True)
    session_id:              Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("marking_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:               Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    question_number:         Mapped[int]            = mapped_column(Integer, nullable=False)
    question_type:           Mapped[str]            = mapped_column(String(50), default="short_answer")
    extracted_answer:        Mapped[str | None]     = mapped_column(Text)
    extraction_confidence:   Mapped[float | None]   = mapped_column(Float)
    source_page:             Mapped[int | None]     = mapped_column(Integer)
    source_reference:        Mapped[str | None]     = mapped_column(String(255))
    correct_answer:          Mapped[str | None]     = mapped_column(String(500))
    proposed_marks:          Mapped[float | None]   = mapped_column(Float)
    max_marks:               Mapped[float | None]   = mapped_column(Float)
    teacher_final_marks:     Mapped[float | None]   = mapped_column(Float)
    grading_method:          Mapped[str]            = mapped_column(String(50), default="deterministic")
    confidence:              Mapped[float | None]   = mapped_column(Float)
    ambiguous_mark:          Mapped[bool]           = mapped_column(Boolean, default=False)
    requires_teacher_review: Mapped[bool]           = mapped_column(Boolean, default=True)
    teacher_overridden:      Mapped[bool]           = mapped_column(Boolean, default=False)
    teacher_comment:         Mapped[str | None]     = mapped_column(Text)
    evidence:                Mapped[dict]           = mapped_column(JSON, default=dict)
    rubric_result:           Mapped[dict]           = mapped_column(JSON, default=dict)
    manual_edit_required:    Mapped[bool]           = mapped_column(Boolean, default=False)
    status:                  Mapped[str]            = mapped_column(String(50), default="proposed")
    created_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:              Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "grading_method IN ('omr','vision','deterministic','rubric_ai')",
            name="valid_grading_method",
        ),
        CheckConstraint(
            "status IN ('unresolved','proposed','teacher_approved','teacher_rejected')",
            name="valid_response_status",
        ),
        UniqueConstraint("submission_id", "question_number", name="uq_question_per_submission"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 10D — Operational Daily Sessions
# ─────────────────────────────────────────────────────────────────────────────

class OperationalSchoolDay(Base):
    """
    Represents the school's operational snapshot for a specific calendar date.

    Identity: one row per (tenant, timetable, school_date).

    timetable_id is the primary operational scope — not the version.
    If V2 supersedes V1 for the same scope and date, timetable_version_id
    (provenance) changes but the OSD row identity is preserved.

    is_teaching_day is False for weekends, non-operational weekdays, and dates
    where an approved calendar event overrides to non_teaching_day.
    timetable_day_key is the solver-convention key (e.g. 'd0') mapping this
    date to the correct weekly timetable column.  NULL when not a teaching day.
    """
    __tablename__ = "operational_school_days"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    timetable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetables.id", ondelete="CASCADE"), nullable=False, index=True)
    timetable_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True, index=True)
    school_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    timetable_day_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bell_schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bell_schedules.id", ondelete="SET NULL"), nullable=True, index=True)
    is_teaching_day: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    non_teaching_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    calendar_override_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operational_calendar_events.id", ondelete="SET NULL"), nullable=True)
    calendar_event_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calendar_event_versions.id", ondelete="SET NULL"), nullable=True)
    materialization_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", index=True)
    materialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_operational_school_days_day_of_week"),
        CheckConstraint(
            "materialization_status IN ('pending','complete','stale')",
            name="ck_operational_school_days_mat_status",
        ),
        CheckConstraint(
            "non_teaching_reason IS NULL OR non_teaching_reason IN ("
            "'not_operational_weekday','calendar_non_teaching','public_holiday',"
            "'school_holiday','cancelled','other')",
            name="ck_osd_non_teaching_reason",
        ),
        UniqueConstraint("tenant_id", "timetable_id", "school_date", name="uq_operational_school_days_timetable_date"),
        Index("ix_operational_school_days_tenant_date", "tenant_id", "school_date"),
    )


class DailySession(Base):
    """
    One materialized session slot for a specific school date.

    Derived from a TimetableVersionAssignment for the matching timetable_day_key,
    enriched with resolved bell-schedule clock times.

    class_facing_session_key: deterministic class-facing identity.
    Ordinary sessions get a unique key per (date, class, period).
    All parallel children of the same block at the same period share
    the same class_facing_session_key so that attendance creates only
    one class register per slot regardless of parallel teacher splits.

    session_status='cancelled' with override_reason='logical_period_unavailable'
    indicates the logical period does not exist in the effective bell profile.
    Such sessions must not be attendance-eligible.

    parallel_block_id / parallel_child_id are passed through from canonical
    assignment data — no subject-name heuristics are applied.
    """
    __tablename__ = "daily_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    operational_school_day_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("operational_school_days.id", ondelete="CASCADE"), nullable=False, index=True)
    timetable_version_assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("timetable_version_assignments.id", ondelete="SET NULL"), nullable=True, index=True)
    school_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    class_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subject_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teacher_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    room_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bell_period_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bell_schedule_periods.id", ondelete="SET NULL"), nullable=True)
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    period_end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    periods_span: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    parallel_block_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    parallel_child_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    session_key: Mapped[str] = mapped_column(String(260), nullable=False)
    class_facing_session_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="scheduled", index=True)
    override_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("periods_span > 0", name="ck_daily_sessions_periods_span_positive"),
        CheckConstraint("period_number > 0", name="ck_daily_sessions_period_number_positive"),
        CheckConstraint(
            "session_status IN ('scheduled','cancelled','modified')",
            name="ck_daily_sessions_session_status",
        ),
        UniqueConstraint("tenant_id", "operational_school_day_id", "session_key", name="uq_daily_sessions_osd_session_key"),
        Index("ix_daily_sessions_tenant_date_class", "tenant_id", "school_date", "class_id"),
        Index("ix_daily_sessions_tenant_date_teacher", "tenant_id", "school_date", "teacher_id"),
    )


# -- Parent Experience models (Phase 8.1) -------------------------------------
# Explicit import ensures all parent tables are registered with Base.metadata.
# Uses a named alias to prevent wildcard import and circular-import risks.
import shared.db.parent_models as _parent_models  # noqa: F401

# -- Weekly Reports models (Phase 8.4) ----------------------------------------
import shared.db.weekly_report_models as _weekly_report_models  # noqa: F401
