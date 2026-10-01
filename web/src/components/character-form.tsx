"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MenuButton, useShell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { createCharacter, deleteCharacter, updateCharacter } from "@/lib/api";
import type { Character, CharacterDraft, ExampleDialogue } from "@/lib/types";

const emptyDraft = (): CharacterDraft => ({
  name: "",
  tagline: "",
  description: "",
  personality: "",
  scenario: "",
  exampleDialogues: [{ user: "", assistant: "" }],
  greeting: "",
  speechStyle: "",
  boundaries: "",
});

function fromCharacter(character: Character): CharacterDraft {
  return {
    name: character.name,
    tagline: character.tagline,
    description: character.description,
    personality: character.personality,
    scenario: character.scenario,
    exampleDialogues:
      character.exampleDialogues.length > 0
        ? character.exampleDialogues
        : [{ user: "", assistant: "" }],
    greeting: character.greeting,
    speechStyle: character.speechStyle,
    boundaries: character.boundaries,
  };
}

export function CharacterForm({ character }: { character?: Character }) {
  const router = useRouter();
  const { refresh } = useShell();
  const [draft, setDraft] = useState<CharacterDraft>(
    character ? fromCharacter(character) : emptyDraft()
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const setField = (key: keyof CharacterDraft, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const setExample = (index: number, key: keyof ExampleDialogue, value: string) => {
    setDraft((current) => ({
      ...current,
      exampleDialogues: current.exampleDialogues.map((example, exampleIndex) =>
        exampleIndex === index ? { ...example, [key]: value } : example
      ),
    }));
  };

  const save = async () => {
    if (!draft.name.trim()) {
      setError("Give the character a name.");
      return;
    }
    setSaving(true);
    setError(null);
    const payload: CharacterDraft = {
      ...draft,
      name: draft.name.trim(),
      exampleDialogues: draft.exampleDialogues.filter(
        (example) => example.user.trim() || example.assistant.trim()
      ),
    };
    try {
      const saved = character
        ? await updateCharacter(character.id, payload)
        : await createCharacter(payload);
      await refresh();
      router.push(`/chat/${saved.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the character");
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!character) return;
    if (!confirm(`Delete ${character.name} and their scene?`)) return;
    setSaving(true);
    try {
      await deleteCharacter(character.id);
      await refresh();
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the character");
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <MenuButton />
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold">{character ? "Edit character" : "New character"}</h1>
          <p className="text-xs text-muted-foreground">
            The card is the stable voice. Boundaries stay in every prompt.
          </p>
        </div>
        <Link href={character ? `/chat/${character.id}` : "/"} className="text-sm text-muted-foreground hover:text-foreground">
          Back
        </Link>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <form
          className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-6"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Field label="Name" value={draft.name} onChange={(value) => setField("name", value)} />
          <Field label="Tagline" value={draft.tagline} onChange={(value) => setField("tagline", value)} />
          <Area label="Description" value={draft.description} onChange={(value) => setField("description", value)} />
          <Area label="Personality" value={draft.personality} onChange={(value) => setField("personality", value)} />
          <Area label="Scenario" value={draft.scenario} onChange={(value) => setField("scenario", value)} />
          <Area label="Greeting" value={draft.greeting} onChange={(value) => setField("greeting", value)} />
          <Area label="Speech style" value={draft.speechStyle} onChange={(value) => setField("speechStyle", value)} />
          <Area label="Boundaries" value={draft.boundaries} onChange={(value) => setField("boundaries", value)} />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Example dialogue</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setDraft((current) => ({
                    ...current,
                    exampleDialogues: [...current.exampleDialogues, { user: "", assistant: "" }],
                  }))
                }
              >
                Add example
              </Button>
            </div>
            {draft.exampleDialogues.map((example, index) => (
              <div key={index} className="space-y-2 rounded-xl border border-border p-3">
                <Textarea
                  value={example.user}
                  placeholder="User"
                  onChange={(event) => setExample(index, "user", event.target.value)}
                />
                <Textarea
                  value={example.assistant}
                  placeholder="Character — include *action* and dialogue"
                  onChange={(event) => setExample(index, "assistant", event.target.value)}
                />
              </div>
            ))}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save character"}
            </Button>
            {character && (
              <Button type="button" variant="destructive" disabled={saving} onClick={() => void remove()}>
                Delete
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Input value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function Area({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Textarea value={value} rows={3} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}
