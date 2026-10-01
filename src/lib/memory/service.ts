import { v4 as uuidv4 } from "uuid";
import { insertMemory, listMemories, markMemorySuperseded } from "@/lib/db";
import type { MemoryExtractor } from "./extractor";
import { DeterministicMemoryExtractor } from "./extractor";
import { findSupersededMemory } from "./supersede";
import type { MemoryRecord } from "./types";

export class MemoryService {
  constructor(private extractor: MemoryExtractor = new DeterministicMemoryExtractor()) {}

  async processAssistantTurn(params: {
    characterId: string;
    userId: string;
    userMessage: string;
    assistantMessage: string;
    turnId: string;
  }): Promise<MemoryRecord[]> {
    const candidates = this.extractor.extract({
      userMessage: params.userMessage,
      assistantMessage: params.assistantMessage,
      turnId: params.turnId,
    });

    const existing = listMemories(params.characterId, params.userId);
    const created: MemoryRecord[] = [];

    for (const candidate of candidates) {
      const id = uuidv4();
      const superseded = findSupersededMemory(candidate, existing);
      const record = insertMemory({
        id,
        characterId: params.characterId,
        userId: params.userId,
        type: candidate.type,
        text: candidate.text,
        salience: candidate.salience,
        sourceTurnId: params.turnId,
        supersededById: null,
        deletedAt: null,
      });
      if (superseded) {
        markMemorySuperseded(superseded.id, id);
      }
      created.push(record);
      existing.push(record);
    }

    return created;
  }
}

export const memoryService = new MemoryService();
