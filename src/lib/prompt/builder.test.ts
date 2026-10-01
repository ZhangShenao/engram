import { describe, it, expect } from "vitest";
import {
  buildPromptSections,
  assertPersonaContainsBoundaries,
  buildGenerationHint,
} from "./builder";
import { PROMPT_SECTION_ORDER } from "./templates";
import type { CharacterCard } from "@/lib/persona/types";

const sampleCharacter: CharacterCard = {
  id: "c1",
  name: "Test Hero",
  tagline: "A test",
  description: "Desc",
  personality: "Brave",
  scenario: "Arena",
  exampleDialogues: [
    { user: "Hi", assistant: "*nods*\nHello." },
  ],
  greeting: "Hey",
  speechStyle: "Short",
  boundaries: "No breaking the fourth wall.",
  createdAt: "",
  updatedAt: "",
};

describe("prompt builder", () => {
  it("keeps defined section order metadata", () => {
    const built = buildPromptSections({
      character: sampleCharacter,
      exampleAnchorCount: 1,
      memories: [],
      summary: "",
      recentTurns: [],
    });
    expect(built.sectionOrder).toEqual(PROMPT_SECTION_ORDER);
    expect(built.sectionOrder.indexOf("boundaries")).toBeLessThan(
      built.sectionOrder.indexOf("recent_turns")
    );
  });

  it("includes persona, boundaries, and output shape", () => {
    const built = buildPromptSections({
      character: sampleCharacter,
      exampleAnchorCount: 1,
      memories: [],
      summary: "They met before.",
      recentTurns: [{ role: "user", content: "Hello" }],
    });
    expect(
      assertPersonaContainsBoundaries(
        built.systemPersona,
        sampleCharacter.boundaries
      )
    ).toBe(true);
    expect(built.systemPersona).toMatch(/\*.*\*/);
    expect(built.systemPersona).toContain("NOT a generic AI assistant");
    expect(buildGenerationHint(sampleCharacter.name)).toContain("Test Hero");
  });
});
