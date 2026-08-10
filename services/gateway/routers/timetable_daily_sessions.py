"""Phase 10D - Operational Daily Sessions API."""
from __future__ import annotations

import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.timetable_setup.daily_sessions import (
    DailySessionError,
    MaterializationOutcome,
    load_operational_day_with_sessions,
    materialize_operational_day,
    operational_day_to_dict,
    session_to_dict,
)
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Tenant, User


router = APIRouter(prefix="/leadership/operations/daily-sessions", tags=["Daily Sessions"])


def _ensure_principal(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if actor.role != "principal":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only principals can access daily session operations.",
        )


class MaterializeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timetable_id: uuid.UUID = Field(
        ...,
        description=(
            "UUID of the Timetable (scope entity). The effective published version "
            "for the target date is resolved automatically."
        ),
    )
    school_date: date_type = Field(..., description="Calendar date to materialize (YYYY-MM-DD).")


@router.post("/materialize", status_code=http_status.HTTP_200_OK)
async def materialize_daily_sessions(
    body: MaterializeRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Materialize OperationalSchoolDay and DailySession records for a specific date.

    The effective published timetable version is selected automatically by date
    using Phase 10C effective-version semantics. The caller provides the Timetable
    scope, not a specific version.

    Immutability contract:
    - First call: creates snapshot; returns status="created".
    - Same canonical inputs: returns existing snapshot; status="already_materialized".
    - Changed canonical inputs: returns 409 code="school_day_stale".
    """
    _ensure_principal(actor, tenant)
    await set_tenant_context(db, tenant.id)

    try:
        outcome: MaterializationOutcome = await materialize_operational_day(
            db,
            tenant_id=tenant.id,
            timetable_id=body.timetable_id,
            school_date=body.school_date,
        )
    except DailySessionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )

    if outcome.status == "created":
        await log_action(
            db,
            tenant_id=tenant.id,
            user_id=actor.id,
            action="materialize_daily_sessions",
            entity_type="operational_school_day",
            entity_id=str(outcome.osd.id),
            details={
                "timetable_id": str(body.timetable_id),
                "timetable_version_id": str(outcome.osd.timetable_version_id),
                "school_date": body.school_date.isoformat(),
                "session_count": outcome.session_count,
            },
        )

    response = operational_day_to_dict(outcome.osd, session_count=outcome.session_count)
    response["status"] = outcome.status
    return response


@router.get("", status_code=http_status.HTTP_200_OK)
async def get_daily_sessions(
    timetable_id: uuid.UUID = Query(..., description="UUID of the Timetable (scope entity)."),
    school_date: date_type = Query(..., description="Calendar date (YYYY-MM-DD)."),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retrieve the materialized OperationalSchoolDay and DailySession list.

    Returns 404 when the day has not yet been materialized.
    """
    _ensure_principal(actor, tenant)
    await set_tenant_context(db, tenant.id)

    result = await load_operational_day_with_sessions(
        db,
        tenant_id=tenant.id,
        timetable_id=timetable_id,
        school_date=school_date,
    )
    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "code": "operational_day_not_found",
                "message": (
                    f"No materialized daily sessions found for timetable "
                    f"{timetable_id} on {school_date.isoformat()}. "
                    "Call POST /materialize to generate them."
                ),
            },
        )

    osd, sessions = result
    return {
        "operational_school_day": operational_day_to_dict(osd, session_count=len(sessions)),
        "sessions": [session_to_dict(s) for s in sessions],
    }
