"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { CharacterCard } from "@/lib/persona/types";
import type { AssembledContext } from "@/lib/context/assembler";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ContextInspector } from "@/components/context-inspector";
import { MemoryPanel } from "@/components/memory-panel";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ArrowLeft, Send } from "lucide-react";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export default function ChatPage() {
  const params = useParams();
  const characterId = params.id as string;
  const [character, setCharacter] = useState<CharacterCard | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [inspector, setInspector] = useState<AssembledContext | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const [cRes, mRes] = await Promise.all([
      fetch(`/api/characters/${characterId}`),
      fetch(`/api/chat/${characterId}`),
    ]);
    const cData = await cRes.json();
    const mData = await mRes.json();
    setCharacter(cData.character);
    setMessages(mData.messages);
  }, [characterId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const send = async () => {
    if (!input.trim() || streaming) return;
    const userText = input.trim();
    setInput("");
    setStreaming(true);
    const tempUserId = `temp-u-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, role: "user", content: userText },
      { id: "streaming", role: "assistant", content: "" },
    ]);

    const res = await fetch(`/api/chat/${characterId}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: userText }),
    });

    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) {
      setStreaming(false);
      return;
    }

    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const payload = JSON.parse(line.slice(5).trim());
        if (payload.type === "inspector") {
          setInspector(payload.inspector as AssembledContext);
        }
        if (payload.type === "chunk") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === "streaming"
                ? { ...m, content: m.content + payload.text }
                : m
            )
          );
        }
        if (payload.type === "done") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === "streaming"
                ? { id: payload.messageId, role: "assistant", content: payload.content }
                : m
            )
          );
        }
      }
    }
    setStreaming(false);
    await load();
  };

  if (!character) {
    return (
      <div className="p-6 text-center text-muted-foreground">Loading chat…</div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-b from-background to-muted/30">
      <header className="border-b bg-background/80 backdrop-blur sticky top-0 z-10 px-4 py-3 flex items-center gap-3">
        <Link href="/" className={cn(buttonVariants({ variant: "ghost", size: "icon" }))}>
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="font-semibold leading-tight">{character.name}</h1>
          <p className="text-xs text-muted-foreground">{character.tagline}</p>
        </div>
      </header>

      <div className="flex-1 grid lg:grid-cols-[1fr_380px] gap-0 max-w-7xl w-full mx-auto">
        <section className="flex flex-col min-h-[calc(100vh-56px)] border-r">
          <ScrollArea className="flex-1 px-4 py-4">
            <div className="space-y-4 max-w-2xl mx-auto">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                    m.role === "user"
                      ? "bg-primary text-primary-foreground ml-8"
                      : "bg-card border mr-8"
                  }`}
                >
                  {m.content || (streaming && m.id === "streaming" ? "…" : "")}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </ScrollArea>
          <div className="p-4 border-t bg-background">
            <div className="flex gap-2 max-w-2xl mx-auto">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Stay in scene — type your line…"
                rows={2}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <Button onClick={send} disabled={streaming} size="icon" className="shrink-0 h-auto">
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>

        <aside className="hidden lg:block p-4">
          <Tabs defaultValue="inspector">
            <TabsList className="w-full">
              <TabsTrigger value="inspector" className="flex-1">Context</TabsTrigger>
              <TabsTrigger value="memory" className="flex-1">Memory</TabsTrigger>
            </TabsList>
            <TabsContent value="inspector" className="mt-3">
              <ContextInspector inspector={inspector} />
            </TabsContent>
            <TabsContent value="memory" className="mt-3">
              <MemoryPanel characterId={characterId} />
            </TabsContent>
          </Tabs>
        </aside>
      </div>

      <div className="lg:hidden border-t p-3">
        <Tabs defaultValue="inspector">
          <TabsList className="w-full">
            <TabsTrigger value="inspector" className="flex-1">Context</TabsTrigger>
            <TabsTrigger value="memory" className="flex-1">Memory</TabsTrigger>
          </TabsList>
          <TabsContent value="inspector" className="mt-2">
            <ContextInspector inspector={inspector} />
          </TabsContent>
          <TabsContent value="memory" className="mt-2">
            <MemoryPanel characterId={characterId} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
