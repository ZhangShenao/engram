import { getLLMConfig } from "@/lib/llm/provider";
import type { MemoryExtractor } from "./extractor";
import { DeterministicMemoryExtractor } from "./extractor";
import { LLMMemoryExtractor } from "./llm-extractor";

export function createMemoryExtractor(): MemoryExtractor {
  if (getLLMConfig().apiKey.trim()) {
    return new LLMMemoryExtractor();
  }
  return new DeterministicMemoryExtractor();
}
