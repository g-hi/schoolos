import { detectAgentIntent } from "./intent-detector";
import { LessonPlanningPromptBuilder } from "./prompt-builder";
import type { LessonPlanInput, LessonPlanningResponse, TeacherContext, LLMProvider } from "./types";
import { LessonPlanningResponseFormatter } from "./response-formatter";

export class LessonPlanningAgent {
  constructor(
    private readonly provider: LLMProvider,
    private readonly promptBuilder = new LessonPlanningPromptBuilder(),
    private readonly formatter = new LessonPlanningResponseFormatter(),
  ) {}

  async run(input: string, context: TeacherContext): Promise<LessonPlanningResponse> {
    const intent = detectAgentIntent(input);
    if (intent !== "lesson-planning") {
      return {
        intent,
        content: "This request is outside the current lesson-planning scope.",
        markdown: "This request is outside the current lesson-planning scope.",
      };
    }

    const parsedInput: LessonPlanInput = {
      curriculum: context.curriculum,
      grade: context.grade,
      subject: context.subject,
      topic: input,
      duration: "45 minutes",
      learningObjectives: ["Understand the main concept", "Apply the idea in guided practice"],
      teachingStrategy: "Inquiry-based learning",
      differentiation: "Provide support and extension prompts",
      specialNeeds: "Use inclusive strategies",
      assessmentMethod: "Observation and exit ticket",
      homework: "Review the key idea at home",
      resources: "Projector, worksheets, notebook",
      language: context.language,
      teacherNotes: "Keep the lesson engaging and purposeful.",
    };

    const prompt = this.promptBuilder.build(parsedInput, context);
    const providerResponse = await this.provider.generate({ prompt, input: parsedInput, context });
    return this.formatter.format(parsedInput, context, providerResponse.content);
  }
}
