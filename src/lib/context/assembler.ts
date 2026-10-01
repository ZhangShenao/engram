import type { CharacterCard } from "@/lib/persona/types";
import {
  buildStablePersonaBody,
  OUTPUT_SHAPE_INSTRUCTION,
  REANCHOR_INSTRUCTION,
  selectExampleAnchors,
  MIN_EXAMPLE_ANCHORS,
} from "@/lib/persona/stability";
import {
  rankMemories,
  packMemoriesByTokenBudget,
  type RankedMemory,
} from "@/lib/memory/rank";
import type { MemoryRecord } from "@/lib/memory/types";
import { buildGenerationHint, formatMemoriesBlock, formatSummaryBlock } from "@/lib/prompt/builder";
import { PROMPT_SECTION_ORDER } from "@/lib/prompt/templates";
import {
  DEFAULT_CONTEXT_TOKEN_BUDGET,
  estimateTokens,
  LAYER_BUDGET_HINTS,
} from "./tokens";

export interface VerbatimTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface ContextLayer {
  id: string;
  label: string;
  content: string;
  tokenEstimate: number;
  trimmed: boolean;
  trimReason?: string;
}

export interface AssembledContext {
  messages: { role: "system" | "user" | "assistant"; content: string }[];
  layers: ContextLayer[];
  trimLog: string[];
  /** Turns removed from the verbatim window this assembly (for rolling summary). */
  evictedTurns: VerbatimTurn[];
  totalTokens: number;
  budget: number;
}

export interface AssembleInput {
  character: CharacterCard;
  memories: MemoryRecord[];
  summary: string;
  verbatimTurns: VerbatimTurn[];
  latestUserMessage: string;
  budget?: number;
}

function turnsToPairs(turns: VerbatimTurn[]): VerbatimTurn[][] {
  const pairs: VerbatimTurn[][] = [];
  let i = 0;
  while (i < turns.length) {
    const pair: VerbatimTurn[] = [];
    if (turns[i].role === "user") {
      pair.push(turns[i]);
      i++;
      if (i < turns.length && turns[i].role === "assistant") {
        pair.push(turns[i]);
        i++;
      }
    } else {
      pair.push(turns[i]);
      i++;
    }
    pairs.push(pair);
  }
  return pairs;
}

function shrinkSummary(summary: string, maxTokens: number): { text: string; trimmed: boolean } {
  const maxChars = maxTokens * 4;
  if (estimateTokens(summary) <= maxTokens) {
    return { text: summary, trimmed: false };
  }
  const cut = summary.slice(0, maxChars - 3) + "...";
  return { text: cut, trimmed: true };
}

export function assembleContext(input: AssembleInput): AssembledContext {
  const budget = input.budget ?? DEFAULT_CONTEXT_TOKEN_BUDGET;
  const trimLog: string[] = [];

  let exampleCount = input.character.exampleDialogues.length;
  let summaryText = input.summary;
  let summaryTrimmed = false;

  const ranked = rankMemories(input.memories, input.latestUserMessage);
  let { packed: packedMemories, dropped: droppedMemories } = packMemoriesByTokenBudget(
    ranked,
    LAYER_BUDGET_HINTS.memoriesMax,
    estimateTokens
  );

  if (droppedMemories.length > 0) {
    trimLog.push(`Dropped ${droppedMemories.length} lower-ranked memories from context.`);
  }

  let pairs = turnsToPairs([...input.verbatimTurns]);
  const trimmedTurnIds: string[] = [];
  const evictedTurns: VerbatimTurn[] = [];

  const buildLayers = () => {
    const anchors = selectExampleAnchors(
      input.character.exampleDialogues,
      exampleCount
    );
    const personaBody = buildStablePersonaBody(input.character, anchors);
    const personaContent = personaBody + "\n\n" + OUTPUT_SHAPE_INSTRUCTION;
    const memBlock = formatMemoriesBlock(packedMemories);
    const sumBlock = formatSummaryBlock(summaryText);
    const hint = buildGenerationHint(input.character.name);

    const layers: ContextLayer[] = [
      {
        id: "persona",
        label: "Stable persona prefix",
        content: personaContent,
        tokenEstimate: estimateTokens(personaContent),
        trimmed: exampleCount < input.character.exampleDialogues.length,
        trimReason:
          exampleCount < input.character.exampleDialogues.length
            ? `Reduced example dialogues to ${exampleCount} (min ${MIN_EXAMPLE_ANCHORS}).`
            : undefined,
      },
      {
        id: "memories",
        label: "Retrieved memories",
        content: memBlock || "(none)",
        tokenEstimate: estimateTokens(memBlock),
        trimmed: droppedMemories.length > 0,
        trimReason: droppedMemories.length > 0 ? "Low-score memories omitted." : undefined,
      },
      {
        id: "summary",
        label: "Rolling summary",
        content: sumBlock || "(none)",
        tokenEstimate: estimateTokens(sumBlock),
        trimmed: summaryTrimmed,
        trimReason: summaryTrimmed ? "Summary truncated." : undefined,
      },
      {
        id: "recent",
        label: "Recent turns (verbatim)",
        content: pairs
          .flat()
          .map((t) => `${t.role}: ${t.content}`)
          .join("\n\n") || "(none)",
        tokenEstimate: estimateTokens(
          pairs.flat().map((t) => t.content).join("\n")
        ),
        trimmed: trimmedTurnIds.length > 0,
        trimReason:
          trimmedTurnIds.length > 0
            ? `Removed ${trimmedTurnIds.length} oldest turn(s).`
            : undefined,
      },
      {
        id: "reanchor",
        label: "Re-anchor",
        content: REANCHOR_INSTRUCTION,
        tokenEstimate: estimateTokens(REANCHOR_INSTRUCTION),
        trimmed: false,
      },
      {
        id: "hint",
        label: "Generation hint",
        content: hint,
        tokenEstimate: estimateTokens(hint),
        trimmed: false,
      },
    ];

    const total = layers.reduce((s, l) => s + l.tokenEstimate, 0);
    return { layers, total, personaContent, memBlock, sumBlock, hint };
  };

  let built = buildLayers();

  while (built.total > budget && pairs.length > 0) {
    const removed = pairs.shift();
    if (removed) {
      trimmedTurnIds.push(...removed.map((t) => t.id));
      evictedTurns.push(...removed);
      trimLog.push("Trimmed oldest verbatim turn pair.");
    }
    built = buildLayers();
  }

  while (built.total > budget && estimateTokens(summaryText) > 50) {
    const shrunk = shrinkSummary(summaryText, Math.floor(LAYER_BUDGET_HINTS.summaryMax * 0.6));
    summaryText = shrunk.text;
    summaryTrimmed = true;
    trimLog.push("Shrunk rolling summary.");
    built = buildLayers();
  }

  while (built.total > budget && packedMemories.length > 1) {
    const removed = packedMemories.pop();
    if (removed) droppedMemories.push(removed);
    trimLog.push("Removed lowest packed memory.");
    built = buildLayers();
  }

  while (
    built.total > budget &&
    exampleCount > MIN_EXAMPLE_ANCHORS
  ) {
    exampleCount--;
    trimLog.push("Reduced example dialogue anchors.");
    built = buildLayers();
  }

  const messages: { role: "system" | "user" | "assistant"; content: string }[] = [
    {
      role: "system",
      content: [
        built.personaContent,
        built.memBlock,
        built.sumBlock,
        REANCHOR_INSTRUCTION,
        built.hint,
      ]
        .filter((x) => x && x.trim())
        .join("\n\n"),
    },
  ];

  for (const pair of pairs) {
    for (const t of pair) {
      messages.push({ role: t.role, content: t.content });
    }
  }

  if (
    messages.length === 1 ||
    messages[messages.length - 1]?.role !== "user"
  ) {
    messages.push({ role: "user", content: input.latestUserMessage });
  }

  return {
    messages,
    layers: built.layers,
    trimLog,
    evictedTurns,
    totalTokens: built.total,
    budget,
  };
}

export function getSectionOrder(): readonly string[] {
  return PROMPT_SECTION_ORDER;
}

export function personaLayerPresent(layers: ContextLayer[]): boolean {
  const persona = layers.find((l) => l.id === "persona");
  return !!persona && persona.content.includes("Boundaries") && persona.tokenEstimate > 0;
}
