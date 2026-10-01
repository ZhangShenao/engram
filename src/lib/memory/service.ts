import { v4 as uuidv4 } from "uuid";
import { insertMemory, listMemories, markMemorySuperseded } from "@/lib/db";
import { createMemoryExtractor } from "./factory";
import { inferMemorySlot } from "./slots";
import { findSupersededMemory } from "./supersede";
import type { MemoryRecord } from "./types";

export class MemoryService {
  constructor(
    private getExtractor = createMemoryExtractor
  ) {}

  async processAssistantTurn(params: {
    characterId: string;
    userId: string;
    userMessage: string;
    assistantMessage: string;
    turnId: string;
  }): Promise<MemoryRecord[]> {
    const extractor = this.getExtractor();
    const candidates = await extractor.extract({
      userMessage: params.userMessage,
      assistantMessage: params.assistantMessage,
      turnId: params.turnId,
    });

    const existing = listMemories(params.characterId, params.userId);
    const created: MemoryRecord[] = [];

    for (const candidate of candidates) {
      const id = uuidv4();
      const slot =
        candidate.slot ?? inferMemorySlot(candidate.type, candidate.text);
      const superseded = findSupersededMemory(candidate, existing);
      const record = insertMemory({
        id,
        characterId: params.characterId,
        userId: params.userId,
        type: candidate.type,
        text: candidate.text,
        salience: candidate.salience,
        slot,
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
