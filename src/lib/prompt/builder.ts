import {
  buildStablePersonaBody,
  OUTPUT_SHAPE_INSTRUCTION,
  REANCHOR_INSTRUCTION,
  selectExampleAnchors,
} from "@/lib/persona/stability";
import type { CharacterCard } from "@/lib/persona/types";
import type { RankedMemory } from "@/lib/memory/rank";
import { PROMPT_SECTION_ORDER } from "./templates";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface BuiltPromptSections {
  version: string;
  sectionOrder: readonly string[];
  systemPersona: string;
  memoriesBlock: string;
  summaryBlock: string;
  reanchorBlock: string;
  recentTurns: ChatTurn[];
  generationHint: string;
  /** Flat system string for providers that use a single system message */
  systemMessage: string;
}

export function buildGenerationHint(characterName: string): string {
  return `Continue the roleplay as ${characterName}. Reply with *action* then dialogue. Stay in character.`;
}

export function formatMemoriesBlock(memories: RankedMemory[]): string {
  if (memories.length === 0) return "";
  const lines = memories.map((m) => `- [${m.type}] ${m.text}`);
  return `[What you remember about the user and story]\n${lines.join("\n")}`;
}

export function formatSummaryBlock(summary: string): string {
  if (!summary.trim()) return "";
  return `[Earlier conversation summary]\n${summary.trim()}`;
}

export function buildPromptSections(params: {
  character: CharacterCard;
  exampleAnchorCount: number;
  memories: RankedMemory[];
  summary: string;
  recentTurns: ChatTurn[];
}): BuiltPromptSections {
  const anchors = selectExampleAnchors(
    params.character.exampleDialogues,
    params.exampleAnchorCount
  );
  const personaBody = buildStablePersonaBody(params.character, anchors);
  const memoriesBlock = formatMemoriesBlock(params.memories);
  const summaryBlock = formatSummaryBlock(params.summary);
  const reanchorBlock = REANCHOR_INSTRUCTION;
  const generationHint = buildGenerationHint(params.character.name);

  const systemParts = [
    personaBody,
    OUTPUT_SHAPE_INSTRUCTION,
    memoriesBlock,
    summaryBlock,
    reanchorBlock,
  ].filter((p) => p.trim().length > 0);

  return {
    version: "1.0.0",
    sectionOrder: PROMPT_SECTION_ORDER,
    systemPersona: personaBody + "\n\n" + OUTPUT_SHAPE_INSTRUCTION,
    memoriesBlock,
    summaryBlock,
    reanchorBlock,
    recentTurns: params.recentTurns,
    generationHint,
    systemMessage: systemParts.join("\n\n"),
  };
}

export function assertPersonaContainsBoundaries(
  systemPersona: string,
  boundaries: string
): boolean {
  return (
    systemPersona.includes("Boundaries") &&
    systemPersona.includes(boundaries) &&
    systemPersona.includes("NOT a generic AI assistant")
  );
}
