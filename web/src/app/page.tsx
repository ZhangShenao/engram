"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useShell } from "@/components/shell";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";

export default function HomePage() {
  const { loading, error, characters, chats, refresh } = useShell();
  const router = useRouter();

  useEffect(() => {
    if (loading || error) return;
    const nextId = chats[0]?.characterId || characters[0]?.id;
    if (nextId) router.replace(`/chat/${nextId}`);
  }, [loading, error, characters, chats, router]);

  if (loading) return <LoadingState label="Loading characters…" />;
  if (error) return <ErrorState message={error} onRetry={() => void refresh()} />;
  if (characters.length === 0) {
    return (
      <EmptyState
        title="No characters yet"
        body="Create a card to start a scene. Engram keeps the voice stable and shows you the context it sends."
        action={
          <Link href="/characters/new" className={buttonVariants()}>
            New character
          </Link>
        }
      />
    );
  }
  return <LoadingState label="Opening a scene…" />;
}
