import { NextResponse } from "next/server";
import { seedIfEmpty } from "@/lib/db/seed";
import { getOrCreateSession, listMessages } from "@/lib/db";
import { LOCAL_USER_ID } from "@/lib/db/schema";
import { runChatTurn } from "@/lib/chat/orchestrator";

export const runtime = "nodejs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ characterId: string }> }
) {
  seedIfEmpty();
  const { characterId } = await params;
  const sessionId = getOrCreateSession(characterId, LOCAL_USER_ID);
  const messages = listMessages(sessionId);
  return NextResponse.json({ messages, sessionId });
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ characterId: string }> }
) {
  seedIfEmpty();
  const { characterId } = await params;
  const { message } = (await req.json()) as { message: string };
  if (!message?.trim()) {
    return NextResponse.json({ error: "Message required" }, { status: 400 });
  }

  const result = await runChatTurn({
    characterId,
    userMessage: message.trim(),
  });

  return NextResponse.json({
    content: result.assistantContent,
    messageId: result.assistantMessageId,
    inspector: result.inspector,
  });
}
