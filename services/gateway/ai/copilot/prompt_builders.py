from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState


def build_lesson_planning_prompt(state: SchoolOSAIState) -> str:
    data = state.get("structured_input", {})
    teacher_context = state.get("teacher_context", {})
    retrieved = state.get("retrieved_context", {})

    return "\n".join(
        [
            "You are the SchoolOS Lesson Planning Agent.",
            "Create a concise but complete lesson plan.",
            f"Grade: {data.get('grade', teacher_context.get('default_grade', 'Grade 5'))}",
            f"Subject: {data.get('subject', teacher_context.get('default_subject', 'Science'))}",
            f"Topic: {data.get('topic', state.get('original_message', 'General topic'))}",
            f"Duration: {data.get('duration_minutes', 45)} minutes",
            f"Curriculum: {data.get('curriculum', retrieved.get('curriculum_context', {}).get('framework', 'General curriculum'))}",
            "Output sections: Lesson Overview, Learning Objectives, Materials, Lesson Activities, Differentiation, Assessment, Homework, Reflection.",
        ]
    )


def build_assessment_generation_prompt(state: SchoolOSAIState) -> str:
    data = state.get("structured_input", {})
    teacher_context = state.get("teacher_context", {})
    school_context = state.get("school_context", {})

    learning_objectives = data.get("learning_objectives", [])
    if isinstance(learning_objectives, list):
        objectives_text = "; ".join(str(item) for item in learning_objectives if item)
    else:
        objectives_text = str(learning_objectives or "")

    question_types = data.get("question_types", [])
    if isinstance(question_types, list):
        question_types_text = ", ".join(str(item) for item in question_types if item)
    else:
        question_types_text = str(question_types or "Mix of Question Types")

    return "\n".join(
        [
            "You are the SchoolOS Assessment Generation Agent inside Assessment Studio.",
            "Generate a professional teacher-ready assessment draft.",
            f"Curriculum: {data.get('curriculum', 'General curriculum')}",
            f"Grade: {data.get('grade', teacher_context.get('default_grade', 'Grade 5'))}",
            f"Subject: {data.get('subject', teacher_context.get('default_subject', 'Science'))}",
            f"Topic: {data.get('topic', state.get('original_message', 'General topic'))}",
            f"Learning Objectives: {objectives_text or 'Understand and apply the core concept'}",
            f"Difficulty: {data.get('difficulty', 'Medium')}",
            f"Assessment Type: {data.get('assessment_type', 'Quiz')}",
            f"Question Types: {question_types_text}",
            f"Number of Questions: {data.get('number_of_questions', 10)}",
            f"Total Marks: {data.get('total_marks', 20)}",
            f"Time Limit: {data.get('duration_minutes', 30)} minutes",
            f"Language: {data.get('language', 'English')}",
            f"Special Needs: {data.get('special_needs', 'None specified')}",
            f"Teacher Notes: {data.get('teacher_notes', 'No additional notes')}",
            f"School Context: {school_context.get('school_name', 'School')} ({state.get('tenant_slug', 'tenant')})",
            "Output sections: Instructions, Questions, Marks Allocation, Answer Key Preview, Rubric Preview, Teacher Notes.",
        ]
    )