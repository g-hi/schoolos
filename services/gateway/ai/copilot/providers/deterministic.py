from __future__ import annotations

from typing import Any


class DeterministicLLMProvider:
    provider_name = "deterministic"

    async def generate(self, prompt: str) -> dict[str, Any]:
        # Deterministic output keeps local development and tests stable.
        if "Exam Marking Rubric Grader" in prompt or "rubric_ai_grading" in prompt.lower():
            # Structured rubric grading response for exam marking tests
            content = (
                "## Rubric Grading Result\n\n"
                "proposed_marks: 3\n\n"
                "## Criteria Results\n"
                "- Content Accuracy: 2/2 — Student demonstrated understanding of core concept.\n"
                "- Explanation Clarity: 1/1 — Clear and concise explanation provided.\n\n"
                "## Evidence\n"
                "Student answer addresses the main rubric criteria with adequate detail.\n\n"
                "## Feedback\n"
                "Good response. Verify factual accuracy before approving.\n\n"
                "## Confidence\n"
                "confidence: 0.75\n"
            )
        elif "Assessment Generation Agent" in prompt or "Assessment Studio" in prompt:
            content = (
                "## Instructions\n"
                "Read all questions carefully. Show working where needed.\n\n"
                "## Questions\n"
                "1. Multiple Choice: Identify the correct concept.\n"
                "2. True / False: Evaluate the statement.\n"
                "3. Short Answer: Explain your reasoning.\n\n"
                "## Marks Allocation\n"
                "Q1: 2 marks\n"
                "Q2: 2 marks\n"
                "Q3: 6 marks\n\n"
                "## Answer Key Preview\n"
                "Q1: Option B\n"
                "Q2: True\n"
                "Q3: Sample points provided\n\n"
                "## Rubric Preview\n"
                "Accuracy, Application, Clarity\n"
            )
        else:
            content = (
                "## Lesson Overview\n"
                "A structured lesson draft was created using deterministic generation.\n\n"
                "## Learning Objectives\n"
                "- Understand the lesson concept\n"
                "- Apply the concept in guided work\n\n"
                "## Materials\n"
                "- Whiteboard\n"
                "- Worksheet\n"
                "- Textbook\n\n"
                "## Lesson Activities\n"
                "- Warm-up and prior knowledge check\n"
                "- Guided explanation\n"
                "- Pair activity and reflection\n\n"
                "## Differentiation\n"
                "- Scaffold for support learners\n"
                "- Challenge extension tasks\n\n"
                "## Assessment\n"
                "- Exit ticket\n\n"
                "## Homework\n"
                "- Complete one review task\n\n"
                "## Reflection\n"
                "- Note what to adjust for the next lesson"
            )

        return {
            "content": content,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
