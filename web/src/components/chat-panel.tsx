"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MoreHorizontal, RefreshCw, SendHorizontal, StepForward } from "lucide-react";
import { Avatar, MenuButton, useShell } from "@/components/shell";
import { ErrorState, LoadingState } from "@/components/states";
import { InspectorSheet, MemorySheet } from "@/components/insight-sheets";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { deleteCharacter, getChat, getInspector, streamTurn } from "@/lib/api";
import { transcriptAfterFailedStream } from "@/lib/transcript";
import type { ChatMessage, Inspector } from "@/lib/types";

export function ChatPanel({ characterId }: { characterId: string }) {
  const router = useRouter();
  const { refresh } = useShell();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [name, setName] = useState("");
  const [tagline, setTagline] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [turnError, setTurnError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [provider, setProvider] = useState<string | null>(null);
  const [inspector, setInspector] = useState<Inspector | null>(null);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [chat, inspection] = await Promise.all([
        getChat(characterId),
        getInspector(characterId),
      ]);
      setName(chat.character.name);
      setTagline(chat.character.tagline);
      setMessages(chat.messages);
      setInspector(inspection.inspector);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open this scene");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // Reload when the selected character changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streaming]);

  const runStream = async (
    path: string,
    body: unknown,
    applyStart: (current: ChatMessage[]) => ChatMessage[]
  ) => {
    setTurnError(null);
    setStreaming(true);
    setMessages(applyStart);
    let failed = false;
    try {
      await streamTurn(path, body, {
        onInspector: setInspector,
        onChunk: (text) => {
          setMessages((current) =>
            current.map((message) =>
              message.id === "streaming" ? { ...message, content: message.content + text } : message
            )
          );
        },
        onDone: (done) => {
          setProvider(done.provider ?? null);
          setMessages((current) =>
            current.map((message) =>
              message.id === "streaming"
                ? { ...message, id: done.messageId, content: done.content }
                : message
            )
          );
        },
        onError: (message) => {
          failed = true;
          setTurnError(message);
        },
      });
      if (!failed) await refresh();
    } catch (err) {
      failed = true;
      setTurnError(err instanceof Error ? err.message : "The turn failed.");
    } finally {
      setStreaming(false);
    }
    if (failed) {
      try {
        const chat = await getChat(characterId);
        setMessages(transcriptAfterFailedStream(chat.messages));
      } catch {
        setMessages((current) => transcriptAfterFailedStream(current));
      }
    }
    return !failed;
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft("");
    const userMessage: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    await runStream(`/gateway/api/chats/${characterId}/stream`, { message: text }, (current) => [
      ...current,
      userMessage,
      { id: "streaming", role: "assistant", content: "", createdAt: "" },
    ]);
  };

  const regenerate = async () => {
    if (streaming) return;
    await runStream(`/gateway/api/chats/${characterId}/regenerate`, {}, (current) => {
      const next = [...current];
      let index = -1;
      for (let cursor = next.length - 1; cursor >= 0; cursor -= 1) {
        if (next[cursor].role === "assistant") {
          index = cursor;
          break;
        }
      }
      if (index === -1) return current;
      next[index] = { ...next[index], id: "streaming", content: "" };
      return next;
    });
  };

  const continueScene = async () => {
    if (streaming) return;
    await runStream(`/gateway/api/chats/${characterId}/continue`, {}, (current) => [
      ...current,
      { id: "streaming", role: "assistant", content: "", createdAt: "" },
    ]);
  };

  const remove = async () => {
    if (!confirm(`Delete ${name || "this character"} and their scene?`)) return;
    await deleteCharacter(characterId);
    await refresh();
    router.push("/");
  };

  if (loading) return <LoadingState label="Loading the scene…" />;
  if (error) return <ErrorState message={error} onRetry={() => void load()} />;

  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-3 py-3 md:px-5">
        <MenuButton />
        <Avatar name={name} />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold">{name}</h1>
          <p className="truncate text-xs text-muted-foreground">{tagline}</p>
        </div>
        {provider === "scripted" && (
          <span className="hidden text-[11px] text-muted-foreground sm:inline">
            Scripted reply
          </span>
        )}
        <Button variant="outline" size="sm" onClick={() => setMemoryOpen(true)}>
          Memories
        </Button>
        <Button variant="outline" size="sm" onClick={() => setContextOpen(true)}>
          Context
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger className={cn(buttonVariants({ variant: "ghost", size: "icon" }))} aria-label="Character actions">
            <MoreHorizontal />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => router.push(`/characters/${characterId}/edit`)}>
              Edit character
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={() => void remove()}>
              Delete character
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
          {messages.length === 0 && (
            <p className="text-sm text-muted-foreground">
              This scene is quiet. Say something to begin.
            </p>
          )}
          {messages.map((message) => {
            const isLastAssistant = message.id === lastAssistant?.id;
            if (message.role === "user") {
              return (
                <div key={message.id} className="flex justify-end">
                  <p className="max-w-[80%] rounded-2xl bg-muted px-4 py-2 text-sm whitespace-pre-wrap">
                    {message.content}
                  </p>
                </div>
              );
            }
            return (
              <article key={message.id} className="flex gap-3">
                <Avatar name={name} className="mt-0.5" />
                <div className="min-w-0">
                  <p className="mb-1 text-sm font-medium">{name}</p>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">
                    {message.content || (streaming && message.id === "streaming" ? "…" : "")}
                  </p>
                  {isLastAssistant && message.id !== "streaming" && (
                    <div className="mt-2 flex gap-2">
                      <Button variant="ghost" size="sm" disabled={streaming} onClick={() => void regenerate()}>
                        <RefreshCw />
                        Regenerate
                      </Button>
                      <Button variant="ghost" size="sm" disabled={streaming} onClick={() => void continueScene()}>
                        <StepForward />
                        Continue
                      </Button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-border px-3 py-3 md:px-5">
        {turnError && (
          <p className="mx-auto mb-2 max-w-3xl text-sm text-destructive">{turnError}</p>
        )}
        <form
          className="mx-auto flex max-w-3xl items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <Textarea
            id="composer"
            name="message"
            autoComplete="off"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={`Message ${name}`}
            rows={1}
            className="max-h-40 min-h-10 resize-none rounded-2xl"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <Button type="submit" size="icon" disabled={streaming || !draft.trim()} aria-label="Send">
            <SendHorizontal />
          </Button>
        </form>
        <p className="mx-auto mt-2 max-w-3xl text-[11px] text-muted-foreground">
          Enter sends. Shift+Enter adds a line.
          {provider === "scripted" ? " No API key, so replies are scripted." : ""}
        </p>
      </div>

      <MemorySheet characterId={characterId} open={memoryOpen} onOpenChange={setMemoryOpen} />
      <InspectorSheet open={contextOpen} onOpenChange={setContextOpen} inspector={inspector} />
      <Link href={`/characters/${characterId}/edit`} className="sr-only">
        Edit {name}
      </Link>
    </div>
  );
}
