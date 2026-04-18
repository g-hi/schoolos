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
    UUID,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
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

    __table_args__ = (
        UniqueConstraint("tenant_id", "grade", "section", "academic_year", name="uq_class_per_tenant"),
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

    student_id:    Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    parent_id:     Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id",    ondelete="CASCADE"), primary_key=True)
    relation_type: Mapped[str]       = mapped_column(String(50), default="parent")  # mother/father/guardian

    student: Mapped["Student"] = relationship("Student", back_populates="parents")
    parent:  Mapped["User"]    = relationship("User")


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
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    recipient: Mapped["User"]           = relationship("User", foreign_keys=[recipient_id])
    student:   Mapped["Student | None"] = relationship("Student")


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
    released_at:       Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    notes:             Mapped[str | None]       = mapped_column(Text, nullable=True)

    # Relationships
    parent:  Mapped["User"]           = relationship("User", foreign_keys=[parent_id])
    student: Mapped["Student"]        = relationship("Student")
    klass:   Mapped["Class"]          = relationship("Class")
    teacher: Mapped["Teacher | None"] = relationship("Teacher", foreign_keys=[teacher_id])


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
