import type { AgentIntent } from "./types";

export function detectAgentIntent(input: string): AgentIntent {
  const normalized = input.toLowerCase();
  const lessonSignals = [
    "lesson",
    "lesson plan",
    "learning objectives",
    "curriculum",
    "teaching strategy",
    "classroom",
    "differentiation",
    "homework",
  ];

  if (lessonSignals.some((signal) => normalized.includes(signal))) {
    return "lesson-planning";
  }

  return "unsupported";
}
