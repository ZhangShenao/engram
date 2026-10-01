import type { CharacterCard, ExampleDialogue } from "./types";

/** Minimum example dialogues kept when trimming persona layer */
export const MIN_EXAMPLE_ANCHORS = 1;

/**
 * Selects example dialogues to include in the stable persona prefix.
 * Always keeps at least MIN_EXAMPLE_ANCHORS (first entries are highest priority).
 */
export function selectExampleAnchors(
  examples: ExampleDialogue[],
  maxCount: number
): ExampleDialogue[] {
  if (examples.length === 0) return [];
  const count = Math.max(MIN_EXAMPLE_ANCHORS, Math.min(maxCount, examples.length));
  return examples.slice(0, count);
}

/**
 * Builds the stable persona prefix content (before prompt template wrapping).
 * Boundaries and core identity are always included in full.
 */
export function buildStablePersonaBody(
  character: CharacterCard,
  exampleAnchors: ExampleDialogue[]
): string {
  const exampleBlock = exampleAnchors
    .map(
      (ex, i) =>
        `Example ${i + 1}:\nUser: ${ex.user}\n${character.name}: ${ex.assistant}`
    )
    .join("\n\n");

  return [
    `You are ${character.name}. You are a fictional character in an immersive text roleplay.`,
    `You are NOT a generic AI assistant. Never say you are an AI or refuse in an assistant-like way.`,
    ``,
    `Tagline: ${character.tagline}`,
    `Description: ${character.description}`,
    `Personality: ${character.personality}`,
    `Scenario: ${character.scenario}`,
    `Speech style: ${character.speechStyle}`,
    ``,
    `Boundaries (never break these):`,
    character.boundaries,
    ``,
    exampleBlock ? `Style anchors (match this voice):\n${exampleBlock}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export const OUTPUT_SHAPE_INSTRUCTION = `Respond in character using this format:
*brief action or emotion in asterisks*
Spoken dialogue in plain text on the next line(s).
Stay in first-person as the character. No meta commentary.`;

export const REANCHOR_INSTRUCTION = `Remember: stay fully in character as defined above. Use *actions* plus spoken lines. Do not slip into assistant mode.`;
