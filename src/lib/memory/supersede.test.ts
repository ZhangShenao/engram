import { describe, it, expect } from "vitest";
import { findSupersededMemory } from "./supersede";
import type { MemoryRecord } from "./types";

const base: MemoryRecord = {
  id: "old",
  characterId: "c",
  userId: "local",
  type: "fact",
  text: "The user's name is Bob.",
  salience: 0.8,
  sourceTurnId: null,
  supersededById: null,
  deletedAt: null,
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
};

describe("memory supersede", () => {
  it("supersedes same-type fact when name changes", () => {
    const target = findSupersededMemory(
      {
        type: "fact",
        text: "The user's name is Alex.",
        salience: 0.9,
      },
      [base]
    );
    expect(target?.id).toBe("old");
  });
});
