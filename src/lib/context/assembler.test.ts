import { describe, it, expect } from "vitest";
import { assembleContext, personaLayerPresent } from "./assembler";
import type { CharacterCard } from "@/lib/persona/types";
import type { MemoryRecord } from "@/lib/memory/types";

const character: CharacterCard = {
  id: "c1",
  name: "Lyra",
  tagline: "Mage",
  description: "A mage",
  personality: "Wise",
  scenario: "Tower",
  exampleDialogues: [
    { user: "Hello", assistant: "*bows*\nWelcome." },
    { user: "Teach me", assistant: "*smiles*\nListen." },
  ],
  greeting: "Hi",
  speechStyle: "Formal",
  boundaries: "Never OOC.",
  createdAt: "",
  updatedAt: "",
};

function makeTurns(count: number) {
  const turns = [];
  for (let i = 0; i < count; i++) {
    turns.push({
      id: `u${i}`,
      role: "user" as const,
      content: `User message number ${i} with some padding text to consume tokens.`,
    });
    turns.push({
      id: `a${i}`,
      role: "assistant" as const,
      content: `Assistant reply number ${i} with roleplay *action* and dialogue.`,
    });
  }
  return turns;
}

describe("context assembler", () => {
  it("trims oldest turns before dropping persona", () => {
    const result = assembleContext({
      character,
      memories: [],
      summary: "A long ".repeat(200),
      verbatimTurns: makeTurns(40),
      latestUserMessage: "Latest?",
      budget: 800,
    });
    expect(personaLayerPresent(result.layers)).toBe(true);
    expect(result.layers.find((l) => l.id === "persona")?.content).toContain(
      "Never OOC."
    );
    expect(result.trimLog.some((t) => t.includes("oldest"))).toBe(true);
    expect(result.evictedTurns.length).toBeGreaterThan(0);
    expect(result.evictedTurns[0].role).toBeDefined();
  });

  it("lists evicted turns in order when trimming verbatim history", () => {
    const turns = makeTurns(8);
    const firstPairId = turns[0].id;
    const result = assembleContext({
      character,
      memories: [],
      summary: "",
      verbatimTurns: turns,
      latestUserMessage: "Latest?",
      budget: 400,
    });
    const evictedIds = result.evictedTurns.map((t) => t.id);
    expect(evictedIds).toContain(firstPairId);
    const recentContent =
      result.layers.find((l) => l.id === "recent")?.content ?? "";
    expect(recentContent).not.toContain(turns[0].content);
  });

  it("records trim log on budget overflow", () => {
    const memories: MemoryRecord[] = Array.from({ length: 20 }).map((_, i) => ({
      id: `m${i}`,
      characterId: "c1",
      userId: "local",
      type: "fact",
      text: `Memory fact number ${i} with extra words`,
      salience: 0.5,
      slot: null,
      sourceTurnId: null,
      supersededById: null,
      deletedAt: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }));
    const result = assembleContext({
      character,
      memories,
      summary: "",
      verbatimTurns: makeTurns(5),
      latestUserMessage: "test",
      budget: 1200,
    });
    expect(result.totalTokens).toBeLessThanOrEqual(result.budget + 50);
    expect(personaLayerPresent(result.layers)).toBe(true);
  });

  it("keeps persona when history is long", () => {
    const result = assembleContext({
      character,
      memories: [],
      summary: "x".repeat(1000),
      verbatimTurns: makeTurns(60),
      latestUserMessage: "Still here?",
      budget: 600,
    });
    const persona = result.layers.find((l) => l.id === "persona");
    expect(persona?.content).toContain("Lyra");
    expect(persona?.content).toContain("Never OOC.");
  });
});
