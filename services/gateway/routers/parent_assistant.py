from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.copilot.schemas import CopilotResponse
from services.gateway.ai.copilot.service import CopilotOrchestratorService
from shared.auth.dependencies import resolve_authenticated_parent
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Tenant, User

router = APIRouter(prefix="/parent/assistant", tags=["Parent Assistant"])
service = CopilotOrchestratorService()


class ParentAssistantContext(BaseModel):
    active_student_id: str | None = None


class ParentAssistantRunRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    context: ParentAssistantContext = Field(default_factory=ParentAssistantContext)


class ParentAssistantContinueRequest(BaseModel):
    request_id: str = Field(min_length=1)
    message: str | None = None
    context: ParentAssistantContext = Field(default_factory=ParentAssistantContext)


def _structured_input(context: ParentAssistantContext) -> dict[str, Any]:
    if context.active_student_id:
        return {"active_student_id": context.active_student_id}
    return {}


@router.post("/run", response_model=CopilotResponse, summary="Run the family-scoped parent assistant")
async def run_parent_assistant(
    body: ParentAssistantRunRequest,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    return await service.run(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        school_context={
            "school_name": tenant.name,
            "term": (tenant.settings or {}).get("current_term", "Current term"),
            "timezone": (tenant.settings or {}).get("timezone") or (tenant.settings or {}).get("school_timezone"),
        },
        user_id=str(parent.id),
        user_role=parent.role,
        intent="parent_assistant",
        message=body.message,
        structured_input=_structured_input(body.context),
        conversation_id=body.conversation_id,
    )


@router.post("/continue", response_model=CopilotResponse, summary="Continue the parent assistant after clarification")
async def continue_parent_assistant(
    body: ParentAssistantContinueRequest,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    return await service.continue_run(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        request_id=body.request_id,
        message=body.message,
        structured_input=_structured_input(body.context),
        current_user_id=str(parent.id),
        current_user_role=parent.role,
        expected_workflow="parent_assistant",
    )


@router.get("/status/{request_id}", response_model=CopilotResponse, summary="Get parent assistant workflow status")
async def parent_assistant_status(
    request_id: str,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    return await service.status(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        request_id=request_id,
        current_user_id=str(parent.id),
        current_user_role=parent.role,
        expected_workflow="parent_assistant",
    )