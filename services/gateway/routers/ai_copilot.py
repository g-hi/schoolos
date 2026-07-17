from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.copilot.service import CopilotOrchestratorService
from services.gateway.ai.copilot.schemas import (
    CopilotApproveRequest,
    CopilotContinueRequest,
    CopilotResponse,
    CopilotRunRequest,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Tenant

router = APIRouter(prefix="/ai/copilot", tags=["AI Copilot"])
service = CopilotOrchestratorService()
_ALLOWED_ROLES = {"teacher", "principal", "school_admin", "staff"}


def _resolve_user_context(request: Request) -> tuple[str, str]:
    user_id = request.headers.get("X-User-Id", "teacher-local")
    user_role = request.headers.get("X-User-Role", "teacher").lower().strip()

    if user_role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this AI workflow.",
        )

    return user_id, user_role


@router.post("/run", response_model=CopilotResponse, summary="Run tenant-aware AI workflow")
async def run_copilot(
    body: CopilotRunRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    user_id, user_role = _resolve_user_context(request)

    response = await service.run(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        school_context={
            "school_name": tenant.name,
            "term": (tenant.settings or {}).get("current_term", "Current term"),
        },
        user_id=user_id,
        user_role=user_role,
        intent=body.intent,
        message=body.message,
        structured_input=body.structured_input,
        conversation_id=body.conversation_id,
    )
    return response


@router.post("/continue", response_model=CopilotResponse, summary="Continue a workflow after clarification")
async def continue_copilot(
    body: CopilotContinueRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    user_id, user_role = _resolve_user_context(request)
    return await service.continue_run(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        request_id=body.request_id,
        message=body.message,
        structured_input=body.structured_input,
        current_user_id=user_id,
        current_user_role=user_role,
    )


@router.post("/approve", response_model=CopilotResponse, summary="Approve generated AI output")
async def approve_copilot(
    body: CopilotApproveRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    user_id, user_role = _resolve_user_context(request)
    return await service.approve(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        request_id=body.request_id,
        approved=body.approved,
        notes=body.notes,
        current_user_id=user_id,
        current_user_role=user_role,
    )


@router.get("/status/{request_id}", response_model=CopilotResponse, summary="Get workflow status")
async def copilot_status(
    request_id: str,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    if not request_id.strip():
        return service._error_response(str(uuid.uuid4()), "Request ID is required.")
    user_id, user_role = _resolve_user_context(request)
    return await service.status(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        request_id=request_id,
        current_user_id=user_id,
        current_user_role=user_role,
    )
