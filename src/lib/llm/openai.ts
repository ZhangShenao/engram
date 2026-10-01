import type { ChatMessage, LLMProvider } from "./provider";
import { getLLMConfig } from "./provider";

export class OpenAICompatibleProvider implements LLMProvider {
  readonly name = "openai-compatible";

  async streamChat(
    messages: ChatMessage[],
    onChunk: (text: string) => void
  ): Promise<string> {
    const { apiKey, baseUrl, model } = getLLMConfig();
    const url = `${baseUrl.replace(/\/$/, "")}/chat/completions`;

    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages,
        stream: true,
      }),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`LLM error ${res.status}: ${err}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let full = "";
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const data = trimmed.slice(5).trim();
        if (data === "[DONE]") continue;
        try {
          const json = JSON.parse(data);
          const delta = json.choices?.[0]?.delta?.content ?? "";
          if (delta) {
            full += delta;
            onChunk(delta);
          }
        } catch {
          /* ignore partial JSON */
        }
      }
    }

    return full;
  }
}

