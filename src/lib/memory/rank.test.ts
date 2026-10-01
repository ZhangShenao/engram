import { describe, it, expect } from "vitest";
import { rankMemories, relevanceScore } from "./rank";
import type { MemoryRecord } from "./types";

function mem(partial: Partial<MemoryRecord> & { id: string }): MemoryRecord {
  return {
    characterId: "c",
    userId: "local",
    type: "fact",
    text: "default",
    salience: 0.5,
    slot: null,
    sourceTurnId: null,
    supersededById: null,
    deletedAt: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...partial,
  };
}

describe("memory rank", () => {
  it("ranks higher salience and relevance", () => {
    const ranked = rankMemories(
      [
        mem({ id: "1", text: "User likes coffee", salience: 0.3 }),
        mem({ id: "2", text: "User name is Alex", salience: 0.9 }),
      ],
      "What is my name Alex?",
      Date.now()
    );
    expect(ranked[0].id).toBe("2");
  });

  it("excludes deleted and superseded", () => {
    const ranked = rankMemories(
      [
        mem({ id: "1", deletedAt: new Date().toISOString() }),
        mem({ id: "2", supersededById: "x" }),
        mem({ id: "3", text: "active" }),
      ],
      "active",
      Date.now()
    );
    expect(ranked).toHaveLength(1);
    expect(ranked[0].id).toBe("3");
  });

  it("relevance score increases with overlap", () => {
    expect(relevanceScore("dragon fire", "ancient dragon breathes fire")).toBeGreaterThan(
      relevanceScore("dragon fire", "quiet library")
    );
  });
});
