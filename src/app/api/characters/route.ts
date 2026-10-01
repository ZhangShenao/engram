import { NextResponse } from "next/server";
import { createCharacter, getOrCreateSession, insertMessage, listCharacters } from "@/lib/db";
import { LOCAL_USER_ID } from "@/lib/db/schema";
import { seedIfEmpty } from "@/lib/db/seed";
import type { CharacterInput } from "@/lib/persona/types";

export const runtime = "nodejs";

export async function GET() {
  seedIfEmpty();
  return NextResponse.json({ characters: listCharacters() });
}

export async function POST(req: Request) {
  seedIfEmpty();
  const body = (await req.json()) as CharacterInput;
  const created = createCharacter(body);
  const sessionId = getOrCreateSession(created.id, LOCAL_USER_ID);
  insertMessage(sessionId, "assistant", created.greeting);
  return NextResponse.json({ character: created });
}
