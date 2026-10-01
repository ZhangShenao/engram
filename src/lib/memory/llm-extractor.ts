import { getLLMConfig } from "@/lib/llm/provider";
import type { ExtractorInput, MemoryExtractor } from "./extractor";
import type { MemoryCandidate, MemoryType } from "./types";
import { MEMORY_TYPES } from "./types";

function parseCandidates(raw: string): MemoryCandidate[] {
  try {
    const json = JSON.parse(raw) as {
      memories?: Array<{
        type?: string;
        text?: string;
        salience?: number;
        slot?: string | null;
        supersedesMemoryId?: string;
      }>;
    };
    if (!Array.isArray(json.memories)) return [];
    return json.memories
      .filter((m) => m.text && m.type && MEMORY_TYPES.includes(m.type as MemoryType))
      .map((m) => ({
        type: m.type as MemoryType,
        text: m.text!.trim(),
        salience: Math.min(1, Math.max(0, m.salience ?? 0.6)),
        slot: m.slot ?? null,
        supersedesMemoryId: m.supersedesMemoryId,
      }));
  } catch {
    return [];
  }
}

export class LLMMemoryExtractor implements MemoryExtractor {
  async extract(input: ExtractorInput): Promise<MemoryCandidate[]> {
    const { apiKey, baseUrl, model } = getLLMConfig();
    const url = `${baseUrl.replace(/\/$/, "")}/chat/completions`;

    const system = `You extract structured roleplay memories from the latest exchange.
Return JSON only: {"memories":[{"type":"fact|relationship|promise|boundary|plot","text":"...","salience":0.0-1.0,"slot":null or "user_name"}]}
Rules:
- Only salient, durable facts worth recalling later.
- Use slot "user_name" only for the user's name (one slot; new name supersedes).
- Multiple facts/promises/plot beats can coexist; do not duplicate the same slot.
- If nothing to store, return {"memories":[]}.`;

    const user = `User: ${input.userMessage}\nAssistant: ${input.assistantMessage}`;

    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        temperature: 0.2,
        response_format: { type: "json_object" },
      }),
    });

    if (!res.ok) {
      return [];
    }

    const data = await res.json();
    const content = data.choices?.[0]?.message?.content ?? "{}";
    return parseCandidates(content);
  }
}
