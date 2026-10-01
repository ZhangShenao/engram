"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { CharacterCard } from "@/lib/persona/types";
import { CharacterForm } from "@/components/character-form";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowLeft } from "lucide-react";

export default function EditCharacterPage() {
  const params = useParams();
  const id = params.id as string;
  const router = useRouter();
  const [character, setCharacter] = useState<CharacterCard | null>(null);

  useEffect(() => {
    fetch(`/api/characters/${id}`)
      .then((r) => r.json())
      .then((d) => setCharacter(d.character));
  }, [id]);

  if (!character) {
    return <p className="p-6 text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="min-h-screen px-4 py-6">
      <Link href="/" className={cn(buttonVariants({ variant: "ghost" }), "mb-4 inline-flex")}>
        <ArrowLeft className="h-4 w-4 mr-2" />Back
      </Link>
      <h1 className="text-2xl font-bold text-center mb-6">Edit {character.name}</h1>
      <CharacterForm
        initial={character}
        submitLabel="Save changes"
        onSubmit={async (data) => {
          await fetch(`/api/characters/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          });
          router.push(`/chat/${id}`);
        }}
      />
    </div>
  );
}
