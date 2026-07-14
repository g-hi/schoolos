import type { LLMProvider, LLMRequest, LLMResponse } from "./types";

export class LocalDeterministicLLMProvider implements LLMProvider {
  async generate(request: LLMRequest): Promise<LLMResponse> {
    const topic = request.input?.topic || "the requested lesson topic";
    const grade = request.input?.grade || "the selected grade";
    const subject = request.input?.subject || "the selected subject";
    const content = [
      `A lesson plan scaffold has been prepared for ${grade} ${subject} on ${topic}.`,
      "",
      "The response uses a structured lesson-planning format that can be routed to future providers without changing the agent interface.",
    ].join("\n");

    return {
      content,
      structured: {},
    };
  }
}
