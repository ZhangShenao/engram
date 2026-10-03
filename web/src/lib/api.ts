import type {
  Character,
  CharacterDraft,
  ChatPayload,
  ChatSummary,
  Inspector,
  Memory,
  TurnTimings,
} from "./types";

async function parseError(response: Response, fallback: string) {
  try {
    const data = (await response.json()) as { error?: unknown; detail?: unknown };
    const raw = data.error ?? data.detail;
    if (typeof raw === "string" && raw.trim()) return raw;
  } catch {
    /* body was not JSON */
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(await parseError(response, `Request failed (${response.status})`));
  }
  return (await response.json()) as T;
}

export function listCharacters() {
  return request<{ characters: Character[] }>("/gateway/api/characters").then(
    (data) => data.characters
  );
}

export function listChats() {
  return request<{ chats: ChatSummary[] }>("/gateway/api/chats").then((data) => data.chats);
}

export function getChat(characterId: string) {
  return request<ChatPayload>(`/gateway/api/chats/${characterId}`);
}

export function createCharacter(draft: CharacterDraft) {
  return request<{ character: Character }>("/gateway/api/characters", {
    method: "POST",
    body: JSON.stringify(draft),
  }).then((data) => data.character);
}

export function updateCharacter(id: string, draft: CharacterDraft) {
  return request<{ character: Character }>(`/gateway/api/characters/${id}`, {
    method: "PUT",
    body: JSON.stringify(draft),
  }).then((data) => data.character);
}

export function deleteCharacter(id: string) {
  return request<{ ok: boolean }>(`/gateway/api/characters/${id}`, { method: "DELETE" });
}

export function listMemories(characterId: string) {
  return request<{ memories: Memory[] }>(`/gateway/api/memories/${characterId}`).then(
    (data) => data.memories
  );
}

export function saveMemory(memory: Memory) {
  return request<{ memory: Memory }>(`/gateway/api/memories/${memory.id}`, {
    method: "PATCH",
    body: JSON.stringify({
      text: memory.text,
      type: memory.type,
      salience: memory.salience,
    }),
  });
}

export function deleteMemory(id: string) {
  return request<{ ok: boolean }>(`/gateway/api/memories/${id}`, { method: "DELETE" });
}

export function getInspector(characterId: string) {
  return request<{ inspector: Inspector | null }>(`/gateway/api/inspector/${characterId}`);
}

export interface StreamHandlers {
  onInspector?: (inspector: Inspector) => void;
  onChunk?: (text: string) => void;
  onDone?: (payload: {
    messageId: string;
    content: string;
    provider?: string;
    timings?: TurnTimings;
  }) => void;
  onError?: (message: string) => void;
}

export async function streamTurn(path: string, body: unknown, handlers: StreamHandlers) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok || !response.body) {
    throw new Error(await parseError(response, `Request failed (${response.status})`));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((item) => item.startsWith("data:"));
      if (!line) continue;
      const payload = JSON.parse(line.slice(5).trim()) as {
        type?: string;
        text?: string;
        inspector?: Inspector;
        message?: string;
        messageId?: string;
        content?: string;
        provider?: string;
        timings?: TurnTimings;
        error?: string;
      };
      if (payload.type === "inspector" && payload.inspector) {
        handlers.onInspector?.(payload.inspector);
      } else if (payload.type === "chunk" && payload.text) {
        handlers.onChunk?.(payload.text);
      } else if (payload.type === "done" && payload.messageId) {
        handlers.onDone?.({
          messageId: payload.messageId,
          content: payload.content ?? "",
          provider: payload.provider,
          timings: payload.timings,
        });
      } else if (payload.type === "error") {
        handlers.onError?.(payload.message || "The turn failed.");
      } else if (payload.error) {
        handlers.onError?.(payload.error);
      }
    }
  }
}
