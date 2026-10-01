"use client";

import { useState } from "react";
import type { CharacterCard, CharacterInput, ExampleDialogue } from "@/lib/persona/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Props = {
  initial?: CharacterCard;
  onSubmit: (data: CharacterInput) => Promise<void>;
  submitLabel: string;
};

export function CharacterForm({ initial, onSubmit, submitLabel }: Props) {
  const [form, setForm] = useState<CharacterInput>({
    name: initial?.name ?? "",
    tagline: initial?.tagline ?? "",
    description: initial?.description ?? "",
    personality: initial?.personality ?? "",
    scenario: initial?.scenario ?? "",
    exampleDialogues: initial?.exampleDialogues ?? [
      { user: "", assistant: "" },
    ],
    greeting: initial?.greeting ?? "",
    speechStyle: initial?.speechStyle ?? "",
    boundaries: initial?.boundaries ?? "",
  });
  const [saving, setSaving] = useState(false);

  const updateExample = (index: number, patch: Partial<ExampleDialogue>) => {
    const next = [...form.exampleDialogues];
    next[index] = { ...next[index], ...patch };
    setForm({ ...form, exampleDialogues: next });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSubmit({
        ...form,
        exampleDialogues: form.exampleDialogues.filter(
          (ex) => ex.user.trim() || ex.assistant.trim()
        ),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle>Character card</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Tagline</Label>
            <Input
              value={form.tagline}
              onChange={(e) => setForm({ ...form, tagline: e.target.value })}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Description</Label>
            <Textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Personality</Label>
            <Textarea
              value={form.personality}
              onChange={(e) => setForm({ ...form, personality: e.target.value })}
              rows={2}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Scenario</Label>
            <Textarea
              value={form.scenario}
              onChange={(e) => setForm({ ...form, scenario: e.target.value })}
              rows={2}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Greeting</Label>
            <Textarea
              value={form.greeting}
              onChange={(e) => setForm({ ...form, greeting: e.target.value })}
              rows={2}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Speech style</Label>
            <Textarea
              value={form.speechStyle}
              onChange={(e) => setForm({ ...form, speechStyle: e.target.value })}
              rows={2}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Boundaries / OOC bans</Label>
            <Textarea
              value={form.boundaries}
              onChange={(e) => setForm({ ...form, boundaries: e.target.value })}
              rows={2}
              required
            />
          </div>
          <div className="space-y-3">
            <Label>Example dialogues</Label>
            {form.exampleDialogues.map((ex, i) => (
              <div key={i} className="rounded-lg border p-3 space-y-2">
                <Input
                  placeholder="User line"
                  value={ex.user}
                  onChange={(e) => updateExample(i, { user: e.target.value })}
                />
                <Textarea
                  placeholder="Character reply"
                  value={ex.assistant}
                  onChange={(e) =>
                    updateExample(i, { assistant: e.target.value })
                  }
                  rows={2}
                />
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                setForm({
                  ...form,
                  exampleDialogues: [
                    ...form.exampleDialogues,
                    { user: "", assistant: "" },
                  ],
                })
              }
            >
              Add example
            </Button>
          </div>
        </CardContent>
      </Card>
      <Button type="submit" disabled={saving} className="w-full">
        {saving ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}
