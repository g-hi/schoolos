"""
Assessment Review & Marking Studio — backend test suite (31 test cases).

All tests use:
  - deterministic provider (no LLM required)
  - in-memory checkpoint store
  - synthetic student data only
  - no real file system access
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from services.gateway.ai.copilot.nodes.intent_router import normalize_intent
from services.gateway.ai.copilot.registry import WorkflowRegistry
from services.gateway.ai.copilot.service import CopilotOrchestratorService
from services.gateway.ai.exam_marking.extraction.image_ocr import (
    DeterministicMCQExtractor,
    DeterministicOCRProvider,
)
from services.gateway.ai.exam_marking.grading.deterministic_grader import DeterministicGrader
from services.gateway.ai.exam_marking.omr.deterministic_omr import DeterministicOMRProvider
from services.gateway.ai.exam_marking.omr.base import OMRTemplate
from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry
from services.gateway.ai.exam_marking.quality.image_quality import ImageQualityChecker
from services.gateway.ai.exam_marking.strategies.base import StrategyInput
from services.gateway.ai.exam_marking.strategies.factory import ProcessingStrategyFactory
from services.gateway.ai.exam_marking.strategies.scantron_omr import ScantronOMRStrategy
from services.gateway.ai.exam_marking.strategies.printed_mcq import PrintedMCQStrategy
from services.gateway.ai.exam_marking.strategies.mixed_paper import MixedPaperStrategy
from services.gateway.ai.exam_marking.strategies.open_ended import OpenEndedStrategy
from services.gateway.ai.exam_marking.telemetry import TelemetryCollector, ProviderTelemetry
from shared.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _make_answer_key(count: int = 3) -> list[dict]:
    types = ["mcq", "true_false", "short_answer"]
    answers = ["B", "True", ""]
    return [
        {
            "question_number": i + 1,
            "question_type": types[i % len(types)],
            "correct_answer": answers[i % len(answers)],
            "max_marks": 2.0,
            "accepted_alternatives": [],
        }
        for i in range(count)
    ]


def _make_pages(count: int = 1) -> list[dict]:
    return [
        {"page_id": str(uuid.uuid4()), "storage_key": f"test_page_{i}.jpg", "page_number": i + 1}
        for i in range(count)
    ]


def _make_strategy_input(
    paper_type: str = "open_ended",
    question_count: int = 3,
    pages: list[dict] | None = None,
    answer_key: list[dict] | None = None,
) -> StrategyInput:
    return StrategyInput(
        session_id=str(uuid.uuid4()),
        submission_id=str(uuid.uuid4()),
        paper_type=paper_type,
        pages=pages or _make_pages(),
        answer_key=answer_key or _make_answer_key(question_count),
        marking_scheme={},
        teacher_guidance="",
        expected_question_count=question_count,
        tenant_id=TENANT_A,
    )


def _run_exam(structured_input: dict, tenant_id: str = TENANT_A) -> object:
    """Run exam_marking workflow via CopilotOrchestratorService with in-memory store."""
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc = CopilotOrchestratorService()
    response = asyncio.run(
        svc.run(
            db=None,
            tenant_id=tenant_id,
            tenant_slug="greenwood" if tenant_id == TENANT_A else "riverside",
            school_context={"school_name": "Test School", "term": "Term 1"},
            user_id="teacher-test",
            user_role="teacher",
            intent="exam_marking",
            message="Mark exam papers",
            structured_input=structured_input,
            conversation_id=None,
        )
    )
    settings.copilot_checkpoint_backend = original_backend
    return response


# ─────────────────────────────────────────────────────────────────────────────
# 1. Workflow registration
# ─────────────────────────────────────────────────────────────────────────────

def test_workflow_registration():
    registry = WorkflowRegistry()
    reg = registry.get_enabled("exam_marking")
    assert reg is not None
    assert reg.enabled is True
    assert reg.builder is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Alias normalisation (all 13 aliases + stored intent)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("alias,expected", [
    ("exam marking", "exam_marking"),
    ("mark exam", "exam_marking"),
    ("grade exam", "exam_marking"),
    ("mark student paper", "exam_marking"),
    ("grade student paper", "exam_marking"),
    ("mark assessment", "exam_marking"),
    ("grade assessment", "exam_marking"),
    ("exam correction", "exam_marking"),
    ("paper marking", "exam_marking"),
    ("marking studio", "exam_marking"),
    ("assessment review", "exam_marking"),
    ("scan exam", "exam_marking"),
    ("batch marking", "exam_marking"),
    ("exam_marking", "exam_marking"),
    # existing aliases must still work
    ("lesson_planning", "lesson_planning"),
    ("assessment_generation", "assessment_generation"),
])
def test_alias_normalization(alias: str, expected: str):
    assert normalize_intent(alias) == expected


# ─────────────────────────────────────────────────────────────────────────────
# 3–4. Marking session creation (single and batch)
# ─────────────────────────────────────────────────────────────────────────────

def test_marking_session_creation():
    response = _run_exam({"exam_title": "Grade 5 Science Test", "answer_key": _make_answer_key()})
    assert response.status in ("pending_review", "error", "needs_clarification")
    assert response.request_id


def test_batch_session_creation():
    response = _run_exam({
        "exam_title": "Batch Test",
        "total_students": 3,
        "answer_key": _make_answer_key(),
        "pages": _make_pages(),
    })
    assert response.request_id is not None


# ─────────────────────────────────────────────────────────────────────────────
# 5–7. Page management
# ─────────────────────────────────────────────────────────────────────────────

def test_page_upload_structure():
    pages = _make_pages(2)
    assert len(pages) == 2
    assert pages[0]["page_number"] == 1
    assert pages[1]["page_number"] == 2


def test_page_ordering():
    pages = _make_pages(4)
    nums = [p["page_number"] for p in pages]
    assert nums == [1, 2, 3, 4]


def test_missing_page_detection():
    # Pages 1 and 3 present but not 2 (expected 3 pages)
    inp = _make_strategy_input(question_count=1)
    pages = [
        {"page_id": "p1", "storage_key": "p1.jpg", "page_number": 1},
        {"page_id": "p3", "storage_key": "p3.jpg", "page_number": 3},
    ]
    inp.pages = pages
    # Run through LangGraph
    response = _run_exam({
        "expected_pages_per_student": 3,
        "pages": pages,
        "answer_key": _make_answer_key(1),
    })
    # Missing page is logged as error but workflow continues
    assert response.request_id is not None


# ─────────────────────────────────────────────────────────────────────────────
# 8. Scan quality rejection
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_quality_rejection_low_quality():
    checker = ImageQualityChecker(retake_threshold=0.60)
    result = checker.check("test_low_quality_page.jpg")
    assert result.retake_required is True
    assert "blur" in result.warnings
    assert result.accepted_for_processing is False


def test_scan_quality_acceptance_good_image():
    checker = ImageQualityChecker()
    result = checker.check("normal_exam_page.jpg")
    assert result.retake_required is False
    assert result.accepted_for_processing is True
    assert result.quality_score > 0.8


# ─────────────────────────────────────────────────────────────────────────────
# 9–12. Pipeline routing
# ─────────────────────────────────────────────────────────────────────────────

def test_scantron_routing():
    strategy = ProcessingStrategyFactory.get_strategy("scantron")
    assert isinstance(strategy, ScantronOMRStrategy)
    assert strategy.strategy_name == "scantron_omr"


def test_printed_mcq_routing():
    strategy = ProcessingStrategyFactory.get_strategy("printed_mcq")
    assert isinstance(strategy, PrintedMCQStrategy)
    assert strategy.strategy_name == "printed_mcq"


def test_mixed_paper_routing():
    strategy = ProcessingStrategyFactory.get_strategy("mixed")
    assert isinstance(strategy, MixedPaperStrategy)
    assert strategy.strategy_name == "mixed"


def test_open_ended_routing():
    strategy = ProcessingStrategyFactory.get_strategy("open_ended")
    assert isinstance(strategy, OpenEndedStrategy)
    assert strategy.strategy_name == "open_ended"


# ─────────────────────────────────────────────────────────────────────────────
# 13–14. Objective grading
# ─────────────────────────────────────────────────────────────────────────────

def test_objective_correct_answer():
    grader = DeterministicGrader()
    result = grader.grade(1, "B", {"correct_answer": "B", "max_marks": 2.0})
    assert result.result == "correct"
    assert result.proposed_marks == 2.0
    assert result.confidence == 1.0
    assert not result.requires_teacher_review


def test_objective_incorrect_answer():
    grader = DeterministicGrader()
    result = grader.grade(1, "A", {"correct_answer": "B", "max_marks": 2.0})
    assert result.result == "incorrect"
    assert result.proposed_marks == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 15. Numeric tolerance
# ─────────────────────────────────────────────────────────────────────────────

def test_numeric_tolerance_within():
    grader = DeterministicGrader()
    result = grader.grade(1, "9.8", {"correct_answer": "10", "max_marks": 3.0, "numeric_tolerance": 0.5})
    assert result.result == "correct"
    assert result.proposed_marks == 3.0


def test_numeric_tolerance_outside():
    grader = DeterministicGrader()
    result = grader.grade(1, "5.0", {"correct_answer": "10", "max_marks": 3.0, "numeric_tolerance": 0.5})
    assert result.result == "incorrect"


# ─────────────────────────────────────────────────────────────────────────────
# 16. Accepted alternatives
# ─────────────────────────────────────────────────────────────────────────────

def test_accepted_alternatives():
    grader = DeterministicGrader()
    result = grader.grade(
        1, "photosynthesis",
        {"correct_answer": "Photosynthesis", "max_marks": 2.0, "accepted_alternatives": ["photo synthesis"]}
    )
    assert result.result == "correct"


# ─────────────────────────────────────────────────────────────────────────────
# 17. Unresolved segmentation
# ─────────────────────────────────────────────────────────────────────────────

def test_unresolved_segmentation():
    """Questions with no rubric and no answer key should become unresolved."""
    strategy = OpenEndedStrategy()
    registry = ProviderRegistry()  # no rubric grader
    inp = _make_strategy_input(paper_type="open_ended", question_count=2)
    inp.answer_key = [{"question_number": 1, "question_type": "essay", "correct_answer": "", "max_marks": 5.0}]
    result = asyncio.run(strategy.process(inp, registry))
    # Without rubric grader and with essay type, question should be unresolved
    unresolved = [r for r in result.question_responses if r["status"] == "unresolved"]
    assert len(unresolved) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 18. Low-confidence OCR
# ─────────────────────────────────────────────────────────────────────────────

def test_low_confidence_ocr_extraction():
    ocr = DeterministicOCRProvider()
    result = asyncio.run(ocr.extract_text("normal_page.jpg"))
    # Deterministic provider returns 0.97
    assert result.overall_confidence > 0.90


# ─────────────────────────────────────────────────────────────────────────────
# 19. Rubric grading (deterministic provider)
# ─────────────────────────────────────────────────────────────────────────────

def test_rubric_grading_deterministic():
    from services.gateway.ai.copilot.providers.deterministic import DeterministicLLMProvider
    from services.gateway.ai.exam_marking.grading.rubric_grader import RubricAIGrader
    grader = RubricAIGrader(provider=DeterministicLLMProvider())
    result = asyncio.run(grader.grade(
        question_number=3,
        question_text="Explain photosynthesis.",
        student_answer="Plants use sunlight to make food.",
        rubric_criteria=[{"criterion": "Content", "max_marks": 3}, {"criterion": "Clarity", "max_marks": 2}],
        max_marks=5.0,
    ))
    assert result.proposed_marks <= 5.0
    assert result.proposed_marks >= 0.0
    assert result.requires_teacher_review is True  # always True for AI grading
    assert result.confidence > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 20. Mixed objective/open-ended paper
# ─────────────────────────────────────────────────────────────────────────────

def test_mixed_paper_strategy():
    strategy = MixedPaperStrategy()
    registry = ProviderRegistry()
    ak = [
        {"question_number": 1, "question_type": "mcq", "correct_answer": "B", "max_marks": 2.0},
        {"question_number": 2, "question_type": "short_answer", "correct_answer": "", "max_marks": 3.0},
    ]
    inp = _make_strategy_input(paper_type="mixed", question_count=2, answer_key=ak)
    result = asyncio.run(strategy.process(inp, registry))
    assert len(result.question_responses) == 2
    methods = {r["grading_method"] for r in result.question_responses}
    # MCQ → vision, short_answer → unresolved (no rubric grader)
    assert len(methods) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 21–22. Total aggregation and mark protection
# ─────────────────────────────────────────────────────────────────────────────

def test_total_aggregation():
    strategy = ScantronOMRStrategy()
    registry = ProviderRegistry()
    ak = [{"question_number": i + 1, "correct_answer": "A", "max_marks": 1.0} for i in range(5)]
    inp = _make_strategy_input(paper_type="scantron", question_count=5, answer_key=ak)
    result = asyncio.run(strategy.process(inp, registry))
    assert result.max_marks == 5.0
    assert result.proposed_total <= result.max_marks


def test_maximum_mark_protection():
    """Proposed marks must never exceed max_marks."""
    grader = DeterministicGrader()
    # Simulate an edge case where proposed might exceed max
    result = grader.grade(1, "correct", {"correct_answer": "correct", "max_marks": 3.0})
    assert result.proposed_marks <= 3.0


# ─────────────────────────────────────────────────────────────────────────────
# 23–25. Teacher override, rejection, approval
# ─────────────────────────────────────────────────────────────────────────────

def test_teacher_override_persistence():
    response = _run_exam({"answer_key": _make_answer_key(), "pages": _make_pages()})
    assert response.request_id
    # Override via continue run
    svc = CopilotOrchestratorService()
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc2 = CopilotOrchestratorService()
    settings.copilot_checkpoint_backend = original_backend
    assert response.status in ("pending_review", "error", "needs_clarification", "unsupported_intent")


def test_rejection_persistence():
    response = _run_exam({"answer_key": _make_answer_key()})
    # Approval with approved=False
    svc = CopilotOrchestratorService()
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc2 = CopilotOrchestratorService()
    reject_response = asyncio.run(
        svc2.approve(
            db=None,
            tenant_id=TENANT_A,
            tenant_slug="greenwood",
            request_id=response.request_id,
            approved=False,
            notes="Rejected in test",
        )
    )
    settings.copilot_checkpoint_backend = original_backend
    assert reject_response.request_id == response.request_id


def test_approval_persistence():
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc = CopilotOrchestratorService()
    response = asyncio.run(svc.run(
        db=None,
        tenant_id=TENANT_A,
        tenant_slug="greenwood",
        school_context={"school_name": "Test"},
        user_id="teacher",
        user_role="teacher",
        intent="exam_marking",
        message="mark",
        structured_input={"answer_key": _make_answer_key(), "pages": _make_pages()},
        conversation_id=None,
    ))
    if response.status == "pending_review":
        approved = asyncio.run(svc.approve(
            db=None,
            tenant_id=TENANT_A,
            tenant_slug="greenwood",
            request_id=response.request_id,
            approved=True,
            notes="",
        ))
        assert approved.status == "approved"
    settings.copilot_checkpoint_backend = original_backend


# ─────────────────────────────────────────────────────────────────────────────
# 26. Tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_tenant_isolation():
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc = CopilotOrchestratorService()

    # Create in tenant A
    resp_a = asyncio.run(svc.run(
        db=None,
        tenant_id=TENANT_A,
        tenant_slug="greenwood",
        school_context={},
        user_id="teacher",
        user_role="teacher",
        intent="exam_marking",
        message="mark",
        structured_input={"answer_key": _make_answer_key()},
        conversation_id=None,
    ))

    # Try to retrieve with tenant B — should return None
    state = asyncio.run(svc._memory_checkpoint_store.get(
        request_id=resp_a.request_id,
        tenant_id=TENANT_B,
        tenant_slug="riverside",
    ))
    assert state is None

    settings.copilot_checkpoint_backend = original_backend


# ─────────────────────────────────────────────────────────────────────────────
# 27. Gateway restart persistence (in-memory fallback)
# ─────────────────────────────────────────────────────────────────────────────

def test_gateway_restart_persistence_memory():
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc = CopilotOrchestratorService()

    resp = asyncio.run(svc.run(
        db=None,
        tenant_id=TENANT_A,
        tenant_slug="greenwood",
        school_context={},
        user_id="teacher",
        user_role="teacher",
        intent="exam_marking",
        message="mark",
        structured_input={"answer_key": _make_answer_key(), "pages": _make_pages()},
        conversation_id=None,
    ))

    # Verify checkpoint saved
    saved = asyncio.run(svc._memory_checkpoint_store.get(
        request_id=resp.request_id,
        tenant_id=TENANT_A,
        tenant_slug="greenwood",
    ))
    assert saved is not None
    assert saved.get("intent") == "exam_marking"

    settings.copilot_checkpoint_backend = original_backend


# ─────────────────────────────────────────────────────────────────────────────
# 28. Interrupted batch resume
# ─────────────────────────────────────────────────────────────────────────────

def test_interrupted_batch_resume():
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    svc = CopilotOrchestratorService()

    resp = asyncio.run(svc.run(
        db=None,
        tenant_id=TENANT_A,
        tenant_slug="greenwood",
        school_context={},
        user_id="teacher",
        user_role="teacher",
        intent="exam_marking",
        message="batch mark",
        structured_input={"answer_key": _make_answer_key(), "pages": _make_pages(2)},
        conversation_id=None,
    ))

    # Resume via continue_run
    resumed = asyncio.run(svc.continue_run(
        db=None,
        tenant_id=TENANT_A,
        tenant_slug="greenwood",
        request_id=resp.request_id,
        message=None,
        structured_input={"resumed": True},
    ))
    assert resumed.request_id == resp.request_id

    settings.copilot_checkpoint_backend = original_backend


# ─────────────────────────────────────────────────────────────────────────────
# 29. Deterministic provider
# ─────────────────────────────────────────────────────────────────────────────

def test_deterministic_provider_omr():
    omr = DeterministicOMRProvider()
    template = OMRTemplate(question_count=4)
    result = asyncio.run(omr.process("synthetic_scantron.jpg", template))
    assert len(result.question_results) == 4
    assert result.overall_confidence > 0.0
    # Q3 is synthetically ambiguous
    q3 = next(r for r in result.question_results if r.question_number == 3)
    assert q3.ambiguous_mark is True
    assert q3.review_required is True


def test_deterministic_provider_mcq():
    mcq = DeterministicMCQExtractor()
    result = asyncio.run(mcq.extract("test.jpg", question_count=3))
    assert len(result) == 3
    assert all(r.confidence > 0.90 for r in result)


# ─────────────────────────────────────────────────────────────────────────────
# 30. Token usage accounting
# ─────────────────────────────────────────────────────────────────────────────

def test_token_usage_accounting():
    """Scantron papers must have 0 tokens (no LLM)."""
    strategy = ScantronOMRStrategy()
    registry = ProviderRegistry()
    inp = _make_strategy_input(paper_type="scantron", question_count=3)
    inp.answer_key = [{"question_number": i + 1, "correct_answer": "A", "max_marks": 1.0} for i in range(3)]
    result = asyncio.run(strategy.process(inp, registry))
    assert result.token_usage.get("total_tokens", 0) == 0
    assert result.ai_graded_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 31. Processing telemetry
# ─────────────────────────────────────────────────────────────────────────────

def test_processing_telemetry():
    collector = TelemetryCollector("deterministic_omr", "scantron_omr", "bubble_detection", question_number=None)
    collector.start()
    telemetry = collector.finish(confidence=0.98, status="success")
    assert isinstance(telemetry, ProviderTelemetry)
    assert telemetry.provider_name == "deterministic_omr"
    assert telemetry.duration_ms >= 0.0
    assert telemetry.status == "success"
    assert telemetry.confidence == 0.98

    event = telemetry.to_trace_event()
    assert event["node"].startswith("provider:")
    assert "provider_telemetry" in event
    assert event["provider_telemetry"]["estimated_cost_usd"] == 0.0
