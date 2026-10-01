"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { CharacterCard } from "@/lib/persona/types";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MoreVertical, Plus, MessageCircle } from "lucide-react";

export default function HomePage() {
  const router = useRouter();
  const [characters, setCharacters] = useState<CharacterCard[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const res = await fetch("/api/characters");
    const data = await res.json();
    setCharacters(data.characters);
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const remove = async (id: string) => {
    if (!confirm("Delete this character?")) return;
    await fetch(`/api/characters/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-violet-50/80 to-background dark:from-violet-950/20">
      <header className="max-w-5xl mx-auto px-4 py-8 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Roleplay Studio</h1>
          <p className="text-muted-foreground mt-1 max-w-lg">
            Character-first text roleplay with transparent context layers and persistent memories — no feed, no voice, just scene.
          </p>
        </div>
        <Link href="/characters/new" className={cn(buttonVariants())}>
          <Plus className="h-4 w-4 mr-2" />New character
        </Link>
      </header>

      <main className="max-w-5xl mx-auto px-4 pb-12">
        {loading ? (
          <p className="text-muted-foreground">Loading characters…</p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {characters.map((c) => (
              <Card key={c.id} className="flex flex-col">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <CardTitle className="text-lg">{c.name}</CardTitle>
                      <CardDescription>{c.tagline}</CardDescription>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "h-8 w-8")}
                      >
                        <MoreVertical className="h-4 w-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => router.push(`/characters/${c.id}/edit`)}>
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => remove(c.id)} className="text-destructive">
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </CardHeader>
                <CardContent className="flex-1 flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground line-clamp-3">{c.description}</p>
                  <Link href={`/chat/${c.id}`} className={cn(buttonVariants(), "mt-auto w-full")}>
                    <MessageCircle className="h-4 w-4 mr-2" />Chat
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
