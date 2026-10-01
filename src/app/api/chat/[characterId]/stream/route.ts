import { seedIfEmpty } from "@/lib/db/seed";
import {
  getCharacter,
  getOrCreateSession,
  getSummary,
  insertMessage,
  listActiveMemories,
  listMessages,
  appendToSummary,
} from "@/lib/db";
import { LOCAL_USER_ID } from "@/lib/db/schema";
import { assembleContext } from "@/lib/context/assembler";
import { createLLMProvider } from "@/lib/llm/factory";
import { memoryService } from "@/lib/memory/service";
import { formatEvictedTurnsForSummary } from "@/lib/chat/summary";

export const runtime = "nodejs";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ characterId: string }> }
) {
  seedIfEmpty();
  const { characterId } = await params;
  const { message } = (await req.json()) as { message: string };
  if (!message?.trim()) {
    return new Response("Message required", { status: 400 });
  }

  const character = getCharacter(characterId);
  if (!character) return new Response("Not found", { status: 404 });

  const sessionId = getOrCreateSession(characterId, LOCAL_USER_ID);
  const userMsgId = insertMessage(sessionId, "user", message.trim());
  const history = listMessages(sessionId).filter((m) => m.id !== userMsgId);

  const inspector = assembleContext({
    character,
    memories: listActiveMemories(characterId, LOCAL_USER_ID),
    summary: getSummary(sessionId),
    verbatimTurns: history.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
    })),
    latestUserMessage: message.trim(),
  });

  const encoder = new TextEncoder();
  let assistantContent = "";

  const stream = new ReadableStream({
    async start(controller) {
      const send = (obj: object) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));
      };

      send({ type: "inspector", inspector });

      try {
        const provider = createLLMProvider();
        await provider.streamChat(inspector.messages, (chunk) => {
          assistantContent += chunk;
          send({ type: "chunk", text: chunk });
        });

        const assistantMessageId = insertMessage(
          sessionId,
          "assistant",
          assistantContent
        );

        await memoryService.processAssistantTurn({
          characterId,
          userId: LOCAL_USER_ID,
          userMessage: message.trim(),
          assistantMessage: assistantContent,
          turnId: assistantMessageId,
        });

        if (inspector.evictedTurns.length > 0) {
          appendToSummary(
            sessionId,
            formatEvictedTurnsForSummary(inspector.evictedTurns)
          );
        }

        send({
          type: "done",
          messageId: assistantMessageId,
          content: assistantContent,
        });
      } catch (err) {
        send({
          type: "error",
          message: err instanceof Error ? err.message : "Stream failed",
        });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
