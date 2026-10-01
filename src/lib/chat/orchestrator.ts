import { assembleContext } from "@/lib/context/assembler";
import {
  appendToSummary,
  getCharacter,
  getOrCreateSession,
  getSummary,
  insertMessage,
  listActiveMemories,
  listMessages,
} from "@/lib/db";
import { createLLMProvider } from "@/lib/llm/factory";
import { memoryService } from "@/lib/memory/service";
import { LOCAL_USER_ID } from "@/lib/db/schema";

export interface ChatResult {
  assistantMessageId: string;
  assistantContent: string;
  inspector: ReturnType<typeof assembleContext>;
  sessionId: string;
}

export async function runChatTurn(params: {
  characterId: string;
  userMessage: string;
}): Promise<ChatResult> {
  const character = getCharacter(params.characterId);
  if (!character) throw new Error("Character not found");

  const sessionId = getOrCreateSession(character.id, LOCAL_USER_ID);
  const userMsgId = insertMessage(sessionId, "user", params.userMessage);

  const history = listMessages(sessionId).filter((m) => m.id !== userMsgId);
  const verbatimTurns = history.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
  }));

  const memories = listActiveMemories(character.id, LOCAL_USER_ID);
  const summary = getSummary(sessionId);

  const inspector = assembleContext({
    character,
    memories,
    summary,
    verbatimTurns,
    latestUserMessage: params.userMessage,
  });

  const provider = createLLMProvider();
  let assistantContent = "";
  await provider.streamChat(inspector.messages, (chunk) => {
    assistantContent += chunk;
  });

  const assistantMessageId = insertMessage(
    sessionId,
    "assistant",
    assistantContent
  );

  await memoryService.processAssistantTurn({
    characterId: character.id,
    userId: LOCAL_USER_ID,
    userMessage: params.userMessage,
    assistantMessage: assistantContent,
    turnId: assistantMessageId,
  });

  if (inspector.trimLog.length > 0) {
    const dropped = inspector.trimLog.join("; ");
    appendToSummary(
      sessionId,
      `Earlier: ${history
        .slice(0, 2)
        .map((m) => `${m.role}: ${m.content.slice(0, 120)}`)
        .join(" | ")} (${dropped})`
    );
  }

  return {
    assistantMessageId,
    assistantContent,
    inspector,
    sessionId,
  };
}

export async function previewContext(params: {
  characterId: string;
  userMessage: string;
}) {
  const character = getCharacter(params.characterId);
  if (!character) throw new Error("Character not found");
  const sessionId = getOrCreateSession(character.id, LOCAL_USER_ID);
  const history = listMessages(sessionId);
  return assembleContext({
    character,
    memories: listActiveMemories(character.id, LOCAL_USER_ID),
    summary: getSummary(sessionId),
    verbatimTurns: history.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
    })),
    latestUserMessage: params.userMessage,
  });
}
