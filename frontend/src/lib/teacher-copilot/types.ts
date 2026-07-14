export type AgentIntent = "lesson-planning" | "unsupported";

export interface TeacherContext {
  curriculum: string;
  grade: string;
  subject: string;
  school: string;
  term: string;
  language: string;
  upcomingLessons: string[];
}

export interface LessonPlanInput {
  curriculum: string;
  grade: string;
  subject: string;
  topic: string;
  duration: string;
  learningObjectives: string[];
  teachingStrategy: string;
  differentiation: string;
  specialNeeds: string;
  assessmentMethod: string;
  homework: string;
  resources: string;
  language: string;
  teacherNotes: string;
}

export interface LessonPlanOutput {
  overview: string;
  learningObjectives: string[];
  materials: string[];
  lessonActivities: string[];
  teacherNotes: string[];
  differentiation: string[];
  assessment: string[];
  homework: string[];
  reflection: string[];
}

export interface LessonPlanningResponse {
  intent: AgentIntent;
  content: string;
  markdown: string;
  lessonPlan?: LessonPlanOutput;
  parsedInput?: LessonPlanInput;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export interface ConversationStorage {
  listMessages(): ConversationMessage[];
  appendMessage(message: ConversationMessage): void;
  clear(): void;
}

export interface LLMRequest {
  prompt: string;
  input?: LessonPlanInput;
  context?: TeacherContext;
}

export interface LLMResponse {
  content: string;
  structured?: Partial<LessonPlanOutput>;
}

export interface LLMProvider {
  generate(request: LLMRequest): Promise<LLMResponse>;
}

export type CopilotWorkflowStatus =
  | "needs_clarification"
  | "pending_review"
  | "approved"
  | "unsupported_intent"
  | "error";

export interface CopilotExecution {
  workflow: string;
  current_step: string;
  validation_passed: boolean;
  retry_count: number;
}

export interface CopilotBackendResponse {
  status: CopilotWorkflowStatus;
  request_id: string;
  conversation_id?: string | null;
  intent?: string | null;
  message: string;
  missing_fields?: string[];
  clarification_question?: string | null;
  result?: Record<string, unknown> | null;
  execution: CopilotExecution;
}
