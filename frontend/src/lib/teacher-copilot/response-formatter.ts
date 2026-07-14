import type { LessonPlanInput, LessonPlanOutput, LessonPlanningResponse, TeacherContext } from "./types";

export class LessonPlanningResponseFormatter {
  format(input: LessonPlanInput, context: TeacherContext, providerContent: string): LessonPlanningResponse {
    const lessonPlan: LessonPlanOutput = {
      overview: `A ${input.duration || "45 minutes"} lesson on ${input.topic || "the requested topic"} for ${input.grade || context.grade} ${input.subject || context.subject}.`,
      learningObjectives: input.learningObjectives.length > 0 ? input.learningObjectives : ["Understand the core concept clearly.", "Apply the idea in a short guided activity."],
      materials: [input.resources || "Projector", "Worksheets", "Textbook", "Whiteboard"],
      lessonActivities: [
        "Open with a warm-up question linked to prior learning.",
        "Model the key concept with a short explanation.",
        "Guide students through a collaborative task with reflection points.",
      ],
      teacherNotes: [input.teacherNotes || "Keep pacing calm and allow time for checking understanding."],
      differentiation: [input.differentiation || "Provide scaffolds for support learners and extension prompts for confident learners."],
      assessment: [input.assessmentMethod || "Use an exit ticket to check understanding."],
      homework: [input.homework || "Ask students to review the concept and write one example."],
      reflection: ["Review what worked well and adjust the pacing for the next lesson."],
    };

    const markdown = this.toMarkdown(lessonPlan);
    return {
      intent: "lesson-planning",
      content: providerContent || markdown,
      markdown,
      lessonPlan,
      parsedInput: input,
    };
  }

  private toMarkdown(lessonPlan: LessonPlanOutput): string {
    return [
      "## Lesson Overview",
      lessonPlan.overview,
      "",
      "## Learning Objectives",
      ...lessonPlan.learningObjectives.map((item) => `- ${item}`),
      "",
      "## Materials",
      ...lessonPlan.materials.map((item) => `- ${item}`),
      "",
      "## Lesson Activities",
      ...lessonPlan.lessonActivities.map((item) => `- ${item}`),
      "",
      "## Teacher Notes",
      ...lessonPlan.teacherNotes.map((item) => `- ${item}`),
      "",
      "## Differentiation",
      ...lessonPlan.differentiation.map((item) => `- ${item}`),
      "",
      "## Assessment",
      ...lessonPlan.assessment.map((item) => `- ${item}`),
      "",
      "## Homework",
      ...lessonPlan.homework.map((item) => `- ${item}`),
      "",
      "## Reflection",
      ...lessonPlan.reflection.map((item) => `- ${item}`),
    ].join("\n");
  }
}
