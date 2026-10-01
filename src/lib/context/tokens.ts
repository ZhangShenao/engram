/** Deterministic token estimate for budgeting (≈ 4 chars per token). */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}

export const DEFAULT_CONTEXT_TOKEN_BUDGET = 4096;

export const LAYER_BUDGET_HINTS = {
  personaMax: 1200,
  memoriesMax: 600,
  summaryMax: 500,
  turnsMax: 2000,
  hintMax: 80,
};
