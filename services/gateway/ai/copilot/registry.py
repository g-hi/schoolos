from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.workflows.assessment_generation_graph import build_assessment_generation_graph
from services.gateway.ai.copilot.workflows.exam_marking_graph import build_exam_marking_graph
from services.gateway.ai.copilot.workflows.lesson_planning_graph import build_lesson_planning_graph
from services.gateway.ai.copilot.workflows.parent_assistant_graph import build_parent_assistant_graph


@dataclass
class WorkflowRegistration:
    name: str
    enabled: bool
    builder: Callable[[LLMProvider, dict[str, Any] | None], object] | None


class WorkflowRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, WorkflowRegistration] = {
            "lesson_planning": WorkflowRegistration(
                name="lesson_planning",
                enabled=True,
                builder=build_lesson_planning_graph,
            ),
            "assessment_generation": WorkflowRegistration(
                name="assessment_generation",
                enabled=True,
                builder=build_assessment_generation_graph,
            ),
            "exam_marking": WorkflowRegistration(
                name="exam_marking",
                enabled=True,
                builder=build_exam_marking_graph,
            ),
            "parent_assistant": WorkflowRegistration(
                name="parent_assistant",
                enabled=True,
                builder=build_parent_assistant_graph,
            ),
            "parent_communication": WorkflowRegistration("parent_communication", False, None),
            "report_comments": WorkflowRegistration("report_comments", False, None),
            "student_analytics": WorkflowRegistration("student_analytics", False, None),
            "finance": WorkflowRegistration("finance", False, None),
            "school_intelligence": WorkflowRegistration("school_intelligence", False, None),
        }

    def get_enabled(self, workflow_name: str) -> WorkflowRegistration | None:
        registration = self._registrations.get(workflow_name)
        if not registration or not registration.enabled:
            return None
        return registration

    def list_registrations(self) -> dict[str, WorkflowRegistration]:
        return dict(self._registrations)
