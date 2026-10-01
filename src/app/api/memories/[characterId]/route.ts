import { NextResponse } from "next/server";
import { listMemories, softDeleteMemory, updateMemory } from "@/lib/db";
import { LOCAL_USER_ID } from "@/lib/db/schema";
import type { MemoryType } from "@/lib/memory/types";

export const runtime = "nodejs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ characterId: string }> }
) {
  const { characterId } = await params;
  const memories = listMemories(characterId, LOCAL_USER_ID).filter(
    (m) => !m.deletedAt
  );
  return NextResponse.json({ memories });
}

export async function PATCH(req: Request) {
  const body = (await req.json()) as {
    id: string;
    text?: string;
    type?: MemoryType;
    salience?: number;
  };
  const updated = updateMemory(body.id, {
    text: body.text,
    type: body.type,
    salience: body.salience,
  });
  if (!updated) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json({ memory: updated });
}

export async function DELETE(req: Request) {
  const { id } = (await req.json()) as { id: string };
  const ok = softDeleteMemory(id);
  if (!ok) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
