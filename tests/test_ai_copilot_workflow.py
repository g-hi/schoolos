import asyncio

import pytest

from services.gateway.ai.copilot.service import CopilotOrchestratorService
from shared.config import settings


@pytest.fixture
def reset_copilot_settings():
    original_retries = settings.copilot_max_retries
    original_backend = settings.copilot_checkpoint_backend
    original_retention = settings.copilot_checkpoint_retention_days
    yield
    settings.copilot_max_retries = original_retries
    settings.copilot_checkpoint_backend = original_backend
    settings.copilot_checkpoint_retention_days = original_retention


def _run_service(service: CopilotOrchestratorService, tenant_id: str, tenant_slug: str, structured_input: dict):
    return asyncio.run(
        service.run(
            db=None,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            school_context={"school_name": "Greenwood", "term": "Fall"},
            user_id="teacher-1",
            user_role="teacher",
            intent="lesson_planning",
            message="Create a Grade 5 Science lesson about ecosystems",
            structured_input=structured_input,
            conversation_id=None,
        )
    )


def _service_identity() -> dict[str, str]:
    return {"current_user_id": "teacher-1", "current_user_role": "teacher"}


def _run_assessment_service(service: CopilotOrchestratorService, tenant_id: str, tenant_slug: str, structured_input: dict):
    return asyncio.run(
        service.run(
            db=None,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            school_context={"school_name": "Greenwood", "term": "Fall"},
            user_id="teacher-1",
            user_role="teacher",
            intent="assessment_generation",
            message="Generate a Grade 5 Science quiz on ecosystems",
            structured_input=structured_input,
            conversation_id=None,
        )
    )


def _assessment_input() -> dict:
    return {
        "curriculum": "Cambridge",
        "grade": "5",
        "subject": "Science",
        "topic": "Ecosystems",
        "learning_objectives": ["Identify ecosystem components", "Explain food chains"],
        "difficulty": "Medium",
        "assessment_type": "Quiz",
        "question_types": ["Multiple Choice", "Short Answer"],
        "number_of_questions": 6,
        "total_marks": 12,
        "duration_minutes": 30,
        "language": "English",
        "special_needs": "Extra reading time",
        "teacher_notes": "Use simple scientific vocabulary",
    }


def test_checkpoint_creation(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )
    status = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            **_service_identity(),
        )
    )
    assert status.status == "pending_review"


def test_resume_after_interruption(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    first = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
        },
    )
    assert first.status == "needs_clarification"

    resumed = asyncio.run(
        service.continue_run(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=first.request_id,
            message="45",
            structured_input={"duration_minutes": 45},
            **_service_identity(),
        )
    )
    assert resumed.status == "pending_review"


def test_tenant_isolation(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    other_tenant = asyncio.run(
        service.status(
            db=None,
            tenant_id="22222222-2222-2222-2222-222222222222",
            tenant_slug="other-school",
            request_id=response.request_id,
            **_service_identity(),
        )
    )
    assert other_tenant.status == "error"


def test_approval_persistence_and_status_retrieval(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    approved = asyncio.run(
        service.approve(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            approved=True,
            notes="Looks good",
            **_service_identity(),
        )
    )
    assert approved.status == "approved"

    status_after = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            **_service_identity(),
        )
    )
    assert status_after.status == "approved"


def test_status_retrieval(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    current_status = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            **_service_identity(),
        )
    )
    assert current_status.request_id == response.request_id
    assert current_status.status == "pending_review"


def test_expired_checkpoint_handling(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    settings.copilot_checkpoint_retention_days = 0
    service = CopilotOrchestratorService()

    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    status_after_expiry = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            **_service_identity(),
        )
    )
    assert status_after_expiry.status == "error"


def test_in_memory_fallback_when_postgres_unavailable(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "postgres"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    # db=None forces fallback to in-memory store even when backend is configured as postgres.
    status = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            **_service_identity(),
        )
    )
    assert status.status == "pending_review"


def test_checkpoint_access_requires_same_user(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    denied = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            current_user_id="teacher-2",
            current_user_role="teacher",
        )
    )

    assert denied.status == "error"
    assert denied.message == "No workflow state found for this request."


def test_checkpoint_access_requires_same_role(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    denied = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            current_user_id="teacher-1",
            current_user_role="principal",
        )
    )

    assert denied.status == "error"
    assert denied.message == "No workflow state found for this request."


def test_checkpoint_access_requires_matching_workflow(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()
    response = _run_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input={
            "grade": "5",
            "subject": "Science",
            "topic": "Ecosystems",
            "duration_minutes": 45,
        },
    )

    denied = asyncio.run(
        service.status(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            request_id=response.request_id,
            expected_workflow="parent_assistant",
            **_service_identity(),
        )
    )

    assert denied.status == "error"
    assert denied.message == "No workflow state found for this request."


def test_assessment_generation_workflow(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()

    response = _run_assessment_service(
        service,
        tenant_id="11111111-1111-1111-1111-111111111111",
        tenant_slug="greenwood",
        structured_input=_assessment_input(),
    )

    assert response.status == "pending_review"
    assert response.execution.workflow == "assessment_generation"
    assert response.result is not None
    assert response.result.get("questions")
    assert response.result.get("total_marks") == 12


@pytest.mark.parametrize(
    "alias",
    ["assessment", "quiz", "worksheet"],
)
def test_assessment_aliases_route_to_assessment_generation(reset_copilot_settings, alias: str):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()

    response = asyncio.run(
        service.run(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            school_context={"school_name": "Greenwood", "term": "Fall"},
            user_id="teacher-1",
            user_role="teacher",
            intent=alias,
            message="Generate a science assessment",
            structured_input=_assessment_input(),
            conversation_id=None,
        )
    )

    assert response.status == "pending_review"
    assert response.intent == "assessment_generation"
    assert response.execution.workflow == "assessment_generation"


def test_unsupported_intent_fallback(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()

    response = asyncio.run(
        service.run(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            school_context={"school_name": "Greenwood", "term": "Fall"},
            user_id="teacher-1",
            user_role="teacher",
            intent="school_transport",
            message="Find bus routes",
            structured_input={},
            conversation_id=None,
        )
    )

    assert response.status == "unsupported_intent"
    assert response.execution.workflow == "fallback"


def test_checkpoint_stores_normalized_intent(reset_copilot_settings):
    settings.copilot_checkpoint_backend = "memory"
    service = CopilotOrchestratorService()

    response = asyncio.run(
        service.run(
            db=None,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
            school_context={"school_name": "Greenwood", "term": "Fall"},
            user_id="teacher-1",
            user_role="teacher",
            intent="assessment studio",
            message="Create a quiz",
            structured_input=_assessment_input(),
            conversation_id=None,
        )
    )

    store = service._resolve_checkpoint_store(db=None)
    persisted = asyncio.run(
        store.get(
            request_id=response.request_id,
            tenant_id="11111111-1111-1111-1111-111111111111",
            tenant_slug="greenwood",
        )
    )

    assert persisted is not None
    assert persisted.get("intent") == "assessment_generation"
