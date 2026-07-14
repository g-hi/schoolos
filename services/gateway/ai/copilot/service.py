from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from services.gateway.ai.copilot.checkpoints.base import CheckpointStore
from services.gateway.ai.copilot.checkpoints.memory import InMemoryCheckpointStore
from services.gateway.ai.copilot.nodes.intent_router import normalize_intent
from services.gateway.ai.copilot.providers.factory import get_provider
from services.gateway.ai.copilot.registry import WorkflowRegistry
from services.gateway.ai.copilot.schemas import CopilotExecutionInfo, CopilotResponse
from services.gateway.ai.copilot.state import SchoolOSAIState, ensure_state_defaults
from shared.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class CopilotOrchestratorService:
    def __init__(self) -> None:
        self._registry = WorkflowRegistry()
        self._memory_checkpoint_store = InMemoryCheckpointStore(retention_days=settings.copilot_checkpoint_retention_days)

    async def run(
        self,
        *,
        db: AsyncSession | None,
        tenant_id: str,
        tenant_slug: str,
        school_context: dict[str, Any],
        user_id: str,
        user_role: str,
        intent: str,
        message: str,
        structured_input: dict[str, Any],
        conversation_id: str | None,
    ) -> CopilotResponse:
        request_id = str(uuid.uuid4())
        normalized_intent = normalize_intent(intent)
        state: SchoolOSAIState = ensure_state_defaults(
            {
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "user_id": user_id,
                "user_role": user_role,
                "conversation_id": conversation_id or str(uuid.uuid4()),
                "request_id": request_id,
                "intent": normalized_intent,
                "original_message": message,
                "structured_input": structured_input,
                "school_context": school_context,
                "max_retries": settings.copilot_max_retries,
            }
        )

        response = await self._execute_graph(state)
        store = self._resolve_checkpoint_store(db)
        await store.save(
            request_id=request_id,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            state=state,
        )
        return response

    async def continue_run(
        self,
        *,
        db: AsyncSession | None,
        tenant_id: str,
        tenant_slug: str,
        request_id: str,
        message: str | None,
        structured_input: dict[str, Any],
    ) -> CopilotResponse:
        store = self._resolve_checkpoint_store(db)
        previous = await store.get(request_id=request_id, tenant_id=tenant_id, tenant_slug=tenant_slug)
        if not previous:
            return self._error_response(request_id, "No workflow state found for this request.")

        merged_input = dict(previous.get("structured_input", {}))
        merged_input.update(structured_input or {})

        if message and "duration_minutes" not in merged_input:
            try:
                merged_input["duration_minutes"] = int(message.strip())
            except ValueError:
                # Keep message as context; do not force conversion if it is not numeric.
                previous["original_message"] = message

        previous["structured_input"] = merged_input
        previous.pop("final_response", None)
        previous["missing_fields"] = []
        previous["clarification_question"] = ""
        previous["tenant_id"] = tenant_id
        previous["tenant_slug"] = tenant_slug
        previous["intent"] = normalize_intent(previous.get("intent", ""))

        response = await self._execute_graph(previous)
        await store.update(request_id=request_id, tenant_id=tenant_id, tenant_slug=tenant_slug, state=previous)
        return response

    async def approve(
        self,
        *,
        db: AsyncSession | None,
        tenant_id: str,
        tenant_slug: str,
        request_id: str,
        approved: bool,
        notes: str | None,
    ) -> CopilotResponse:
        store = self._resolve_checkpoint_store(db)
        previous = await store.get(request_id=request_id, tenant_id=tenant_id, tenant_slug=tenant_slug)
        if not previous:
            return self._error_response(request_id, "No workflow state found for this request.")

        final = previous.get("final_response", {})
        if final.get("status") != "pending_review":
            return self._error_response(request_id, "This request is not awaiting approval.")

        workflow = final.get("execution", {}).get("workflow") or previous.get("intent") or "lesson_planning"
        status = "approved" if approved else "pending_review"
        if approved:
            if workflow == "assessment_generation":
                message = "Assessment approved."
            elif workflow == "lesson_planning":
                message = "Lesson plan approved."
            else:
                message = "Generated output approved."
        else:
            message = "Approval is still pending teacher review."

        if notes:
            message = f"{message} Notes: {notes}"

        approved_response = CopilotResponse(
            status=status,  # type: ignore[arg-type]
            request_id=request_id,
            conversation_id=previous.get("conversation_id"),
            intent=previous.get("intent"),
            message=message,
            missing_fields=[],
            result=final.get("result"),
            execution=CopilotExecutionInfo(
                workflow=workflow,
                current_step="approved" if approved else "human_approval",
                validation_passed=bool(previous.get("validation_result", {}).get("passed")),
                retry_count=previous.get("retry_count", 0),
                tenant_slug=previous.get("tenant_slug"),
            ),
        )

        previous["approval_status"] = status
        previous["final_response"] = approved_response.model_dump()
        previous["tenant_id"] = tenant_id
        previous["tenant_slug"] = tenant_slug
        await store.update(request_id=request_id, tenant_id=tenant_id, tenant_slug=tenant_slug, state=previous)
        return approved_response

    async def status(
        self,
        *,
        db: AsyncSession | None,
        tenant_id: str,
        tenant_slug: str,
        request_id: str,
    ) -> CopilotResponse:
        store = self._resolve_checkpoint_store(db)
        previous = await store.get(request_id=request_id, tenant_id=tenant_id, tenant_slug=tenant_slug)
        if not previous:
            return self._error_response(request_id, "No workflow state found for this request.")

        final = previous.get("final_response")
        if not final:
            return self._error_response(request_id, "Workflow has not produced a final response yet.")

        return CopilotResponse.model_validate(final)

    async def _execute_graph(self, state: SchoolOSAIState) -> CopilotResponse:
        provider = get_provider()

        requested_workflow = normalize_intent(state.get("intent", "lesson_planning"))
        state["intent"] = requested_workflow
        registration = self._registry.get_enabled(requested_workflow)
        if not registration:
            registration = self._registry.get_enabled("lesson_planning")

        if not registration or not registration.builder:
            return self._error_response(state["request_id"], "No enabled workflow is available.")

        try:
            graph = registration.builder(provider)
            result_state = await graph.ainvoke(state)
            state.update(result_state)
        except Exception as exc:
            state.setdefault("errors", []).append(str(exc))
            return self._error_response(
                state["request_id"],
                "Provider or workflow execution failed.",
                tenant_slug=state.get("tenant_slug"),
            )

        final = state.get("final_response")
        if not final:
            return self._error_response(
                state["request_id"],
                "Workflow finished without a final response.",
                tenant_slug=state.get("tenant_slug"),
            )

        return CopilotResponse.model_validate(final)

    def _error_response(self, request_id: str, message: str, tenant_slug: str | None = None) -> CopilotResponse:
        return CopilotResponse(
            status="error",
            request_id=request_id,
            message=message,
            execution=CopilotExecutionInfo(
                workflow="fallback",
                current_step="error",
                validation_passed=False,
                retry_count=0,
                tenant_slug=tenant_slug,
            ),
        )

    def _resolve_checkpoint_store(self, db: AsyncSession | None) -> CheckpointStore:
        if settings.copilot_checkpoint_backend.lower().strip() == "postgres" and db is not None:
            from services.gateway.ai.copilot.checkpoints.postgres import PostgresCheckpointStore

            return PostgresCheckpointStore(db=db, retention_days=settings.copilot_checkpoint_retention_days)
        return self._memory_checkpoint_store
