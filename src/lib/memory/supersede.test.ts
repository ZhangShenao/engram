import { describe, it, expect } from "vitest";
import { findSupersededMemory } from "./supersede";
import type { MemoryRecord } from "./types";

function mem(
  partial: Partial<MemoryRecord> & { id: string; text: string }
): MemoryRecord {
  return {
    characterId: "c",
    userId: "local",
    type: "fact",
    salience: 0.8,
    slot: null,
    sourceTurnId: null,
    supersededById: null,
    deletedAt: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...partial,
  };
}

describe("memory supersede", () => {
  it("supersedes name fact when a new name is learned", () => {
    const oldName = mem({
      id: "old",
      text: "The user's name is Bob.",
      slot: "user_name",
    });
    const target = findSupersededMemory(
      {
        type: "fact",
        text: "The user's name is Alex.",
        salience: 0.9,
        slot: "user_name",
      },
      [oldName]
    );
    expect(target?.id).toBe("old");
  });

  it("keeps two unrelated facts active", () => {
    const coffee = mem({
      id: "coffee",
      type: "fact",
      text: "The user likes coffee.",
    });
    const target = findSupersededMemory(
      {
        type: "fact",
        text: "The user has a dog named Pepper.",
        salience: 0.7,
      },
      [coffee]
    );
    expect(target).toBeNull();
  });
});
