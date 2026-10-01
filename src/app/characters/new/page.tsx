"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { CharacterForm } from "@/components/character-form";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowLeft } from "lucide-react";

export default function NewCharacterPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen px-4 py-6">
      <Link href="/" className={cn(buttonVariants({ variant: "ghost" }), "mb-4 inline-flex")}>
        <ArrowLeft className="h-4 w-4 mr-2" />Back
      </Link>
      <h1 className="text-2xl font-bold text-center mb-6">Create a character</h1>
      <CharacterForm
        submitLabel="Create character"
        onSubmit={async (data) => {
          const res = await fetch("/api/characters", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          });
          const { character } = await res.json();
          router.push(`/chat/${character.id}`);
        }}
      />
    </div>
  );
}
