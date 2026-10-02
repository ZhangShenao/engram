"use client";

import { useParams } from "next/navigation";
import { ChatPanel } from "@/components/chat-panel";

export default function ChatPage() {
  const params = useParams<{ id: string }>();
  return <ChatPanel characterId={params.id} />;
}
