from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.routers import student_enrollments as enrollments_router
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    AccountInvitation,
    Class,
    GradeLevel,
    Student,
    StudentEnrollment,
    StudentParent,
    Teacher,
    Tenant,
    User,
)

router = APIRouter(prefix="/leadership/people", tags=["People"])

SUPPORTED_RELATIONSHIP_TYPES = {"mother", "father", "guardian", "sponsor", "other"}
INVITABLE_ROLES = {"teacher", "parent"}


class TeacherProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    email: str
    employee_id: str | None = None
    max_weekly_hours: int = 20
    send_invitation: bool = True


class ParentRelationshipSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID
    relationship_type: str = "guardian"
    is_primary: bool = False


class ParentProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    email: str
    phone: str | None = None
    send_invitation: bool = True
    relationships: list[ParentRelationshipSeed] = []


class StudentRelationshipSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID
    relationship_type: str = "guardian"
    is_primary: bool = False


class InitialEnrollmentSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_id: uuid.UUID
    enrolled_on: date_type


class StudentProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    class_id: uuid.UUID
    student_code: str | None = None
    relationships: list[StudentRelationshipSeed] = []
    initial_enrollment: InitialEnrollmentSeed | None = None


class UserStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool
    reason: str | None = None


class InviteUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_in_hours: int = 168


class RevokeInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _relationship_is_active_clause():
    # Compatibility: legacy rows created before lifecycle metadata existed are
    # considered active when is_active is NULL.
    return or_(StudentParent.is_active.is_(True), StudentParent.is_active.is_(None))


def _invitation_status(invitation: AccountInvitation | None) -> str | None:
    if invitation is None:
        return None
    now = _now_utc()
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.expires_at <= now:
        return "expired"
    return "pending"


async def _issue_invitation(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user: User,
    actor_id: uuid.UUID,
    expires_in_hours: int = 168,
    reissue_if_expired: bool = True,
) -> tuple[AccountInvitation, str]:
    if user.role not in INVITABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invitations are allowed only for teacher or parent accounts.")

    user_email = _normalize_email(user.email)
    if not user_email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Target account email is required.")

    now = _now_utc()
    pending = (
        await db.execute(
            select(AccountInvitation)
            .where(
                AccountInvitation.tenant_id == tenant_id,
                AccountInvitation.user_id == user.id,
                AccountInvitation.accepted_at.is_(None),
                AccountInvitation.revoked_at.is_(None),
            )
            .order_by(AccountInvitation.created_at.desc())
        )
    ).scalars().first()

    if pending is not None:
        if pending.expires_at > now:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A pending invitation already exists for this account.")
        if reissue_if_expired:
            pending.revoked_at = now
        else:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An expired pending invitation exists and must be revoked first.")

    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invitation = AccountInvitation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user.id,
        invited_email=user_email,
        role=user.role,
        token_hash=token_hash,
        expires_at=now + timedelta(hours=max(1, min(expires_in_hours, 24 * 30))),
        accepted_at=None,
        revoked_at=None,
        created_by_user_id=actor_id,
    )
    db.add(invitation)

    await log_action(
        db=db,
        tenant_id=tenant_id,
        action="invitation.issued",
        entity_type="AccountInvitation",
        entity_id=invitation.id,
        actor_id=actor_id,
        details={
            "user_id": str(user.id),
            "role": user.role,
            "expires_at": invitation.expires_at.isoformat(),
        },
    )

    return invitation, raw_token


async def _latest_invitation_by_user(db: AsyncSession, tenant_id: uuid.UUID) -> dict[uuid.UUID, AccountInvitation]:
    rows = (
        await db.execute(
            select(AccountInvitation)
            .where(AccountInvitation.tenant_id == tenant_id)
            .order_by(AccountInvitation.created_at.desc())
        )
    ).scalars().all()
    by_user: dict[uuid.UUID, AccountInvitation] = {}
    for row in rows:
        by_user.setdefault(row.user_id, row)
    return by_user


@router.get("", summary="Unified people directory")
async def list_people(
    role: str | None = Query(default=None),
    status: str | None = Query(default=None, description="active|inactive"),
    search: str | None = Query(default=None),
    has_account: bool | None = Query(default=None),
    profile_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    invitation_by_user = await _latest_invitation_by_user(db, tenant.id)

    rows: list[dict] = []

    teacher_rows = (
        await db.execute(
            select(Teacher, User)
            .join(User, User.id == Teacher.user_id)
            .where(Teacher.tenant_id == tenant.id, User.tenant_id == tenant.id)
        )
    ).all()
    for teacher, user in teacher_rows:
        inv = invitation_by_user.get(user.id)
        row = {
            "person_id": str(teacher.id),
            "user_id": str(user.id),
            "display_name": user.name,
            "email": user.email,
            "role": user.role,
            "profile_type": "teacher",
            "is_active": bool(user.is_active),
            "invitation_status": _invitation_status(inv),
            "profile_consistency_status": "ok",
            "created_at": user.created_at,
            "has_account": True,
        }
        rows.append(row)

    parent_rows = (
        await db.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.role == "parent",
            )
        )
    ).scalars().all()
    for user in parent_rows:
        inv = invitation_by_user.get(user.id)
        rows.append(
            {
                "person_id": str(user.id),
                "user_id": str(user.id),
                "display_name": user.name,
                "email": user.email,
                "role": user.role,
                "profile_type": "parent",
                "is_active": bool(user.is_active),
                "invitation_status": _invitation_status(inv),
                "profile_consistency_status": "ok",
                "created_at": user.created_at,
                "has_account": True,
            }
        )

    student_rows = (
        await db.execute(
            select(Student).where(Student.tenant_id == tenant.id)
        )
    ).scalars().all()
    for student in student_rows:
        rows.append(
            {
                "person_id": str(student.id),
                "user_id": None,
                "display_name": student.name,
                "email": None,
                "role": "student",
                "profile_type": "student",
                "is_active": True,
                "invitation_status": None,
                "profile_consistency_status": "ok",
                "created_at": student.created_at,
                "has_account": False,
            }
        )

    # Teacher role users without teacher profile.
    teacher_profile_user_ids = {teacher.user_id for teacher, _ in teacher_rows}
    orphan_users = (
        await db.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.role.in_(["teacher", "parent"]),
            )
        )
    ).scalars().all()
    for user in orphan_users:
        if user.role == "teacher" and user.id not in teacher_profile_user_ids:
            inv = invitation_by_user.get(user.id)
            rows.append(
                {
                    "person_id": str(user.id),
                    "user_id": str(user.id),
                    "display_name": user.name,
                    "email": user.email,
                    "role": user.role,
                    "profile_type": "user_only",
                    "is_active": bool(user.is_active),
                    "invitation_status": _invitation_status(inv),
                    "profile_consistency_status": "missing_teacher_profile",
                    "created_at": user.created_at,
                    "has_account": True,
                }
            )

    if role:
        rows = [r for r in rows if r["role"] == role]
    if status:
        target_active = status == "active"
        rows = [r for r in rows if bool(r["is_active"]) is target_active]
    if has_account is not None:
        rows = [r for r in rows if bool(r["has_account"]) is has_account]
    if profile_status:
        rows = [r for r in rows if r["profile_consistency_status"] == profile_status]
    if search:
        q = search.strip().lower()
        rows = [
            r
            for r in rows
            if q in (r.get("display_name") or "").lower()
            or q in (r.get("email") or "").lower()
        ]

    rows.sort(key=lambda r: (r["created_at"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": page,
    }


@router.get("/summary", summary="People and invitation summary diagnostics")
async def people_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    now = _now_utc()

    total_active_users = await db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id, User.is_active.is_(True))) or 0
    active_teachers = await db.scalar(
        select(func.count(Teacher.id)).join(User, User.id == Teacher.user_id).where(Teacher.tenant_id == tenant.id, User.is_active.is_(True))
    ) or 0
    active_parents = await db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id, User.role == "parent", User.is_active.is_(True))) or 0
    active_students = await db.scalar(select(func.count(Student.id)).where(Student.tenant_id == tenant.id)) or 0

    teachers_without_user_accounts = await db.scalar(
        select(func.count(Teacher.id)).outerjoin(User, User.id == Teacher.user_id).where(Teacher.tenant_id == tenant.id, User.id.is_(None))
    ) or 0

    # Parent profile is account-backed in current data model.
    parents_without_user_accounts = 0

    users_without_matching_role_profiles = await db.scalar(
        select(func.count(User.id)).where(
            User.tenant_id == tenant.id,
            User.role == "teacher",
            ~User.id.in_(select(Teacher.user_id).where(Teacher.tenant_id == tenant.id)),
        )
    ) or 0

    inactive_users_with_active_profiles = await db.scalar(
        select(func.count(Teacher.id))
        .join(User, User.id == Teacher.user_id)
        .where(Teacher.tenant_id == tenant.id, User.is_active.is_(False))
    ) or 0

    pending_invitations = await db.scalar(
        select(func.count(AccountInvitation.id)).where(
            AccountInvitation.tenant_id == tenant.id,
            AccountInvitation.accepted_at.is_(None),
            AccountInvitation.revoked_at.is_(None),
            AccountInvitation.expires_at > now,
        )
    ) or 0

    expired_invitations = await db.scalar(
        select(func.count(AccountInvitation.id)).where(
            AccountInvitation.tenant_id == tenant.id,
            AccountInvitation.accepted_at.is_(None),
            AccountInvitation.revoked_at.is_(None),
            AccountInvitation.expires_at <= now,
        )
    ) or 0

    accepted_invitations = await db.scalar(
        select(func.count(AccountInvitation.id)).where(
            AccountInvitation.tenant_id == tenant.id,
            AccountInvitation.accepted_at.is_not(None),
        )
    ) or 0

    revoked_invitations = await db.scalar(
        select(func.count(AccountInvitation.id)).where(
            AccountInvitation.tenant_id == tenant.id,
            AccountInvitation.revoked_at.is_not(None),
        )
    ) or 0

    return {
        "total_active_users": total_active_users,
        "active_teachers": active_teachers,
        "active_parents": active_parents,
        "active_students": active_students,
        "teachers_without_user_accounts": teachers_without_user_accounts,
        "parents_without_user_accounts": parents_without_user_accounts,
        "users_without_matching_role_profiles": users_without_matching_role_profiles,
        "inactive_users_with_active_profiles": inactive_users_with_active_profiles,
        "pending_invitations": pending_invitations,
        "expired_invitations": expired_invitations,
        "accepted_invitations": accepted_invitations,
        "revoked_invitations": revoked_invitations,
    }


@router.post("/teachers", summary="Provision teacher account and profile")
async def provision_teacher(
    body: TeacherProvisionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    email = _normalize_email(body.email)
    if not email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Email is required.")

    existing = await db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
    if existing is not None:
        if existing.role != "teacher":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already belongs to another role.")
        existing_teacher = await db.scalar(select(Teacher).where(Teacher.tenant_id == tenant.id, Teacher.user_id == existing.id))
        if existing_teacher is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Teacher already provisioned for this account.")
        user = existing
    else:
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=body.display_name.strip(),
            email=email,
            role="teacher",
            is_active=False,
            password_hash=None,
            preferred_channel="email",
        )
        db.add(user)
        await db.flush()

    teacher = Teacher(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=user.id,
        employee_id=body.employee_id,
        max_weekly_hours=body.max_weekly_hours,
    )
    db.add(teacher)

    one_time_token: str | None = None
    invitation: AccountInvitation | None = None
    if body.send_invitation:
        invitation, one_time_token = await _issue_invitation(
            db=db,
            tenant_id=tenant.id,
            user=user,
            actor_id=actor.id,
        )

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="teacher.provisioned",
        entity_type="Teacher",
        entity_id=teacher.id,
        actor_id=actor.id,
        details={"user_id": str(user.id), "email": email},
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "teacher_id": str(teacher.id),
        "user_id": str(user.id),
        "email": email,
        "invitation_id": str(invitation.id) if invitation else None,
        "activation_token": one_time_token,
        "activation_token_one_time": bool(one_time_token),
    }


@router.post("/parents", summary="Provision parent account")
async def provision_parent(
    body: ParentProvisionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    email = _normalize_email(body.email)
    if not email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Email is required.")

    existing = await db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
    if existing is not None and existing.role != "parent":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already belongs to another role.")

    if existing is None:
        parent_user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=body.display_name.strip(),
            email=email,
            phone=body.phone,
            role="parent",
            is_active=False,
            password_hash=None,
            preferred_channel="email",
        )
        db.add(parent_user)
        await db.flush()
    else:
        parent_user = existing

    for rel in body.relationships:
        if rel.relationship_type not in SUPPORTED_RELATIONSHIP_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid relationship_type.")

        student = await db.scalar(select(Student).where(Student.id == rel.student_id, Student.tenant_id == tenant.id))
        if student is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found for relationship seed.")

        duplicate = await db.scalar(
            select(StudentParent.student_id).where(
                StudentParent.student_id == student.id,
                StudentParent.parent_id == parent_user.id,
                _relationship_is_active_clause(),
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active parent/student relationship.")

        db.add(
            StudentParent(
                student_id=student.id,
                parent_id=parent_user.id,
                relation_type=rel.relationship_type,
                is_primary=rel.is_primary,
                is_active=True,
            )
        )

    one_time_token: str | None = None
    invitation: AccountInvitation | None = None
    if body.send_invitation:
        invitation, one_time_token = await _issue_invitation(
            db=db,
            tenant_id=tenant.id,
            user=parent_user,
            actor_id=actor.id,
        )

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="parent.provisioned",
        entity_type="User",
        entity_id=parent_user.id,
        actor_id=actor.id,
        details={"email": email, "seed_relationships": len(body.relationships)},
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "parent_user_id": str(parent_user.id),
        "email": email,
        "invitation_id": str(invitation.id) if invitation else None,
        "activation_token": one_time_token,
        "activation_token_one_time": bool(one_time_token),
    }


@router.post("/students", summary="Provision student profile")
async def provision_student(
    body: StudentProvisionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    klass = await db.scalar(select(Class).where(Class.id == body.class_id, Class.tenant_id == tenant.id))
    if klass is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found.")

    student = Student(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        class_id=klass.id,
        name=body.name.strip(),
        student_code=body.student_code,
    )
    db.add(student)
    await db.flush()

    for rel in body.relationships:
        if rel.relationship_type not in SUPPORTED_RELATIONSHIP_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid relationship_type.")

        parent_user = await db.scalar(
            select(User).where(
                User.id == rel.parent_id,
                User.tenant_id == tenant.id,
                User.role == "parent",
            )
        )
        if parent_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent not found.")

        duplicate = await db.scalar(
            select(StudentParent.student_id).where(
                StudentParent.student_id == student.id,
                StudentParent.parent_id == parent_user.id,
                _relationship_is_active_clause(),
            )
        )
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active parent/student relationship.")

        db.add(
            StudentParent(
                student_id=student.id,
                parent_id=parent_user.id,
                relation_type=rel.relationship_type,
                is_primary=rel.is_primary,
                is_active=True,
            )
        )

    enrollment_id: str | None = None
    if body.initial_enrollment is not None:
        if body.initial_enrollment.class_id != body.class_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="initial_enrollment.class_id must match class_id.")

        canonical_class = await enrollments_router._load_canonical_class(  # noqa: SLF001
            db=db,
            tenant_id=tenant.id,
            class_id=body.initial_enrollment.class_id,
        )
        year = await enrollments_router._load_academic_year(  # noqa: SLF001
            db=db,
            tenant_id=tenant.id,
            academic_year_id=canonical_class.academic_year_id,
        )
        grade = await enrollments_router._load_grade_level(  # noqa: SLF001
            db=db,
            tenant_id=tenant.id,
            grade_level_id=canonical_class.grade_level_id,
        )
        enrollments_router._validate_enrolled_on_in_academic_year(  # noqa: SLF001
            enrolled_on=body.initial_enrollment.enrolled_on,
            academic_year=year,
        )

        enrollment = StudentEnrollment(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            academic_year_id=year.id,
            student_id=student.id,
            class_id=canonical_class.id,
            grade_level_id=grade.id,
            status="active",
            enrolled_on=body.initial_enrollment.enrolled_on,
            exited_on=None,
            exit_reason=None,
        )
        db.add(enrollment)
        student.class_id = canonical_class.id
        enrollment_id = str(enrollment.id)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="student.provisioned",
        entity_type="Student",
        entity_id=student.id,
        actor_id=actor.id,
        details={"class_id": str(student.class_id), "relationships": len(body.relationships)},
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "student_id": str(student.id),
        "class_id": str(student.class_id),
        "enrollment_id": enrollment_id,
    }


@router.patch("/users/{user_id}/status", summary="Activate or deactivate account")
async def update_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    target = await db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant.id))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if actor.id == target.id and not body.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You cannot deactivate your own account.")

    if not body.is_active and target.role == "principal" and target.is_active:
        active_principals = await db.scalar(
            select(func.count(User.id)).where(
                User.tenant_id == tenant.id,
                User.role == "principal",
                User.is_active.is_(True),
            )
        ) or 0
        if active_principals <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot deactivate the last active principal.")

    target.is_active = body.is_active

    now = _now_utc()
    if not body.is_active:
        pending = (
            await db.execute(
                select(AccountInvitation).where(
                    AccountInvitation.tenant_id == tenant.id,
                    AccountInvitation.user_id == target.id,
                    AccountInvitation.accepted_at.is_(None),
                    AccountInvitation.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        for inv in pending:
            inv.revoked_at = now

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="account.activated" if body.is_active else "account.deactivated",
        entity_type="User",
        entity_id=target.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )

    await db.commit()
    return {"user_id": str(target.id), "is_active": bool(target.is_active)}


@router.post("/users/{user_id}/invite", summary="Issue account invitation")
async def invite_user(
    user_id: uuid.UUID,
    body: InviteUserRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    user = await db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant.id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    email = _normalize_email(user.email)
    if not email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Target user must have an email.")

    invitation, token = await _issue_invitation(
        db=db,
        tenant_id=tenant.id,
        user=user,
        actor_id=actor.id,
        expires_in_hours=body.expires_in_hours,
        reissue_if_expired=True,
    )

    await db.commit()

    return {
        "invitation_id": str(invitation.id),
        "user_id": str(user.id),
        "role": user.role,
        "expires_at": invitation.expires_at,
        "activation_token": token,
        "activation_token_one_time": True,
    }


@router.post("/invitations/{invitation_id}/revoke", summary="Revoke pending invitation")
async def revoke_invitation(
    invitation_id: uuid.UUID,
    body: RevokeInvitationRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    invitation = await db.scalar(
        select(AccountInvitation).where(
            AccountInvitation.id == invitation_id,
            AccountInvitation.tenant_id == tenant.id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")

    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending invitations can be revoked.")

    invitation.revoked_at = _now_utc()
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="invitation.revoked",
        entity_type="AccountInvitation",
        entity_id=invitation.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()

    return {"invitation_id": str(invitation.id), "status": "revoked"}


@router.get("/invitations", summary="List invitations")
async def list_invitations(
    status_filter: Literal["pending", "accepted", "revoked", "expired"] | None = Query(default=None, alias="status"),
    role: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(AccountInvitation, User)
            .join(User, User.id == AccountInvitation.user_id)
            .where(AccountInvitation.tenant_id == tenant.id)
            .order_by(AccountInvitation.created_at.desc())
        )
    ).all()

    now = _now_utc()
    items = []
    for inv, user in rows:
        state = _invitation_status(inv)
        if role and inv.role != role:
            continue
        if status_filter and state != status_filter:
            continue
        items.append(
            {
                "id": str(inv.id),
                "user_id": str(inv.user_id),
                "invited_email": inv.invited_email,
                "role": inv.role,
                "status": state,
                "expires_at": inv.expires_at,
                "accepted_at": inv.accepted_at,
                "revoked_at": inv.revoked_at,
                "created_at": inv.created_at,
                "is_expired": inv.accepted_at is None and inv.revoked_at is None and inv.expires_at <= now,
            }
        )

    total = len(items)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items[offset : offset + limit],
    }
