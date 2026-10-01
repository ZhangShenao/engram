import type { MemoryRecord } from "./types";

const DEFAULT_WEIGHTS = {
  salience: 0.45,
  recency: 0.35,
  relevance: 0.2,
};

function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^\w\s]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 2)
  );
}

export function relevanceScore(query: string, memoryText: string): number {
  const q = tokenize(query);
  const m = tokenize(memoryText);
  if (q.size === 0 || m.size === 0) return 0;
  let overlap = 0;
  for (const w of q) {
    if (m.has(w)) overlap++;
  }
  return overlap / q.size;
}

function recencyScore(createdAt: string, nowMs: number): number {
  const ageMs = nowMs - new Date(createdAt).getTime();
  const dayMs = 86400000;
  const days = ageMs / dayMs;
  return Math.max(0, 1 - days / 30);
}

export interface RankedMemory extends MemoryRecord {
  score: number;
}

export function rankMemories(
  memories: MemoryRecord[],
  query: string,
  nowMs = Date.now(),
  weights = DEFAULT_WEIGHTS
): RankedMemory[] {
  const active = memories.filter((m) => !m.deletedAt && !m.supersededById);
  return active
    .map((m) => {
      const score =
        weights.salience * m.salience +
        weights.recency * recencyScore(m.createdAt, nowMs) +
        weights.relevance * relevanceScore(query, m.text);
      return { ...m, score };
    })
    .sort((a, b) => b.score - a.score);
}

export function packMemoriesByTokenBudget(
  ranked: RankedMemory[],
  budgetTokens: number,
  estimateTokens: (text: string) => number
): { packed: RankedMemory[]; dropped: RankedMemory[] } {
  const packed: RankedMemory[] = [];
  const dropped: RankedMemory[] = [];
  let used = 0;
  const headerTokens = estimateTokens("[memories]\n");

  for (const m of ranked) {
    const line = `- [${m.type}] ${m.text}`;
    const cost = estimateTokens(line + "\n");
    if (used + cost + headerTokens <= budgetTokens || packed.length === 0) {
      if (packed.length > 0 || used + cost + headerTokens <= budgetTokens) {
        packed.push(m);
        used += cost;
      } else {
        dropped.push(m);
      }
    } else {
      dropped.push(m);
    }
  }
  return { packed, dropped };
}
