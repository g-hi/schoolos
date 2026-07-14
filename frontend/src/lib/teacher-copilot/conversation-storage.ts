import type { ConversationMessage, ConversationStorage } from "./types";

export class InMemoryConversationStorage implements ConversationStorage {
  private messages: ConversationMessage[] = [];

  listMessages(): ConversationMessage[] {
    return [...this.messages];
  }

  appendMessage(message: ConversationMessage): void {
    this.messages.push(message);
  }

  clear(): void {
    this.messages = [];
  }
}
