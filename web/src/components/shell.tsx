"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Plus, Sparkles } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { listCharacters, listChats } from "@/lib/api";
import type { Character, ChatSummary } from "@/lib/types";

interface ShellValue {
  characters: Character[];
  chats: ChatSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  openNav: () => void;
}

const ShellContext = createContext<ShellValue | null>(null);

export function useShell() {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used inside AppShell");
  return value;
}

function initial(name: string) {
  return name.trim().charAt(0).toUpperCase() || "?";
}

function tone(name: string) {
  const tones = [
    "bg-amber-400/90 text-amber-950",
    "bg-sky-400/90 text-sky-950",
    "bg-emerald-400/90 text-emerald-950",
    "bg-rose-400/90 text-rose-950",
    "bg-violet-400/90 text-violet-950",
  ];
  let hash = 0;
  for (const char of name) hash = (hash + char.charCodeAt(0)) % tones.length;
  return tones[hash];
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
        tone(name),
        className
      )}
    >
      {initial(name)}
    </span>
  );
}

function Rail({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { characters, chats, loading, error } = useShell();
  const activeId = pathname.startsWith("/chat/") ? pathname.split("/")[2] : "";

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-4 pt-4 pb-3">
        <span className="inline-flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles className="size-4" />
        </span>
        <div>
          <p className="text-sm font-semibold tracking-tight">Engram</p>
          <p className="text-[11px] text-muted-foreground">Text roleplay, memory open</p>
        </div>
      </div>
      <div className="px-3 pb-3">
        <Link
          href="/characters/new"
          onClick={onNavigate}
          className={cn(buttonVariants({ variant: "default" }), "w-full")}
        >
          <Plus className="size-4" />
          New character
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        <p className="px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Characters
        </p>
        {loading && <p className="px-2 py-2 text-sm text-muted-foreground">Loading…</p>}
        {error && !loading && (
          <p className="px-2 py-2 text-sm text-destructive">Could not load the roster.</p>
        )}
        {!loading && !error && characters.length === 0 && (
          <p className="px-2 py-2 text-sm text-muted-foreground">No characters yet.</p>
        )}
        <ul className="space-y-0.5">
          {characters.map((character) => (
            <li key={character.id}>
              <Link
                href={`/chat/${character.id}`}
                onClick={onNavigate}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-sidebar-accent",
                  activeId === character.id && "bg-sidebar-accent"
                )}
              >
                <Avatar name={character.name} className="size-7" />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{character.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {character.tagline}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="px-2 pt-4 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Recent
        </p>
        {!loading && chats.length === 0 && (
          <p className="px-2 py-2 text-sm text-muted-foreground">No scenes yet.</p>
        )}
        <ul className="space-y-0.5">
          {chats.map((chat) => (
            <li key={chat.sessionId}>
              <Link
                href={`/chat/${chat.characterId}`}
                onClick={onNavigate}
                className={cn(
                  "block rounded-lg px-2 py-1.5 hover:bg-sidebar-accent",
                  activeId === chat.characterId && "bg-sidebar-accent"
                )}
              >
                <span className="block truncate text-sm font-medium">{chat.name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {chat.lastMessage.replace(/\s+/g, " ") || "Empty scene"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextCharacters, nextChats] = await Promise.all([listCharacters(), listChats()]);
      setCharacters(nextCharacters);
      setChats(nextChats);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach Engram");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(
    () => ({
      characters,
      chats,
      loading,
      error,
      refresh,
      openNav: () => setNavOpen(true),
    }),
    [characters, chats, loading, error, refresh]
  );

  return (
    <ShellContext.Provider value={value}>
      <div className="flex h-dvh overflow-hidden bg-background text-foreground">
        <aside className="hidden w-72 shrink-0 border-r border-sidebar-border md:block">
          <Rail />
        </aside>
        <Sheet open={navOpen} onOpenChange={setNavOpen}>
          <SheetContent side="left" className="w-72 p-0 sm:max-w-xs" showCloseButton>
            <Rail onNavigate={() => setNavOpen(false)} />
          </SheetContent>
        </Sheet>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </ShellContext.Provider>
  );
}

export function MenuButton() {
  const { openNav } = useShell();
  return (
    <Button variant="ghost" size="icon" className="md:hidden" onClick={openNav} aria-label="Open navigation">
      <Menu />
    </Button>
  );
}
