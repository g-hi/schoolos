import type { LessonPlanInput, TeacherContext } from "./types";

export class LessonPlanningPromptBuilder {
  build(input: LessonPlanInput, context: TeacherContext): string {
    const objectives = input.learningObjectives.length > 0 ? input.learningObjectives.join("; ") : "Define clear learning outcomes.";
    return [
      "You are the SchoolOS Lesson Planning Agent.",
      "Create a structured lesson plan for a teacher working in a school environment.",
      "",
      `Curriculum: ${input.curriculum || context.curriculum}`,
      `Grade: ${input.grade || context.grade}`,
      `Subject: ${input.subject || context.subject}`,
      `Topic: ${input.topic || "General topic"}`,
      `Duration: ${input.duration || "45 minutes"}`,
      `Language: ${input.language || context.language}`,
      `Learning Objectives: ${objectives}`,
      `Teaching Strategy: ${input.teachingStrategy || "Inquiry-based learning"}`,
      `Differentiation: ${input.differentiation || "Support and challenge strategies"}`,
      `Special Needs: ${input.specialNeeds || "Inclusive support for varied learners"}`,
      `Assessment Method: ${input.assessmentMethod || "Observation and exit ticket"}`,
      `Homework: ${input.homework || "Optional practice task"}`,
      `Resources: ${input.resources || "Library, projector, worksheets"}`,
      `Teacher Notes: ${input.teacherNotes || "Keep the lesson warm, structured, and student-centred."}`,
      `School Context: ${context.school} · ${context.term}`,
      `Upcoming Lessons: ${context.upcomingLessons.join(", ") || "None listed"}`,
      "",
      "Return a concise, well-structured markdown lesson plan with the following headings:",
      "- Lesson Overview",
      "- Learning Objectives",
      "- Materials",
      "- Lesson Activities",
      "- Teacher Notes",
      "- Differentiation",
      "- Assessment",
      "- Homework",
      "- Reflection",
    ].join("\n");
  }
}
