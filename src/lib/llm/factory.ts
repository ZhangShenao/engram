import type { LLMProvider } from "./provider";
import { getLLMConfig } from "./provider";
import { OpenAICompatibleProvider } from "./openai";
import { ScriptedLLMProvider } from "./scripted";

export function createLLMProvider(): LLMProvider {
  const { apiKey } = getLLMConfig();
  if (apiKey.trim()) {
    return new OpenAICompatibleProvider();
  }
  return new ScriptedLLMProvider();
}
