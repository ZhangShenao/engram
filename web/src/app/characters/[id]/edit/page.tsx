"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CharacterForm } from "@/components/character-form";
import { ErrorState, LoadingState } from "@/components/states";
import type { Character } from "@/lib/types";

export default function EditCharacterPage() {
  const params = useParams<{ id: string }>();
  const [character, setCharacter] = useState<Character | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    fetch(`/gateway/api/characters/${params.id}`)
      .then(async (response) => {
        if (!response.ok) throw new Error("That character is gone.");
        const data = (await response.json()) as { character: Character };
        setCharacter(data.character);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not load the character");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (loading) return <LoadingState label="Loading the character…" />;
  if (error || !character) return <ErrorState message={error || "That character is gone."} onRetry={load} />;
  return <CharacterForm character={character} />;
}
