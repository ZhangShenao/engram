import type { VerbatimTurn } from "@/lib/context/assembler";

export function formatEvictedTurnsForSummary(turns: VerbatimTurn[]): string {
  if (turns.length === 0) return "";
  return turns.map((t) => `${t.role}: ${t.content}`).join("\n");
}
